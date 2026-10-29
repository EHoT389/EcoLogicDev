"""Artificial tiny arrays are test fixtures only, not measured satellite results."""
import numpy as np
import pytest
from backend.monitoring.core import calculate_ndvi, quality_mask, median_composite, comparison_mask, classify_changes, compute_statistics
from backend.monitoring.pipeline import reflectance_conversion, grid_for_bbox, select_scenes


def test_ndvi_formula_quality_and_missing():
    assert calculate_ndvi([[.1]], [[.3]])[0, 0] == pytest.approx(.5)
    assert np.isnan(calculate_ndvi([[0]], [[0]])[0, 0])
    assert np.isnan(calculate_ndvi([[.1]], [[.3]], [[9]])[0, 0])
    assert quality_mask(np.arange(12)).tolist() == [False, False, False, False, True, True, True, False, False, False, False, False]
    with pytest.raises(ValueError):
        calculate_ndvi([[.1]], [[.2, .3]])


def test_median_counts_and_common_mask():
    a, count = median_composite([[[.1, np.nan]], [[.5, .2]], [[.3, np.nan]]])
    assert a[0, 0] == pytest.approx(.3)
    assert count.tolist() == [[3, 1]]
    assert comparison_mask(a, a, count, count).tolist() == [[True, False]]


def test_gain_loss_area_uses_common_valid_pixels():
    a = np.array([[.1, .7, .4, np.nan]])
    b = np.array([[.6, .1, .5, .8]])
    c = classify_changes(a, b)
    assert c.tolist() == [[1, 2, 0, 255]]
    r = compute_statistics(a, b)
    assert r['vegetation_2020_ha'] == .02 and r['vegetation_2026_ha'] == .02
    assert r['gain_ha'] == .01 and r['loss_ha'] == .01
    assert r['net_change_ha'] == 0 and r['comparable_fraction'] == .75
    r = compute_statistics(a, b, region_mask=[[True, False, False, True]])
    assert r['total_pixels'] == 2 and r['comparable_pixels'] == 1
    assert r['gain_ha'] == .01 and r['loss_ha'] == 0
    assert r['change_percent'] is None  # no vegetation baseline, never divide by zero


def test_missing_data_never_looks_like_measured_zero():
    r = compute_statistics([[np.nan]], [[.4]])
    assert r['status'] == 'no_data'
    assert r['vegetation_2020_ha'] is None and r['gain_ha'] is None and r['mean_ndvi_2026'] is None
    assert r['comparable_fraction'] == 0


def test_harmonization_never_subtracts_boa_offset_twice():
    asset = {'raster:bands': [{'scale': .0001, 'offset': -.1}]}
    def item(baseline, applied):
        return {'properties': {'s2:processing_baseline': baseline, 'earthsearch:boa_offset_applied': applied}}
    assert reflectance_conversion(item('02.14', False), asset) == (.0001, 0)
    assert reflectance_conversion(item('05.12', True), asset) == (.0001, 0)
    assert reflectance_conversion(item('05.00', False), asset) == (.0001, -.1)
    with pytest.raises(ValueError):
        reflectance_conversion(item('05.00', None), asset)


def test_grid_is_10m_aligned_and_bounded():
    grid = grid_for_bbox([76.925, 52.265, 76.985, 52.310])
    assert grid['transform'].a == 10 and grid['transform'].e == -10
    assert grid['width'] * grid['height'] < 1_000_000
    with pytest.raises(ValueError):
        grid_for_bbox([0, 0, 1, 1])


def test_scenes_deduplicate_same_acquisition_and_keep_season():
    def scene(id, date, baseline='02.14'):
        return {'id': id, 'properties': {'datetime': date, 'platform': 'sentinel-2a', 'grid:code': 'MGRS-43UFT', 's2:processing_baseline': baseline, 'eo:cloud_cover': 0}, 'assets': {'red': {}, 'nir': {}, 'scl': {}}}
    scenes = select_scenes([scene('old', '2020-07-01T00:00:00Z'), scene('new', '2020-07-01T00:00:00Z', '05.00'), scene('other', '2020-08-01T00:00:00Z')])
    assert [s['id'] for s in scenes] == ['new', 'other']
