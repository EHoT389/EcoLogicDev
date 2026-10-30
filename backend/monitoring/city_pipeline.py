"""Bounded, resumable Sentinel-2 comparison for the verified administrative AOI.

Source cutouts are prepared once by city_catalog. Numerical processing uses local
bands in 512-pixel blocks; no full-scene stack or per-pixel GeoJSON is created.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import os
import time

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window, transform as window_transform
from shapely.geometry import shape, mapping
from shapely.ops import transform as geometry_transform
from pyproj import Transformer
from PIL import Image

from .core import NODATA, calculate_ndvi, median_composite, comparison_mask, classify_changes
from .pipeline import reflectance_conversion
from .city_catalog import load_boundary, build_city_catalog, ensure_crop, DEFAULT_BOUNDARY, DEFAULT_OUTPUT

VERSION = 'administrative-city-1'
YEARS = (2020, 2026)
DEFAULT_BLOCK = 512
MAX_GRID_PIXELS = 30_000_000


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.partial')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for attempt in range(5):
        try:
            temporary.replace(path)
            break
        except OSError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def city_grid(boundary, max_pixels=MAX_GRID_PIXELS):
    geometry = shape(boundary['geometry'])
    if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in ('Polygon', 'MultiPolygon'):
        raise ValueError('Administrative geometry is invalid')
    west, south, east, north = geometry.bounds
    if not (76 <= west < east <= 78 and 51.5 <= south < north <= 53):
        raise ValueError('Administrative AOI must be near Pavlodar')
    projected = geometry_transform(Transformer.from_crs(4326, 32643, always_xy=True).transform, geometry)
    left, bottom, right, top = projected.bounds
    left, bottom = math.floor(left / 10) * 10, math.floor(bottom / 10) * 10
    right, top = math.ceil(right / 10) * 10, math.ceil(top / 10) * 10
    width, height = int((right - left) / 10), int((top - bottom) / 10)
    if width * height > max_pixels:
        raise ValueError('Administrative grid exceeds the bounded processing budget')
    return {'crs': CRS.from_epsg(32643), 'transform': from_origin(left, top, 10, 10),
            'width': width, 'height': height, 'projected_geometry': mapping(projected)}


def windows(grid, block_size=DEFAULT_BLOCK):
    if block_size not in (128, 256, 512, 1024):
        raise ValueError('Block size must be 128, 256, 512 or 1024')
    for row in range(0, grid['height'], block_size):
        for col in range(0, grid['width'], block_size):
            yield Window(col, row, min(block_size, grid['width'] - col), min(block_size, grid['height'] - row))


def aoi_mask(grid, window):
    return geometry_mask([grid['projected_geometry']], out_shape=(int(window.height), int(window.width)),
                         transform=window_transform(window, grid['transform']), invert=True, all_touched=False)


def profile(grid, dtype, nodata):
    return dict(driver='GTiff', count=1, dtype=dtype, nodata=nodata, crs=grid['crs'],
                transform=grid['transform'], width=grid['width'], height=grid['height'],
                tiled=True, blockxsize=256, blockysize=256, compress='deflate',
                predictor=3 if dtype == 'float32' else 2, BIGTIFF='IF_SAFER')


def add_overviews(path):
    with rasterio.open(path, 'r+') as raster:
        factors = [factor for factor in (2, 4, 8, 16, 32) if min(raster.width, raster.height) // factor >= 32]
        if factors:
            raster.build_overviews(factors, Resampling.nearest)
            raster.update_tags(ns='rio_overview', resampling='nearest')


def _scene_key(item):
    """Adjacent MGRS tiles of one acquisition are one observation, not two."""
    props = item['properties']
    return props['datetime'][:10], props.get('platform', '')


def group_acquisitions(items):
    groups = {}
    for item in sorted(items, key=lambda value: value['id']):
        groups.setdefault(_scene_key(item), []).append(item)
    return sorted(groups.items())


def scene_metadata(item):
    props, assets = item['properties'], item['assets']
    conversion = {band: reflectance_conversion(item, assets[band]) for band in ('red', 'nir')}
    return {'id': item['id'], 'date': props['datetime'], 'cloud_cover': props.get('eo:cloud_cover'),
            'mgrs_tile': props.get('grid:code'), 'platform': props.get('platform'),
            'source': next((link['href'] for link in item.get('links', []) if link.get('rel') == 'self'),
                           'https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items/' + item['id']),
            'assets': {band: assets[band]['href'] for band in ('red', 'nir', 'scl')},
            'processing_baseline': props.get('s2:processing_baseline'),
            'boa_offset_applied': props.get('earthsearch:boa_offset_applied'),
            'reflectance_scale': conversion['red'][0], 'reflectance_offset': conversion['red'][1],
            'asset_radiometry': {band: {'declared_scale': assets[band].get('raster:bands', [{}])[0].get('scale'),
                'declared_offset': assets[band].get('raster:bands', [{}])[0].get('offset'),
                'applied_scale': conversion[band][0], 'applied_offset': conversion[band][1]} for band in ('red', 'nir')},
            'provenance': 'observed_satellite'}


def prepare_sources(items, boundary, cache_dir, grid, stack):
    opened = {}
    for item in items:
        bands = {}
        for band in ('red', 'nir', 'scl'):
            path = ensure_crop(item, band, boundary, cache_dir)
            source = stack.enter_context(rasterio.open(path))
            bands[band] = stack.enter_context(WarpedVRT(source, crs=grid['crs'], transform=grid['transform'],
                width=grid['width'], height=grid['height'], src_nodata=source.nodata or 0,
                nodata=0, resampling=Resampling.nearest, warp_mem_limit=32))
        opened[item['id']] = bands
    return opened


def observation_block(items, opened, window, inside):
    """Mosaic valid pixels of adjacent tiles for a single acquisition."""
    observation = np.full(inside.shape, np.nan, dtype='float32')
    for item in items:
        bands = opened[item['id']]
        red = bands['red'].read(1, window=window, out_dtype='float32')
        nir = bands['nir'].read(1, window=window, out_dtype='float32')
        scl = bands['scl'].read(1, window=window)
        raw_valid = (red != 0) & (nir != 0)
        red_scale, red_offset = reflectance_conversion(item, item['assets']['red'])
        nir_scale, nir_offset = reflectance_conversion(item, item['assets']['nir'])
        ndvi = calculate_ndvi(red * red_scale + red_offset, nir * nir_scale + nir_offset, scl)
        accept = inside & raw_valid & np.isfinite(ndvi) & ~np.isfinite(observation)
        observation[accept] = ndvi[accept]
    return observation


def process_year(year, items, boundary, grid, output, signature, block_size):
    if len(items) < 2:
        raise ValueError(f'Too few identified real source scenes for {year}')
    block_cache = output / 'blocks' / signature / str(year)
    block_cache.mkdir(parents=True, exist_ok=True)
    ndvi_path, count_path = output / f'ndvi_{year}.partial.tif', output / f'count_{year}.partial.tif'
    groups = group_acquisitions(items)
    with ExitStack() as stack, rasterio.Env(GDAL_CACHEMAX=48):
        opened = prepare_sources(items, boundary, output / 'source-crops', grid, stack)
        ndvi_out = stack.enter_context(rasterio.open(ndvi_path, 'w', **profile(grid, 'float32', NODATA)))
        count_out = stack.enter_context(rasterio.open(count_path, 'w', **profile(grid, 'uint16', 0)))
        for index, window in enumerate(windows(grid, block_size)):
            inside = aoi_mask(grid, window)
            ndvi = np.full(inside.shape, np.nan, dtype='float32')
            counts = np.zeros(inside.shape, dtype='uint16')
            cached = block_cache / f'{int(window.row_off)}-{int(window.col_off)}.npz'
            if inside.any():
                # Only this fingerprint matches the AOI, source scenes, grid and
                # processing code. Another run's block can have the same shape
                # while containing different observations or radiometry.
                if cached.exists():
                    with np.load(cached, allow_pickle=False) as saved:
                        ndvi, counts = saved['ndvi'], saved['count']
                    if ndvi.shape != inside.shape or counts.shape != inside.shape:
                        raise ValueError('Resumed block dimensions do not match the city grid')
                else:
                    observations = [observation_block(group, opened, window, inside) for _, group in groups]
                    ndvi, counts = median_composite(np.stack(observations))
                    ndvi[~inside], counts[~inside] = np.nan, 0
                    temporary = cached.with_suffix('.partial.npz')
                    np.savez_compressed(temporary, ndvi=ndvi, count=counts)
                    temporary.replace(cached)
            ndvi_out.write(np.nan_to_num(ndvi, nan=NODATA), 1, window=window)
            count_out.write(counts, 1, window=window)
            if index % 8 == 0:
                print(f'{year}: block {index + 1}, row={int(window.row_off)}, col={int(window.col_off)}', flush=True)
    for partial, target in ((ndvi_path, output / f'ndvi_{year}.tif'), (count_path, output / f'count_{year}.tif')):
        add_overviews(partial)
        partial.replace(target)


def final_statistics_and_changes(grid, output, block_size):
    totals = {'total': 0, 'common': 0, 'valid_2020': 0, 'valid_2026': 0,
              'old': 0, 'new': 0, 'gain': 0, 'loss': 0, 'sum_old': 0., 'sum_new': 0.}
    delta_path, changes_path = output / 'delta_ndvi.partial.tif', output / 'changes.partial.tif'
    with ExitStack() as stack:
        sources = {f'{kind}_{year}': stack.enter_context(rasterio.open(output / f'{kind}_{year}.tif'))
                   for year in YEARS for kind in ('ndvi', 'count')}
        delta_out = stack.enter_context(rasterio.open(delta_path, 'w', **profile(grid, 'float32', NODATA)))
        change_out = stack.enter_context(rasterio.open(changes_path, 'w', **profile(grid, 'uint8', 255)))
        for window in windows(grid, block_size):
            inside = aoi_mask(grid, window)
            old, new = (sources[f'ndvi_{year}'].read(1, window=window) for year in YEARS)
            counts0, counts1 = (sources[f'count_{year}'].read(1, window=window) for year in YEARS)
            old[old == NODATA], new[new == NODATA] = np.nan, np.nan
            valid0 = inside & np.isfinite(old) & (counts0 >= 2)
            valid1 = inside & np.isfinite(new) & (counts1 >= 2)
            common = comparison_mask(old, new, counts0, counts1) & inside
            classes = classify_changes(old, new, .3, common)
            delta_out.write(np.where(common, new - old, NODATA).astype('float32'), 1, window=window)
            change_out.write(classes, 1, window=window)
            totals['total'] += int(inside.sum()); totals['common'] += int(common.sum())
            totals['valid_2020'] += int(valid0.sum()); totals['valid_2026'] += int(valid1.sum())
            totals['old'] += int((common & (old >= .3)).sum()); totals['new'] += int((common & (new >= .3)).sum())
            totals['gain'] += int((classes == 1).sum()); totals['loss'] += int((classes == 2).sum())
            totals['sum_old'] += float(old[common].sum(dtype=np.float64)); totals['sum_new'] += float(new[common].sum(dtype=np.float64))
    for partial, target in ((delta_path, output / 'delta_ndvi.tif'), (changes_path, output / 'changes.tif')):
        add_overviews(partial); partial.replace(target)
    total, common = totals['total'], totals['common']
    if not total or not common:
        raise ValueError('No common, quality-checked observations inside the administrative AOI')
    coverage = {'total_aoi_pixels': total, 'total_pixels': total, 'aoi_pixel_area_km2': total * .0001,
                'common_valid_pixels': common, 'common_fraction': common / total,
                'missing_common_pixels': total - common, 'missing_common_fraction': (total - common) / total,
                'years': {str(year): {'valid_pixels': totals[f'valid_{year}'],
                    'valid_fraction': totals[f'valid_{year}'] / total,
                    'min_observations': 2} for year in YEARS}}
    summary = {'status': 'ready', 'threshold': .3, 'pixel_area_m2': 100,
        'total_pixels': total, 'comparable_pixels': common, 'comparable_fraction': common / total,
        'comparable_area_ha': common * .01, 'vegetation_2020_ha': totals['old'] * .01,
        'vegetation_2026_ha': totals['new'] * .01, 'gain_ha': totals['gain'] * .01, 'loss_ha': totals['loss'] * .01,
        'net_change_ha': (totals['new'] - totals['old']) * .01,
        'change_percent': (totals['new'] - totals['old']) / totals['old'] * 100 if totals['old'] else None,
        'mean_ndvi_2020': totals['sum_old'] / common, 'mean_ndvi_2026': totals['sum_new'] / common,
        'mean_ndvi_difference': (totals['sum_new'] - totals['sum_old']) / common}
    return summary, coverage


def preview(output):
    with rasterio.open(output / 'changes.tif') as source:
        ratio = min(1, 1000 / max(source.width, source.height))
        values = source.read(1, out_shape=(max(1, round(source.height * ratio)), max(1, round(source.width * ratio))),
                             resampling=Resampling.nearest)
    rgba = np.zeros((*values.shape, 4), dtype='uint8')
    for value, color in ((0, (138, 145, 143, 230)), (1, (35, 142, 74, 255)), (2, (198, 64, 55, 255))):
        rgba[values == value] = color
    Image.fromarray(rgba).save(output / 'changes-preview.png')


def build_city(output=DEFAULT_OUTPUT, boundary_path=DEFAULT_BOUNDARY, catalog_path=None, block_size=DEFAULT_BLOCK, year_only=None):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    boundary = load_boundary(boundary_path)
    props = boundary['properties']
    grid = city_grid(boundary)
    if catalog_path:
        catalog = json.loads(Path(catalog_path).read_text(encoding='utf-8'))
    elif (output / 'city-scenes.stac.json').exists():
        catalog = json.loads((output / 'city-scenes.stac.json').read_text(encoding='utf-8'))
    else:
        catalog = build_city_catalog(output_dir=output, boundary_path=boundary_path)
    sources = {year: catalog[str(year)]['features'] for year in YEARS}
    code = hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).with_name('core.py').read_bytes()
                          + Path(__file__).with_name('pipeline.py').read_bytes()).hexdigest()
    fingerprint = {'version': VERSION, 'code': code, 'boundary': props['geometry_sha256'],
                   'shape': [grid['height'], grid['width']], 'transform': list(grid['transform'])[:6], 'block_size': block_size,
                   'scenes': {str(year): [scene_metadata(item) for item in sources[year]] for year in YEARS}}
    signature = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()[:24]
    aoi = {'geometry': boundary['geometry'], 'id': props['id'],
           'name_ru': props.get('display_name_ru', props['name_ru']), 'name_kk': props.get('display_name_kk', props['name_kk']),
           'area_km2': props['area_km2_geodesic'], 'area_km2_projected': props['area_km2_projected'],
           'source': props['source']['url'], 'provenance': props}
    manifest = {'version': VERSION, 'status': 'processing', 'scope': 'administrative_city', 'dataset_id': signature,
        'source': 'https://earth-search.aws.element84.com/v1', 'collection': 'sentinel-2-l2a',
        'bbox_wgs84': list(shape(boundary['geometry']).bounds), 'crs': 'EPSG:32643', 'resolution_m': 10,
        'width': grid['width'], 'height': grid['height'], 'transform': list(grid['transform'])[:6],
        'min_observations': 2, 'aoi': aoi, 'boundary_geometry_sha256': props['geometry_sha256'],
        'processing_code_sha256': code, 'created_at': datetime.now(timezone.utc).isoformat(),
        'method': {'ndvi': '(B08-B04)/(B08+B04)', 'composite': 'median of quality-masked per-acquisition mosaics',
                   'quality': 'SCL classes 4,5,6; native 20 m SCL resampled nearest to common 10 m grid',
                   'area': '100 square metres per pixel centre inside administrative polygon and common quality mask',
                   'default_threshold': .3, 'block_size': block_size, 'adjacent_tiles_same_acquisition': 'mosaicked before observation count',
                   'overviews': 'nearest only; display does not interpolate new observations'},
        'warnings': ['Administrative city AOI includes subordinate and unbuilt territories, not only the urban settlement.',
                     'NoData indicates absent or insufficient observations; coverage is reported for each year and jointly.',
                     'NDVI includes grass and shrubs and does not prove tree planting or felling.',
                     'Same summer season does not remove phenology, moisture, registration or cloud-mask errors.'],
        'periods': {str(year): {'year': year, 'start': f'{year}-06-01', 'end': f'{year}-08-31',
                    'scene_count': len(sources[year]), 'selected_scene_count': len(sources[year]),
                    'scenes': [scene_metadata(item) for item in sources[year]], 'median_composite': True,
                    'min_observations': 2, 'acquisition_count': len(group_acquisitions(sources[year]))} for year in YEARS}}
    atomic_json(output / 'manifest.json', manifest)
    try:
        if year_only is not None and year_only not in YEARS:
            raise ValueError('Only 2020 and 2026 are supported')
        for year in ((year_only,) if year_only is not None else YEARS):
            process_year(year, sources[year], boundary, grid, output, signature, block_size)
        if year_only is not None:
            manifest['phase'] = f'year_{year_only}_processed_awaiting_other_year'
            atomic_json(output / 'manifest.json', manifest)
            print(json.dumps({'status': 'processing', 'phase': manifest['phase'], 'dataset_id': signature}), flush=True)
            return manifest
        summary, coverage = final_statistics_and_changes(grid, output, block_size)
        manifest['summary'], manifest['coverage'] = summary, coverage
        for year in YEARS:
            manifest['periods'][str(year)]['usable_fraction'] = coverage['years'][str(year)]['valid_fraction']
        atomic_json(output / 'coverage.json', coverage)
        atomic_json(output / 'city-statistics.json', summary)
        atomic_json(output / 'processing-footprint.geojson', boundary)
        atomic_json(output / 'selected-scenes.stac.json', catalog)
        preview(output)
        names = [f'{kind}_{year}.tif' for kind in ('ndvi', 'count') for year in YEARS] + [
            'delta_ndvi.tif', 'changes.tif', 'coverage.json', 'city-statistics.json', 'processing-footprint.geojson',
            'selected-scenes.stac.json', 'changes-preview.png']
        manifest['artifacts'] = {name: {'sha256': sha256_file(output / name), 'bytes': (output / name).stat().st_size} for name in names}
        manifest['processed_bytes'] = sum(record['bytes'] for record in manifest['artifacts'].values())
        manifest['status'], manifest['completed_at'] = 'ready', datetime.now(timezone.utc).isoformat()
        atomic_json(output / 'manifest.json', manifest)
        print(json.dumps({'status': 'ready', 'dataset_id': signature, 'summary': summary, 'coverage': coverage}), flush=True)
        return manifest
    except Exception as error:
        manifest.update(status='unavailable', reason=str(error)[:1000])
        atomic_json(output / 'manifest.json', manifest)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(DEFAULT_OUTPUT))
    parser.add_argument('--boundary', default=str(DEFAULT_BOUNDARY))
    parser.add_argument('--catalog')
    parser.add_argument('--block-size', type=int, default=DEFAULT_BLOCK, choices=(128, 256, 512, 1024))
    parser.add_argument('--year-only', type=int, choices=YEARS, help='Prepare a completed source year without declaring comparison ready')
    args = parser.parse_args()
    build_city(args.output, args.boundary, args.catalog, args.block_size, args.year_only)


if __name__ == '__main__':
    main()
