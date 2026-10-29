import pytest
import asyncio,time,json
import httpx
from fastapi import HTTPException
from backend.ai import AIModelRouter
from backend.imports import import_layer

def test_free_model_gate():
 good={'id':'example:free','pricing':{'prompt':'0','completion':'0','request':'0'}}
 assert AIModelRouter.is_free(good)
 assert AIModelRouter.is_free({**good,'id':'openrouter/free'})
 assert not AIModelRouter.is_free({**good,'id':'paid-model'})
 assert not AIModelRouter.is_free({**good,'pricing':{'prompt':'0','completion':'0.001'}})
 assert not AIModelRouter.is_free({**good,'pricing':{}})

def test_import_validation():
 with pytest.raises(HTTPException): import_layer('bad.csv',b'longitude,latitude\n0,0')
 with pytest.raises(HTTPException): import_layer('bad.kml',b'<!DOCTYPE foo><kml/>')
 with pytest.raises(HTTPException): import_layer('bad.zip',b'not a zip')
 r=import_layer('good.geojson',b'{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[76.9,52.2]},"properties":{}}]}')
 assert r['features'][0]['properties']['provenance']=='imported_unverified'

def test_retry_after_stops_all_fallback_attempts(monkeypatch):
 from backend.db import init_db,SessionLocal
 init_db();monkeypatch.setenv('OPENROUTER_API_KEY','test-key-not-a-real-credential')
 attempts=[]
 def handle(request):
  body=json.loads(request.content)
  assert body['provider']['max_price']=={'prompt':0,'completion':0}
  assert body['model'].endswith(':free')
  attempts.append(body['model'])
  return httpx.Response(429,json={'error':{'message':'Rate limited'}},headers={'Retry-After':'120'})
 mock_client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
 monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:mock_client)
 model_router=AIModelRouter();model_router.models=[{'id':'test-one:free'},{'id':'test-two:free'}];model_router.expires=time.time()+60
 with SessionLocal() as db:
  with pytest.raises(HTTPException) as error: asyncio.run(model_router.chat('Test',{},db,'test-actor'))
  assert error.value.status_code==429
  assert error.value.headers['Retry-After']=='120'
 assert attempts==['test-one:free']
 assert model_router.global_cooldown>time.time()+110

def test_model_specific_forbidden_falls_back_to_different_free_publisher(monkeypatch):
 from backend.db import init_db,SessionLocal
 init_db();monkeypatch.setenv('OPENROUTER_API_KEY','test-key-not-a-real-credential')
 attempted=[]
 def handle(request):
  body=json.loads(request.content);attempted.append(body['model'])
  assert body['provider']['max_price']=={'prompt':0,'completion':0}
  if body['model']=='publisher-a/blocked:free':return httpx.Response(403,json={'error':{'message':'Model access denied'}})
  return httpx.Response(200,json={'choices':[{'message':{'content':'Проверьте почву и коммуникации.'}}],'usage':{'cost':0}})
 mock_client=httpx.AsyncClient(transport=httpx.MockTransport(handle));monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:mock_client)
 model_router=AIModelRouter();model_router.models=[{'id':'publisher-a/blocked:free'},{'id':'publisher-a/also-blocked:free'},{'id':'publisher-b/available:free'}];model_router.expires=time.time()+60
 with SessionLocal() as db: answer=asyncio.run(model_router.chat('Test',{},db,'test-actor'))
 assert attempted==['publisher-a/blocked:free','publisher-b/available:free']
 assert answer['model']=='publisher-b/available:free'
 assert answer['cloud']
