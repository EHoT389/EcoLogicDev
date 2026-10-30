"""Independent checks against the real city products, never demo substitutes.

Skip only when separately downloaded city data is absent. These checks verify
every output pixel, plus bounded source-band samples from both city tiles.
"""
from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
import hashlib
import json
import os
import math
import warnings

import numpy as np
import pytest
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window, transform as window_transform
from rasterio.vrt import WarpedVRT
from shapely.geometry import shape, mapping
from shapely.ops import transform
from pyproj import Transformer
from openpyxl import load_workbook
from pypdf import PdfReader
from PIL import Image

from backend.data import ZONES
from backend.monitoring import service, reports

FOLDER = Path(__file__).resolve().parents[1] / 'backend/storage/monitoring-city'


@pytest.fixture(scope='module')
def city_products():
    if not (FOLDER / 'manifest.json').exists():
        pytest.skip('Real city satellite data has not been downloaded; no substitute used')
    manifest = json.loads((FOLDER / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['status'] == 'ready', 'Existing city products must pass, not silently skip'
    return manifest


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def test_city_real_artifacts_and_all_72_source_cutouts(city_products):
    manifest = city_products
    for name, record in manifest['artifacts'].items():
        path = FOLDER / name
        assert path.stat().st_size == record['bytes'] and digest(path) == record['sha256']
    catalog = json.loads((FOLDER / 'selected-scenes.stac.json').read_text(encoding='utf-8'))
    for year in (2020, 2026):
        items = catalog[str(year)]['features']
        assert len(items) == 12 and {i['id'].split('_')[1] for i in items} == {'43UFT', '43UFU'}
        assert {i['properties']['datetime'][5:7] for i in items} == {'06', '07', '08'}
        for item in items:
            assert item['properties']['datetime'].startswith(str(year))
            for band in ('red', 'nir', 'scl'):
                paths = list((FOLDER / 'source-crops').glob(f'{item["id"]}-{band}-*.json'))
                assert len(paths) == 1
                record = json.loads(paths[0].read_text(encoding='utf-8'))
                path = paths[0].with_suffix('.tif')
                assert record['raw_dn'] and record['href'] == item['assets'][band]['href']
                assert record['href'].startswith('https://sentinel-cogs.s3.us-west-2.amazonaws.com/')
                assert path.stat().st_size == record['bytes'] and digest(path) == record['sha256']
                with rasterio.open(path) as source:
                    assert source.crs.to_epsg() == 32643
                    assert source.dtypes == (('uint8',) if band == 'scl' else ('uint16',))
                    assert source.res == ((20., 20.) if band == 'scl' else (10., 10.))


def test_city_real_every_pixel_masks_changes_and_api_totals(city_products, monkeypatch):
    monkeypatch.setenv('MONITORING_DATA_DIR', str(FOLDER))
    boundary = json.loads(service.BOUNDARY_FILE.read_text(encoding='utf-8'))
    region = mapping(transform(Transformer.from_crs(4326, 32643, always_xy=True).transform,
                               shape(boundary['geometry'])))
    totals = dict.fromkeys(('total', 'common', 'old', 'new', 'gain', 'loss', 'valid0', 'valid1'), 0)
    sums = np.zeros(2)
    with ExitStack() as stack:
        readers = {name: stack.enter_context(rasterio.open(FOLDER / (name + '.tif')))
                   for name in ('ndvi_2020', 'ndvi_2026', 'count_2020', 'count_2026', 'delta_ndvi', 'changes')}
        ref = readers['ndvi_2020']
        for source in readers.values():
            assert (source.width, source.height, source.crs, source.transform) == (ref.width, ref.height, ref.crs, ref.transform)
        for _, window in ref.block_windows(1):
            values = {key: source.read(1, window=window) for key, source in readers.items()}
            inside = geometry_mask([region], out_shape=values['changes'].shape,
                                   transform=window_transform(window, ref.transform), invert=True)
            a, b = values['ndvi_2020'], values['ndvi_2026']
            valid0 = inside & np.isfinite(a) & (a >= -1) & (a <= 1) & (values['count_2020'] >= 2)
            valid1 = inside & np.isfinite(b) & (b >= -1) & (b <= 1) & (values['count_2026'] >= 2)
            common = valid0 & valid1
            old, new = common & (a >= .3), common & (b >= .3)
            expected = np.full(a.shape, 255, dtype='uint8')
            expected[common] = 0; expected[common & ~old & new] = 1; expected[common & old & ~new] = 2
            assert np.array_equal(values['changes'], expected)
            assert np.all(values['delta_ndvi'][~common] == -9999)
            np.testing.assert_allclose(values['delta_ndvi'][common], (b-a)[common], atol=1e-7)
            for year in (2020, 2026):
                assert np.all(values[f'ndvi_{year}'][~inside] == -9999)
                assert not values[f'count_{year}'][~inside].any()
            for key, mask in zip(totals, (inside, common, old, new, expected == 1, expected == 2, valid0, valid1)):
                totals[key] += int(mask.sum())
            sums += [a[common].sum(dtype=np.float64), b[common].sum(dtype=np.float64)]
    stats = service.get_vegetation_change()['statistics']
    assert stats['total_pixels'] == totals['total'] == city_products['coverage']['total_aoi_pixels']
    assert stats['comparable_pixels'] == totals['common'] == city_products['coverage']['common_valid_pixels']
    for key, count in (('vegetation_2020_ha', 'old'), ('vegetation_2026_ha', 'new'), ('gain_ha', 'gain'), ('loss_ha', 'loss')):
        assert stats[key] == pytest.approx(totals[count] * .01)
        assert stats[key] == pytest.approx(city_products['summary'][key])
    assert stats['net_change_ha'] == pytest.approx((totals['gain'] - totals['loss']) * .01)
    np.testing.assert_allclose([stats['mean_ndvi_2020'], stats['mean_ndvi_2026']], sums / totals['common'])
    for zone in ZONES:
        result = service.get_vegetation_change(zone['id'])
        assert result['status'] == 'ready' and result['statistics']['aoi_coverage_fraction'] == 1
        assert result['statistics']['comparable_pixels'] > 0


def test_city_real_composites_match_source_dn_samples(city_products):
    catalog = json.loads((FOLDER / 'selected-scenes.stac.json').read_text(encoding='utf-8'))
    # Windows in the north, tile overlap and south; all computations below are
    # independent of production NDVI/composite helpers and block checkpoints.
    probes = []
    with rasterio.open(FOLDER / 'count_2020.tif') as counts:
        for row in (700, 1700, 3100):
            observed = np.flatnonzero(counts.read(1, window=Window(0, row, counts.width, 1))[0] >= 2)
            assert len(observed), 'Each north/overlap/south probe row must intersect the observed AOI'
            column = max(0, min(counts.width - 16, int(observed[len(observed)//2])-8))
            probes.append(Window(column, row, 16, 16))
    for year in (2020, 2026):
        with rasterio.open(FOLDER / f'ndvi_{year}.tif') as ref, rasterio.open(FOLDER / f'count_{year}.tif') as counts:
            for window in probes:
                observations = {}
                for item in sorted(catalog[str(year)]['features'], key=lambda item: item['id']):
                    props = item['properties']; key = (props['datetime'][:10], props['platform'])
                    bands = {}
                    for band in ('red', 'nir', 'scl'):
                        path = next((FOLDER / 'source-crops').glob(f'{item["id"]}-{band}-*.tif'))
                        with rasterio.open(path) as source, WarpedVRT(source, crs=ref.crs,
                                transform=window_transform(window, ref.transform), width=16, height=16,
                                src_nodata=0, nodata=0, resampling=rasterio.enums.Resampling.nearest) as view:
                            bands[band] = view.read(1).astype('float32')
                    raw = (bands['red'] != 0) & (bands['nir'] != 0)
                    offset = 0 if float(props['s2:processing_baseline']) < 4 or props.get('earthsearch:boa_offset_applied') else -.1
                    red, nir = bands['red'] * .0001 + offset, bands['nir'] * .0001 + offset
                    valid = raw & np.isin(bands['scl'], (4, 5, 6)) & (red >= 0) & (nir >= 0) & ((red+nir) > 0)
                    ndvi = np.full((16, 16), np.nan, dtype='float32')
                    np.divide(nir-red, nir+red, out=ndvi, where=valid)
                    observation = observations.setdefault(key, np.full((16, 16), np.nan, dtype='float32'))
                    accept = np.isfinite(ndvi) & ~np.isfinite(observation)
                    observation[accept] = ndvi[accept]
                stack = np.stack(list(observations.values()))
                actual_count = counts.read(1, window=window)
                inside = actual_count > 0
                assert inside.any(), 'Source probe must contain observed city pixels'
                np.testing.assert_array_equal(np.isfinite(stack).sum(axis=0)[inside], actual_count[inside])
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', RuntimeWarning)
                    median = np.nanmedian(stack, axis=0)
                np.testing.assert_allclose(median[inside], ref.read(1, window=window)[inside], atol=1e-6)


def test_city_real_bilingual_reports_keep_all_scenes_and_actual_values(city_products, monkeypatch):
    monkeypatch.setenv('MONITORING_DATA_DIR', str(FOLDER))
    result = service.get_vegetation_change()
    image = service.change_map_png()
    for language in ('ru', 'kk'):
        pdf = PdfReader(BytesIO(reports.export_pdf(result, image, language)))
        text = '\n'.join(page.extract_text() for page in pdf.pages)
        assert len(pdf.pages) >= 3
        assert str(round(result['statistics']['vegetation_2020_ha'], 4)) in text
        for period in city_products['periods'].values():
            for scene in period['scenes']:
                assert scene['id'] in text
        workbook = load_workbook(BytesIO(reports.export_xlsx(result, image, language)))
        assert workbook.worksheets[0]['B5'].value == result['statistics']['vegetation_2020_ha']
        assert len(workbook.worksheets[2]._images) == 1


def test_city_real_overview_tiles_contain_data_at_whole_city_zoom(city_products, monkeypatch):
    monkeypatch.setenv('MONITORING_DATA_DIR', str(FOLDER))
    for zoom in (8, 9, 10):
        x = int((76.95+180)/360 * 2**zoom)
        y = int((1-math.asinh(math.tan(math.radians(52.285)))/math.pi)/2 * 2**zoom)
        image = np.asarray(Image.open(BytesIO(service.tile_png('changes', zoom, x, y))))
        assert image.shape == (256, 256, 4) and (image[:,:,3] > 0).any()


@pytest.mark.skipif(os.getenv('MONITORING_VERIFY_REMOTE') != '1', reason='Optional direct public COG range reads')
def test_city_real_remote_cogs_match_cached_dn_both_years_and_tiles(city_products):
    catalog = json.loads((FOLDER / 'selected-scenes.stac.json').read_text(encoding='utf-8'))
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',
                      GDAL_HTTP_TIMEOUT='25', GDAL_HTTP_CONNECTTIMEOUT='10', GDAL_HTTP_MAX_RETRY='1'):
        for year in ('2020', '2026'):
            for tile in ('43UFT', '43UFU'):
                item = next(item for item in catalog[year]['features'] if item['id'].split('_')[1] == tile)
                for band in ('red', 'nir', 'scl'):
                    path = next((FOLDER / 'source-crops').glob(f'{item["id"]}-{band}-*.tif'))
                    record = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
                    with rasterio.open(path) as cached, rasterio.open(item['assets'][band]['href']) as remote:
                        column, row = cached.width//2, cached.height//2
                        offset_x, offset_y = record['source_window'][:2]
                        actual = cached.read(1, window=Window(column, row, 4, 4))
                        expected = remote.read(1, window=Window(column+offset_x, row+offset_y, 4, 4))
                        assert actual.any(), 'Provenance probe must contain original observed DN'
                        np.testing.assert_array_equal(actual, expected)
