"""Read-only, bounded access to precomputed Sentinel-2 products. No network I/O."""
from functools import lru_cache
from contextlib import ExitStack
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
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window,from_bounds as window_from_bounds,transform as window_transform
from shapely.geometry import shape, box, mapping
from shapely.ops import transform as geometry_transform
from pyproj import Transformer
from PIL import Image
from fastapi import HTTPException
from ..data import ZONES

YEARS=(2020,2026)
CATALOG='https://earth-search.aws.element84.com/v1'
MAX_PIXELS=2_000_000
MAX_CITY_PIXELS=25_000_000
CITY_FOLDER=Path(__file__).resolve().parents[1]/'storage'/'monitoring-city'
PILOT_FOLDER=Path(__file__).resolve().parents[1]/'storage'/'monitoring'
BOUNDARY_FILE=Path(__file__).resolve().parents[1]/'assets'/'pavlodar-boundary.geojson'

def tr(ru,kk,language='ru'): return kk if language=='kk' else ru
def data_directory():
 explicit=os.getenv('MONITORING_DATA_DIR')
 if explicit: return Path(explicit).resolve()
 # A prepared city is selected only after the same integrity and AOI checks used
 # by every request. Never replace or rewrite the validated central pilot.
 try:
  manifest=json.loads((CITY_FOLDER/'manifest.json').read_text(encoding='utf-8'))
  if manifest.get('status')=='ready' and manifest.get('scope')=='administrative_city' and not _load(_signature(CITY_FOLDER)).get('error'):
   return CITY_FOLDER.resolve()
 except (OSError,ValueError,TypeError): pass
 return PILOT_FOLDER.resolve()
def check_threshold(value):
 if not isinstance(value,(int,float)) or not math.isfinite(value) or not .1<=value<=.9:
  raise HTTPException(422,'NDVI threshold must be between 0.1 and 0.9')
 return float(value)

def warnings(language='ru',city=False):
 return [tr('NDVI показывает вероятный растительный покров, включая траву и кустарники. Изменение не доказывает посадку или вырубку деревьев.','NDVI шөп пен бұталарды қоса алғандағы ықтимал өсімдік жамылғысын көрсетеді. Өзгеріс ағаш отырғызылғанын немесе кесілгенін дәлелдемейді.',language),
 tr('Сравнивается только общая пригодная сетка 10 м за 1 июня — 31 августа. SCL 20 м приведён к сетке 10 м без повышения детализации.','Тек 1 маусым — 31 тамыз аралығындағы ортақ жарамды 10 м тор салыстырылады. 20 м SCL егжей-тегжейін арттырмай 10 м торға келтірілген.',language),
 tr('Медиана нескольких наблюдений снижает влияние облаков, но не устраняет фенологию, различия влажности и ошибки маски. Нужна проверка на месте.','Бірнеше бақылаудың медианасы бұлт әсерін азайтады, бірақ фенологияны, ылғал айырмашылығын және маска қателерін жоймайды. Жергілікті тексеру қажет.',language),
 tr('Административная AOI Павлодар Г.А. включает подчинённые и незастроенные территории. NoData не подменяется нулями; пригодность наблюдений раскрывается отдельно.','Павлодар Қ.Ә. әкімшілік AOI құрамына бағынысты және құрылыс салынбаған аумақтар кіреді. NoData нөлмен алмастырылмайды; бақылаулар жарамдылығы бөлек көрсетіледі.',language) if city else tr('Покрытие ограничено центром Павлодара и 12 зонами проекта; результаты не относятся ко всему городу.','Қамту Павлодар орталығы және жобаның 12 аумағымен шектелген; нәтижелер бүкіл қалаға қатысты емес.',language)]

def _sha256(path):
 digest=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1_048_576),b''): digest.update(chunk)
 return digest.hexdigest()

def _city_geometry(manifest):
 aoi=manifest.get('aoi',{});geometry=aoi.get('geometry')
 canonical=json.loads(BOUNDARY_FILE.read_text(encoding='utf-8'))
 polygon=shape(geometry);expected=shape(canonical['geometry'])
 if polygon.is_empty or not polygon.is_valid or polygon.geom_type not in ('Polygon','MultiPolygon') or not polygon.equals(expected):
  raise ValueError('City AOI is not the verified administrative boundary')
 if aoi.get('id')!=canonical['properties']['id']: raise ValueError('Administrative boundary identifier differs')
 return polygon

def _signature(folder):
 files=[folder/'manifest.json']+[folder/f'{kind}_{year}.tif' for year in YEARS for kind in ('ndvi','count')]
 return tuple((str(p),p.stat().st_mtime_ns,p.stat().st_size) if p.exists() else (str(p),None,None) for p in files)

@lru_cache(maxsize=1)
def _load(signature):
 paths=[Path(v[0]) for v in signature]
 if not paths[0].exists(): return {'error':'not_processed'}
 try:
  manifest=json.loads(paths[0].read_text(encoding='utf-8'))
  if manifest.get('status')!='ready': return {'error':'not_ready','manifest':manifest}
  arrays={};reference=None;city=manifest.get('scope')=='administrative_city'
  polygon=_city_geometry(manifest) if city else None
  for path in paths[1:]:
   checksum=manifest.get('artifacts',{}).get(path.name,{}).get('sha256')
   if city and not checksum: raise ValueError('City raster checksum missing')
   if checksum and _sha256(path)!=checksum: raise ValueError('Raster checksum mismatch')
   with rasterio.open(path) as source:
    current=(source.width,source.height,source.crs,source.transform)
    if source.width*source.height>(MAX_CITY_PIXELS if city else MAX_PIXELS) or source.count!=1: raise ValueError('Raster exceeds bounded analysis area')
    if source.crs!=rasterio.crs.CRS.from_epsg(32643) or abs(source.transform.a-10)>1e-6 or abs(source.transform.e+10)>1e-6 or source.transform.b or source.transform.d:
     raise ValueError('Expected aligned 10 m EPSG:32643 raster')
    if reference is not None and current!=reference: raise ValueError('Raster grids are not aligned')
    reference=current
    if not city:
     arr=source.read(1)
     if path.stem.startswith('ndvi'):
      arr=arr.astype('float32');arr[(arr==source.nodata)|~np.isfinite(arr)|(arr < -1)|(arr>1)]=np.nan
     arr.setflags(write=False);arrays[path.stem]=arr
  for year in YEARS:
   scenes=manifest.get('periods',{}).get(str(year),{}).get('scenes',[])
   if len(scenes)<2 or any(not s.get('id') or not (s.get('date') or s.get('datetime')) for s in scenes): raise ValueError('Missing identified source scenes')
  result={'manifest':manifest,'arrays':arrays,'grid':reference,'lazy':city,'paths':{p.stem:p for p in paths[1:]}}
  if city:
   width,height,crs,affine=reference
   if (manifest.get('width'),manifest.get('height'))!=(width,height) or list(affine)[:6]!=manifest.get('transform'):
    raise ValueError('Manifest and raster grid differ')
   projected=geometry_transform(Transformer.from_crs(4326,crs,always_xy=True).transform,polygon)
   bounds=box(*rasterio.transform.array_bounds(height,width,affine))
   if not bounds.buffer(.01).covers(projected): raise ValueError('City raster does not span the administrative AOI')
   result['city_geometry']=projected
  return result
 except Exception as exc:
  # No guessed values when products are missing, corrupt, or mutually inconsistent.
  return {'error':'invalid_products','technical_reason':type(exc).__name__}

def dataset(): return _load(_signature(data_directory()))

def metadata(language='ru'):
 data=dataset();manifest=data.get('manifest',{})
 city=manifest.get('scope')=='administrative_city' and not data.get('error')
 reason=None
 if data.get('error'):
  reason=tr('Подготовленные спутниковые данные недоступны. Запустите pipeline и проверьте доступность снимков обоих периодов.','Дайын спутниктік деректер қолжетімсіз. Pipeline іске қосып, екі кезеңнің де суреттерін тексеріңіз.',language)
  if data['error']=='invalid_products': reason=tr('Спутниковые продукты не прошли проверку целостности или общей сетки. Расчёт остановлен.','Спутниктік өнімдердің тұтастығы немесе ортақ торы тексеруден өтпеді. Есеп тоқтатылды.',language)
 return {'status':'unavailable' if data.get('error') else 'ready','reason':reason,'reason_code':data.get('error'),
  'dataset_id':manifest.get('dataset_id'),'version':manifest.get('version'),'scope':'administrative_city' if city else 'pavlodar_centre','bbox_wgs84':manifest.get('bbox_wgs84'),
  'available_layers':['vegetation','ndvi','quality'] if not data.get('error') else [],
  'aoi':manifest.get('aoi') if city else None,'coverage':manifest.get('coverage') if city else None,
  'resolution_m':10,'min_observations':2,'created_at':manifest.get('created_at'),
  'periods':manifest.get('periods',{str(y):{'start':f'{y}-06-01','end':f'{y}-08-31','scenes':[]} for y in YEARS}),
  'methodology':tr('NDVI=(B08−B04)/(B08+B04). Медиана NDVI за сезон; SCL допускает только классы 4, 5, 6. В сравнении нужны минимум два пригодных наблюдения каждого года на одной ячейке. Площади рассчитаны только на общей маске, по центрам пикселей 10×10 м. Порог растительности по умолчанию 0,30, настраивается от 0,10 до 0,90.','NDVI=(B08−B04)/(B08+B04). Маусымдық NDVI медианасы; SCL тек 4, 5, 6 кластарын өткізеді. Салыстыру үшін әр тор ұяшығында әр жылға кемінде екі жарамды бақылау қажет. Аудандар тек ортақ маскада, 10×10 м пиксель орталықтары бойынша есептелген. Өсімдік шегі әдепкіде 0,30; 0,10–0,90 аралығында бапталады.',language),
  'warnings':warnings(language,city),'source':{'catalog':CATALOG,'attribution':'Contains modified Copernicus Sentinel data; Sentinel-2 L2A via Earth Search / Element 84'}}

def _region(data,zone_id=None):
 """Native projected AOI/zone intersection; geometry is small, not a raster mask."""
 crs=data['grid'][2]
 footprint=data.get('city_geometry')
 if footprint is None:
  footprint=geometry_transform(Transformer.from_crs(4326,crs,always_xy=True).transform,box(*data['manifest']['bbox_wgs84']))
 if zone_id:
  zone=next((z for z in ZONES if z['id']==zone_id),None)
  if zone is None: raise HTTPException(404,'Участок не найден')
  projected=geometry_transform(Transformer.from_crs(4326,crs,always_xy=True).transform,shape(zone['geometry']))
  intersection=projected.intersection(footprint)
  return intersection,{'ru':zone['ru'],'kk':zone['kk'],'status':zone.get('status'),'geometry':zone['geometry']},projected.area/10000,intersection.area/projected.area if projected.area else 0
 aoi=data['manifest'].get('aoi',{})
 territory={'ru':aoi.get('name_ru','Центр Павлодара — обработанная область'),'kk':aoi.get('name_kk','Павлодар орталығы — өңделген аумақ')}
 if data.get('lazy'): territory['geometry']=aoi['geometry']
 return footprint,territory,footprint.area/10000,1.

def _region_window(data,region):
 width,height,_,affine=data['grid']
 if region.is_empty:return Window(0,0,0,0)
 candidate=window_from_bounds(*region.bounds,transform=affine)
 left=max(0,math.floor(candidate.col_off));top=max(0,math.floor(candidate.row_off))
 right=min(width,math.ceil(candidate.col_off+candidate.width));bottom=min(height,math.ceil(candidate.row_off+candidate.height))
 return Window(left,top,max(0,right-left),max(0,bottom-top))

def _blocks(window,size=512):
 for row in range(int(window.row_off),int(window.row_off+window.height),size):
  for column in range(int(window.col_off),int(window.col_off+window.width),size):
   yield Window(column,row,min(size,int(window.col_off+window.width)-column),min(size,int(window.row_off+window.height)-row))

def _sanitize(values):
 values=values.astype('float32',copy=False)
 values[(values < -1)|(values>1)|~np.isfinite(values)]=np.nan
 return values

@lru_cache(maxsize=32)
def _city_statistics(signature,zone_id,threshold):
 """At most four 512² band arrays live at a time, even for the entire city."""
 data=_load(signature)
 if data.get('error'): return None
 region,_,area,coverage=_region(data,zone_id)
 totals={k:0 for k in ('total','common','old','new','gain','loss','valid0','valid1')};sum0=sum1=0.
 with ExitStack() as stack:
  readers={name:stack.enter_context(rasterio.open(path)) for name,path in data['paths'].items()}
  for window in _blocks(_region_window(data,region)):
   mask=geometry_mask([mapping(region)],out_shape=(int(window.height),int(window.width)),transform=window_transform(window,data['grid'][3]),invert=True,all_touched=False)
   if not mask.any():continue
   old=_sanitize(readers['ndvi_2020'].read(1,window=window));new=_sanitize(readers['ndvi_2026'].read(1,window=window))
   count0=readers['count_2020'].read(1,window=window);count1=readers['count_2026'].read(1,window=window)
   valid0=mask&np.isfinite(old)&(count0>=2);valid1=mask&np.isfinite(new)&(count1>=2);common=valid0&valid1
   old_class=common&(old>=threshold);new_class=common&(new>=threshold)
   totals['total']+=int(mask.sum());totals['common']+=int(common.sum());totals['valid0']+=int(valid0.sum());totals['valid1']+=int(valid1.sum())
   totals['old']+=int(old_class.sum());totals['new']+=int(new_class.sum());totals['gain']+=int((common&~old_class&new_class).sum());totals['loss']+=int((common&old_class&~new_class).sum())
   sum0+=float(old[common].sum(dtype=np.float64));sum1+=float(new[common].sum(dtype=np.float64))
 total,n=totals['total'],totals['common']
 result={'threshold':threshold,'total_pixels':total,'comparable_pixels':n,'comparable_fraction':n/total if total else None,'comparable_area_ha':n*.01,'pixel_area_m2':100,
  'requested_area_ha':round(area,4),'scope_area_ha':round(total*.01,4),'aoi_coverage_fraction':round(coverage,6),
  'valid_2020_fraction':totals['valid0']/total if total else None,'valid_2026_fraction':totals['valid1']/total if total else None}
 result.update(dict.fromkeys(['vegetation_2020_ha','vegetation_2026_ha','gain_ha','loss_ha','net_change_ha','change_percent','mean_ndvi_2020','mean_ndvi_2026','mean_ndvi_difference']))
 if n:
  result.update(vegetation_2020_ha=totals['old']*.01,vegetation_2026_ha=totals['new']*.01,gain_ha=totals['gain']*.01,loss_ha=totals['loss']*.01,net_change_ha=(totals['new']-totals['old'])*.01,
   change_percent=(totals['new']-totals['old'])/totals['old']*100 if totals['old'] else None,mean_ndvi_2020=sum0/n,mean_ndvi_2026=sum1/n,mean_ndvi_difference=round((sum1-sum0)/n,6))
 return result

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
 if data.get('lazy'): raise ValueError('City rasters require bounded window reads')
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
 base={'status':meta['status'],'reason':meta['reason'],'scope':'zone' if zone_id else meta['scope'],'zone_id':zone_id,'period_start':2020,'period_end':2026,'threshold':threshold,'dataset_id':meta['dataset_id'],'statistics':{k:None for k in fields},'warnings':meta['warnings'],'source':meta['source'],'periods':meta['periods'],'aoi':meta.get('aoi'),'coverage':meta.get('coverage')}
 data=dataset()
 if data.get('lazy') and not data.get('error'):
  _,territory,_,coverage=_region(data,zone_id)
  stats=dict(_city_statistics(_signature(data_directory()),zone_id,threshold))
  has_common=stats['comparable_pixels']>0
  base.update(territory=territory,statistics=stats,status='ready' if has_common else 'no_data',reason=None if has_common else tr('Нет пикселей с достаточным числом пригодных наблюдений обоих лет.','Екі жылда да жарамды бақылауы жеткілікті пиксель жоқ.',language))
  if coverage<.999:base['warnings'].append(tr('Часть выбранной зоны находится вне обработанной административной AOI.','Таңдалған аумақтың бір бөлігі өңделген әкімшілік AOI аумағынан тыс.',language))
  if has_common and stats['change_percent'] is None:base['warnings'].append(tr('Процент изменения не определён: в базовом периоде площадь растительности равна нулю.','Өзгеріс пайызы анықталмаған: бастапқы кезеңде өсімдік ауданы нөл.',language))
  return base
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
 data=dataset()
 if data.get('error'): raise HTTPException(409,'Satellite products unavailable')
 if data.get('lazy'):
  region,*_=_region(data,zone_id)
  if region.is_empty:raise HTTPException(409,'No pixels in selected area')
  left,bottom,right,top=region.bounds
  scale=min(1200/max(10,right-left),850/max(10,top-bottom))
  width=max(1,math.ceil((right-left)*scale));height=max(1,math.ceil((top-bottom)*scale))
  image=_render(data,'changes',from_bounds(left,bottom,right,top,width,height),data['grid'][2],width,height,threshold,'vegetation',region)
  output=BytesIO();Image.fromarray(image).save(output,format='PNG');return output.getvalue()
 selection=selection_data(zone_id,threshold)
 if selection is None: raise HTTPException(409,'Satellite products unavailable')
 data,mask,common,classes,*_=selection
 rows,cols=np.where(mask)
 if not len(rows): raise HTTPException(409,'No pixels in selected area')
 image=Image.fromarray(rgba_changes(classes)[rows.min():rows.max()+1,cols.min():cols.max()+1])
 image.thumbnail((1200,850),Image.Resampling.NEAREST)
 output=BytesIO();image.save(output,format='PNG');return output.getvalue()

def _render(data,year,affine,crs,width,height,threshold,layer,region=None):
 """Read only this output window. GDAL is limited to 16 MiB warp workspaces."""
 arrays={}
 for name,path in data['paths'].items():
  with rasterio.open(path) as source:
   with WarpedVRT(source,crs=crs,transform=affine,width=width,height=height,resampling=Resampling.nearest,warp_mem_limit=16,nodata=-9999 if name.startswith('ndvi') else 0) as view:
    values=view.read(1,out_dtype='float32' if name.startswith('ndvi') else 'uint16')
    arrays[name]=_sanitize(values) if name.startswith('ndvi') else values
 footprint=data.get('city_geometry')
 if footprint is None:
  footprint=geometry_transform(Transformer.from_crs(4326,data['grid'][2],always_xy=True).transform,box(*data['manifest']['bbox_wgs84']))
 selected=region if region is not None else footprint
 if str(crs)!=str(data['grid'][2]):selected=geometry_transform(Transformer.from_crs(data['grid'][2],crs,always_xy=True).transform,selected)
 mask=geometry_mask([mapping(selected)],out_shape=(height,width),transform=affine,invert=True,all_touched=False)
 from .core import comparison_mask,classify_changes
 common=comparison_mask(arrays['ndvi_2020'],arrays['ndvi_2026'],arrays['count_2020'],arrays['count_2026'])&mask
 if year=='changes':return rgba_changes(classify_changes(arrays['ndvi_2020'],arrays['ndvi_2026'],threshold,common))
 output=np.zeros((height,width,4),dtype='uint8')
 if layer=='quality':
  count=np.minimum(arrays['count_2020'],arrays['count_2026'])
  # These colours denote the number of actual observations, not a modelled probability.
  output[mask&(count<2)]=(138,145,143,190)
  output[mask&(count>=2)&(count<4)]=(209,156,55,220)
  output[mask&(count>=4)]=(38,134,67,230)
 elif layer=='ndvi':
  values=arrays['ndvi_'+year]
  for channel,colors in enumerate(((165,245,32),(91,239,126),(49,216,65))):
   output[:,:,channel]=np.interp(np.nan_to_num(values,nan=0),[-1,0,1],colors).astype('uint8')
  output[:,:,3]=np.where(common,225,0)
 else:
  output[common&(arrays['ndvi_'+year]>=threshold)]=(38,134,67,230)
  output[common&(arrays['ndvi_'+year]<threshold)]=(138,145,143,190)
 return output

@lru_cache(maxsize=64)
def _tile(signature,year,z,x,y,threshold,layer='vegetation'):
 data=_load(signature)
 if data.get('error'): raise HTTPException(503,'Satellite products unavailable')
 size=40075016.68557849/(2**z);left=-20037508.342789244+x*size;top=20037508.342789244-y*size
 tile_bounds=box(left,top-size,left+size,top)
 native_bounds=box(*transform_bounds(data['grid'][2],'EPSG:3857',*rasterio.transform.array_bounds(data['grid'][1],data['grid'][0],data['grid'][3])))
 if not tile_bounds.intersects(native_bounds):rgba=np.zeros((256,256,4),dtype='uint8')
 else:rgba=_render(data,year,from_bounds(left,top-size,left+size,top,256,256),'EPSG:3857',256,256,threshold,layer)
 output=BytesIO();Image.fromarray(rgba).save(output,format='PNG');return output.getvalue()

def tile_png(year,z,x,y,threshold=.3,layer='vegetation'):
 if year not in ('2020','2026','changes') or not 8<=z<=19 or not (0<=x<2**z and 0<=y<2**z): raise HTTPException(422,'Invalid tile coordinates or period')
 if layer not in ('vegetation','ndvi','quality'):raise HTTPException(422,'Invalid satellite layer')
 check_threshold(threshold)
 return _tile(_signature(data_directory()),year,z,x,y,threshold,layer)
