"""Checks against the actual OSM boundary asset, not synthetic city extents."""
import hashlib
import json
from pathlib import Path

import pytest
from pyproj import Geod, Transformer
from shapely.geometry import box, shape
from shapely.geometry.polygon import orient
from shapely.ops import transform

from scripts.fetch_pavlodar_boundary import prepare_boundary

ROOT = Path(__file__).resolve().parents[1]


def source_assets():
    folder = ROOT / 'backend' / 'assets'
    return (json.loads((folder / 'pavlodar-boundary.geojson').read_text(encoding='utf-8')),
            json.loads((folder / 'pavlodar-boundary.metadata.json').read_text(encoding='utf-8')))


def test_verified_administrative_identity_geometry_and_area():
    feature, metadata = source_assets()
    polygon = shape(feature['geometry'])
    assert polygon.is_valid and not polygon.is_empty and polygon.geom_type == 'MultiPolygon'
    assert metadata['source']['osm_id'] == 5501700 and metadata['source']['osm_type'] == 'relation'
    assert metadata['source']['version'] >= 28 and metadata['admin_level'] == 6
    assert metadata['boundary'] == 'administrative' and metadata['scope'] == 'administrative_city'
    assert metadata['coordinate_reference_system'] == 'EPSG:4326'
    assert metadata['license']['name'] == 'ODbL 1.0' and metadata['source']['url'].endswith('/relation/5501700')
    assert metadata['source']['retrieved_at'].startswith('2026-10-29')
    assert list(polygon.bounds) == metadata['bbox_wgs84']
    assert len(polygon.geoms) == metadata['components'] == 4
    area = sum(abs(Geod(ellps='WGS84').geometry_area_perimeter(orient(p, sign=1))[0]) for p in polygon.geoms) / 1e6
    projected = transform(Transformer.from_crs(4326, 32643, always_xy=True).transform, polygon).area / 1e6
    assert area == pytest.approx(metadata['area_km2_geodesic'], abs=1e-6)
    assert projected == pytest.approx(metadata['area_km2_projected'], abs=1e-6)
    assert area == pytest.approx(630.5952154729371, abs=1e-6)
    assert polygon.area < .7 * box(*polygon.bounds).area  # administrative outline, not its bounding rectangle
    digest = hashlib.sha256(json.dumps(feature['geometry'], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert digest == metadata['geometry_sha256'] == feature['properties']['geometry_sha256']


def test_all_existing_osm_reference_zones_are_inside_administrative_aoi():
    feature, metadata = source_assets()
    polygon = shape(feature['geometry'])
    zones = json.loads((ROOT / 'backend' / 'assets' / 'pavlodar-zones.json').read_text(encoding='utf-8'))
    assert len(zones) == 12
    assert all(polygon.covers(shape(z['geometry'])) for z in zones)
    assert metadata['zone_validation'] == {z['id']: True for z in zones}


def test_validation_rejects_province_settlement_and_invalid_geometry_substitutions():
    feature, metadata = source_assets()
    place = {'osm_type': 'relation', 'osm_id': 5501700, 'geojson': feature['geometry']}
    relation = {'type': 'relation', 'id': 5501700, 'tags': {'boundary': 'administrative', 'admin_level': '6'}}
    for wrong in ({**place, 'osm_id': 215772}, {**place, 'osm_type': 'way', 'osm_id': 170089891},
                  {**place, 'geojson': {'type': 'Point', 'coordinates': [76.95, 52.28]}}):
        with pytest.raises(ValueError):
            prepare_boundary(wrong, relation)
    with pytest.raises(ValueError):
        prepare_boundary(place, {**relation, 'tags': {'boundary': 'administrative', 'admin_level': '4'}})
