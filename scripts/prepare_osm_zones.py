"""Curate actual OSM outlines; suggested planting status is an explicitly unverified inference."""
from pathlib import Path
import json
from shapely.geometry import Polygon,mapping
from pyproj import Geod
raw=json.loads(Path('backend/assets/osm-pavlodar.raw.json').read_text(encoding='utf-8'))
geod=Geod(ellps='WGS84');objects=[]
for item in raw['elements']:
 points=[[p['lon'],p['lat']] for p in item.get('geometry',[])]
 if len(points)<4 or points[0]!=points[-1]: continue
 polygon=Polygon(points)
 if not polygon.is_valid: continue
 area=abs(geod.geometry_area_perimeter(polygon)[0])
 if not 300<=area<=1_000_000: continue
 objects.append((item,polygon,area))
def distance(o): return (o[1].centroid.x-76.95)**2*.4+(o[1].centroid.y-52.285)**2
parks=sorted([o for o in objects if o[0]['tags'].get('leisure')=='park' and o[0]['tags'].get('name')],key=distance)[:8]
all_parks=[o[1] for o in objects if o[0]['tags'].get('leisure') in ('park','garden')]
candidates=[]
for o in sorted(objects,key=distance):
 if o[0]['tags'].get('landuse') not in ('grass','brownfield') or not 1200<=o[2]<=25000: continue
 if any(o[1].intersection(p).area/o[1].area>.05 for p in all_parks): continue
 if any(o[1].distance(p[1])<.0018 for p in candidates): continue
 candidates.append(o)
 if len(candidates)==4: break
zones=[]
for status,group in [('existing_green',parks),('planting_candidate',candidates)]:
 for i,(obj,poly,area) in enumerate(group):
  tags=obj['tags'];original=tags.get('name:ru',tags.get('name',''))
  ru=original if status=='existing_green' else f'Участок для оценки посадок №{i+1}'
  kk=tags.get('name:kk',tags.get('name',ru)) if status=='existing_green' else f'Отырғызуды бағалау аумағы №{i+1}'
  center=poly.representative_point()
  zones.append({'id':f'osm-way-{obj["id"]}','ru':ru,'kk':kk,'original_name':original or 'Без названия в OSM','geometry':mapping(poly),'area_m2':round(area,1),'status':status,'provenance':'osm','assessment_provenance':'synthetic','source':f'https://www.openstreetmap.org/way/{obj["id"]}','source_date':'2026-10-29','osm_tags':tags,'center':[center.x,center.y],'green':.7 if status=='existing_green' else .25,'soil':'loam','moisture':.4,'salinity':.2,'traffic':.4,'temperature':-38,'light':'sun','heat':None,'social':.5,'population':None,'status_note':'Зелёная территория по OpenStreetMap; инвентаризация деревьев не проводилась.' if status=='existing_green' else 'Предложение для обследования открытой территории по OSM. Отсутствие деревьев, право посадки и отсутствие коммуникаций не подтверждены.'})
Path('backend/assets/pavlodar-zones.json').write_text(json.dumps(zones,ensure_ascii=False,indent=2),encoding='utf-8')
print('Existing green:',len(parks),'Planting candidates:',len(candidates))
for z in zones: print(z['id'],z['status'],z['area_m2'],z['center'])
