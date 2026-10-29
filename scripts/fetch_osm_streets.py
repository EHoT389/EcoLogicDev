"""Bounded read-only snapshot of named Pavlodar streets for offline zone landmarks."""
from pathlib import Path
import json
import httpx
query='''[out:json][timeout:45];way["highway"]["name"]["highway"!~"^(footway|path|steps|cycleway|service|track)$"](52.25,76.91,52.33,77.03);out geom;'''
with httpx.Client(timeout=55) as client:
 for endpoint in ['https://overpass-api.de/api/interpreter','https://overpass.kumi.systems/api/interpreter']:
  try:
   response=client.post(endpoint,data={'data':query},headers={'User-Agent':'EcoLogicDev-local-MVP/1.0 (Pavlodar street landmarks)'})
   response.raise_for_status();data=response.json();break
  except httpx.HTTPError:
   if 'kumi' in endpoint: raise
Path('backend/assets/osm-streets.raw.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
print('Named street segments:',len(data.get('elements',[])))
