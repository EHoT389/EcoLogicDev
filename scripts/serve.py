"""Start API. Optional --stdin-env reads a JSON object without echoing or persisting secrets."""
import os,sys,json,getpass
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if '--stdin-env' in sys.argv:
 print('Ready for environment JSON on stdin (not echoed).',flush=True)
 line=getpass.getpass('Environment JSON (hidden): ') if sys.stdin.isatty() else sys.stdin.readline()
 line=line.strip()
 values=json.loads(line) if line.startswith('{') else {'OPENROUTER_API_KEY':line}
 if values.get('OPENROUTER_API_KEY') and not values['OPENROUTER_API_KEY'].startswith('sk-or-'):
  raise SystemExit('Invalid key format; value not displayed.')
 for key,value in values.items():
  if key in ('OPENROUTER_API_KEY','DATABASE_URL'): os.environ[key]=str(value)
import uvicorn
uvicorn.run('backend.main:app',host='127.0.0.1',port=8000,log_level='warning')
