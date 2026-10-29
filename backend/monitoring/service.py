"""Read-only, bounded access to precomputed Sentinel-2 products. No network I/O."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import json
import hashlib
import math
import os

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds
from rasterio.warp import reproject, transform_bounds, Resampling
from shapely.geometry import shape, box, mapping
from shapely.ops import transform as geometry_transform
from pyproj import Transformer
from PIL import Image
from fastapi import HTTPException
from ..data import ZONES

YEARS=(2020,2026)
CATALOG='https://earth-search.aws.element84.com/v1'
MAX_PIXELS=2_000_000

def tr(ru,kk,language='ru'): return kk if language=='kk' else ru
def data_directory():
 return Path(os.getenv('MONITORING_DATA_DIR',Path(__file__).resolve().parents[1]/'storage'/'monitoring')).resolve()
def check_threshold(value):
 if not isinstance(value,(int,float)) or not math.isfinite(value) or not .1<=value<=.9:
  raise HTTPException(422,'NDVI threshold must be between 0.1 and 0.9')
 return float(value)

def warnings(language='ru'):
 return [tr('NDVI показывает вероятный растительный покров, включая траву и кустарники. Изменение не доказывает посадку или вырубку деревьев.','NDVI шөп пен бұталарды қоса алғандағы ықтимал өсімдік жамылғысын көрсетеді. Өзгеріс ағаш отырғызылғанын немесе кесілгенін дәлелдемейді.',language),
 tr('Сравнивается только общая пригодная сетка 10 м за 1 июня — 31 августа. SCL 20 м приведён к сетке 10 м без повышения детализации.','Тек 1 маусым — 31 тамыз аралығындағы ортақ жарамды 10 м тор салыстырылады. 20 м SCL егжей-тегжейін арттырмай 10 м торға келтірілген.',language),
 tr('Медиана нескольких наблюдений снижает влияние облаков, но не устраняет фенологию, различия влажности и ошибки маски. Нужна проверка на месте.','Бірнеше бақылаудың медианасы бұлт әсерін азайтады, бірақ фенологияны, ылғал айырмашылығын және маска қателерін жоймайды. Жергілікті тексеру қажет.',language),
 tr('Покрытие ограничено центром Павлодара и 12 зонами проекта; результаты не относятся ко всему городу.','Қамту Павлодар орталығы және жобаның 12 аумағымен шектелген; нәтижелер бүкіл қалаға қатысты емес.',language)]

def _signature(folder):
 files=[folder/'manifest.json']+[folder/f'{kind}_{year}.tif' for year in YEARS for kind in ('ndvi','count')]
 return tuple((str(p),p.stat().st_mtime_ns,p.stat().st_size) if p.exists() else (str(p),None,None) for p in files)

@lru_cache(maxsize=2)
def _load(signature):
 paths=[Path(v[0]) for v in signature]
 if not paths[0].exists(): return {'error':'not_processed'}
 try:
  manifest=json.loads(paths[0].read_text(encoding='utf-8'))
  if manifest.get('status')!='ready': return {'error':'not_ready','manifest':manifest}
  arrays={};reference=None
  for path in paths[1:]:
   checksum=manifest.get('artifacts',{}).get(path.name,{}).get('sha256')
   if checksum and hashlib.sha256(path.read_bytes()).hexdigest()!=checksum: raise ValueError('Raster checksum mismatch')
   with rasterio.open(path) as source:
    current=(source.width,source.height,source.crs,source.transform)
    if source.width*source.height>MAX_PIXELS or source.count!=1: raise ValueError('Raster exceeds bounded analysis area')
    if source.crs!=rasterio.crs.CRS.from_epsg(32643) or abs(source.transform.a-10)>1e-6 or abs(source.transform.e+10)>1e-6 or source.transform.b or source.transform.d:
     raise ValueError('Expected aligned 10 m EPSG:32643 raster')
    if reference is not None and current!=reference: raise ValueError('Raster grids are not aligned')
    reference=current
    arr=source.read(1)
    if path.stem.startswith('ndvi'):
     arr=arr.astype('float32');arr[(arr==source.nodata)|~np.isfinite(arr)|(arr < -1)|(arr>1)]=np.nan
    arr.setflags(write=False);arrays[path.stem]=arr
  for year in YEARS:
   scenes=manifest.get('periods',{}).get(str(year),{}).get('scenes',[])
   if len(scenes)<2 or any(not s.get('id') or not (s.get('date') or s.get('datetime')) for s in scenes): raise ValueError('Missing identified source scenes')
  return {'manifest':manifest,'arrays':arrays,'grid':reference}
 except Exception as exc:
  # No guessed values when products are missing, corrupt, or mutually inconsistent.
  return {'error':'invalid_products','technical_reason':type(exc).__name__}

def dataset(): return _load(_signature(data_directory()))

def metadata(language='ru'):
 data=dataset();manifest=data.get('manifest',{})
 reason=None
 if data.get('error'):
  reason=tr('Подготовленные спутниковые данные недоступны. Запустите pipeline и проверьте доступность снимков обоих периодов.','Дайын спутниктік деректер қолжетімсіз. Pipeline іске қосып, екі кезеңнің де суреттерін тексеріңіз.',language)
  if data['error']=='invalid_products': reason=tr('Спутниковые продукты не прошли проверку целостности или общей сетки. Расчёт остановлен.','Спутниктік өнімдердің тұтастығы немесе ортақ торы тексеруден өтпеді. Есеп тоқтатылды.',language)
 return {'status':'unavailable' if data.get('error') else 'ready','reason':reason,'reason_code':data.get('error'),
  'dataset_id':manifest.get('dataset_id'),'version':manifest.get('version'),'scope':'pavlodar_centre','bbox_wgs84':manifest.get('bbox_wgs84'),
  'resolution_m':10,'min_observations':2,'created_at':manifest.get('created_at'),
  'periods':manifest.get('periods',{str(y):{'start':f'{y}-06-01','end':f'{y}-08-31','scenes':[]} for y in YEARS}),
  'methodology':tr('NDVI=(B08−B04)/(B08+B04). Медиана NDVI за сезон; SCL допускает только классы 4, 5, 6. В сравнении нужны минимум два пригодных наблюдения каждого года на одной ячейке. Площади рассчитаны только на общей маске, по центрам пикселей 10×10 м. Порог растительности по умолчанию 0,30, настраивается от 0,10 до 0,90.','NDVI=(B08−B04)/(B08+B04). Маусымдық NDVI медианасы; SCL тек 4, 5, 6 кластарын өткізеді. Салыстыру үшін әр тор ұяшығында әр жылға кемінде екі жарамды бақылау қажет. Аудандар тек ортақ маскада, 10×10 м пиксель орталықтары бойынша есептелген. Өсімдік шегі әдепкіде 0,30; 0,10–0,90 аралығында бапталады.',language),
  'warnings':warnings(language),'source':{'catalog':CATALOG,'attribution':'Contains modified Copernicus Sentinel data; Sentinel-2 L2A via Earth Search / Element 84'}}

def _selection(data,zone_id=None):
 width,height,crs,affine=data['grid']
 project=Transformer.from_crs(4326,crs,always_xy=True).transform
 footprint=geometry_transform(project,box(*data['manifest']['bbox_wgs84']))
 mask=geometry_mask([mapping(footprint)],out_shape=(height,width),transform=affine,invert=True,all_touched=False)
 if zone_id:
  zone=next((z for z in ZONES if z['id']==zone_id),None)
  if zone is None: raise HTTPException(404,'Участок не найден')
  projected=geometry_transform(project,shape(zone['geometry']))
  mask &= geometry_mask([mapping(projected)],out_shape=(height,width),transform=affine,invert=True,all_touched=False)
  coverage=projected.intersection(footprint).area/projected.area if projected.area else 0
  return mask,{'ru':zone['ru'],'kk':zone['kk'],'status':zone.get('status'),'geometry':zone['geometry']},projected.area/10000,coverage
 area=footprint.area/10000
 return mask,{'ru':'Центр Павлодара — обработанная область','kk':'Павлодар орталығы — өңделген аумақ'},area,1.0

def selection_data(zone_id=None,threshold=.3):
 threshold=check_threshold(threshold);data=dataset()
 if data.get('error'): return None
 a=data['arrays'];mask,territory,area,coverage=_selection(data,zone_id)
 from .core import comparison_mask,classify_changes
 common=comparison_mask(a['ndvi_2020'],a['ndvi_2026'],a['count_2020'],a['count_2026'],min_observations=2)&mask
 classes=classify_changes(a['ndvi_2020'],a['ndvi_2026'],threshold=threshold,valid=common)
 return data,mask,common,classes,territory,area,coverage

def get_vegetation_change(zone_id=None,period_start=2020,period_end=2026,threshold=.3,language='ru'):
 if (period_start,period_end)!=YEARS: raise HTTPException(422,'Available comparison: 2020–2026, June–August')
 check_threshold(threshold)
 if zone_id and not any(z['id']==zone_id for z in ZONES): raise HTTPException(404,tr('Участок не найден','Аумақ табылмады',language))
 meta=metadata(language)
 fields=['vegetation_2020_ha','vegetation_2026_ha','gain_ha','loss_ha','net_change_ha','change_percent','mean_ndvi_2020','mean_ndvi_2026','mean_ndvi_difference','comparable_fraction']
 base={'status':meta['status'],'reason':meta['reason'],'scope':'zone' if zone_id else 'pavlodar_centre','zone_id':zone_id,'period_start':2020,'period_end':2026,'threshold':threshold,'dataset_id':meta['dataset_id'],'statistics':{k:None for k in fields},'warnings':meta['warnings'],'source':meta['source'],'periods':meta['periods']}
 selection=selection_data(zone_id,threshold)
 if selection is None:
  zone=next((z for z in ZONES if z['id']==zone_id),None)
  base['territory']={k:zone[k] for k in ('ru','kk','status') if k in zone} if zone else {'ru':'Центр Павлодара','kk':'Павлодар орталығы'}
  return base
 data,mask,common,classes,territory,area,coverage=selection
 from .core import compute_statistics
 stats=compute_statistics(data['arrays']['ndvi_2020'],data['arrays']['ndvi_2026'],threshold=threshold,valid=common,region_mask=mask,pixel_area_m2=100)
 stats.pop('status',None)
 stats['mean_ndvi_difference']=round(float(np.mean((data['arrays']['ndvi_2026']-data['arrays']['ndvi_2020'])[common])),6) if common.any() else None
 stats.update(requested_area_ha=round(area,4),scope_area_ha=round(int(mask.sum())*.01,4),aoi_coverage_fraction=round(coverage,6))
 base.update(territory=territory,statistics=stats,status='ready' if common.any() else 'no_data',reason=None if common.any() else tr('Нет пикселей с достаточным числом пригодных наблюдений обоих лет.','Екі жылда да жарамды бақылауы жеткілікті пиксель жоқ.',language))
 if coverage<.999: base['warnings'].append(tr('Часть выбранной зоны находится вне обработанной области. Показатели относятся только к её пересечению с сеткой.','Таңдалған аумақтың бір бөлігі өңделген аймақтан тыс. Көрсеткіштер тек тор ішіндегі бөлігіне қатысты.',language))
 if stats.get('change_percent') is None and common.any(): base['warnings'].append(tr('Процент изменения не определён: в базовом периоде площадь растительности равна нулю.','Өзгеріс пайызы анықталмаған: бастапқы кезеңде өсімдік ауданы нөл.',language))
 return base

def rgba_changes(classes):
 out=np.zeros((*classes.shape,4),dtype=np.uint8)
 for code,color in [(0,(138,145,143,190)),(1,(35,142,74,230)),(2,(198,64,55,230))]: out[classes==code]=color
 return out

def change_map_png(zone_id=None,threshold=.3):
 selection=selection_data(zone_id,threshold)
 if selection is None: raise HTTPException(409,'Satellite products unavailable')
 data,mask,common,classes,*_=selection
 rows,cols=np.where(mask)
 if not len(rows): raise HTTPException(409,'No pixels in selected area')
 image=Image.fromarray(rgba_changes(classes)[rows.min():rows.max()+1,cols.min():cols.max()+1])
 image.thumbnail((1200,850),Image.Resampling.NEAREST)
 output=BytesIO();image.save(output,format='PNG');return output.getvalue()

@lru_cache(maxsize=256)
def _tile(signature,year,z,x,y,threshold):
 data=_load(signature)
 if data.get('error'): raise HTTPException(503,'Satellite products unavailable')
 from .core import comparison_mask,classify_changes
 arrays=data['arrays'];common=comparison_mask(arrays['ndvi_2020'],arrays['ndvi_2026'],arrays['count_2020'],arrays['count_2026'],min_observations=2)&_selection(data)[0]
 if year=='changes': values=classify_changes(arrays['ndvi_2020'],arrays['ndvi_2026'],threshold=threshold,valid=common)
 else:
  values=np.full(common.shape,255,dtype='uint8');values[common]=np.where(arrays['ndvi_'+year][common]>=threshold,1,0)
 size=40075016.68557849/(2**z);left=-20037508.342789244+x*size;top=20037508.342789244-y*size
 target=np.full((256,256),255,dtype='uint8')
 reproject(values,target,src_transform=data['grid'][3],src_crs=data['grid'][2],dst_transform=from_bounds(left,top-size,left+size,top,256,256),dst_crs='EPSG:3857',src_nodata=255,dst_nodata=255,resampling=Resampling.nearest,num_threads=1)
 rgba=rgba_changes(target)
 if year!='changes': rgba[target==1]=(38,134,67,230)
 output=BytesIO();Image.fromarray(rgba).save(output,format='PNG');return output.getvalue()

def tile_png(year,z,x,y,threshold=.3):
 if year not in ('2020','2026','changes') or not 11<=z<=19 or not (0<=x<2**z and 0<=y<2**z): raise HTTPException(422,'Invalid tile coordinates or period')
 check_threshold(threshold)
 return _tile(_signature(data_directory()),year,z,x,y,threshold)
