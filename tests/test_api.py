import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from backend.main import app
from backend.db import SessionLocal,User
from backend.data import ZONES

@pytest.fixture
def client():
 with TestClient(app) as c: yield c

def register(client,email):
 r=client.post('/api/auth/register',json={'email':email,'password':'test-password-very-long','name':'Test'})
 assert r.status_code==200,r.text
 return r.json()

def test_auth_ownership_csrf_and_exports(client):
 a=register(client,'alice@example.com');csrf={'X-CSRF-Token':a['csrf']}
 payload={'name':'Тест =1+1','payload':{'geometry':ZONES[0]['geometry']}}
 assert client.post('/api/projects',json=payload).status_code==403
 saved=client.post('/api/projects',json=payload,headers=csrf)
 assert saved.status_code==200,saved.text
 id=saved.json()['id']
 assert client.get('/api/reports/'+id+'/pdf').content.startswith(b'%PDF')
 assert client.get('/api/reports/'+id+'/xlsx').content.startswith(b'PK')
 assert client.get('/api/admin').status_code==403
 assert client.post('/api/auth/logout',headers=csrf).status_code==200
 assert client.get('/api/projects/'+id).status_code==401
 b=register(client,'bob@example.com')
 assert client.get('/api/projects/'+id).status_code==404
 assert client.put('/api/projects/'+id,json=payload,headers={'X-CSRF-Token':b['csrf']}).status_code==404
 assert client.get('/api/reports/'+id+'/pdf').status_code==404

def test_analysis_and_ai_without_key(client):
 r=client.post('/api/analysis',json={'geometry':ZONES[0]['geometry']});assert r.status_code==200,r.text
 assert r.json()['version']
 assert client.post('/api/ai/chat',json={'message':'test'}).status_code==503
 assert client.post('/api/analysis',json={'geometry':ZONES[0]['geometry'],'years':4}).status_code==422
 assert client.post('/api/analysis',json={'geometry':ZONES[0]['geometry']},headers={'Origin':'https://evil.example'}).status_code==403
 assert client.post('/api/analysis',json={'geometry':ZONES[0]['geometry']},headers={'Origin':'http://127.0.0.1:4173'}).status_code==200

def test_admin_import_and_audit(client):
 data=register(client,'admin-test@example.com')
 with SessionLocal() as db:
  u=db.scalar(select(User).where(User.email=='admin-test@example.com'));u.role='admin';db.commit()
 h={'X-CSRF-Token':data['csrf']}
 r=client.post('/api/admin/layers/import',files={'file':('points.csv',b'longitude,latitude,name\n76.95,52.29,Test','text/csv')},headers=h)
 assert r.status_code==200,r.text
 assert r.json()['status']=='unverified'
 assert client.put('/api/admin/layers/'+r.json()['id']+'/publish',headers=h).status_code==200
 assert client.get('/api/admin').json()['events'][0]['kind']=='layer_publish'

def test_zone_catalog_has_real_outlines_and_distinct_statuses(client):
 zones=client.get('/api/zones').json()
 assert len([z for z in zones if z['status']=='existing_green'])==8
 assert len([z for z in zones if z['status']=='planting_candidate'])==4
 assert all(z['source'].startswith('https://www.openstreetmap.org/way/') for z in zones)
 assert all(z['assessment_provenance']=='synthetic' for z in zones)
 assert all(z['area_m2']>0 for z in zones)

def test_personal_names_persist_and_are_private(client):
 assert client.get('/api/zones/names').status_code==401
 a=register(client,'zone-names-alice@example.com');h={'X-CSRF-Token':a['csrf']}
 path='/api/zones/'+ZONES[0]['id']+'/name';names={'ru':'Мой зелёный двор','kk':'Менің жасыл аулам'}
 assert client.put(path,json=names).status_code==403
 assert client.put(path,json=names,headers=h).status_code==200
 assert client.get('/api/zones/names').json()[ZONES[0]['id']]==names
 assert client.put(path,json={'ru':'   ','kk':'Test'},headers=h).status_code==422
 assert client.get('/api/zones').json()[0]['ru']==ZONES[0]['ru']
 client.post('/api/auth/logout',headers=h)
 register(client,'zone-names-bob@example.com')
 assert client.get('/api/zones/names').json()=={}

def test_chat_receives_selected_zone_and_isolates_history(client,monkeypatch):
 from backend.ai import router
 seen=[]
 async def fake_chat(message,context,db,actor,language=None):
  assert language=='ru'
  seen.append(context)
  return {'answer':'Проверьте участок на месте.','model':'test:free','cloud':True}
 monkeypatch.setattr(router,'chat',fake_chat)
 data=register(client,'zone-chat@example.com');h={'X-CSRF-Token':data['csrf']}
 for index in [0,1]:
  z=ZONES[index]
  analysis={'geometry':z['geometry'],'zone_id':z['id'],'zone_name':'Личное название '+str(index)}
  r=client.post('/api/ai/chat',json={'message':'Что проверить?','analysis':analysis},headers=h)
  assert r.status_code==200,r.text
  assert seen[-1]['selected_zone']['id']==z['id']
  assert seen[-1]['selected_zone']['name']==analysis['zone_name']
  assert seen[-1]['selected_zone']['status']==z['status']
  assert 'positions' not in seen[-1]
 history=client.get('/api/ai/history',params={'zone_id':ZONES[0]['id']}).json()
 assert len(history)==1 and history[0]['zone_id']==ZONES[0]['id']
 wrong={'geometry':ZONES[1]['geometry'],'zone_id':ZONES[0]['id'],'zone_name':'Mismatch'}
 assert client.post('/api/analysis',json=wrong).status_code==422

