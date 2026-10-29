"""Deterministic expert models; all numbers include assumptions and version."""
import math
from pyproj import Geod
from shapely.geometry import shape, Point
from fastapi import HTTPException
from .data import VERSION, PLANTS, RATES, COEFFICIENTS, WEIGHTS

GEOD = Geod(ellps="WGS84")

def validated_geometry(geometry):
 try:
  if geometry.get("type") not in ("Polygon","MultiPolygon"):
   raise ValueError("Нужен Polygon или MultiPolygon")
  g = shape(geometry)
  if g.is_empty or not g.is_valid or len(str(geometry)) > 300_000:
   raise ValueError("Геометрия пуста, пересекает сама себя или слишком велика")
  x1,y1,x2,y2 = g.bounds
  if not (76.5 <= x1 < x2 <= 77.5 and 51.9 <= y1 < y2 <= 52.7):
   raise ValueError("Выберите участок в пределах Павлодара")
  area = abs(GEOD.geometry_area_perimeter(g)[0])
  if not 10 <= area <= 2_000_000:
   raise ValueError("Площадь должна быть от 10 м² до 200 га")
  return g, area
 except (ValueError, TypeError, KeyError) as e:
  raise HTTPException(422, str(e))

def recommendation(site, plants=PLANTS, goal=None):
 output=[]
 for p in plants:
  reasons=[]
  if site["temperature"] < p["frost"]: reasons.append("Температура ниже принятой морозостойкости")
  if site["salinity"] > p["salt"] + .3: reasons.append("Высокое засоление")
  if site["purpose"] == "children" and p["id"] in ["caragana","birch"]: reasons.append("Ограничение безопасности для детской территории")
  soil=1 if site["soil"] in p["soils"] else .35
  drought=1-abs((1-site["moisture"])-p["drought"])*.8
  score=100*(.3*soil+.25*drought+.2*(1-site["salinity"]*(1-p["salt"]))+.15*(1-site["traffic"]*(1-p["wind"]))+.1*(1 if site["light"] == p["light"] else .7))
  goal_reason=None
  if goal=='shade':
   score+=8*p['crown']/max(1,max(x['crown'] for x in plants));goal_reason='Учтена цель: тень; приоритет площади зрелой кроны — экспертное допущение.'
  elif goal=='road':
   score+=8*(p['wind']+p['salt'])/2;goal_reason='Учтена цель: защита у дороги; устойчивость к ветру и соли — экспертное допущение.'
  elif goal=='low_maintenance':
   score+=8*p['drought'];goal_reason='Учтена цель: простой уход; устойчивость к засухе — экспертное допущение.'
  output.append({**p,"score":round(max(0,min(100,score))),"excluded":bool(reasons),"reasons":reasons or ["Почва соответствует" if soil==1 else "Требуется улучшение почвы","Оценена устойчивость к засухе, ветру и городской нагрузке"]})
  if goal_reason: output[-1]['reasons'].append(goal_reason)
 return sorted(output,key=lambda p:(p["excluded"],-p["score"]))

def survival(p, site, irrigation, maintenance, coefficients):
 # Conditional annual survival hazards; cumulative probability never increases with time.
 hazard=.03+.15*(1-p["drought"])*(1-site["moisture"])+.12*site["salinity"]*(1-p["salt"])+.07*site["traffic"]
 hazard+=.08*(site["soil"] not in p["soils"])+.06*(1-maintenance)
 hazard-=.035*irrigation+.025*maintenance
 hazard+=max(0,p["frost"]-site["temperature"])*.025
 base=1-coefficients.get("survival_base",.97)
 hazard=max(.01,min(.65,hazard+(base-.03)))
 yearly=[1-hazard,(1-hazard)*(1-hazard*.7),(1-hazard)*(1-hazard*.7)*(1-hazard*.6)]
 return [round(x*100,1) for x in yearly]

def analyze(payload, plants=PLANTS, rates=RATES, coefficients=COEFFICIENTS):
 g,area=validated_geometry(payload["geometry"])
 site={**payload["site"]}
 goal=payload.get('goal')
 if goal in ('children','road'): site['purpose']=goal
 ranks=recommendation(site, plants, goal)
 eligible=[p for p in ranks if not p["excluded"]]
 excluded={p["id"] for p in ranks if p["excluded"]}
 by_id={p["id"]:p for p in plants}
 years=payload.get("years",3); irrigation=payload.get("irrigation",True); maintenance=payload.get("maintenance",.8)
 planted_area=area*payload.get("plantable",.45)
 budget=payload.get("budget",5_000_000)
 fixed=rates['delivery']
 requested=payload.get("plants")
 plan=[]
 if requested is not None:
  for item in requested:
   if item["id"] not in by_id: raise HTTPException(422,"Неизвестное растение")
   if item["id"] in excluded and item["count"]: raise HTTPException(422,"Растение нарушает критические ограничения")
   if item["count"]: plan.append({"id":item["id"],"count":item["count"]})
 else:
  choices=eligible[:3]
  for p in choices:
   part=planted_area/max(1,len(choices))
   full_unit=p["price"]+(rates["planting_tree"] if p["category"]=="tree" else rates["planting_shrub"])+years*(rates["care_tree"] if p["category"]=="tree" else rates["care_shrub"])*maintenance+p["price"]*rates["replacement"]
   # Prepare the actual planting footprint, not every potentially available square metre.
   full_unit+=p['spacing']**2*(rates['preparation']+rates['soil'])
   full_unit+=years*(.8 if p["category"]=="tree" else .2)*rates["water_m3"]*irrigation
   count=max(0,min(math.floor(part/p["spacing"]**2),math.floor(max(0,budget-fixed)/max(1,len(choices))/full_unit)))
   if count: plan.append({"id":p["id"],"count":count})
 quantities={"seedlings":0,"planting":0,"watering":0,"care":0,"replacement":0}
 weighted=[0.,0.,0.];total=0;water=0;space=0
 for item in plan:
  p=by_id[item["id"]];n=item["count"];total+=n;space+=n*p["spacing"]**2
  v=survival(p,site,irrigation,maintenance,coefficients)
  item.update({"ru":p["ru"],"kk":p["kk"],"unit_price":p["price"],"spacing":p["spacing"],"category":p["category"],"survival":v})
  weighted=[a+b*n for a,b in zip(weighted,v)]
  quantities["seedlings"]+=n*p["price"]
  quantities["planting"]+=n*rates["planting_"+p["category"]]
  water+=n*(.8 if p["category"]=="tree" else .2)*irrigation
  quantities["care"]+=n*rates["care_"+p["category"]]*years*maintenance
  quantities["replacement"]+=n*p["price"]*rates["replacement"]
 quantities["watering"]=water*rates["water_m3"]*years
 prepared_area=round(space,1)
 rows=[{"id":"preparation","ru":"Подготовка территории","kk":"Аумақты дайындау","quantity":prepared_area,"unit":"м²","price":rates["preparation"]},{"id":"soil","ru":"Улучшение почвы","kk":"Топырақты жақсарту","quantity":prepared_area,"unit":"м²","price":rates["soil"]},{"id":"delivery","ru":"Доставка","kk":"Жеткізу","quantity":1 if total else 0,"unit":"рейс","price":rates["delivery"]}]
 for k,title,kk in [("seedlings","Саженцы","Көшеттер"),("planting","Посадочные работы","Отырғызу жұмыстары"),("watering","Полив","Суару"),("care","Уход","Күтім"),("replacement","Резерв на замену","Ауыстыру резерві")]:
  rows.append({"id":k,"ru":title,"kk":kk,"quantity":1,"unit":"расчёт","price":round(quantities[k])})
 for row in rows: row["total"]=round(row["quantity"]*row["price"])
 cost=sum(r["total"] for r in rows)
 eco=[]
 for horizon in [5,10,20]:
  co2=dust=rain=canopy=cumulative=0
  for item in plan:
   p=by_id[item["id"]];n=item["count"]
   first3=item["survival"][2]/100
   alive=first3*.985**max(0,horizon-3)
   growth=min(1,horizon/coefficients["growth_years"])**1.5
   dust+=n*p["dust"]*growth*alive
   rain+=n*p["rain"]*growth*alive
   canopy+=n*math.pi*(p["crown"]/2)**2*growth*alive
  canopy=min(planted_area,canopy)
  # Nowak et al. 2013: 0.28 kg C / m² tree canopy / year. Transfer estimate, not local calibration.
  co2=canopy*.28*44/12
  for t in range(1,horizon+1):
   annual_canopy=0
   for item in plan:
    p=by_id[item['id']]
    surv=item['survival'][min(2,t-1)]/100*.985**max(0,t-3)
    annual_canopy+=item['count']*math.pi*(p['crown']/2)**2*min(1,t/coefficients['growth_years'])**1.5*surv
   cumulative+=min(planted_area,annual_canopy)*.28*44/12
  eco.append({"year":horizon,"co2":round(co2,1),"cumulative_co2":round(cumulative,1),"oxygen":round(co2*32/44,1),"dust":round(dust,1) if coefficients["dust_enabled"] else None,"rain":round(rain) if coefficients["rain_enabled"] else None,"canopy":round(canopy),"shade_percent":round(canopy/area*100,1),"cooling_c":None,"kzt_per_kg_co2":round(cost/cumulative,1) if cumulative else None})
 warnings=[]
 if site["provenance"] != "measured": warnings.append("Характеристики участка — демонстрационные или введены пользователем; полевые измерения не проводились.")
 if space>planted_area: warnings.append("Плотность посадки превышает доступную площадь. Уменьшите количество растений.")
 if cost>budget: warnings.append("Смета превышает заданный бюджет.")
 if not total: warnings.append("Бюджета недостаточно либо нет подходящих растений. Измените условия.")
 risks=[]
 if site["moisture"]<.35 and not irrigation: risks.append("Недостаток влаги без полива")
 if site["salinity"]>.3: risks.append("Засоление: требуется анализ почвы")
 if site["traffic"]>.6: risks.append("Высокая транспортная нагрузка")
 if maintenance<.5: risks.append("Недостаточный уход")
 # Schematic grid, bounded and clipped to actual selected polygon.
 positions=[]
 if total and space<=planted_area:
  minx,miny,maxx,maxy=g.bounds
  step=max(1.5,max(by_id[x["id"]]["spacing"] for x in plan))
  dy=step/111320;dx=dy/max(.1,math.cos(math.radians(g.centroid.y)))
  pool=[x["id"] for x in plan for _ in range(x["count"])]
  y=miny+dy/2
  while y<maxy and len(positions)<min(total,1000):
   x=minx+dx/2
   while x<maxx and len(positions)<min(total,1000):
    if g.contains(Point(x,y)):
     positions.append({"id":pool[len(positions)],"coordinates":[x,y]})
    x+=dx
   y+=dy
 return {"version":VERSION,"coefficient_snapshot":coefficients,"rate_snapshot":rates,"area":round(area,1),"plantable_area":round(planted_area,1),"recommendations":ranks,"plan":plan,"total_plants":total,"estimate":{"rows":rows,"total":cost,"years":years,"water_m3_year":round(water,1),"within_budget":cost<=budget,"source":rates["source"],"formula":"Площадь × подготовка + площадь × улучшение почвы + доставка + Σ(количество × цена + посадка + годы × полив + годы × уход × интенсивность + резерв)."},"survival":[round(x/total,1) if total else 0 for x in weighted],"confidence":"low","risks":risks,"ecology":eco,"warnings":warnings,"positions":positions,"placement_status":"Схема для обсуждения, не проект производства работ. До 1000 точек; инженерные сети и отступы требуют обследования.","care":care_schedule(irrigation,maintenance,total)}

def care_schedule(irrigation,maintenance,total):
 tasks={1:"Проверка снеговой нагрузки и защиты стволов",2:"Осмотр зимних повреждений",3:"Санитарный осмотр до сокодвижения",4:"Подготовка почвы, посадка после оттаивания",5:"Полив после посадки, мульча 5–8 см",6:"Контроль влажности и сорняков",7:"Контроль вредителей; полив по влажности",8:"Полив в засуху; без поздних азотных подкормок",9:"Осенняя посадка при подходящей погоде",10:"Влагозарядковый полив, подготовка к зиме",11:"Защита молодых стволов и корней",12:"Осмотр укрытий, снегозадержание"}
 tasks_kk={1:'Қар жүктемесін және дің қорғанысын тексеру',2:'Қысқы зақымдарды тексеру',3:'Шырын жүруіне дейін санитарлық тексеру',4:'Топырақты дайындау, жер жібігеннен кейін отырғызу',5:'Отырғызудан кейін суару, 5–8 см мульча',6:'Ылғал мен арамшөптерді бақылау',7:'Зиянкестерді бақылау; ылғалға қарай суару',8:'Құрғақшылықта суару; кеш азотты қорек бермеу',9:'Ауа райы қолайлы болса күзгі отырғызу',10:'Қыс алдындағы суару және дайындық',11:'Жас діңдер мен тамырларды қорғау',12:'Жабындарды тексеру, қар тоқтату'}
 return [{"month":m,"task":task,"task_kk":tasks_kk[m],"irrigation":bool(irrigation and 4<=m<=10),"visits":(4 if maintenance>.6 else 2) if 4<=m<=10 else 1,"status":"Экспертный календарь; корректируется по погоде и виду","plants":total} for m,task in tasks.items()]

def assess_zones(zones,weights=WEIGHTS,budget=5_000_000):
 output=[]
 for z in zones:
  values={"green":max(0,1-z["green"]/.4) if z.get("green") is not None else None,"social":z.get("social"),"traffic":z.get("traffic"),"soil":z.get("salinity"),"heat":z.get("heat"),"population":z.get("population")}
  available=sum(weights[k] for k,v in values.items() if v is not None)
  score=100*sum(weights[k]*v for k,v in values.items() if v is not None)/available if available else None
  _,area=validated_geometry(z["geometry"])
  cost=round(area*.45*300+15000+area*.45/20*10000)
  reasons=[]
  if values["green"] is not None and values["green"]>.4: reasons.append("Дефицит зелени в демонстрационных данных")
  if z.get("traffic",0)>.6: reasons.append("Транспортная нагрузка — экспертное допущение")
  if z.get("salinity",0)>.3: reasons.append("Неблагоприятная почва — экспертное допущение")
  output.append({**z,"priority":round(score,1) if score is not None else None,"severity":"high" if score and score>=65 else "medium" if score and score>=40 else "low","missing":[k for k,v in values.items() if v is None],"coverage":round(available/max(.001,sum(weights.values()))*100),"reasons":reasons,"preliminary_cost":cost,"area":round(area),"effect_per_million":round(area*.45/cost*1e6)})
 output.sort(key=lambda z:z["priority"] or 0,reverse=True)
 remaining=budget
 for z in output:
  z["funded"]=z["preliminary_cost"]<=remaining
  if z["funded"]: remaining-=z["preliminary_cost"]
 return {"zones":output,"weights":weights,"budget":budget,"remaining":remaining,"method":"Взвешенный индекс по доступным факторам с перенормировкой весов. Дорожная карта: последовательный выбор по приоритету в пределах бюджета, не глобальный оптимум.","confidence":"low"}
