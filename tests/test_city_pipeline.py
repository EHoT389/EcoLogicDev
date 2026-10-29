"""Small, explicitly synthetic fixtures validate the block algorithm, never product data."""
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box, mapping

from backend.monitoring import city_pipeline as pipeline
from backend.monitoring.core import NODATA


def test_city_grid_preserves_administrative_shape_and_limits():
    boundary = {'type': 'Feature', 'geometry': mapping(box(76.94, 52.28, 76.941, 52.281)), 'properties': {}}
    grid = pipeline.city_grid(boundary)
    assert grid['crs'].to_epsg() == 32643
    assert grid['transform'].a == 10 and grid['transform'].e == -10
    masks = [pipeline.aoi_mask(grid, window) for window in pipeline.windows(grid, 128)]
    assert sum(int(mask.sum()) for mask in masks) > 0
    with pytest.raises(ValueError): pipeline.city_grid(boundary, max_pixels=1)
    with pytest.raises(ValueError): list(pipeline.windows(grid, 511))


def test_adjacent_mgrs_tiles_are_not_duplicate_observations():
    def scene(id, date, platform='sentinel-2a'):
        return {'id': id, 'properties': {'datetime': date, 'platform': platform}}
    groups = pipeline.group_acquisitions([
        scene('tile-A', '2020-06-15T06:00:00Z'), scene('tile-B', '2020-06-15T06:00:01Z'),
        scene('next-date', '2020-06-20T06:00:00Z')])
    assert len(groups) == 2 and len(groups[0][1]) == 2


def test_block_products_resume_mask_clouds_and_compute_native_pixel_areas(tmp_path, monkeypatch):
    """Fixture has two dates/two tiles, one cloud cell and one loss cell."""
    transform = from_origin(632000, 5796000, 10, 10)
    area = box(632000, 5795960, 632040, 5796000).difference(box(632000, 5795990, 632010, 5796000))
    grid = {'width': 4, 'height': 4, 'crs': rasterio.crs.CRS.from_epsg(32643),
            'transform': transform, 'projected_geometry': mapping(area)}
    sources = {}
    scenes = {}
    for year in (2020, 2026):
        scenes[year] = []
        for date in ('06-15', '07-15'):
            for tile in ('A', 'B'):
                id = f'explicit-test-fixture-{year}-{date}-{tile}'
                item = {'id': id, 'properties': {'datetime': f'{year}-{date}T06:00:00Z', 'platform': 'fixture',
                        's2:processing_baseline': '02.14'}, 'assets': {}}
                red = np.full((4, 4), 1000, dtype='uint16')
                nir = np.full((4, 4), 3000, dtype='uint16')
                scl = np.full((4, 4), 4, dtype='uint16')
                if tile == 'A': red[:, 2:] = 0; nir[:, 2:] = 0
                else: red[:, :1] = 0; nir[:, :1] = 0
                if year == 2020: scl[1, 1] = 8
                if year == 2026: red[2, 2], nir[2, 2] = 3000, 1000
                for band, values in [('red', red), ('nir', nir), ('scl', scl)]:
                    path = tmp_path / f'{id}-{band}.tif'
                    with rasterio.open(path, 'w', driver='GTiff', crs=grid['crs'], transform=transform,
                                       width=4, height=4, count=1, dtype='uint16', nodata=0) as raster:
                        raster.write(values, 1)
                    sources[id, band] = path
                    item['assets'][band] = {'href': 'https://explicit-test-fixture.invalid/' + path.name,
                                            'raster:bands': [{'scale': .0001, 'offset': 0}]}
                scenes[year].append(item)
    monkeypatch.setattr(pipeline, 'ensure_crop', lambda item, band, *args: sources[item['id'], band])
    for year in (2020, 2026):
        pipeline.process_year(year, scenes[year], {}, grid, tmp_path, 'explicit-fixture-v1', 128)
    with rasterio.open(tmp_path / 'count_2020.tif') as raster:
        counts = raster.read(1)
        assert counts[0, 0] == 0 and counts[1, 1] == 0
        assert counts[3, 3] == 2  # Four tile files represent only two dates.
    with rasterio.open(tmp_path / 'ndvi_2020.tif') as raster:
        values = raster.read(1)
        assert values[0, 0] == NODATA and values[1, 1] == NODATA
        assert values[3, 3] == pytest.approx(.5, abs=1e-6)
    # Re-running a completed year uses validated per-block checkpoints.
    monkeypatch.setattr(pipeline, 'observation_block', lambda *args: (_ for _ in ()).throw(AssertionError('cache not used')))
    pipeline.process_year(2020, scenes[2020], {}, grid, tmp_path, 'explicit-fixture-v1', 128)
    statistics, coverage = pipeline.final_statistics_and_changes(grid, tmp_path, 128)
    assert coverage['total_aoi_pixels'] == 15 and coverage['common_valid_pixels'] == 14
    assert coverage['years']['2020']['valid_fraction'] == pytest.approx(14 / 15)
    assert coverage['years']['2026']['valid_fraction'] == 1
    assert statistics['vegetation_2020_ha'] == .14
    assert statistics['vegetation_2026_ha'] == .13
    assert statistics['loss_ha'] == .01 and statistics['gain_ha'] == 0
    assert statistics['net_change_ha'] == -.01
    with rasterio.open(tmp_path / 'changes.tif') as raster:
        classified = raster.read(1)
        assert classified[0, 0] == 255 and classified[1, 1] == 255 and classified[2, 2] == 2
