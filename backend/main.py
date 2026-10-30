import os,json,time,secrets,hashlib,math
from datetime import datetime,timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI,Depends,HTTPException,Request,Response,UploadFile,File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse,JSONResponse
from sqlalchemy import select,func,delete
from sqlalchemy.orm import Session as DB
from .db import User,Session,Project,Event,AIMessage,get_db,init_db,get_setting,put_setting,log,password_hash,password_matches
from .schemas import AnalysisInput,Credentials,FirebaseToken,ProjectInput,ChatInput,RoleInput,PriorityInput,ZoneNameInput
from .analytics import analyze,assess_zones,recommendation
from .data import PLANTS,ZONES,RATES,COEFFICIENTS,WEIGHTS,VERSION
from .ai import router
from .imports import import_layer
from .reports import export_pdf,export_xlsx
from .localization import language,text,validation_message
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from .monitoring.api import router as monitoring_router

@asynccontextmanager
async def lifespan(app): init_db();yield
app=FastAPI(title='EcoLogicDev API',version='1.0.0',lifespan=lifespan,docs_url='/api/docs',openapi_url='/api/openapi.json')
app.include_router(monitoring_router)
origins=[o.strip() for o in os.getenv('ALLOWED_ORIGINS','http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:4173,http://localhost:4173,http://127.0.0.1:5174,http://localhost:5174,http://127.0.0.1:5175,http://localhost:5175,http://127.0.0.1:3000,http://localhost:3000').split(',')]
secure=os.getenv('COOKIE_SECURE','false').lower()=='true'
production=os.getenv('ENVIRONMENT')=='production'
def is_allowed_origin(origin:str|None)->bool:
 if not origin: return not production
 if origin in origins: return True
 if not production:
  import re
  if re.match(r'^https?://(localhost|127\.0\.0\.1)(:\d+)?$',origin): return True
 return False

app.add_middleware(CORSMiddleware,allow_origins=origins,allow_origin_regex=r'^https?://(localhost|127\.0\.0\.1)(:\d+)?$' if not production else None,allow_credentials=True,allow_methods=['GET','POST','PUT','DELETE'],allow_headers=['Content-Type','X-CSRF-Token','Accept-Language'])

@app.exception_handler(StarletteHTTPException)
async def localized_exception(request,exc):
 lang=language(request)
 return JSONResponse({'detail':text(exc.detail,lang)},exc.status_code,headers={**(exc.headers or {}),'Content-Language':lang})

@app.exception_handler(RequestValidationError)
async def localized_validation(request,exc):
 lang=language(request)
 # Do not echo raw inputs (passwords and tokens may be among them).
 return JSONResponse({'detail':' · '.join(validation_message(e,lang) for e in exc.errors()[:6])},422,headers={'Content-Language':lang})

@app.middleware('http')
async def protection(request,call_next):
 def fail(detail,status): return JSONResponse({'detail':text(detail,language(request))},status)
 try:
  if int(request.headers.get('content-length','0'))>6_000_000: return fail('Запрос больше 6 МБ',413)
 except ValueError: return fail('Неверная длина запроса',400)
 if request.method in ('POST','PUT','PATCH','DELETE'):
  origin=request.headers.get('origin')
  if origin and not is_allowed_origin(origin): return fail('Недопустимый Origin',403)
  if production and not origin: return fail('Требуется Origin',403)
 response=await call_next(request)
 response.headers['X-Content-Type-Options']='nosniff'
 response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
 if not request.url.path.startswith('/api/monitoring/tiles/'):
  response.headers['Cache-Control']='no-store'
 return response

def public_user(u): return {'id':u.id,'email':u.email,'name':u.name,'role':u.role}
def session_user(request:Request,db:DB=Depends(get_db)):
 token=request.cookies.get('eco_session')
 if not token: return None
 s=db.get(Session,hashlib.sha256(token.encode()).hexdigest())
 if not s or s.expires<time.time(): return None
 u=db.get(User,s.user_id)
 if not u or u.blocked=='yes': return None
 if request.method not in ('GET','HEAD','OPTIONS') and not secrets.compare_digest(request.headers.get('x-csrf-token',''),s.csrf): raise HTTPException(403,'Недействительный CSRF-токен')
 request.state.session=s
 return u
def required(u=Depends(session_user)):
 if not u: raise HTTPException(401,'Войдите в аккаунт')
 return u
def admin(u=Depends(required)):
 if u.role!='admin': raise HTTPException(403,'Требуются права администратора')
 return u
def specialist(u=Depends(required)):
 if u.role not in ('specialist','admin'): raise HTTPException(403,'Требуются права специалиста')
 return u
def throttle(request,db,kind,limit,seconds):
 addr=request.client.host if request.client else 'local'
 # Forwarded headers are trusted only behind a configured proxy.
 if os.getenv('TRUST_PROXY')=='true': addr=request.headers.get('x-forwarded-for',addr).split(',')[0].strip()
 actor=hashlib.sha256(addr.encode()).hexdigest()[:24]
 count=db.scalar(select(func.count()).select_from(Event).where(Event.kind==kind,Event.actor==actor,Event.created>time.time()-seconds)) or 0
 if count>=limit: raise HTTPException(429,'Слишком много запросов. Попробуйте позже.',headers={'Retry-After':str(seconds)})
 log(db,kind,actor,{});db.commit()
 return actor
def create_session(u,response,db):
 token=secrets.token_urlsafe(36);csrf=secrets.token_urlsafe(24)
 db.add(Session(token_hash=hashlib.sha256(token.encode()).hexdigest(),user_id=u.id,expires=time.time()+7*86400,csrf=csrf))
 # Cleanup expired sessions while already writing.
 db.execute(delete(Session).where(Session.expires<time.time()));db.commit()
 response.set_cookie('eco_session',token,max_age=7*86400,httponly=True,secure=secure,samesite='lax',path='/')
 return {'user':public_user(u),'csrf':csrf}
def catalog(db): return get_setting(db,'plants',PLANTS)
def selected_zone_context(payload,db):
 zones=get_setting(db,'zones',ZONES)
 zone=next((z for z in zones if z['id']==payload.zone_id),None) if payload.zone_id else None
 if zone:
  from shapely.geometry import shape
  try: matches=shape(payload.geometry).equals(shape(zone['geometry']))
  except Exception: matches=False
  if not matches: raise HTTPException(422,'Граница участка не соответствует выбранной зоне. Выберите участок заново на карте.')
  return {'id':zone['id'],'name':payload.zone_name or zone['ru'],'original_name':zone.get('original_name',zone['ru']),'status':zone.get('status','planting_candidate'),'source':zone.get('source'),'nearby_streets':zone.get('nearby_streets',[]),'address_note':'Nearby streets are approximate landmarks, not a postal address.','geometry_provenance':zone.get('provenance'),'assessment_provenance':payload.site.provenance,'note':zone.get('status_note','')}
 return {'id':payload.zone_id,'name':payload.zone_name or 'Пользовательский участок','status':'planting_candidate','geometry_provenance':'user_input','assessment_provenance':payload.site.provenance,'note':'Пользовательский контур; необходимость и возможность посадок требуют обследования.'}

def calculation(payload,db):
 result=analyze(payload.model_dump(),catalog(db),get_setting(db,'rates',RATES),get_setting(db,'coefficients',COEFFICIENTS))
 result['selected_zone']=selected_zone_context(payload,db)
 return result

def chat_context(payload,db):
 result=calculation(payload,db)
 # Keep actual numbers and explicit selected-zone metadata; exclude schematic point arrays.
 return {key:result[key] for key in ['selected_zone','version','area','plantable_area','plan','total_plants','estimate','survival','ecology','warnings','risks']}|{'recommendations':[{k:p[k] for k in ['id','ru','kk','score','excluded','reasons','safety','source']} for p in result['recommendations']],'note':'Статус кандидата не доказывает необходимость посадки. Существующие насаждения нужно сохранять; количество реально растущих деревьев неизвестно.'}
def own_project(id,u,db,write=False):
 p=db.get(Project,id)
 if not p or (p.owner_id!=u.id and not (u.role=='specialist' and p.assigned_to==u.id)): raise HTTPException(404,'Проект не найден')
 return p
def project_view(p,full=False):
 result={'id':p.id,'name':p.name,'updated':p.updated,'total':json.loads(p.result)['estimate']['total'],'owner_id':p.owner_id,'assigned_to':p.assigned_to}
 if full: result.update(payload=json.loads(p.payload),result=json.loads(p.result))
 return result

@app.get('/api/health')
def health(): return {'status':'ok','version':VERSION,'ai_configured':bool(os.getenv('OPENROUTER_API_KEY')),'storage':'postgresql' if 'postgres' in os.getenv('DATABASE_URL','') else 'sqlite','email_delivery':False}
@app.get('/api/plants')
def plants(db:DB=Depends(get_db)): return catalog(db)
@app.get('/api/zones')
def zones(db:DB=Depends(get_db)): return get_setting(db,'zones',ZONES)
@app.get('/api/zones/names')
def zone_names(u=Depends(required),db:DB=Depends(get_db)): return get_setting(db,'zone_names:'+u.id,{})
@app.put('/api/zones/{zone_id}/name')
def rename_zone(zone_id:str,payload:ZoneNameInput,u=Depends(required),db:DB=Depends(get_db)):
 import re
 if not re.fullmatch(r'[a-zA-Z0-9:_-]{1,80}',zone_id): raise HTTPException(422,'Недопустимый идентификатор участка')
 names=get_setting(db,'zone_names:'+u.id,{})
 if zone_id not in names and len(names)>=200: raise HTTPException(422,'Достигнут лимит личных названий')
 names[zone_id]=payload.model_dump();put_setting(db,'zone_names:'+u.id,names);db.commit()
 return names[zone_id]
@app.get('/api/layers')
def layers(db:DB=Depends(get_db)): return get_setting(db,'layers',[])
@app.get('/api/sources')
def sources(db:DB=Depends(get_db)): return {'version':VERSION,'rates':get_setting(db,'rates',RATES),'coefficients':get_setting(db,'coefficients',COEFFICIENTS),'plants':catalog(db),'geodata':'Контуры 8 парков и скверов и 4 открытых территорий получены из OpenStreetMap 29.10.2026. Кандидаты на дополнительные посадки — предварительное предложение, не утверждённые участки. Характеристики почв, влажности и нагрузок — демонстрационные; инвентаризации деревьев нет.','links':[{'name':'OpenStreetMap / ODbL','url':'https://www.openstreetmap.org/copyright'},{'name':'Nowak et al. 2013 · секвестрация C','url':'https://research.fs.usda.gov/treesearch/46254'},{'name':'i-Tree · методы','url':'https://www.itreetools.org/documents/650/i-Tree_Methods_gtr_nrs200-2021.pdf'}]}
@app.post('/api/analysis')
def analysis(payload:AnalysisInput,request:Request,db:DB=Depends(get_db)):
 throttle(request,db,'analysis',90,60)
 return calculation(payload,db)
@app.post('/api/recommendations')
def recommendations(payload:AnalysisInput,db:DB=Depends(get_db)): return calculation(payload,db)['recommendations']
@app.post('/api/estimates')
def estimates(payload:AnalysisInput,db:DB=Depends(get_db)): return calculation(payload,db)['estimate']
@app.post('/api/survival')
def survival(payload:AnalysisInput,db:DB=Depends(get_db)): return {'years':[1,2,3],'probabilities':calculation(payload,db)['survival'],'confidence':'low'}
@app.post('/api/care')
def care(payload:AnalysisInput,db:DB=Depends(get_db)): return calculation(payload,db)['care']
@app.post('/api/ecology')
def ecology(payload:AnalysisInput,db:DB=Depends(get_db)): return calculation(payload,db)['ecology']
@app.post('/api/priorities')
def priorities(payload:PriorityInput,db:DB=Depends(get_db)):
 weights=payload.weights or get_setting(db,'weights',WEIGHTS)
 if set(weights)!=set(WEIGHTS) or not all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1 for v in weights.values()) or not sum(weights.values()): raise HTTPException(422,'Недопустимые веса')
 return assess_zones(get_setting(db,'zones',ZONES),weights,payload.budget)

@app.post('/api/auth/register')
def register(payload:Credentials,request:Request,response:Response,db:DB=Depends(get_db)):
 throttle(request,db,'auth',10,600)
 email=payload.email.lower().strip()
 if db.scalar(select(User).where(User.email==email)): raise HTTPException(409,'Аккаунт с таким email уже существует')
 u=User(email=email,name=payload.name,password=password_hash(payload.password),role='user');db.add(u);db.flush()
 return create_session(u,response,db)
@app.post('/api/auth/login')
def login(payload:Credentials,request:Request,response:Response,db:DB=Depends(get_db)):
 throttle(request,db,'auth',10,600)
 u=db.scalar(select(User).where(User.email==payload.email.lower().strip()))
 if not u or not password_matches(payload.password,u.password) or u.blocked=='yes': raise HTTPException(401,'Неверный email или пароль')
 return create_session(u,response,db)
@app.post('/api/auth/firebase')
def firebase_login(payload:FirebaseToken,request:Request,response:Response,db:DB=Depends(get_db)):
 import jwt
 from jwt import PyJWKClient
 throttle(request,db,'auth',10,600)
 project=os.getenv('FIREBASE_PROJECT_ID','ozel-a14d1')
 try:
  jwks=PyJWKClient('https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com')
  key=jwks.get_signing_key_from_jwt(payload.token)
  claims=jwt.decode(payload.token,key.key,algorithms=['RS256'],audience=project,issuer='https://securetoken.google.com/'+project,options={'require':['exp','iat','sub']})
  if not claims.get('email_verified') or not claims.get('email'): raise ValueError()
 except Exception: raise HTTPException(401,'Firebase-токен недействителен или email не подтверждён')
 email=claims['email'].lower()
 u=db.scalar(select(User).where(User.email==email))
 if not u: u=User(email=email,name=claims.get('name',email.split('@')[0]),password='',role='user');db.add(u);db.flush()
 if u.blocked=='yes': raise HTTPException(403,'Аккаунт заблокирован')
 return create_session(u,response,db)
@app.get('/api/auth/me')
def me(request:Request,u=Depends(session_user)): return {'user':public_user(u) if u else None,'csrf':request.state.session.csrf if u else None}
@app.post('/api/auth/logout')
def logout(request:Request,response:Response,u=Depends(required),db:DB=Depends(get_db)):
 db.execute(delete(Session).where(Session.token_hash==request.state.session.token_hash));db.commit();response.delete_cookie('eco_session',path='/');return {'ok':True}

@app.get('/api/projects')
def projects(u=Depends(required),db:DB=Depends(get_db)):
 query=select(Project).where(Project.owner_id==u.id)
 if u.role=='specialist': query=select(Project).where((Project.owner_id==u.id)|(Project.assigned_to==u.id))
 return [project_view(p) for p in db.scalars(query.order_by(Project.updated.desc())).all()]
@app.post('/api/projects')
def save_project(payload:ProjectInput,u=Depends(required),db:DB=Depends(get_db)):
 result=calculation(payload.payload,db)
 p=Project(owner_id=u.id,name=payload.name,payload=payload.payload.model_dump_json(),result=json.dumps(result,ensure_ascii=False));db.add(p);db.commit();return project_view(p,True)
@app.get('/api/projects/{id}')
def get_project(id:str,u=Depends(required),db:DB=Depends(get_db)): return project_view(own_project(id,u,db),True)
@app.put('/api/projects/{id}')
def update_project(id:str,payload:ProjectInput,u=Depends(required),db:DB=Depends(get_db)):
 p=own_project(id,u,db);result=calculation(payload.payload,db)
 # Previous version retained for reproducibility.
 log(db,'project_version',u.id,{'project_id':id,'payload':json.loads(p.payload),'result':json.loads(p.result)})
 p.name=payload.name;p.payload=payload.payload.model_dump_json();p.result=json.dumps(result,ensure_ascii=False);p.updated=datetime.now(timezone.utc).isoformat();db.commit();return project_view(p,True)
@app.delete('/api/projects/{id}')
def remove_project(id:str,u=Depends(required),db:DB=Depends(get_db)):
 p=own_project(id,u,db)
 if p.owner_id!=u.id: raise HTTPException(403,'Удалить проект может владелец')
 db.delete(p);db.commit();return {'ok':True}
@app.get('/api/projects/{id}/history')
def project_history(id:str,u=Depends(required),db:DB=Depends(get_db)):
 own_project(id,u,db)
 events=db.scalars(select(Event).where(Event.kind=='project_version').order_by(Event.created.desc()).limit(200)).all()
 return [{'date':e.created,'result':json.loads(e.data)['result']} for e in events if json.loads(e.data).get('project_id')==id]
@app.get('/api/reports/{id}/{format}')
def report(id:str,format:str,request:Request,u=Depends(required),db:DB=Depends(get_db)):
 from types import SimpleNamespace
 p=own_project(id,u,db);item=SimpleNamespace(name=p.name,updated=p.updated,result=json.loads(p.result))
 if format=='pdf': data=export_pdf(item,language(request));mime='application/pdf'
 elif format=='xlsx': data=export_xlsx(item,language(request));mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
 else: raise HTTPException(404,'Формат не найден')
 return Response(data,media_type=mime,headers={'Content-Disposition':f'attachment; filename="EcoLogicDev-{id}.{format}"'})
@app.post('/api/ai/chat')
async def chat(payload:ChatInput,request:Request,u=Depends(session_user),db:DB=Depends(get_db)):
 actor=throttle(request,db,'chat',12 if u else 4,3600)
 context=chat_context(payload.analysis,db) if payload.analysis else {'zones':assess_zones(get_setting(db,'zones',ZONES)),'plants':catalog(db),'note':'Участок не выбран. Для сметы выберите участок.'}
 if payload.monitoring:
  from .monitoring.ai_tool import get_vegetation_change
  lang=payload.language or language(request)
  if not payload.analysis:
   raise HTTPException(422,'Для спутникового анализа выберите зону на карте.' if lang!='kk' else 'Спутниктік талдау үшін картадан аумақты таңдаңыз.')
  # chat_context already verifies ID against the canonical geometry before this tool runs.
  tool_result=get_vegetation_change(payload.monitoring,context['selected_zone'],lang)
  # Keep the satellite evidence first and small enough for every free model's context.
  # Planning quantities are a hypothetical scenario, never an inventory of existing trees.
  context={'selected_zone':context['selected_zone'],'topic':'vegetation_change','tool_results':[tool_result],
   'planning_scenario':{'provenance':'expert_scenario_not_observed_state','new_plants_proposed':context['total_plants'],'risks':context['risks']}}
 result=await router.chat(payload.message,context,db,u.id if u else actor,language=payload.language or language(request))
 if u:
  selected=context.get('selected_zone',{})
  question=json.dumps({'kind':'zone_message_v1','text':payload.message,'zone_id':selected.get('id'),'zone_name':selected.get('name')},ensure_ascii=False)
  db.add(AIMessage(owner_id=u.id,question=question,answer=result['answer']));db.commit()
 return result
@app.get('/api/ai/history')
def ai_history(zone_id:str|None=None,u=Depends(required),db:DB=Depends(get_db)):
 messages=[]
 for m in db.scalars(select(AIMessage).where(AIMessage.owner_id==u.id).order_by(AIMessage.created.desc()).limit(200)).all():
  try: stored=json.loads(m.question)
  except (ValueError,TypeError): stored=None
  if not isinstance(stored,dict) or stored.get('kind')!='zone_message_v1': stored={'text':m.question,'zone_id':None,'zone_name':None}
  if zone_id and stored.get('zone_id')!=zone_id: continue
  messages.append({'question':stored['text'],'answer':m.answer,'created':m.created,'zone_id':stored.get('zone_id'),'zone_name':stored.get('zone_name')})
 return messages[:50]

@app.get('/api/admin')
def admin_data(u=Depends(admin),db:DB=Depends(get_db)):
 events=db.scalars(select(Event).order_by(Event.created.desc()).limit(100)).all()
 return {'users':[public_user(x)|{'blocked':x.blocked=='yes'} for x in db.scalars(select(User)).all()],'rates':get_setting(db,'rates',RATES),'coefficients':get_setting(db,'coefficients',COEFFICIENTS),'weights':get_setting(db,'weights',WEIGHTS),'plants':catalog(db),'zones':get_setting(db,'zones',ZONES),'ai_enabled':get_setting(db,'ai_enabled',True),'ai_configured':bool(os.getenv('OPENROUTER_API_KEY')),'events':[{'kind':e.kind,'created':e.created,'data':json.loads(e.data)} for e in events],'counts':{'projects':db.scalar(select(func.count()).select_from(Project)),'users':db.scalar(select(func.count()).select_from(User))}}
@app.put('/api/admin/users/{id}')
def role(id:str,payload:RoleInput,u=Depends(admin),db:DB=Depends(get_db)):
 target=db.get(User,id)
 if not target: raise HTTPException(404,'Пользователь не найден')
 if target.id==u.id and (payload.role!='admin' or payload.blocked): raise HTTPException(422,'Нельзя заблокировать или понизить собственный аккаунт')
 target.role=payload.role;target.blocked='yes' if payload.blocked else 'no';log(db,'user_change',u.id,{'target':id,'role':payload.role,'blocked':payload.blocked});db.commit();return public_user(target)
@app.put('/api/admin/settings/{key}')
def settings(key:str,value:dict,u=Depends(admin),db:DB=Depends(get_db)):
 defaults={'rates':RATES,'coefficients':COEFFICIENTS,'weights':WEIGHTS}
 if key=='ai':
  if not isinstance(value.get('enabled'),bool): raise HTTPException(422,'Нужен enabled: boolean')
  put_setting(db,'ai_enabled',value['enabled'])
 elif key in defaults:
  template=defaults[key]
  if set(value)!=set(template): raise HTTPException(422,'Нужно передать все поля справочника без дополнительных')
  for k,v in value.items():
   if isinstance(template[k],bool):
    if not isinstance(v,bool): raise HTTPException(422,'Нужно логическое значение: '+k)
   elif isinstance(template[k],(int,float)):
    if not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 or v>1_000_000: raise HTTPException(422,'Неверное число: '+k)
   elif not isinstance(v,str) or len(v)>500: raise HTTPException(422,'Неверная строка: '+k)
  if key=='weights' and (not sum(value.values()) or max(value.values())>1): raise HTTPException(422,'Веса должны быть 0–1 и иметь ненулевую сумму')
  if key=='coefficients' and (value['growth_years']<1 or not 0<value['green_target']<=1 or not 0<value['survival_base']<=1): raise HTTPException(422,'Проверьте доли и период роста')
  if key=='rates' and value['replacement']>1: raise HTTPException(422,'Резерв должен быть долей 0–1')
  value={**value};put_setting(db,key,value)
 else: raise HTTPException(404,'Справочник не найден')
 log(db,'setting_change',u.id,{'key':key,'value':value});db.commit();return {'ok':True}
@app.put('/api/admin/plants')
def set_plants(value:list[dict],u=Depends(admin),db:DB=Depends(get_db)):
 if not 1<=len(value)<=100 or len({p.get('id') for p in value})!=len(value): raise HTTPException(422,'Нужно 1–100 уникальных видов')
 for p in value:
  if not set(PLANTS[0]).issubset(p): raise HTTPException(422,'Не хватает обязательных полей растения')
  for k in ['price','spacing','crown','height','co2','dust','rain','drought','salt','wind']:
   if not isinstance(p[k],(int,float)) or not math.isfinite(p[k]) or p[k]<0 or (k=='spacing' and p[k]<.5): raise HTTPException(422,'Недопустимый параметр '+k)
  if p['category'] not in ('tree','shrub'): raise HTTPException(422,'Допустимы tree/shrub')
  for key in ['source','botany']:
   from urllib.parse import urlparse
   url=urlparse(str(p[key]))
   if url.scheme!='https' or not url.netloc: raise HTTPException(422,'Нужна HTTPS-ссылка источника')
  for key in ['id','ru','kk','latin','stock','safety']:
   if not isinstance(p[key],str) or not 1<=len(p[key])<=1000: raise HTTPException(422,'Неверная строка '+key)
  if not isinstance(p['soils'],list) or not p['soils'] or not set(p['soils']).issubset({'sand','loam','clay'}): raise HTTPException(422,'Неверные почвы')
  if not isinstance(p['frost'],(float,int)) or not math.isfinite(p['frost']) or not -60<=p['frost']<=10: raise HTTPException(422,'Неверная морозостойкость')
  if any(p[key]>1 for key in ['drought','salt','wind']): raise HTTPException(422,'Оценки устойчивости должны быть от 0 до 1')
 put_setting(db,'plants',value);log(db,'plant_change',u.id,{'count':len(value)});db.commit();return {'ok':True}
@app.post('/api/admin/layers/import')
async def upload(file:UploadFile=File(...),u=Depends(admin),db:DB=Depends(get_db)):
 content=await file.read(5_000_001);layer=import_layer(file.filename or 'data',content)
 layers=get_setting(db,'layers',[]);layer['id']=secrets.token_hex(8);layers.append(layer);put_setting(db,'layers',layers[-10:]);log(db,'layer_import',u.id,{'name':file.filename,'features':len(layer['features'])});db.commit();return layer
@app.put('/api/admin/layers/{id}/publish')
def publish_layer(id:str,u=Depends(admin),db:DB=Depends(get_db)):
 layers=get_setting(db,'layers',[]);found=False
 for layer in layers:
  if layer['id']==id: layer['status']='published';found=True
 if not found: raise HTTPException(404,'Слой не найден')
 put_setting(db,'layers',layers);log(db,'layer_publish',u.id,{'id':id});db.commit();return {'ok':True}
@app.delete('/api/admin/layers/{id}')
def delete_layer(id:str,u=Depends(admin),db:DB=Depends(get_db)):
 layers=get_setting(db,'layers',[]);put_setting(db,'layers',[x for x in layers if x['id']!=id]);log(db,'layer_delete',u.id,{'id':id});db.commit();return {'ok':True}
