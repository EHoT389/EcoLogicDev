"""Small read-only diagnosis of public source range support; no whole scene."""
import json
import time
from pathlib import Path
import httpx

catalog=json.loads(Path('backend/storage/monitoring-city/selected-scenes.stac.json').read_text(encoding='utf-8'))
url=catalog['2020']['features'][0]['assets']['green']['href']
with httpx.Client(timeout=5) as client:
    for size in (4096,32768,65536,131072,262144):
        start=time.monotonic()
        try:
            response=client.get(url,headers={'Range':f'bytes=0-{size-1}'})
            print(size,response.status_code,len(response.content),response.headers.get('content-range'),round(time.monotonic()-start,2),flush=True)
        except httpx.HTTPError as error:
            print(size,type(error).__name__,round(time.monotonic()-start,2),flush=True)
