"""The model receives only server tool results; test fixtures are never product data."""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from backend.data import ZONES
from backend.main import app
from backend.monitoring import ai_tool
from backend.monitoring.ai_tool import VegetationChangeArguments, get_vegetation_change


def test_tool_arguments_are_bounded_and_reject_client_measurements():
    for extra in ({'period_start': 2021}, {'threshold': 1.1}, {'threshold': float('nan')}, {'statistics': {'gain_ha': 9999}}):
        with pytest.raises(ValidationError):
            VegetationChangeArguments(zone_id=ZONES[0]['id'], **extra)


def test_tool_reads_server_result_and_keeps_unavailable_data_null(monkeypatch):
    zone_id = ZONES[0]['id']
    observed = []
    def source(**arguments):
        observed.append(arguments)
        return {'status': 'unavailable', 'reason': 'Explicit missing source test fixture', 'statistics': None,
                'zone_id': zone_id, 'periods': {}, 'source': {'catalog': 'test-fixture'}, 'warnings': []}
    monkeypatch.setattr(ai_tool.service, 'get_vegetation_change', source)
    result = get_vegetation_change(VegetationChangeArguments(zone_id=zone_id, threshold=.45), {'id': zone_id}, 'kk')
    assert result['name'] == 'get_vegetation_change'
    assert result['result']['status'] == 'unavailable' and result['result']['statistics'] is None
    assert observed == [{'zone_id': zone_id, 'period_start': 2020, 'period_end': 2026, 'threshold': .45, 'language': 'kk'}]
    with pytest.raises(HTTPException) as error:
        get_vegetation_change(VegetationChangeArguments(zone_id=zone_id), {'id': ZONES[1]['id']})
    assert error.value.status_code == 422 and len(observed) == 1


def test_chat_tool_context_uses_validated_zone_and_actual_threshold(monkeypatch):
    import backend.main as main
    contexts = []
    calls = []
    # Avoid consuming either user's persistent quota or the suite's unrelated quota scenarios.
    monkeypatch.setattr(main, 'throttle', lambda *args, **kwargs: 'monitoring-qa')
    def source(**arguments):
        calls.append(arguments)
        return {'status': 'ready', 'zone_id': arguments['zone_id'], 'period_start': 2020, 'period_end': 2026,
                'threshold': arguments['threshold'], 'dataset_id': 'explicit-test-fixture',
                'statistics': {'gain_ha': 1.23, 'loss_ha': .45, 'comparable_fraction': .95},
                'territory': {'ru': 'Test zone', 'kk': 'Test zone', 'geometry': {'must_not': 'reach_cloud'}},
                'periods': {'2020': {'scenes': [{'id': 'fixture-2020', 'date': '2020-06-15', 'assets': {'large': 'excluded'}}]}},
                'warnings': ['Test-only fixture; not real data'], 'source': {'catalog': 'test-fixture'}}
    monkeypatch.setattr(ai_tool.service, 'get_vegetation_change', source)
    async def model(message, context, db, actor, language=None):
        contexts.append(context)
        assert language == 'kk'
        return {'answer': 'Жергілікті тексеру қажет.', 'model': 'test:free', 'cloud': True}
    monkeypatch.setattr(main.router, 'chat', model)
    zone = ZONES[0]
    payload = {'message': 'Өзгерісті түсіндір', 'language': 'kk',
               'analysis': {'geometry': zone['geometry'], 'zone_id': zone['id']},
               'monitoring': {'zone_id': zone['id'], 'period_start': 2020, 'period_end': 2026, 'threshold': .45}}
    with TestClient(app) as client:
        response = client.post('/api/ai/chat', json=payload)
        assert response.status_code == 200, response.text
        context = contexts[0]
        assert context['selected_zone']['id'] == zone['id'] and context['topic'] == 'vegetation_change'
        result = context['tool_results'][0]
        assert result['name'] == 'get_vegetation_change' and result['result']['statistics']['gain_ha'] == 1.23
        assert result['arguments']['threshold'] == .45
        assert 'geometry' not in result['result']['territory']
        assert 'assets' not in result['result']['periods']['2020']['scenes'][0]
        assert context['planning_scenario']['provenance'] == 'expert_scenario_not_observed_state'
        mismatch = {**payload, 'monitoring': {**payload['monitoring'], 'zone_id': ZONES[1]['id']}}
        assert client.post('/api/ai/chat', json=mismatch).status_code == 422
        wrong_geometry = {**payload, 'analysis': {**payload['analysis'], 'geometry': ZONES[1]['geometry']}}
        assert client.post('/api/ai/chat', json=wrong_geometry).status_code == 422
        no_selection = {key: value for key, value in payload.items() if key != 'analysis'}
        assert client.post('/api/ai/chat', json=no_selection).status_code == 422
        untrusted_stats = {**payload, 'monitoring': {**payload['monitoring'], 'statistics': {'gain_ha': 9999}}}
        assert client.post('/api/ai/chat', json=untrusted_stats).status_code == 422
    assert len(contexts) == 1 and len(calls) == 1


def test_city_zone_keeps_city_source_scope_without_claiming_city_statistics(monkeypatch):
    zone_id = ZONES[0]['id']
    monkeypatch.setattr(ai_tool.service, 'get_vegetation_change', lambda **kwargs: {
        'status': 'ready', 'scope': 'zone', 'zone_id': zone_id,
        'aoi': {'id': 'osm-relation-5501700', 'name_ru': 'Pavlodar', 'area_km2': 630.595,
                'geometry': {'excluded': 'cloud context'}},
        'coverage': {'common_fraction': .997}, 'statistics': {'gain_ha': 1.23},
    })
    result = get_vegetation_change(VegetationChangeArguments(zone_id=zone_id), {'id': zone_id})['result']
    assert result['scope'] == 'zone' and result['dataset_scope'] == 'administrative_city'
    assert result['aoi']['area_km2'] == 630.595 and 'geometry' not in result['aoi']
    rules = ' '.join(result['interpretation_rules'])
    assert 'pilot' not in rules and 'only the selected zone' in rules
