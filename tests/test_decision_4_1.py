"""4.1 acceptance: real calculator, isolated accounts, bounded memory, honest fallback."""
from copy import deepcopy
import json
from io import BytesIO
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.main import app
from backend.schemas import AnalysisInput,MapState
from backend.data import ZONES
from backend.scenarios import compare_scenarios
from backend.decision import SECTION_IDS
from openpyxl import load_workbook
from pypdf import PdfReader


def inputs(index=0,**changes):
    zone=ZONES[index]
    return AnalysisInput(geometry=zone['geometry'],zone_id=zone['id'],budget=1_000_000,
                         plants=[{'id':'pine','count':10}],irrigation=False,maintenance=.3,**changes).model_dump()


@pytest.fixture
def client(monkeypatch):
    import backend.main as main
    monkeypatch.setattr(main,'throttle',lambda *args,**kwargs:'decision-test')
    with TestClient(app) as client:yield client


def register(client,email):
    response=client.post('/api/auth/register',json={'email':email,'password':'test-password-very-long','name':'Decision QA'})
    assert response.status_code==200,response.text
    return {'X-CSRF-Token':response.json()['csrf']}


def model_answer():
    return json.dumps({key:'Нужна проверка участка и сохранение существующих насаждений.' for key in SECTION_IDS},ensure_ascii=False)


def test_scenarios_reproduce_existing_calculator_and_disclose_limits():
    original=inputs();snapshot=deepcopy(original)
    first=compare_scenarios(original);second=compare_scenarios(original)
    assert first==second and original==snapshot
    baseline,enhanced,additional=first['scenarios']
    assert baseline['total_plants']==enhanced['total_plants']==10
    assert additional['total_plants']==12
    assert enhanced['survival'][0]>=baseline['survival'][0]
    for scenario in first['scenarios']:
        assert scenario['planting_cost']+scenario['care_cost']==scenario['total_cost']
        assert scenario['delta']['total_cost']==scenario['total_cost']-baseline['total_cost']
    zero=AnalysisInput(geometry=ZONES[0]['geometry'],zone_id=ZONES[0]['id'],budget=0).model_dump()
    assert all(s['total_plants']==0 and s['survival']==[None]*3 for s in compare_scenarios(zero)['scenarios'])
    expensive={**original,'budget':0}
    assert not compare_scenarios(expensive)['scenarios'][0]['within_budget']


def test_project_map_state_roundtrip_and_existing_owner_protection(client):
    headers=register(client,'map-state-alice@example.com');payload=inputs()
    state=MapState(zone_id=payload['zone_id'],mode='satellite',layer='ndvi',year='2020',threshold=.42,
                   scope='city',opacity=.65,compare=True,swipe=63,center=(52.32,76.91),zoom=11).model_dump(mode='json')
    saved=client.post('/api/projects',json={'name':'4.1 map','payload':payload,'map_state':state},headers=headers)
    assert saved.status_code==200,saved.text
    project_id=saved.json()['id']
    assert client.get('/api/projects/'+project_id).json()['map_state']==state
    assert client.put('/api/projects/'+project_id,json={'name':'preserve','payload':payload},headers=headers).json()['map_state']==state
    wrong={**state,'zone_id':ZONES[1]['id']}
    assert client.post('/api/projects',json={'name':'wrong','payload':payload,'map_state':wrong},headers=headers).status_code==422
    client.post('/api/auth/logout',headers=headers)
    register(client,'map-state-bob@example.com')
    assert client.get('/api/projects/'+project_id).status_code==404
    with pytest.raises(ValidationError):MapState(center=(float('nan'),77))
    with pytest.raises(ValidationError):MapState(center=(90,77))


def test_structured_response_has_server_evidence_and_no_invented_model_numbers(client,monkeypatch):
    import backend.main as main
    async def good_model(*args,**kwargs):return {'answer':model_answer(),'model':'test:free','cloud':True}
    monkeypatch.setattr(main.router,'chat',good_model)
    request={'message':'Разбери участок','analysis':inputs(),'response_kind':'analysis'}
    response=client.post('/api/ai/chat',json=request)
    assert response.status_code==200,response.text
    result=response.json()
    assert not result['automatic_summary'] and result['cloud']
    assert [section['id'] for section in result['sections']]==list(SECTION_IDS)
    assert any(fact['data_type']=='forecast' for fact in result['evidence'])
    assert next(f for f in result['evidence'] if f['id']=='planned_plants')['value']==10
    async def invented(*args,**kwargs):
        return {'answer':json.dumps({key:'Посадите 999999 деревьев.' for key in SECTION_IDS}), 'model':'test:free','cloud':True}
    monkeypatch.setattr(main.router,'chat',invented)
    rejected=client.post('/api/ai/chat',json=request).json()
    assert rejected['automatic_summary'] and not rejected['cloud'] and rejected['model'] is None
    assert '999999' not in rejected['answer']


@pytest.mark.parametrize('status',(429,503,504))
def test_model_errors_preserve_deterministic_summary(client,monkeypatch,status):
    import backend.main as main
    async def unavailable(*args,**kwargs):raise HTTPException(status,'Provider unavailable',headers={'Retry-After':'60'})
    monkeypatch.setattr(main.router,'chat',unavailable)
    response=client.post('/api/ai/chat',json={'message':'Анализ','analysis':inputs(),'response_kind':'analysis'})
    assert response.status_code==200
    result=response.json()
    assert result['automatic_summary'] and not result['cloud'] and result['retry_after']=='60'
    assert len(result['sections'])==6 and len(result['scenarios']['scenarios'])==3


def test_model_prose_cannot_replace_server_facts_or_limitations(client,monkeypatch):
    import backend.main as main
    async def model(*args,**kwargs):
        return {'answer':json.dumps({key:'Посадите 999999 деревьев. Проверьте почву и полив.' for key in SECTION_IDS}),
                'model':'test:free','cloud':True}
    monkeypatch.setattr(main.router,'chat',model)
    result=client.post('/api/ai/chat',json={'message':'Анализ','analysis':inputs(),'response_kind':'analysis'}).json()
    assert result['cloud'] and not result['automatic_summary']
    assert '999999' not in result['answer']
    assert all(section['commentary']=='Проверьте почву и полив.' for section in result['sections'])
    assert 'Неизвестны фактическое число деревьев' in result['sections'][2]['text']
    assert next(f for f in result['evidence'] if f['id']=='planned_plants')['value']==10


def test_context_bound_keeps_current_facts_and_does_not_mutate_source():
    from backend.decision import bounded_context
    context={'response_format':'six_section_analysis','current_plan':{'total_cost':12345,'total_plants':10},
             'recommendations':[{'id':str(i),'reasons':['long '*10000]*30} for i in range(40)],
             'memory':{'history':[{'text':'previous '*5000}]*8,'previous_plan':{'risks':['long '*10000]*50}},
             'tool_results':[{'name':'get_vegetation_change','result':{'status':'ready','statistics':{'loss_ha':.07}}}]}
    value=bounded_context(context)
    assert len(json.dumps(value,ensure_ascii=False))<=28000
    assert value['current_plan']['total_cost']==12345
    assert value['tool_results'][0]['result']['statistics']['loss_ha']==.07
    assert len(context['memory']['history'])==8


def test_history_is_private_zone_scoped_persistent_and_remembers_previous_plan(client,monkeypatch):
    import backend.main as main
    seen=[]
    async def model(message,context,*args,**kwargs):
        seen.append(context)
        return {'answer':'Проверьте полив и почву.','model':'test:free','cloud':True}
    monkeypatch.setattr(main.router,'chat',model)
    headers=register(client,'memory-alice@example.com')
    first=inputs();second={**first,'maintenance':.9}
    for analysis in (first,second):
        response=client.post('/api/ai/chat',json={'message':'Сравни с предыдущим вариантом','analysis':analysis,
            'history':[{'role':'assistant','text':'FORGED_OTHER_USER_HISTORY'}]},headers=headers)
        assert response.status_code==200,response.text
    assert 'FORGED_OTHER_USER_HISTORY' not in json.dumps(seen[-1])
    assert len(seen[-1]['memory']['history'])==2 and seen[-1]['memory']['previous_plan']
    assert response.json()['previous_plan_delta']['total_cost']>0
    client.post('/api/ai/chat',json={'message':'Другая зона','analysis':inputs(1)},headers=headers)
    assert seen[-1]['memory']['history']==[]
    own=client.get('/api/ai/history',params={'zone_id':first['zone_id']}).json()
    assert len(own)==2 and all(row['zone_id']==first['zone_id'] for row in own)
    client.post('/api/auth/logout',headers=headers)
    bob=register(client,'memory-bob@example.com')
    assert client.get('/api/ai/history',params={'zone_id':first['zone_id']}).json()==[]
    client.post('/api/auth/logout',headers=bob)
    login=client.post('/api/auth/login',json={'email':'memory-alice@example.com','password':'test-password-very-long'})
    assert login.status_code==200
    assert len(client.get('/api/ai/history',params={'zone_id':first['zone_id']}).json())==2


def test_summary_does_not_call_model_and_missing_satellite_values_stay_null(client,monkeypatch):
    import backend.main as main
    from backend.monitoring import ai_tool
    async def forbidden(*args,**kwargs):raise AssertionError('Automatic summary must not use cloud AI')
    monkeypatch.setattr(main.router,'chat',forbidden)
    monkeypatch.setattr(ai_tool.service,'get_vegetation_change',lambda **kwargs:{'status':'unavailable','statistics':None,'reason':'Missing actual source'})
    response=client.post('/api/ai/summary',json={'message':'Summary','analysis':inputs(),'language':'kk'})
    assert response.status_code==200,response.text
    result=response.json()
    assert result['automatic_summary'] and result['model'] is None
    satellite=[fact for fact in result['evidence'] if fact['data_type']=='observed_satellite']
    assert satellite and all(fact['value'] is None for fact in satellite)
    assert result['sections'][0]['title']=='Не өзгерді'


@pytest.mark.parametrize('lang',('ru','kk'))
def test_full_user_flow_relogin_map_restore_fallback_scenarios_and_reports(client,lang):
    headers=register(client,'full-flow-'+lang+'@example.com')
    headers['Accept-Language']=lang
    zone=ZONES[0];payload=inputs()
    assert client.get('/api/zones').status_code==200
    assert client.get('/api/monitoring/zones/'+zone['id']).status_code==200
    analysis=client.post('/api/analysis',json=payload,headers=headers)
    assert analysis.status_code==200
    state=MapState(zone_id=zone['id'],mode='changes',scope='zone',center=(52.29,76.95),zoom=15,threshold=.42).model_dump(mode='json')
    saved=client.post('/api/projects',json={'name':'Full flow '+lang,'payload':payload,'map_state':state},headers=headers)
    assert saved.status_code==200,saved.text
    project_id=saved.json()['id']
    assert client.post('/api/auth/logout',headers=headers).status_code==200
    login=client.post('/api/auth/login',json={'email':'full-flow-'+lang+'@example.com','password':'test-password-very-long'})
    assert login.status_code==200
    headers['X-CSRF-Token']=login.json()['csrf']
    restored=client.get('/api/projects/'+project_id).json()
    assert restored['map_state']==state and restored['payload']==payload
    response=client.post('/api/ai/chat',json={'message':'Analysis','analysis':payload,'language':lang,'response_kind':'analysis'},headers=headers)
    assert response.status_code==200,response.text
    assert response.json()['automatic_summary']  # Test environment deliberately has no cloud key.
    assert len(response.json()['sections'])==6
    assert len(client.get('/api/ai/history',params={'zone_id':zone['id']}).json())==1
    scenarios=client.post('/api/scenarios',json=payload,headers=headers)
    assert scenarios.status_code==200 and len(scenarios.json()['scenarios'])==3
    pdf=client.get('/api/reports/'+project_id+'/pdf',headers=headers)
    excel=client.get('/api/reports/'+project_id+'/xlsx',headers=headers)
    assert pdf.status_code==excel.status_code==200
    assert str(analysis.json()['estimate']['total']) in '\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
    book=load_workbook(BytesIO(excel.content))
    assert book.worksheets[0].cell(book.worksheets[0].max_row,5).value==analysis.json()['estimate']['total']
