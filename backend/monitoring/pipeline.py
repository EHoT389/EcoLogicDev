"""Bounded, offline-first Sentinel-2 L2A processing via public COG range reads.

No cloud account, paid API, interpolation of observations, or invented measurements.
Only windows intersecting the explicitly bounded centre of Pavlodar are requested.
"""
import argparse
import hashlib
import gzip
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds, reproject
from rasterio.windows import from_bounds, transform as window_transform
from rasterio.features import shapes, geometry_mask
from shapely.geometry import shape, mapping, box
from shapely.ops import transform as transform_geometry, unary_union
from pyproj import Transformer

from .core import NODATA, calculate_ndvi, median_composite, comparison_mask, classify_changes, compute_statistics

STAC = 'https://earth-search.aws.element84.com/v1'
DEFAULT_BBOX = [76.925, 52.265, 76.985, 52.310]
YEARS = (2020, 2026)
RESOLUTION = 10
VERSION = 'monitoring-1.1'


def reflectance_conversion(item, asset):
    """EarthSearch harmonizes many COGs already: never apply offset twice.

    raster:bands.offset can describe source SAFE DN even where COG BOA offset was
    already applied. Baseline <04 has no BOA DN offset at all. Unknown >=04 item
    harmonization is refused rather than guessed.
    """
    properties = item['properties']
    bands = asset.get('raster:bands', [])
    if not bands or not isinstance(bands[0].get('scale'), (int, float)):
        raise ValueError('Reflectance scale is missing')
    scale = float(bands[0]['scale'])
    if not 0 < scale <= .01:
        raise ValueError('Unsupported reflectance scale')
    try:
        baseline = float(properties['s2:processing_baseline'])
    except (KeyError, ValueError, TypeError):
        raise ValueError('Processing baseline is missing; cannot harmonize safely')
    applied = properties.get('earthsearch:boa_offset_applied')
    if baseline < 4:
        offset = 0.
    elif applied is True:
        offset = 0.
    elif applied is False:
        offset = -1000. * scale
    else:
        raise ValueError('Unknown BOA offset harmonization')
    return scale, offset


def grid_for_bbox(bbox):
    if len(bbox) != 4 or not (76.8 <= bbox[0] < bbox[2] <= 77.15 and 52.15 <= bbox[1] < bbox[3] <= 52.45):
        raise ValueError('Bounded Pavlodar AOI is required')
    left, bottom, right, top = transform_bounds('EPSG:4326', 'EPSG:32643', *bbox, densify_pts=21)
    left, bottom = math.floor(left / 10) * 10, math.floor(bottom / 10) * 10
    right, top = math.ceil(right / 10) * 10, math.ceil(top / 10) * 10
    width, height = int((right - left) / 10), int((top - bottom) / 10)
    if width * height > 1_000_000:
        raise ValueError('AOI exceeds one million 10 m pixels; reduce region')
    return {'crs': CRS.from_epsg(32643), 'transform': from_origin(left, top, 10, 10), 'width': width, 'height': height}


def search(year, bbox):
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        response = client.post(STAC + '/search', json={'collections': ['sentinel-2-l2a'], 'bbox': bbox,
            'datetime': f'{year}-06-01T00:00:00Z/{year}-08-31T23:59:59Z', 'limit': 100,
            'query': {'eo:cloud_cover': {'lt': 35}}})
        response.raise_for_status()
        features = response.json()['features']
    return features


def select_scenes(features, per_month=2):
    # Primary tile fully contains this limited centre AOI. Neighbouring UFU scenes
    # intersect the bounding search polygon but do not cover the requested centre.
    selected = []
    for month in (6, 7, 8):
        unique = {}
        for item in features:
            p = item['properties']
            if p.get('grid:code') != 'MGRS-43UFT' or int(p['datetime'][5:7]) != month:
                continue
            if not all(key in item.get('assets', {}) for key in ('red', 'nir', 'scl')):
                continue
            acquisition = (p['datetime'][:10], p.get('platform'))
            # Prefer latest processing for duplicates, not multiple observations of
            # the very same acquisition. Both COG variants are harmonized explicitly.
            previous = unique.get(acquisition)
            if previous is None or (float(p.get('s2:processing_baseline', 0)), item['id']) > (float(previous['properties'].get('s2:processing_baseline', 0)), previous['id']):
                unique[acquisition] = item
        candidates = sorted(unique.values(), key=lambda f: (f['properties'].get('eo:cloud_cover', 100), f['id']))
        selected.extend(candidates[:per_month])
    return sorted(selected, key=lambda f: f['properties']['datetime'])


def read_window(asset, grid, categorical=False):
    href = asset['href']
    if not href.startswith('https://sentinel-cogs.s3.us-west-2.amazonaws.com/'):
        raise ValueError('Only allowlisted public Sentinel COG assets are accepted')
    bounds = rasterio.transform.array_bounds(grid['height'], grid['width'], grid['transform'])
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',
                      GDAL_HTTP_TIMEOUT='60', GDAL_HTTP_CONNECTTIMEOUT='15', GDAL_HTTP_MAX_RETRY='2',
                      VSI_CACHE=True, VSI_CACHE_SIZE=8_000_000, GDAL_CACHEMAX=64):
        with rasterio.open(href) as source:
            if source.crs is None:
                raise ValueError('Source CRS missing')
            crop_bounds = transform_bounds(grid['crs'], source.crs, *bounds, densify_pts=21)
            window = from_bounds(*crop_bounds, transform=source.transform).round_offsets().round_lengths()
            # A small explicit overlap is useful for reprojection on a different grid.
            window = rasterio.windows.Window(window.col_off - 2, window.row_off - 2, window.width + 4, window.height + 4)
            if window.width * window.height > 1_100_000:
                raise ValueError('Source crop too large')
            raw = source.read(1, window=window, boundless=True, fill_value=source.nodata or 0)
            destination = np.zeros((grid['height'], grid['width']), dtype=raw.dtype)
            reproject(raw, destination, src_transform=window_transform(window, source.transform), src_crs=source.crs,
                      src_nodata=source.nodata or 0, dst_transform=grid['transform'], dst_crs=grid['crs'], dst_nodata=0,
                      resampling=Resampling.nearest if categorical else Resampling.nearest)
            return destination


def write_raster(path, array, grid, nodata, dtype):
    temporary = path.with_suffix('.tmp.tif')
    with rasterio.open(temporary, 'w', driver='GTiff', count=1, dtype=dtype, crs=grid['crs'],
                       transform=grid['transform'], width=grid['width'], height=grid['height'],
                       nodata=nodata, compress='deflate', tiled=True, blockxsize=256, blockysize=256) as dst:
        dst.write(array.astype(dtype), 1)
    temporary.replace(path)


def atomic_json(path, data):
    temporary = path.with_suffix('.tmp.json')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def write_geojson(output, classified, grid, bbox):
    """Compact display vectors; authoritative statistics remain the native grid.

    Two class features can be MultiPolygons. Simplification is 2 m in UTM and is
    explicitly metadata, never used to recompute areas or claim parcel accuracy.
    """
    to_wgs84 = Transformer.from_crs(grid['crs'], 4326, always_xy=True).transform
    groups = {1: [], 2: []}
    for geometry, value in shapes(classified, mask=np.isin(classified, [1, 2]), transform=grid['transform']):
        groups[int(value)].append(shape(geometry))
    features = []
    for value, polygons in groups.items():
        if not polygons:
            continue
        merged = unary_union(polygons).simplify(2, preserve_topology=True)
        features.append({'type': 'Feature', 'properties': {
            'class': 'gain' if value == 1 else 'loss', 'threshold': .3,
            'provenance': 'derived_observed_satellite', 'display_simplification_m': 2,
            'area_source': 'native 10 m common valid raster; not simplified geometry'},
            'geometry': mapping(transform_geometry(to_wgs84, merged))})
    atomic_json(output / 'changes.geojson', {'type': 'FeatureCollection', 'features': features,
        'properties': {'threshold': .3, 'simplification_m': 2, 'statistics_from_native_raster': True}})
    (output / 'changes.geojson.gz').write_bytes(gzip.compress((output / 'changes.geojson').read_bytes(), mtime=0))
    atomic_json(output / 'processing-footprint.geojson', {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'scope': 'central_pavlodar_pilot', 'not_city_boundary': True},
         'geometry': mapping(box(*bbox))}]})


def build(output, bbox=DEFAULT_BBOX, per_month=2, source_catalog=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if not 1 <= per_month <= 3:
        raise ValueError('Only 1–3 scenes per month allowed')
    grid = grid_for_bbox(bbox)
    to_grid = Transformer.from_crs(4326, grid['crs'], always_xy=True).transform
    # Reprojecting a longitude/latitude box produces a non-axis-aligned polygon:
    # its enclosing UTM rectangle must not silently expand the analysis region.
    footprint = transform_geometry(to_grid, box(*bbox))
    region_mask = geometry_mask([mapping(footprint)], out_shape=(grid['height'], grid['width']),
                                transform=grid['transform'], invert=True, all_touched=False)
    source_data = json.loads(Path(source_catalog).read_text(encoding='utf-8')) if source_catalog else None
    manifest = {'version': VERSION, 'status': 'processing', 'source': STAC, 'collection': 'sentinel-2-l2a',
        'bbox_wgs84': bbox, 'crs': 'EPSG:32643', 'resolution_m': 10,
        'width': grid['width'], 'height': grid['height'], 'transform': list(grid['transform'])[:6],
        'min_observations': 2, 'periods': {}, 'created_at': datetime.now(timezone.utc).isoformat(),
        'method': {'ndvi': '(B08-B04)/(B08+B04)', 'composite': 'median of quality-masked per-scene NDVI',
                   'quality': 'SCL classes 4,5,6 only; nearest-neighbour resampling from native 20 m SCL',
                   'area': '100 m² per common valid 10 m pixel; polygon selection uses pixel centres',
                   'default_threshold': .3, 'classification': 'gain/loss are transitions across NDVI threshold',
                   'reflectance': 'scale from STAC, offset according to processing baseline and EarthSearch BOA flag'},
        'warnings': [
            'Pilot covers central Pavlodar and 12 OSM zones, not the whole city.',
            'NDVI measures probable vegetation including grass and shrubs, not tree planting or felling.',
            'Same June–August season does not remove phenology, irrigation and weather effects.',
            '10 m pixels and native 20 m quality mask cannot resolve individual trees or cadastral detail.',
            'Vegetation areas are compared only on pixels with at least two valid observations in each year.'
        ]}
    manifest['processing_code_sha256'] = hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).with_name('core.py').read_bytes()).hexdigest()
    # Do not let the web API serve stale ready metadata while replacing raster files.
    atomic_json(output / 'manifest.json', manifest)
    arrays, counts, selected_catalog = {}, {}, {}
    try:
        for year in YEARS:
            features = source_data[str(year)]['features'] if source_data else search(year, bbox)
            scenes = select_scenes(features, per_month)
            selected_catalog[str(year)] = {'type': 'FeatureCollection', 'features': scenes}
            if len(scenes) < 2:
                raise ValueError(f'Insufficient real scenes for {year}: {len(scenes)}')
            cache_dir = output / 'cache'
            cache_dir.mkdir(exist_ok=True)
            stack, observations, failures = [], [], []
            for item in scenes:
                p = item['properties']
                print(f"{year}: {item['id']}", flush=True)
                assets = item['assets']
                scales = {key: reflectance_conversion(item, assets[key]) for key in ('red', 'nir')}
                signature = hashlib.sha256(json.dumps({'id': item['id'], 'bbox': bbox, 'grid': manifest['transform'], 'shape': [grid['height'], grid['width']], 'scale': scales, 'quality': '456-v1'}, sort_keys=True).encode()).hexdigest()[:20]
                cache = cache_dir / (item['id'] + '-' + signature + '.npz')
                try:
                    if cache.exists():
                        with np.load(cache, allow_pickle=False) as saved:
                            ndvi = saved['ndvi'].copy()
                    else:
                        red, nir, scl = (read_window(assets[b], grid, b == 'scl') for b in ('red', 'nir', 'scl'))
                        raw_valid = (red != 0) & (nir != 0)
                        ndvi = calculate_ndvi(red.astype(np.float32) * scales['red'][0] + scales['red'][1],
                                              nir.astype(np.float32) * scales['nir'][0] + scales['nir'][1], scl)
                        ndvi[~raw_valid] = np.nan
                        np.savez_compressed(cache, ndvi=ndvi)
                    if ndvi.shape != (grid['height'], grid['width']):
                        raise ValueError('Cached observation grid mismatch')
                    ndvi[~region_mask] = np.nan
                    stack.append(ndvi)
                    observations.append({'id': item['id'], 'date': p['datetime'], 'cloud_cover': p.get('eo:cloud_cover'),
                        'source': next((link['href'] for link in item.get('links', []) if link.get('rel') == 'self'), STAC + '/collections/sentinel-2-l2a/items/' + item['id']),
                        'assets': {b: assets[b]['href'] for b in ('red', 'nir', 'scl')},
                        'asset_radiometry': {b: {'declared_scale': assets[b].get('raster:bands', [{}])[0].get('scale'),
                                                'declared_offset': assets[b].get('raster:bands', [{}])[0].get('offset'),
                                                'applied_scale': scales[b][0], 'applied_offset': scales[b][1]}
                                             for b in ('red', 'nir')},
                        'processing_baseline': p['s2:processing_baseline'], 'boa_offset_applied': p.get('earthsearch:boa_offset_applied'),
                        'reflectance_scale': scales['red'][0], 'reflectance_offset': scales['red'][1],
                        'valid_fraction': float(np.isfinite(ndvi[region_mask]).mean()), 'provenance': 'observed_satellite',
                        'scene_ndvi_mean': float(np.nanmean(ndvi)) if np.isfinite(ndvi).any() else None})
                except Exception as error:
                    failures.append({'id': item['id'], 'reason': str(error)[:500]})
                    print(f"Skipped {item['id']}: {type(error).__name__}: {error}", flush=True)
            if len(stack) < 2:
                raise ValueError(f'Fewer than two successfully read scenes for {year}')
            arrays[year], counts[year] = median_composite(stack)
            if not (counts[year] >= 2).any():
                raise ValueError(f'No pixels with two valid observations in {year}')
            write_raster(output / f'ndvi_{year}.tif', np.nan_to_num(arrays[year], nan=NODATA), grid, NODATA, 'float32')
            write_raster(output / f'count_{year}.tif', counts[year], grid, 0, 'uint16')
            manifest['periods'][str(year)] = {'year': year, 'start': f'{year}-06-01', 'end': f'{year}-08-31',
                'available_scene_count': len(features), 'selected_scene_count': len(scenes), 'scene_count': len(observations),
                'scenes': observations, 'failed_scenes': failures,
                'min_observations': 2, 'median_composite': True, 'usable_fraction': float((counts[year][region_mask] >= 2).mean())}
            atomic_json(output / 'manifest.json', manifest)
        common = comparison_mask(arrays[2020], arrays[2026], counts[2020], counts[2026])
        if not common.any():
            raise ValueError('No jointly valid comparison pixels')
        delta = np.where(common, arrays[2026] - arrays[2020], NODATA)
        change = classify_changes(arrays[2020], arrays[2026], .3, common)
        write_raster(output / 'delta_ndvi.tif', delta, grid, NODATA, 'float32')
        write_raster(output / 'changes.tif', change, grid, 255, 'uint8')
        write_geojson(output, change, grid, bbox)
        manifest['summary'] = compute_statistics(arrays[2020], arrays[2026], valid=common, region_mask=region_mask)
        atomic_json(output / 'selected-scenes.stac.json', selected_catalog)
        manifest['dataset_id'] = hashlib.sha256(json.dumps({'version': VERSION, 'code': manifest['processing_code_sha256'], 'bbox': bbox, 'scenes': {year: [s['id'] for s in manifest['periods'][str(year)]['scenes']] for year in YEARS}}, sort_keys=True).encode()).hexdigest()[:20]
        manifest['artifacts'] = {name: {'sha256': hashlib.sha256((output / name).read_bytes()).hexdigest(), 'bytes': (output / name).stat().st_size}
            for name in ['ndvi_2020.tif', 'ndvi_2026.tif', 'count_2020.tif', 'count_2026.tif', 'delta_ndvi.tif', 'changes.tif', 'changes.geojson', 'changes.geojson.gz', 'processing-footprint.geojson', 'selected-scenes.stac.json']}
        manifest['status'] = 'ready'
        manifest['completed_at'] = datetime.now(timezone.utc).isoformat()
        atomic_json(output / 'manifest.json', manifest)
        print(json.dumps({'status': 'ready', 'dataset_id': manifest['dataset_id'], 'shape': [grid['height'], grid['width']], 'summary': manifest['summary']}), flush=True)
        return manifest
    except Exception as error:
        manifest.update(status='unavailable', reason=str(error)[:1000])
        atomic_json(output / 'manifest.json', manifest)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='backend/storage/monitoring')
    parser.add_argument('--bbox', nargs=4, type=float, default=DEFAULT_BBOX)
    parser.add_argument('--per-month', type=int, default=2)
    parser.add_argument('--catalog', help='Reuse a previously downloaded STAC catalog JSON with 2020/2026 keys')
    args = parser.parse_args()
    build(args.output, args.bbox, args.per_month, args.catalog)


if __name__ == '__main__':
    main()
