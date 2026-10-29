"""Reproducible nearby-street landmarks, not postal addresses. Offline OSM snapshot."""
import json
from pathlib import Path
from shapely.geometry import Point,LineString
from shapely.ops import transform
from pyproj import Transformer

root=Path('backend/assets')
zones=json.loads((root/'pavlodar-zones.json').read_text(encoding='utf-8'))
streets=json.loads((root/'osm-streets.raw.json').read_text(encoding='utf-8'))['elements']
project=Transformer.from_crs(4326,32643,always_xy=True).transform
for zone in zones:
 point=transform(project,Point(zone['center']))
 nearest={}
 for street in streets:
  geom=street.get('geometry',[]);tags=street['tags']
  if len(geom)<2: continue
  distance=point.distance(transform(project,LineString([(n['lon'],n['lat']) for n in geom])))
  name=tags.get('name:ru',tags['name'])
  if name not in nearest or distance<nearest[name][0]: nearest[name]=(distance,street)
 candidates=sorted(nearest.values(),key=lambda v:v[0])[:2]
 candidates=[v for v in candidates if v[0]<max(180,candidates[0][0]+90)]
 zone['nearby_streets']=[{'ru':s['tags'].get('name:ru',s['tags']['name']),'kk':s['tags'].get('name:kk',s['tags']['name']),'distance_m':round(d/10)*10,'source':'https://www.openstreetmap.org/way/'+str(s['id'])} for d,s in candidates]
 zone['address_ru']=' / '.join(s['ru'] for s in zone['nearby_streets'])
 zone['address_kk']=' / '.join(s['kk'] for s in zone['nearby_streets'])
 zone['address_date']='2026-10-29'
 zone['address_kind']='nearby_streets'
 if zone['id']=='osm-way-1533348871': zone['kk']='Жұлдызнама белгілері саябағы'
(root/'pavlodar-zones.json').write_text(json.dumps(zones,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for z in zones: print(z['id']+' '+z['address_ru']+' | '+z['address_kk'])
