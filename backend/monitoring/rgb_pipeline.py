"""Real seasonal B04/B03/B02 products on the existing city grid, bounded by block.

Never modifies NDVI products or their manifest. No synthetic imagery or basemap
tiles are used. Every colour band comes from the same selected acquisitions.
"""
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import warnings

import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling

from .city_catalog import DEFAULT_OUTPUT, DEFAULT_BOUNDARY, ensure_crop, load_boundary, atomic_json
from .city_pipeline import city_grid, windows, aoi_mask, group_acquisitions, add_overviews, sha256_file
from .pipeline import reflectance_conversion

RGB_BANDS = ('red', 'green', 'blue')


def load_inputs(output, boundary_path):
    manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('status') != 'ready' or manifest.get('scope') != 'administrative_city':
        raise ValueError('Verified city NDVI products must be ready first')
    boundary = load_boundary(boundary_path)
    if manifest['boundary_geometry_sha256'] != boundary['properties']['geometry_sha256']:
        raise ValueError('RGB AOI differs from the original NDVI AOI')
    catalog = json.loads((output/'selected-scenes.stac.json').read_text(encoding='utf-8'))
    for year in ('2020', '2026'):
        if {s['id'] for s in catalog[year]['features']} != {s['id'] for s in manifest['periods'][year]['scenes']}:
            raise ValueError('RGB and NDVI scene periods differ')
        for scene in catalog[year]['features']:
            for band in RGB_BANDS:
                reflectance_conversion(scene, scene['assets'][band])
    return manifest, boundary, catalog, city_grid(boundary)


def download_sources(output=DEFAULT_OUTPUT, boundary_path=DEFAULT_BOUNDARY):
    output = Path(output)
    manifest, boundary, catalog, grid = load_inputs(output, boundary_path)
    jobs = [(scene, band) for period in catalog.values() for scene in period['features']
            for band in (*RGB_BANDS, 'scl')]
    records = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(ensure_crop, scene, band, boundary, output/'source-crops'): (scene, band)
                   for scene, band in jobs}
        for number, future in enumerate(as_completed(futures), 1):
            scene, band = futures[future]
            path = future.result()
            records.setdefault(scene['id'], {})[band] = str(path.resolve())
            atomic_json(output/'rgb-source-index.json', records)
            print(f'RGB raw bands ready {number}/{len(jobs)}: {scene["id"]} {band}', flush=True)
    return manifest, boundary, catalog, grid, records


def build_rgb(output=DEFAULT_OUTPUT, boundary_path=DEFAULT_BOUNDARY, download_only=False):
    output = Path(output).resolve()
    base, boundary, catalog, grid, records = download_sources(output, boundary_path)
    if download_only:
        return {'status': 'source_bands_ready', 'scenes': len(records)}
    code = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    signature = hashlib.sha256((base['dataset_id']+code).encode()).hexdigest()[:24]
    manifest = {'status': 'processing', 'dataset_id': signature, 'source_dataset_id': base['dataset_id'],
                'processing_code_sha256': code, 'crs': 'EPSG:32643', 'resolution_m': 10,
                'width': grid['width'], 'height': grid['height'], 'transform': list(grid['transform'])[:6],
                'bands': ['B04', 'B03', 'B02'], 'min_observations': 2,
                'method': 'Per-acquisition SCL 4/5/6 mask, mosaic adjacent tiles once, seasonal per-channel median reflectance; fixed display stretch 0..0.30, gamma 2.2. NoData retained.',
                'periods': {year: {'start': base['periods'][year]['start'], 'end': base['periods'][year]['end'],
                                  'scene_ids': [s['id'] for s in catalog[year]['features']]} for year in ('2020','2026')},
                'created_at': datetime.now(timezone.utc).isoformat()}
    atomic_json(output/'rgb-manifest.json', manifest)
    try:
        usable = {}
        for year in ('2020', '2026'):
            target = output/f'rgb_{year}.partial.tif'
            profile = dict(driver='GTiff', width=grid['width'], height=grid['height'], count=3, dtype='uint8',
                           crs=grid['crs'], transform=grid['transform'], nodata=0, compress='deflate',
                           tiled=True, blockxsize=256, blockysize=256, photometric='RGB')
            usable[year] = 0
            groups = group_acquisitions(catalog[year]['features'])
            cache = output/'rgb-blocks'/signature/year
            cache.mkdir(parents=True, exist_ok=True)
            with ExitStack() as stack, rasterio.Env(GDAL_CACHEMAX=48):
                readers = {}
                for scene in catalog[year]['features']:
                    readers[scene['id']] = {}
                    for band in (*RGB_BANDS, 'scl'):
                        source = stack.enter_context(rasterio.open(records[scene['id']][band]))
                        readers[scene['id']][band] = stack.enter_context(WarpedVRT(source,
                            crs=grid['crs'], transform=grid['transform'], width=grid['width'], height=grid['height'],
                            src_nodata=0, nodata=0, resampling=Resampling.nearest, warp_mem_limit=16))
                destination = stack.enter_context(rasterio.open(target, 'w', **profile))
                for number, window in enumerate(windows(grid, 256)):
                    inside = aoi_mask(grid, window)
                    shape = inside.shape
                    checkpoint = cache/f'{int(window.row_off)}-{int(window.col_off)}.npz'
                    rgb = np.zeros((3, *shape), dtype='uint8')
                    if inside.any():
                        if checkpoint.exists():
                            with np.load(checkpoint, allow_pickle=False) as saved:
                                rgb = saved['rgb']
                            if rgb.shape != (3,*shape): raise ValueError('RGB checkpoint grid differs')
                        else:
                            observations = []
                            for _, scenes in groups:
                                observation = np.full((3,*shape), np.nan, dtype='float32')
                                for scene in scenes:
                                    readers_for_scene = readers[scene['id']]
                                    quality = readers_for_scene['scl'].read(1, window=window)
                                    raw = np.stack([readers_for_scene[b].read(1, window=window).astype('float32') for b in RGB_BANDS])
                                    bands = np.stack([raw[i]*reflectance_conversion(scene,scene['assets'][band])[0]
                                                      +reflectance_conversion(scene,scene['assets'][band])[1]
                                                      for i,band in enumerate(RGB_BANDS)])
                                    accept = inside & np.isin(quality,(4,5,6)) & (raw>0).all(axis=0) & (bands>=0).all(axis=0) & ~np.isfinite(observation[0])
                                    observation[:,accept] = bands[:,accept]
                                observations.append(observation)
                            observations = np.stack(observations)
                            count = np.isfinite(observations[:,0]).sum(axis=0)
                            with warnings.catch_warnings():
                                warnings.simplefilter('ignore', RuntimeWarning)
                                median = np.nanmedian(observations, axis=0)
                            valid = inside & (count>=2) & np.isfinite(median).all(axis=0)
                            display = np.power(np.clip(np.nan_to_num(median)/.30,0,1),1/2.2)
                            rgb[:,valid] = np.maximum(1,np.rint(display[:,valid]*255)).astype('uint8')
                            temporary = checkpoint.with_suffix('.partial.npz')
                            np.savez_compressed(temporary,rgb=rgb);temporary.replace(checkpoint)
                    destination.write(rgb, window=window)
                    usable[year] += int((rgb>0).all(axis=0).sum())
                    if number%24==0: print(f'RGB {year}: block {number+1}', flush=True)
            add_overviews(target);target.replace(output/f'rgb_{year}.tif')
        manifest['artifacts'] = {f'rgb_{year}.tif': {'sha256':sha256_file(output/f'rgb_{year}.tif'),
            'bytes':(output/f'rgb_{year}.tif').stat().st_size} for year in ('2020','2026')}
        manifest['usable_pixels'] = usable
        manifest['status'] = 'ready'
        atomic_json(output/'rgb-manifest.json',manifest)
        print(json.dumps({'status':'ready','dataset_id':signature,'usable_pixels':usable}),flush=True)
        return manifest
    except Exception as error:
        manifest.update(status='unavailable',reason=str(error)[:500])
        atomic_json(output/'rgb-manifest.json',manifest)
        raise
