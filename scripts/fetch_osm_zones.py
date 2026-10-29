"""One bounded read-only Overpass snapshot; no runtime dependency on Overpass."""
from pathlib import Path
import json,sys
import httpx
query='''[out:json][timeout:45];
(
 way["leisure"="park"](52.25,76.91,52.33,77.03);
 way["leisure"="garden"](52.25,76.91,52.33,77.03);
 way["landuse"="forest"](52.25,76.91,52.33,77.03);
 way["natural"="wood"](52.25,76.91,52.33,77.03);
 way["landuse"="grass"](52.25,76.91,52.33,77.03);
 way["landuse"="brownfield"](52.25,76.91,52.33,77.03);
);
out geom;'''
url=sys.argv[1] if len(sys.argv)>1 else 'https://overpass-api.de/api/interpreter'
with httpx.Client(timeout=60) as client:
 response=client.post(url,data={'data':query},headers={'User-Agent':'EcoLogicDev-local-MVP/1.0 (OSM data snapshot for Pavlodar)'})
 response.raise_for_status();data=response.json()
folder=Path('backend/assets');folder.mkdir(exist_ok=True)
(folder/'osm-pavlodar.raw.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
print('OSM objects:',len(data.get('elements',[])))
for x in data.get('elements',[]):
 if x.get('tags',{}).get('name'): print(x['id'],json.dumps(x['tags'],ensure_ascii=True))
