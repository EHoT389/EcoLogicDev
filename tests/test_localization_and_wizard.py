import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader
from backend.main import app
from backend.data import ZONES
from backend.analytics import analyze
from backend.schemas import AnalysisInput
from backend.localization import MESSAGES
from backend.reports import export_pdf,export_xlsx

def test_kazakh_errors_and_validation_do_not_expose_inputs():
 with TestClient(app) as c:
  h={'Accept-Language':'kk-KZ,ru;q=0.5'}
  assert c.get('/api/projects',headers=h).json()['detail']=='Аккаунтқа кіріңіз'
  r=c.post('/api/auth/login',json={'email':'bad','password':'private'},headers=h)
  assert r.status_code==422
  assert 'Құпиясөз' in r.json()['detail'] and 'private' not in r.text
  assert r.headers['content-language']=='kk'
  r=c.post('/api/analysis',json={'geometry':ZONES[0]['geometry'],'years':4},headers=h)
  assert r.status_code==422 and 'Мерзім' in r.json()['detail']
  r=c.post('/api/analysis',json={'geometry':{'type':'Point','coordinates':[76.95,52.28]}},headers=h)
  assert r.json()['detail']=='Polygon немесе MultiPolygon қажет'

def test_wizard_goals_respect_hard_safety_rules_and_zero_budget():
 base=AnalysisInput(geometry=ZONES[-1]['geometry']).model_dump()
 normal=analyze(base);shade=analyze({**base,'goal':'shade'})
 assert any(a['score']!=b['score'] for a in normal['recommendations'] for b in shade['recommendations'] if a['id']==b['id'])
 children=analyze({**base,'goal':'children'})
 assert all(p['excluded'] for p in children['recommendations'] if p['id'] in ('birch','caragana'))
 assert not any(p['id'] in ('birch','caragana') for p in children['plan'])
 empty=analyze({**base,'budget':0,'goal':'low_maintenance'})
 assert empty['total_plants']==0 and empty['estimate']['total']==0
 assert shade['estimate']['within_budget']

def test_address_landmarks_are_reproducible_osm_names():
 ways={str(s['id']):s for s in json.loads(Path('backend/assets/osm-streets.raw.json').read_text(encoding='utf-8'))['elements']}
 for zone in ZONES:
  assert zone['address_kind']=='nearby_streets' and zone['address_ru'] and zone['address_kk']
  for s in zone['nearby_streets']:
   tags=ways[s['source'].rsplit('/',1)[-1]]['tags']
   assert s['ru']==tags.get('name:ru',tags['name'])
   assert s['kk']==tags.get('name:kk',tags['name'])
   assert s['distance_m']>=0

def test_kazakh_reports_keep_numbers_and_user_title():
 result=analyze(AnalysisInput(geometry=ZONES[-1]['geometry'],goal='shade').model_dump())
 project=SimpleNamespace(name='Жасыл аула — жеке атау',updated='2026-10-29',result=result)
 wb=load_workbook(BytesIO(export_xlsx(project,'kk')))
 assert wb.sheetnames==['Смета','Экология','Дереккөздер']
 assert wb['Смета']['B1'].value==project.name and wb['Смета']['A4'].value=='Шығын бабы'
 assert wb['Смета']['E13'].value==result['estimate']['total']
 pdf=PdfReader(BytesIO(export_pdf(project,'kk')))
 content='\n'.join(p.extract_text() for p in pdf.pages)
 assert project.name in content and 'Отырғызу құрамы мен әдістеме' in content
 assert 'Предварительная экспертная оценка' not in content
 assert len(pdf.pages)==2

def test_all_generated_explanations_have_kazakh_translations():
 r=analyze(AnalysisInput(geometry=ZONES[-1]['geometry'],goal='road',irrigation=False,maintenance=.2).model_dump())
 texts=r['warnings']+r['risks']+[r['placement_status'],r['estimate']['formula'],r['estimate']['source'],r['coefficient_snapshot']['source']]
 for p in r['recommendations']: texts += p['reasons']+[p['safety'],p['stock']]
 assert all(t in MESSAGES for t in texts)

def test_chat_passes_requested_kazakh_language_and_street_context(monkeypatch):
 from backend.ai import router
 seen=[]
 async def fake(message,context,db,actor,language=None):
  seen.append((language,context))
  return {'answer':'Аумақты тексеріңіз.','model':'test:free','cloud':True}
 monkeypatch.setattr(router,'chat',fake)
 zone=ZONES[-1]
 with TestClient(app) as c:
  r=c.post('/api/ai/chat',json={'message':'Не істеу керек?','language':'kk','analysis':{'zone_id':zone['id'],'geometry':zone['geometry']}})
  assert r.status_code==200
  assert seen[0][0]=='kk' and seen[0][1]['selected_zone']['nearby_streets']==zone['nearby_streets']
