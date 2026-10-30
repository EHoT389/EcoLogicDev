"""Public Sentinel-2 L2A catalog and bounded native-band cutouts for a real city AOI.

This module does not compute or invent observations. Cached source pixels remain
raw DN, with original CRS/transform/nodata. GIS processing applies the recorded
reflectance conversion and SCL mask on one common grid.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import hashlib
import json
import math
import re
import time

import httpx
import rasterio
from rasterio.windows import Window, from_bounds, transform as window_transform
from rasterio.warp import transform_bounds
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

from .pipeline import reflectance_conversion

STAC = 'https://earth-search.aws.element84.com/v1'
COLLECTION = 'sentinel-2-l2a'
YEARS = (2020, 2026)
BANDS = ('red', 'nir', 'scl')
ALLOWED_COG_HOSTS = {
    'sentinel-cogs.s3.us-west-2.amazonaws.com',
    'e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com',
    'e84-earth-search-sentinel-data.s3.amazonaws.com',
}
VERSION = 'city-source-catalog-1'
DEFAULT_BOUNDARY = Path(__file__).resolve().parents[1] / 'assets' / 'pavlodar-boundary.geojson'
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / 'storage' / 'monitoring-city'


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.partial')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    for attempt in range(5):
        try:
            temporary.replace(path)
            break
        except OSError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def load_boundary(path=DEFAULT_BOUNDARY):
    feature = json.loads(Path(path).read_text(encoding='utf-8'))
    if feature.get('type') != 'Feature':
        raise ValueError('Administrative AOI must be a GeoJSON Feature')
    geometry = shape(feature['geometry'])
    properties = feature.get('properties', {})
    if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in ('Polygon', 'MultiPolygon'):
        raise ValueError('Invalid city boundary geometry')
    if properties.get('boundary') != 'administrative' or properties.get('scope') != 'administrative_city':
        raise ValueError('A verified administrative city boundary is required')
    west, south, east, north = geometry.bounds
    if not (76.4 <= west < east <= 77.4 and 51.9 <= south < north <= 52.7):
        raise ValueError('AOI is outside the bounded Pavlodar administrative region')
    return feature


def _geometry(boundary):
    return shape(boundary['geometry']) if isinstance(boundary, dict) else boundary


def _safe_scene_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value):
        raise ValueError('Unsafe source scene identifier')
    return value


def _cache_key(boundary, year, max_cloud):
    document = {'geometry': mapping(_geometry(boundary)), 'year': year, 'max_cloud': max_cloud, 'collection': COLLECTION}
    return hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()[:20]


def _validate_item(item, aoi, year, max_cloud=35):
    try:
        properties = item['properties']
        date = properties['datetime']
        observed = datetime.fromisoformat(date.replace('Z', '+00:00'))
        if observed.year != year or observed.month not in (6, 7, 8):
            return False
        cloud = float(properties['eo:cloud_cover'])
        if not math.isfinite(cloud) or not 0 <= cloud < max_cloud:
            return False
        footprint = shape(item['geometry'])
        if not footprint.is_valid or footprint.is_empty or footprint.intersection(aoi).area <= 0:
            return False
        for band in BANDS:
            href = item['assets'][band]['href']
            url = urlparse(href)
            if url.scheme != 'https' or url.hostname not in ALLOWED_COG_HOSTS or not url.path.endswith('.tif'):
                return False
        # Ambiguous post-baseline04 harmonization is not silently guessed.
        for band in ('red', 'nir'):
            reflectance_conversion(item, item['assets'][band])
        return bool(_safe_scene_id(item.get('id')))
    except (KeyError, TypeError, ValueError):
        return False


def search_city(boundary, year, cache_dir=DEFAULT_OUTPUT / 'source-cache', max_cloud=35, refresh=False, client=None):
    """Paginate the actual STAC search, then filter by the exact administrative AOI."""
    if year not in YEARS or not 0 < max_cloud <= 100:
        raise ValueError('Unsupported season or cloud filter')
    aoi = _geometry(boundary)
    cached = Path(cache_dir) / f'search-{year}-{_cache_key(boundary, year, max_cloud)}.json'
    if cached.exists() and not refresh:
        data = json.loads(cached.read_text(encoding='utf-8'))
        return [item for item in data['features'] if _validate_item(item, aoi, year, max_cloud)]
    body = {'collections': [COLLECTION], 'bbox': list(aoi.bounds),
            'datetime': f'{year}-06-01T00:00:00Z/{year}-08-31T23:59:59Z',
            'query': {'eo:cloud_cover': {'lt': max_cloud}}, 'limit': 100}
    own_client = client is None
    client = client or httpx.Client(timeout=65, follow_redirects=True, headers={'User-Agent': 'EcoLogicDev-monitoring/4.0'})
    found = {}
    url, method, payload = STAC + '/search', 'POST', body
    seen_pages = set()
    try:
        for _ in range(25):
            page_key = (url, method, json.dumps(payload, sort_keys=True))
            if page_key in seen_pages:
                raise ValueError('Repeated STAC pagination link')
            seen_pages.add(page_key)
            response = client.request(method, url, json=payload if method == 'POST' else None)
            response.raise_for_status()
            page = response.json()
            for item in page.get('features', []):
                if _validate_item(item, aoi, year, max_cloud):
                    found[item['id']] = item
            next_link = next((link for link in page.get('links', []) if link.get('rel') == 'next'), None)
            if not next_link:
                break
            url = next_link['href']
            if urlparse(url).hostname != 'earth-search.aws.element84.com':
                raise ValueError('Untrusted catalog pagination target')
            method = next_link.get('method', 'GET').upper()
            if method not in ('GET', 'POST'):
                raise ValueError('Unsupported pagination method')
            next_body = next_link.get('body', {})
            payload = ({**payload, **next_body} if next_link.get('merge') else next_body) if method == 'POST' else None
        else:
            raise ValueError('Catalog exceeds bounded 25-page search')
    finally:
        if own_client:
            client.close()
    features = sorted(found.values(), key=lambda f: (f['properties']['datetime'], f['id']))
    atomic_json(cached, {'type': 'FeatureCollection', 'features': features, 'search': body,
                        'retrieved_at': datetime.now(timezone.utc).isoformat(), 'pages': len(seen_pages), 'source': STAC})
    return features


def tile_code(item):
    code = item['properties'].get('grid:code')
    if code:
        return code.removeprefix('MGRS-')
    code = item['properties'].get('s2:mgrs_tile')
    if code:
        return code
    # Legacy EarthSearch IDs have the form S2A_43UFT_20200615_0_L2A.
    parts = item['id'].split('_')
    if len(parts) > 2 and len(parts[1]) == 5:
        return parts[1]
    raise ValueError('MGRS tile identifier missing')


def select_city_scenes(features, boundary, per_month=2):
    """Choose distinct acquisitions in each month for every truly intersecting tile."""
    if not isinstance(per_month, int) or not 1 <= per_month <= 6:
        raise ValueError('per_month must be 1–6')
    aoi = _geometry(boundary)
    groups = {}
    for item in features:
        if shape(item['geometry']).intersection(aoi).area <= 0:
            continue
        p = item['properties']; tile = tile_code(item); month = int(p['datetime'][5:7])
        if month not in (6, 7, 8):
            continue
        # One day per tile is one acquisition, even if reprocessed or duplicated.
        acquisition = p['datetime'][:10]
        previous = groups.setdefault((tile, month), {}).get(acquisition)
        current_version = (float(p.get('s2:processing_baseline', 0)), item['id'])
        previous_version = (float(previous['properties'].get('s2:processing_baseline', 0)), previous['id']) if previous else None
        if previous is None or current_version > previous_version:
            groups[(tile, month)][acquisition] = item
    selected = []
    for key, values in sorted(groups.items()):
        ranked = sorted(values.values(), key=lambda f: (float(f['properties']['eo:cloud_cover']), f['properties']['datetime'], f['id']))
        selected.extend(ranked[:per_month])
    return sorted(selected, key=lambda f: (f['properties']['datetime'], tile_code(f), f['id']))


def _scene_summary(item):
    p = item['properties']
    radiometry = {}
    for band in ('red', 'nir'):
        scale, offset = reflectance_conversion(item, item['assets'][band])
        declared = item['assets'][band].get('raster:bands', [{}])[0]
        radiometry[band] = {'declared_scale': declared.get('scale'), 'declared_offset': declared.get('offset'),
                            'applied_scale': scale, 'applied_offset': offset}
    return {'id': item['id'], 'date': p['datetime'], 'mgrs_tile': tile_code(item), 'cloud_cover': p['eo:cloud_cover'],
            'source': f'{STAC}/collections/{COLLECTION}/items/{item["id"]}',
            'assets': {band: item['assets'][band]['href'] for band in BANDS},
            'processing_baseline': p['s2:processing_baseline'], 'boa_offset_applied': p.get('earthsearch:boa_offset_applied'),
            'asset_radiometry': radiometry, 'provenance': 'observed_satellite'}


def build_city_catalog(output_dir=DEFAULT_OUTPUT, boundary_path=DEFAULT_BOUNDARY, per_month=2, refresh=False):
    output = Path(output_dir); boundary = load_boundary(boundary_path); aoi = _geometry(boundary)
    catalog, periods = {}, {}
    for year in YEARS:
        features = search_city(boundary, year, output / 'source-cache', refresh=refresh)
        chosen = select_city_scenes(features, boundary, per_month)
        if len(chosen) < 2:
            raise ValueError(f'Fewer than two real identified scenes for {year}')
        footprints = unary_union([shape(f['geometry']) for f in chosen])
        coverage = aoi.intersection(footprints).area / aoi.area
        tiles = sorted({tile_code(item) for item in chosen})
        catalog[str(year)] = {'type': 'FeatureCollection', 'features': chosen}
        periods[str(year)] = {'year': year, 'start': f'{year}-06-01', 'end': f'{year}-08-31',
                              'available_scene_count': len(features), 'selected_scene_count': len(chosen),
                              'mgrs_tiles': tiles, 'footprint_coverage_fraction': coverage,
                              'scenes': [_scene_summary(item) for item in chosen]}
        print(f'{year}: {len(features)} candidates, {len(chosen)} selected, tiles {tiles}, geometric coverage {coverage:.6f}', flush=True)
    atomic_json(output / 'city-scenes.stac.json', catalog)
    metadata = {'version': VERSION, 'status': 'catalogued', 'scope': 'administrative_city',
                'boundary_id': boundary['properties']['id'], 'boundary_geometry_sha256': boundary['properties']['geometry_sha256'],
                'boundary_geometry': boundary['geometry'], 'bbox_wgs84': list(aoi.bounds),
                'source': STAC, 'collection': COLLECTION, 'periods': periods,
                'selection': 'up to two lowest scene-cloud acquisitions per calendar month and MGRS tile; actual quality is pixelwise SCL',
                'created_at': datetime.now(timezone.utc).isoformat(),
                'limitations': ['Footprint coverage is not cloud-free usable coverage. Pixel coverage must be measured after SCL masking.',
                               'NoData is retained where fewer than two valid observations are available in either year.']}
    atomic_json(output / 'catalog-metadata.json', metadata)
    return catalog


def _ensure_crop_once(item, band, boundary, cache_dir=DEFAULT_OUTPUT / 'source-crops'):
    """Cache a raw native-grid GeoTIFF cutout, streamed by block; never a whole scene."""
    if band not in (*BANDS, 'green', 'blue'):
        raise ValueError('Unsupported source band')
    _safe_scene_id(item.get('id'))
    href = item['assets'][band]['href']; parsed = urlparse(href)
    if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_COG_HOSTS or not parsed.path.endswith('.tif'):
        raise ValueError('Untrusted source asset')
    intersection = _geometry(boundary).intersection(shape(item['geometry']))
    if intersection.is_empty:
        raise ValueError('Source scene does not intersect the administrative AOI')
    signature = hashlib.sha256(json.dumps({'url': href, 'bbox': intersection.bounds,
        'baseline': item['properties'].get('s2:processing_baseline'),
        'boa': item['properties'].get('earthsearch:boa_offset_applied'), 'version': VERSION}, sort_keys=True).encode()).hexdigest()[:16]
    target = Path(cache_dir) / f'{item["id"]}-{band}-{signature}.tif'; sidecar = target.with_suffix('.json')
    if target.exists() and sidecar.exists():
        meta = json.loads(sidecar.read_text(encoding='utf-8'))
        if target.stat().st_size == meta.get('bytes') and hashlib.sha256(target.read_bytes()).hexdigest() == meta.get('sha256'):
            return target
    target.parent.mkdir(parents=True, exist_ok=True); temporary = target.with_suffix('.partial.tif')
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',
                      GDAL_HTTP_TIMEOUT='60', GDAL_HTTP_CONNECTTIMEOUT='15', GDAL_HTTP_MAX_RETRY='2',
                      GDAL_HTTP_MULTIRANGE='NO', GDAL_HTTP_MULTIPLEX='NO',
                      VSI_CACHE=True, VSI_CACHE_SIZE=8_000_000, GDAL_CACHEMAX=64):
        if band in ('green','blue'):
            from .range_reader import range_opener
            open_options={'opener':range_opener}
        else:open_options={}
        with rasterio.open(href,**open_options) as source:
            if source.crs is None or source.count != 1:
                raise ValueError('Invalid source raster')
            expected_resolution = 20 if band == 'scl' else 10
            if source.crs.to_epsg() != 32643 or abs(source.transform.a) != expected_resolution or abs(source.transform.e) != expected_resolution:
                raise ValueError('Expected Sentinel-2 B04/B08 10 m and SCL 20 m in EPSG:32643')
            bounds = transform_bounds('EPSG:4326', source.crs, *intersection.bounds, densify_pts=21)
            requested = from_bounds(*bounds, transform=source.transform)
            x0, y0 = max(0, math.floor(requested.col_off) - 2), max(0, math.floor(requested.row_off) - 2)
            x1 = min(source.width, math.ceil(requested.col_off + requested.width) + 2)
            y1 = min(source.height, math.ceil(requested.row_off + requested.height) + 2)
            window = Window(x0, y0, x1 - x0, y1 - y0)
            if window.width <= 0 or window.height <= 0 or window.width * window.height > 30_000_000:
                raise ValueError('City source cutout exceeds bounded 30 million native pixels')
            if window.width * window.height >= source.width * source.height * .95:
                raise ValueError('Whole-scene download is not permitted by this pipeline')
            profile = source.profile.copy()
            profile.update(driver='GTiff', width=int(window.width), height=int(window.height),
                           transform=window_transform(window, source.transform), compress='deflate',
                           tiled=True, blockxsize=512, blockysize=512)
            with rasterio.open(temporary, 'w', **profile) as destination:
                # Wide bounded strips let GDAL coalesce concurrent COG range reads;
                # writing individual 512x512 destination tiles serializes requests.
                # At most 1024 rows are resident, never an entire satellite scene.
                for row in range(0, int(window.height), 256):
                    block = Window(0, row, window.width, min(256, window.height - row))
                    native = Window(window.col_off, window.row_off + row, block.width, block.height)
                    destination.write(source.read(1, window=native), 1, window=block)
            source_meta = {'source_crs': str(source.crs), 'source_transform': list(source.transform)[:6],
                           'source_shape': [source.height, source.width], 'source_window': [window.col_off, window.row_off, window.width, window.height],
                           'native_resolution_m': abs(source.transform.a), 'nodata': source.nodata,
                           'dtype': source.dtypes[0]}
    temporary.replace(target)
    metadata = {'scene_id': item['id'], 'band': band, 'href': href, 'crop_signature': signature,
                **source_meta, 'bbox_wgs84': list(intersection.bounds), 'raw_dn': True,
                'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'bytes': target.stat().st_size,
                'created_at': datetime.now(timezone.utc).isoformat()}
    if band != 'scl':
        metadata['applied_scale'], metadata['applied_offset'] = reflectance_conversion(item, item['assets'][band])
    atomic_json(sidecar, metadata)
    print(f'Cached {item["id"]} {band}: {metadata["bytes"]} bytes', flush=True)
    return target


def ensure_crop(item, band, boundary, cache_dir=DEFAULT_OUTPUT / 'source-crops'):
    """Retry transient incomplete HTTP range reads, never accept truncated pixels."""
    for attempt in range(3):
        try:
            return _ensure_crop_once(item, band, boundary, cache_dir)
        except (rasterio.errors.RasterioIOError, httpx.HTTPError, OSError):
            if attempt == 2:
                raise
            print(f'Retrying source cutout {item["id"]} {band} after incomplete range read ({attempt + 1}/3)', flush=True)
            time.sleep(attempt + 1)
