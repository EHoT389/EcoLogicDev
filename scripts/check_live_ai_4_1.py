"""One explicitly bounded free-model integration check against the local API."""
from pathlib import Path
import json
import sys
import os
import asyncio
import getpass
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.schemas import AnalysisInput
from backend.data import ZONES

zone=ZONES[0]
payload={'message':'Выполни структурированный разбор этого участка: наблюдения, ограничения и дальнейшие действия.',
         'response_kind':'analysis','language':'ru',
         'analysis':AnalysisInput(geometry=zone['geometry'],zone_id=zone['id'],budget=1_000_000).model_dump(),
         'monitoring':{'zone_id':zone['id'],'period_start':2020,'period_end':2026,'threshold':.3}}
if '--diagnose' in sys.argv:
    # Public canonical zone only. Key is read without echo and never written.
    os.environ['OPENROUTER_API_KEY']=getpass.getpass('Server key (hidden): ').strip()
    from backend.db import SessionLocal
    from backend.schemas import ChatInput
    from backend.main import prepare_decision,router
    from backend.decision import parse_model_sections
    with SessionLocal() as db:
        context,*_=prepare_decision(ChatInput(**payload),db,None,'ru')
        raw=asyncio.run(router.chat(payload['message'],context,db,'qa-public-zone',language='ru'))
    Path('output/qa/live-ai-raw-4-1.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Format accepted:',parse_model_sections(raw['answer']) is not None)
    print(raw['answer'])
    sys.exit(0)
else:
    with httpx.Client(timeout=95) as client:
        response=client.post('http://127.0.0.1:8000/api/ai/chat',json=payload)
        response.raise_for_status()
        result=response.json()
Path('output/qa/live-ai-4-1.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({key:result.get(key) for key in ('cloud','automatic_summary','model','reason','plan_version')},ensure_ascii=False))
print('Structured sections:',len(result.get('sections',[])))
