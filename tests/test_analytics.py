from copy import deepcopy
import pytest
from fastapi import HTTPException
from backend.analytics import analyze,validated_geometry,assess_zones,recommendation
from backend.data import ZONES,PLANTS,RATES,COEFFICIENTS,rectangle
from backend.schemas import AnalysisInput

@pytest.fixture
def payload(): return AnalysisInput(geometry=ZONES[1]['geometry']).model_dump()

def test_geodesic_area_and_rejection():
 _,area=validated_geometry(rectangle(76.935,52.290));assert 30_000<area<50_000
 with pytest.raises(HTTPException): validated_geometry({'type':'Polygon','coordinates':[[[0,0],[1,0],[1,1],[0,0]]]})
 with pytest.raises(HTTPException): validated_geometry({'type':'Polygon','coordinates':[[[76.9,52.2],[77,52.3],[76.9,52.3],[77,52.2],[76.9,52.2]]]})

def test_reproducibility_and_estimate_arithmetic(payload):
 a=analyze(payload);assert a==analyze(payload)
 assert a['estimate']['total']==sum(r['total'] for r in a['estimate']['rows'])
 assert a['total_plants']==sum(p['count'] for p in a['plan'])
 assert a['estimate']['total']<=payload['budget']

def test_improved_care_improves_survival(payload):
 payload.update(irrigation=False,maintenance=.2)
 poor=analyze(payload)
 payload['plants']=[{'id':p['id'],'count':p['count']} for p in poor['plan']]
 payload.update(irrigation=True,maintenance=1)
 better=analyze(payload)
 assert better['survival'][0]>poor['survival'][0]
 assert better['survival'][0]>=better['survival'][1]>=better['survival'][2]

def test_critical_constraints_and_manual_validation(payload):
 payload['site']['purpose']='children'
 ranks=recommendation(payload['site']);assert next(p for p in ranks if p['id']=='caragana')['excluded']
 payload['plants']=[{'id':'caragana','count':3}]
 with pytest.raises(HTTPException): analyze(payload)

def test_zero_budget_not_fabricated(payload):
 payload['budget']=0;a=analyze(payload)
 assert a['total_plants']==0
 assert all(x['co2']==0 for x in a['ecology'])
 assert a['estimate']['total']==0

def test_ecology_units_and_unknown_temperature(payload):
 a=analyze(payload)
 for e in a['ecology']:
  assert abs(e['co2']-e['canopy']*.28*44/12)<1
  assert abs(e['oxygen']-e['co2']*32/44)<.2
  assert e['cumulative_co2']>=e['co2']
  assert e['canopy']<=a['plantable_area']
  assert e['cooling_c'] is None

def test_missing_factors_excluded_from_priority():
 result=assess_zones(ZONES)
 assert all('heat' in z['missing'] and 'population' in z['missing'] for z in result['zones'])
 assert sum(z['preliminary_cost'] for z in result['zones'] if z['funded'])<=result['budget']
