"""Reproducible scenarios using the existing expert calculator without new formulas."""
from copy import deepcopy
import hashlib
import json
import math
from .analytics import analyze
from .data import PLANTS, RATES, COEFFICIENTS, VERSION


def plan_version(payload, plants=PLANTS, rates=RATES, coefficients=COEFFICIENTS):
    inputs={key:value for key,value in payload.items() if key!='zone_name'}
    data={'payload':inputs,'plants':plants,'rates':rates,'coefficients':coefficients,'formula_version':VERSION}
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()[:20]


def summarize(result):
    rows={row['id']:row['total'] for row in result['estimate']['rows']}
    planting=sum(rows.get(key,0) for key in ('preparation','soil','delivery','seedlings','planting'))
    care=sum(rows.get(key,0) for key in ('care','watering','replacement'))
    occupied=sum(plant['count']*plant['spacing']**2 for plant in result['plan'])
    return {'total_plants':result['total_plants'],'planting_cost':planting,'care_cost':care,
            'total_cost':result['estimate']['total'],'within_budget':result['estimate']['within_budget'],
            'within_area':occupied<=result['plantable_area']+.1,
            'survival':result['survival'] if result['total_plants'] else [None,None,None],
            'plan':[{'id':p['id'],'count':p['count'],'ru':p['ru'],'kk':p['kk']} for p in result['plan']],
            'warnings':result['warnings'],'risks':result['risks']}


def compare_scenarios(payload, plants=PLANTS, rates=RATES, coefficients=COEFFICIENTS):
    original=deepcopy(payload)
    current=analyze(original,plants,rates,coefficients)
    composition=[{'id':p['id'],'count':p['count']} for p in current['plan']]
    base={**original,'plants':composition}
    enhanced={**deepcopy(base),'irrigation':True,'maintenance':1.}
    additional={**deepcopy(base),'plants':[{'id':p['id'],'count':min(5000,math.floor(p['count']*1.2))} for p in composition]}
    definitions=[('baseline','Базовый уход','Негізгі күтім',base),
                 ('enhanced','Усиленный уход','Күшейтілген күтім',enhanced),
                 ('additional','Дополнительные посадки','Қосымша отырғызу',additional)]
    scenarios=[]
    for key,ru,kk,inputs in definitions:
        result=analyze(inputs,plants,rates,coefficients)
        scenarios.append({'id':key,'ru':ru,'kk':kk,'provenance':'expert_calculation',
                          'inputs':{'irrigation':inputs['irrigation'],'maintenance':inputs['maintenance'],
                                    'plants':inputs['plants']},**summarize(result)})
    baseline=scenarios[0]
    for scenario in scenarios:
        scenario['delta']={key:scenario[key]-baseline[key] for key in ('total_plants','planting_cost','care_cost','total_cost')}
        scenario['delta']['survival']=[round(a-b,1) if a is not None and b is not None else None
                                        for a,b in zip(scenario['survival'],baseline['survival'])]
    return {'version':1,'plan_version':plan_version(original,plants,rates,coefficients),
            'formula_version':VERSION,'zone_id':original.get('zone_id'),'scenarios':scenarios,
            'conditions':{'budget':original['budget'],'years':original['years'],
                          'area_m2':current['area'],'plantable_m2':current['plantable_area'],
                          'site_provenance':original['site']['provenance']},
            'method':{'ru':'Одинаковые контур, почва, бюджет и период. Базовый сохраняет состав новых посадок. Усиленный: тот же состав, полив и интенсивность 1. Дополнительный: +20% каждого количества с округлением вниз, прежний уход. Превышения бюджета/площади не скрываются.',
                      'kk':'Контур, топырақ, бюджет және мерзім бірдей. Негізгі сценарий жаңа отырғызу құрамын сақтайды. Күшейтілгенде құрам өзгермейді, суару қосылып, күтім қарқыны 1 болады. Қосымша сценарийде әр сан төмен қарай дөңгелектеліп 20% артады; күтім сақталады. Бюджет/аудан асуы жасырылмайды.'},
            'limitation':{'ru':'Сценарии относятся к новым посадкам плана. Фактическое число и состояние существующих деревьев неизвестны. Приживаемость — экспертный прогноз, не измерение.',
                          'kk':'Сценарийлер жоспардағы жаңа отырғызуға қатысты. Бар ағаштардың нақты саны мен жағдайы белгісіз. Жерсіну — сараптамалық болжам, өлшем емес.'},
            'source':{'rates':rates.get('source'),'formula_version':VERSION}}
