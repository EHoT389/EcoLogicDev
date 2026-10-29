"""Fetch the verified OSM Pavlodar city-administration AOI, without inventing a rectangle.

One Nominatim lookup per explicit refresh; responses are cached locally. Public
Nominatim policy: https://operations.osmfoundation.org/policies/nominatim/
This is a bounded, one-off extraction, never an autocomplete or recurring job.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import httpx
from pyproj import Geod, Transformer
from shapely.geometry import shape
from shapely.geometry.polygon import orient
from shapely.ops import transform
from shapely.validation import explain_validity

ROOT = Path(__file__).resolve().parents[1]
RELATION_ID = 5501700
UA = 'EcoLogicDev-local-monitoring/4.0 (Pavlodar administrative boundary extraction)'
LOOKUP = 'https://nominatim.openstreetmap.org/lookup'
RELATION_URL = f'https://api.openstreetmap.org/api/0.6/relation/{RELATION_ID}.json'
SOURCE_URL = f'https://www.openstreetmap.org/relation/{RELATION_ID}'
GEOD = Geod(ellps='WGS84')


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def prepare_boundary(place, relation, retrieved_at=None):
    """Pure validation/metadata assembly; rejects province/place-only substitutions."""
    if place.get('osm_type') != 'relation' or place.get('osm_id') != RELATION_ID:
        raise ValueError('Expected verified OSM relation 5501700, not a settlement way or province')
    if relation.get('type') != 'relation' or relation.get('id') != RELATION_ID:
        raise ValueError('Native OSM relation identity differs from the geometry source')
    tags = relation.get('tags', {})
    if tags.get('boundary') != 'administrative' or tags.get('admin_level') != '6':
        raise ValueError('The selected object must be the admin_level=6 administrative boundary')
    geometry = place.get('geojson', {})
    polygon = shape(geometry)
    if polygon.geom_type not in ('Polygon', 'MultiPolygon') or polygon.is_empty or not polygon.is_valid:
        raise ValueError('Invalid administrative geometry: ' + explain_validity(polygon))
    west, south, east, north = polygon.bounds
    if not (76 < west < east < 78 and 51 < south < north < 54):
        raise ValueError('The administrative geometry is outside the expected Pavlodar region')
    if not polygon.covers(shape({'type': 'Point', 'coordinates': [76.95, 52.285]})):
        raise ValueError('Administrative polygon does not contain central Pavlodar')
    parts = list(polygon.geoms) if polygon.geom_type == 'MultiPolygon' else [polygon]
    geodesic_km2 = sum(abs(GEOD.geometry_area_perimeter(orient(part, sign=1))[0]) for part in parts) / 1e6
    projected = transform(Transformer.from_crs(4326, 32643, always_xy=True).transform, polygon)
    if not 100 < geodesic_km2 < 2000:
        raise ValueError('Unexpected city-administration area; manual source review required')
    date = retrieved_at or datetime.now(timezone.utc).isoformat()
    metadata = {
        'id': f'osm-relation-{RELATION_ID}',
        'scope': 'administrative_city',
        'name_ru': tags.get('name:ru', tags.get('name')),
        'name_kk': tags.get('name:kk', tags.get('name')),
        'display_name_ru': 'Павлодар — территория городской администрации',
        'display_name_kk': 'Павлодар — қалалық әкімдік аумағы',
        'boundary': 'administrative',
        'admin_level': 6,
        'source': {'provider': 'OpenStreetMap contributors', 'osm_type': 'relation', 'osm_id': RELATION_ID,
                   'url': SOURCE_URL, 'api_url': RELATION_URL, 'version': relation.get('version'),
                   'object_timestamp': relation.get('timestamp'), 'geometry_service': LOOKUP,
                   'retrieved_at': date},
        'coordinate_reference_system': 'EPSG:4326',
        'coordinate_order': 'longitude,latitude',
        'area_crs': 'EPSG:32643',
        'area_km2_geodesic': geodesic_km2,
        'area_km2_projected': projected.area / 1e6,
        'bbox_wgs84': list(polygon.bounds),
        'geometry_type': polygon.geom_type,
        'components': len(parts),
        'valid': True,
        'validation': explain_validity(polygon),
        'geometry_sha256': hashlib.sha256(json_bytes(geometry)).hexdigest(),
        'license': {'name': 'ODbL 1.0', 'url': 'https://www.openstreetmap.org/copyright',
                    'attribution': '© OpenStreetMap contributors'},
        'selection_reason_ru': 'Выбрана административная relation городской администрации. Граница включает город и подчинённые территории; она не равна только застроенной части.',
        'selection_reason_kk': 'Қалалық әкімдіктің әкімшілік relation шекарасы таңдалды. Ол қала мен бағынысты аумақтарды қамтиды; тек салынған бөліктің шекарасы емес.',
        'rejected_alternatives': [
            {'osm_type': 'relation', 'osm_id': 215772, 'reason': 'Pavlodar Region/province, not the city administration'},
            {'osm_type': 'way', 'osm_id': 170089891, 'reason': 'place=city settlement polygon, not an administrative boundary'}
        ],
        'limitations_ru': 'Открытая картографическая граница OSM, не кадастровое или юридическое удостоверение. Незастроенные части и отдельные компоненты также входят в AOI.',
        'limitations_kk': 'OSM ашық картографиялық шекарасы; кадастрлық немесе заңдық куәлік емес. Салынбаған бөліктер мен бөлек компоненттер де AOI құрамына кіреді.'
    }
    feature = {'type': 'Feature', 'id': metadata['id'], 'bbox': list(polygon.bounds),
               'properties': metadata, 'geometry': geometry}
    return feature, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', help='Explicitly re-fetch the two public source records')
    parser.add_argument('--cache-dir', type=Path, default=ROOT / 'output' / 'qa' / 'boundary-source')
    args = parser.parse_args()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    place_path, relation_path = args.cache_dir / 'nominatim.json', args.cache_dir / 'relation.json'
    if args.refresh or not (place_path.exists() and relation_path.exists()):
        with httpx.Client(timeout=50, headers={'User-Agent': UA, 'Accept-Language': 'ru,kk,en'}) as client:
            response = client.get(LOOKUP, params={'osm_ids': f'R{RELATION_ID}', 'format': 'jsonv2',
                'polygon_geojson': 1, 'addressdetails': 1, 'extratags': 1})
            response.raise_for_status()
            places = response.json()
            if len(places) != 1:
                raise ValueError('The verified relation geometry is unavailable; no substitute created')
            response = client.get(RELATION_URL)
            response.raise_for_status()
            relations = response.json().get('elements', [])
            relation = next(v for v in relations if v.get('type') == 'relation' and v.get('id') == RELATION_ID)
        place_path.write_text(json.dumps(places, ensure_ascii=False, indent=2), encoding='utf-8')
        relation_path.write_text(json.dumps(relation, ensure_ascii=False, indent=2), encoding='utf-8')
    places = json.loads(place_path.read_text(encoding='utf-8'))
    relation = json.loads(relation_path.read_text(encoding='utf-8'))
    feature, metadata = prepare_boundary(places[0], relation)
    zones_path = ROOT / 'backend' / 'assets' / 'pavlodar-zones.json'
    if zones_path.exists():
        boundary = shape(feature['geometry'])
        zones = json.loads(zones_path.read_text(encoding='utf-8'))
        metadata['zone_validation'] = {z['id']: boundary.covers(shape(z['geometry'])) for z in zones}
        if not all(metadata['zone_validation'].values()):
            raise ValueError('Existing reference zones fall outside administrative geometry; review source')
    target = ROOT / 'backend' / 'assets'
    (target / 'pavlodar-boundary.geojson').write_text(json.dumps(feature, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (target / 'pavlodar-boundary.metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'id': metadata['id'], 'bbox': metadata['bbox_wgs84'], 'area_km2_geodesic': metadata['area_km2_geodesic'],
                      'area_km2_projected': metadata['area_km2_projected'], 'valid': metadata['valid'], 'components': metadata['components']}))


if __name__ == '__main__':
    main()
