"""Catalog selection tests use labelled synthetic metadata, never production pixels."""
from copy import deepcopy
from pathlib import Path
import json

import httpx
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds
from shapely.geometry import box, mapping

from backend.monitoring.city_catalog import search_city, select_city_scenes, tile_code, load_boundary
from backend.monitoring import city_catalog


def boundary():
    return {'type': 'Feature', 'geometry': mapping(box(76.9, 52.2, 77.1, 52.4)),
            'properties': {'scope': 'administrative_city', 'boundary': 'administrative'}}


def fixture_item(id, tile='43UFT', date='2020-06-15', cloud=2, baseline='02.14', footprint=None):
    assets = {band: {'href': f'https://sentinel-cogs.s3.us-west-2.amazonaws.com/test-only/{id}/{band}.tif',
                     'raster:bands': [{'scale': .0001, 'offset': 0}]} for band in ('red', 'nir', 'scl')}
    return {'id': id, 'type': 'Feature', 'geometry': mapping(footprint or box(76.8, 52.1, 77.2, 52.5)),
            'properties': {'datetime': date + 'T06:00:00Z', 'eo:cloud_cover': cloud,
                           'grid:code': 'MGRS-' + tile, 's2:processing_baseline': baseline,
                           'earthsearch:boa_offset_applied': False}, 'assets': assets}


def test_city_catalog_follows_all_pages_and_uses_actual_polygon(tmp_path):
    first = fixture_item('fixture-first')
    second = fixture_item('fixture-second', tile='43UFU', date='2020-07-15')
    outside = fixture_item('fixture-outside', footprint=box(76.5, 52.0, 76.6, 52.1))
    seen = []
    def handle(request):
        body = json.loads(request.content)
        seen.append(body)
        if body.get('next'):
            return httpx.Response(200, json={'features': [second, outside], 'links': []})
        return httpx.Response(200, json={'features': [first], 'links': [
            {'rel': 'next', 'href': 'https://earth-search.aws.element84.com/v1/search',
             'method': 'POST', 'merge': True, 'body': {'next': 'page-2'}}]})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        features = search_city(boundary(), 2020, tmp_path, client=client)
    assert [item['id'] for item in features] == ['fixture-first', 'fixture-second']
    assert len(seen) == 2 and seen[1]['collections'] == ['sentinel-2-l2a']
    assert seen[1]['next'] == 'page-2'
    # Cached repeat must not need the network.
    assert search_city(boundary(), 2020, tmp_path) == features


def test_city_selection_covers_every_tile_and_deduplicates_processing():
    features = []
    for tile in ('43UFT', '43UFU'):
        for month in (6, 7, 8):
            for day, cloud in ((1, 1), (10, 2), (20, 20)):
                features.append(fixture_item(f'fixture-{tile}-{month}-{day}', tile, f'2020-{month:02d}-{day:02d}', cloud))
    reprocessed = deepcopy(features[0]); reprocessed['id'] = 'fixture-reprocessed'
    reprocessed['properties']['s2:processing_baseline'] = '03.01'; features.append(reprocessed)
    chosen = select_city_scenes(features, boundary())
    assert len(chosen) == 12
    assert {tile_code(item) for item in chosen} == {'43UFT', '43UFU'}
    assert 'fixture-reprocessed' in [item['id'] for item in chosen]
    assert features[0]['id'] not in [item['id'] for item in chosen]
    assert all(item['properties']['datetime'][8:10] != '20' for item in chosen)


def test_catalog_rejects_untrusted_bands_ambiguous_offsets_and_wrong_season(tmp_path):
    bad_host = fixture_item('fixture-host'); bad_host['assets']['red']['href'] = 'https://example.invalid/red.tif'
    ambiguous = fixture_item('fixture-offset', baseline='05.12'); ambiguous['properties'].pop('earthsearch:boa_offset_applied')
    wrong_month = fixture_item('fixture-winter', date='2020-12-15')
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        'features': [bad_host, ambiguous, wrong_month], 'links': []}))) as client:
        assert search_city(boundary(), 2020, tmp_path, client=client) == []


def test_pagination_cannot_follow_foreign_host(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        'features': [], 'links': [{'rel': 'next', 'href': 'https://example.invalid/search'}]}))) as client:
        with pytest.raises(ValueError, match='Untrusted'):
            search_city(boundary(), 2020, tmp_path, client=client)


def test_boundary_loader_requires_verified_administrative_polygon(tmp_path):
    path = tmp_path / 'boundary.geojson'; path.write_text(json.dumps(boundary()), encoding='utf-8')
    assert load_boundary(path)['properties']['scope'] == 'administrative_city'
    bad = boundary(); bad['properties']['boundary'] = 'place'; path.write_text(json.dumps(bad), encoding='utf-8')
    with pytest.raises(ValueError, match='verified'):
        load_boundary(path)


def test_cutout_is_raw_bounded_and_resumes_only_when_checksum_matches(tmp_path, monkeypatch):
    # Explicit local analytical source. It is never written into production caches.
    origin = from_origin(625000, 5800000, 10, 10)
    source_path = tmp_path / 'test-only-source.tif'
    values = np.arange(1_000_000, dtype=np.uint16).reshape(1000, 1000)
    with rasterio.open(source_path, 'w', driver='GTiff', width=1000, height=1000, count=1,
                       dtype='uint16', crs='EPSG:32643', transform=origin, nodata=0) as dst:
        dst.write(values, 1)
    full = transform_bounds('EPSG:32643', 'EPSG:4326', 625000, 5790000, 635000, 5800000)
    requested = transform_bounds('EPSG:32643', 'EPSG:4326', 628000, 5793000, 632000, 5797000)
    aoi = {'type': 'Feature', 'geometry': mapping(box(*requested)), 'properties': {}}
    item = fixture_item('fixture-cutout', footprint=box(*full))
    original_open = rasterio.open
    remote_reads = []
    def open_source(path, *args, **kwargs):
        if str(path).startswith('https://'):
            remote_reads.append(str(path))
            return original_open(source_path)
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(city_catalog.rasterio, 'open', open_source)
    crop = city_catalog.ensure_crop(item, 'red', aoi, tmp_path / 'cutouts')
    with original_open(crop) as result:
        assert 300 < result.width < 450 and 300 < result.height < 450
        assert result.crs.to_epsg() == 32643 and result.nodata == 0
        assert result.dtypes == ('uint16',)
        c = int(round((result.transform.c-origin.c)/10)); r = int(round((origin.f-result.transform.f)/10))
        assert np.array_equal(result.read(1), values[r:r+result.height, c:c+result.width])
    assert city_catalog.ensure_crop(item, 'red', aoi, tmp_path / 'cutouts') == crop
    assert len(remote_reads) == 1
    damaged = bytearray(crop.read_bytes()); damaged[-1] ^= 1; crop.write_bytes(damaged)
    city_catalog.ensure_crop(item, 'red', aoi, tmp_path / 'cutouts')
    assert len(remote_reads) == 2
