"""Versioned sources: actual OSM outlines, explicit expert/synthetic assessment fields."""
import json
from pathlib import Path
VERSION = "2026-10-29.2"
PLANTS = [
 {"id":"pine","ru":"Сосна обыкновенная","kk":"Кәдімгі қарағай","latin":"Pinus sylvestris","category":"tree","price":2000,"stock":"20–40 см, C3","frost":-40,"drought":0.85,"salt":0.35,"wind":0.8,"soils":["sand","loam"],"light":"sun","spacing":5,"crown":6,"height":25,"co2":12,"dust":0.8,"rain":300,"safety":"Светолюбива. Не подходит для сильно засолённых и заболоченных почв.","source":"https://www.greenmax.kz/index.php/price","botany":"https://plants.ces.ncsu.edu/plants/pinus-sylvestris/"},
 {"id":"birch","ru":"Берёза повислая","kk":"Қотыр қайың","latin":"Betula pendula","category":"tree","price":2000,"stock":"1,5–2 м, C3","frost":-40,"drought":0.45,"salt":0.2,"wind":0.65,"soils":["sand","loam"],"light":"sun","spacing":5,"crown":7,"height":20,"co2":14,"dust":1.1,"rain":360,"safety":"Пыльца аллергенна; у детских и медицинских учреждений предпочтительны другие виды.","source":"https://www.greenmax.kz/index.php/price","botany":"https://plants.ces.ncsu.edu/plants/betula-pendula/"},
 {"id":"rowan","ru":"Рябина обыкновенная","kk":"Кәдімгі шетен","latin":"Sorbus aucuparia","category":"tree","price":1500,"stock":"40–60 см, C3","frost":-40,"drought":0.5,"salt":0.25,"wind":0.7,"soils":["loam","sand"],"light":"sun","spacing":4,"crown":5,"height":12,"co2":8,"dust":0.7,"rain":200,"safety":"При засухе нужен полив; учитывать плоды на пешеходных дорожках.","source":"https://www.greenmax.kz/index.php/price","botany":"https://plants.ces.ncsu.edu/plants/sorbus-aucuparia/"},
 {"id":"caragana","ru":"Карагана древовидная","kk":"Ағаш тәрізді қараған","latin":"Caragana arborescens","category":"shrub","price":1500,"stock":"40–60 см, C3","frost":-45,"drought":0.95,"salt":0.7,"wind":0.9,"soils":["sand","loam","clay"],"light":"sun","spacing":1.8,"crown":3,"height":4,"co2":2,"dust":0.25,"rain":60,"safety":"Есть колючки. Исключается непосредственно у детских площадок.","source":"https://www.greenmax.kz/index.php/price","botany":"https://plants.ces.ncsu.edu/plants/caragana-arborescens/"},
 {"id":"spruce","ru":"Ель канадская","kk":"Канадалық шырша","latin":"Picea glauca","category":"tree","price":3500,"stock":"20–40 см, C3","frost":-45,"drought":0.4,"salt":0.25,"wind":0.7,"soils":["loam","clay"],"light":"partial","spacing":4.5,"crown":5,"height":20,"co2":9,"dust":0.9,"rain":280,"safety":"Нужны умеренно влажная почва и защита молодых растений от ожогов.","source":"https://www.greenmax.kz/index.php/price","botany":"https://plants.ces.ncsu.edu/plants/picea-glauca/"},
 {"id":"dogwood","ru":"Дёрен белый","kk":"Ақ свидина","latin":"Cornus alba","category":"shrub","price":8000,"stock":"до 1 м; цена от","frost":-40,"drought":0.5,"salt":0.45,"wind":0.75,"soils":["loam","clay","sand"],"light":"partial","spacing":1.5,"crown":2.5,"height":3,"co2":1.8,"dust":0.2,"rain":50,"safety":"Для декоративной посадки; плоды не предназначены для питания.","source":"https://plants.kz/sajenci-deren-belyj-almaty","botany":"https://plants.ces.ncsu.edu/plants/cornus-alba/"}
]
for p in PLANTS:
 p.update({"price_date":"2026-10-28","provenance":"reference","parameter_status":"expert_estimate","ecology_status":"illustrative_assumption","care":"Полив после посадки, мульчирование 5–8 см, ежегодный осмотр."})

def rectangle(lon, lat, dx=.0028, dy=.0018):
 return {"type":"Polygon","coordinates":[[[lon,lat],[lon+dx,lat],[lon+dx,lat+dy],[lon,lat+dy],[lon,lat]]]}

ZONES = json.loads((Path(__file__).parent/'assets'/'pavlodar-zones.json').read_text(encoding='utf-8'))

RATES = {"preparation":180,"soil":120,"planting_tree":2500,"planting_shrub":900,"delivery":15000,"water_m3":300,"care_tree":2000,"care_shrub":700,"replacement":.12,"source":"Экспертные демонстрационные ставки, не коммерческая оферта","date":"2026-10-28"}
COEFFICIENTS = {"version":VERSION,"green_target":.4,"growth_years":15,"survival_base":.97,"dust_enabled":True,"rain_enabled":True,"source":"Экспертные допущения MVP; не калиброваны по Павлодару"}
WEIGHTS = {"green":.35,"social":.2,"traffic":.2,"soil":.15,"heat":.05,"population":.05}
