"""Independent acceptance checks for downloaded satellite products, never fixtures.

These tests skip when the separately built real dataset is absent. Pure analytical
and missing-data tests in test_monitoring_core/api remain mandatory everywhere.
Set MONITORING_VERIFY_REMOTE=1 for the additional bounded public-COG probe.
"""
from datetime import datetime
from io import BytesIO
from pathlib import Path
import hashlib
import json
import math
import os
import warnings

import numpy as np
import pytest
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import xy
from shapely.geometry import box, mapping, shape
from shapely.ops import transform
from pyproj import Transformer
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image
from pypdf import PdfReader

from backend.data import ZONES
from backend.monitoring import service
from backend.main import app

REAL_FOLDER=Path(__file__).resolve().parents[1]/'backend'/'storage'/'monitoring'


@pytest.fixture
def real_products(monkeypatch):
 manifest_path=REAL_FOLDER/'manifest.json'
 if not manifest_path.exists(): pytest.skip('Real Sentinel-2 dataset has not been built; no analytical fixture substituted')
 manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
 if manifest.get('status')!='ready': pytest.skip('Real source unavailable: '+str(manifest.get('reason','not ready')))
 monkeypatch.setenv('MONITORING_DATA_DIR',str(REAL_FOLDER));service._load.cache_clear();service._tile.cache_clear()
 arrays={};grid=None
 for name in ('ndvi_2020','ndvi_2026','count_2020','count_2026','delta_ndvi','changes'):
  with rasterio.open(REAL_FOLDER/(name+'.tif')) as src:
   arrays[name]=src.read(1)
   signature=(src.width,src.height,src.crs,src.transform)
   assert src.crs.to_epsg()==32643 and src.transform.a==10 and src.transform.e==-10
   assert src.transform.b==src.transform.d==0
   if grid is not None: assert signature==grid
   grid=signature
 width,height,crs,affine=grid
 projected=transform(Transformer.from_crs(4326,crs,always_xy=True).transform,box(*manifest['bbox_wgs84']))
 inside=geometry_mask([mapping(projected)],out_shape=(height,width),transform=affine,invert=True,all_touched=False)
 old,new=arrays['ndvi_2020'],arrays['ndvi_2026']
 common=inside & np.isfinite(old)&np.isfinite(new)&(old>=-1)&(old<=1)&(new>=-1)&(new<=1)&(arrays['count_2020']>=2)&(arrays['count_2026']>=2)
 yield manifest,arrays,grid,inside,common
 service._load.cache_clear();service._tile.cache_clear()


def test_real_provenance_checksums_and_same_summer_seasons(real_products):
 manifest,arrays,grid,inside,common=real_products
 assert manifest['collection']=='sentinel-2-l2a' and manifest['resolution_m']==10
 assert manifest['dataset_id'] and manifest['processing_code_sha256']
 for filename,artifact in manifest['artifacts'].items():
  content=(REAL_FOLDER/filename).read_bytes()
  assert len(content)==artifact['bytes']
  assert hashlib.sha256(content).hexdigest()==artifact['sha256']
 archived=json.loads((REAL_FOLDER/'selected-scenes.stac.json').read_text(encoding='utf-8'))
 for year in (2020,2026):
  period=manifest['periods'][str(year)];scenes=period['scenes']
  assert period['start']==f'{year}-06-01' and period['end']==f'{year}-08-31'
  assert len(scenes)>=2 and len({s['id'] for s in scenes})==len(scenes)
  assert period['median_composite'] and period['min_observations']==2
  items={i['id']:i for i in archived[str(year)]['features']}
  months=[]
  for scene in scenes:
   date=datetime.fromisoformat(scene['date'].replace('Z','+00:00'))
   assert date.year==year and 6<=date.month<=8;months.append(date.month)
   assert scene['provenance']=='observed_satellite'
   assert scene['id'] in items and scene['source'].startswith(service.CATALOG+'/collections/sentinel-2-l2a/items/')
   assert 0<=scene['cloud_cover']<35
   for band,filename in [('red','B04.tif'),('nir','B08.tif'),('scl','SCL.tif')]:
    assert scene['assets'][band].startswith('https://sentinel-cogs.s3.us-west-2.amazonaws.com/')
    assert scene['assets'][band].endswith(filename)
   baseline=float(scene['processing_baseline'])
   expected_offset=0 if baseline<4 or scene['boa_offset_applied'] is True else -.1
   assert baseline<4 or isinstance(scene['boa_offset_applied'],bool)
   for band in ('red','nir'):
    audit=scene['asset_radiometry'][band]
    assert audit['applied_scale']==.0001 and audit['applied_offset']==expected_offset
   assert not scene['id'].startswith(('analytical-fixture','test','demo'))
  assert set(months)=={6,7,8},'Season must span the same three summer months'
 assert common.any()


def test_real_composites_reproduce_cached_observations_and_quality(real_products):
 manifest,arrays,grid,inside,common=real_products
 for year in (2020,2026):
  observations=[]
  for scene in manifest['periods'][str(year)]['scenes']:
   files=list((REAL_FOLDER/'cache').glob(scene['id']+'-*.npz'))
   assert len(files)==1,'An identified observation must have one unambiguous cached grid'
   with np.load(files[0],allow_pickle=False) as cache: values=cache['ndvi'].copy()
   assert values.shape==inside.shape
   values[~inside]=np.nan;observations.append(values)
  stack=np.stack(observations)
  valid=np.isfinite(stack)&(stack>=-1)&(stack<=1)
  counts=valid.sum(axis=0)
  with warnings.catch_warnings():
   warnings.simplefilter('ignore',RuntimeWarning);median=np.nanmedian(np.where(valid,stack,np.nan),axis=0)
  actual=arrays[f'ndvi_{year}']
  assert np.array_equal(arrays[f'count_{year}'],counts)
  assert np.all(actual[~inside]==-9999) and np.all(counts[~inside]==0)
  assert np.allclose(actual[counts>0],median[counts>0],rtol=0,atol=0)
  assert np.all(actual[counts==0]==-9999)
 expected_delta=(arrays['ndvi_2026']-arrays['ndvi_2020'])[common]
 assert np.array_equal(arrays['delta_ndvi'][common],expected_delta)
 assert np.all(arrays['delta_ndvi'][~common]==-9999)
 assert np.all(arrays['changes'][~common]==255)


def test_real_statistics_independently_match_common_mask_and_all_zones(real_products):
 manifest,arrays,grid,inside,common=real_products
 before_status={z['id']:z['status'] for z in ZONES}
 before,new=arrays['ndvi_2020'],arrays['ndvi_2026']
 result=service.get_vegetation_change();s=result['statistics']
 old_vegetation=common&(before>=.3);new_vegetation=common&(new>=.3)
 gain=common&(before<.3)&(new>=.3);loss=common&(before>=.3)&(new<.3)
 assert s['total_pixels']==int(inside.sum()) and s['comparable_pixels']==int(common.sum())
 expected={'vegetation_2020_ha':old_vegetation.sum()*.01,'vegetation_2026_ha':new_vegetation.sum()*.01,'gain_ha':gain.sum()*.01,'loss_ha':loss.sum()*.01,'net_change_ha':(int(new_vegetation.sum())-int(old_vegetation.sum()))*.01,'comparable_fraction':common.sum()/inside.sum()}
 for name,value in expected.items():assert s[name]==pytest.approx(float(value),abs=1e-9)
 assert s['net_change_ha']==pytest.approx(s['gain_ha']-s['loss_ha'])
 assert s['change_percent']==pytest.approx(s['net_change_ha']/s['vegetation_2020_ha']*100)
 assert s['mean_ndvi_2020']==pytest.approx(before[common].mean(dtype=np.float64))
 assert s['mean_ndvi_2026']==pytest.approx(new[common].mean(dtype=np.float64))
 assert np.all(arrays['changes'][gain]==1) and np.all(arrays['changes'][loss]==2)
 assert service.get_vegetation_change(threshold=.5)['statistics']['vegetation_2020_ha']<s['vegetation_2020_ha']
 project=Transformer.from_crs(4326,grid[2],always_xy=True).transform
 for zone in ZONES:
  selected=inside & geometry_mask([mapping(transform(project,shape(zone['geometry'])))],out_shape=inside.shape,transform=grid[3],invert=True,all_touched=False)
  zone_common=selected & common;z=service.get_vegetation_change(zone['id'])['statistics']
  assert z['total_pixels']==int(selected.sum()) and z['comparable_pixels']==int(zone_common.sum())
  assert z['vegetation_2020_ha']==pytest.approx(int((zone_common&(before>=.3)).sum())*.01)
  assert z['vegetation_2026_ha']==pytest.approx(int((zone_common&(new>=.3)).sum())*.01)
  assert z['net_change_ha']==pytest.approx(z['gain_ha']-z['loss_ha'])
 assert {z['id']:z['status'] for z in ZONES}==before_status


def test_real_geojson_is_display_wgs84_not_statistical_area_source(real_products):
 doc=json.loads((REAL_FOLDER/'changes.geojson').read_text(encoding='utf-8'))
 assert doc['type']=='FeatureCollection' and doc['properties']['statistics_from_native_raster'] is True
 assert {f['properties']['class'] for f in doc['features']}=={'gain','loss'}
 for feature in doc['features']:
  geom=shape(feature['geometry']);assert geom.is_valid and not geom.is_empty
  assert feature['properties']['display_simplification_m']==2
  assert feature['properties']['provenance']=='derived_observed_satellite'
  assert box(76.92,52.26,76.99,52.315).covers(geom)


def test_real_api_tiles_and_bilingual_reports(real_products):
 result=service.get_vegetation_change();s=result['statistics']
 with TestClient(app) as client:
  assert client.get('/api/monitoring/metadata').json()['status']=='ready'
  assert client.get('/api/monitoring/periods').json()['season']=={'start':'06-01','end':'08-31'}
  live=client.get('/api/monitoring/changes').json()
  assert live['dataset_id']==result['dataset_id'] and live['statistics']==s
  zoom=15;lon,lat=76.95,52.285
  x=int((lon+180)/360*2**zoom);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**zoom)
  for period in ('2020','2026','changes'):
   tile=client.get(f'/api/monitoring/tiles/{period}/{zoom}/{x}/{y}')
   assert tile.status_code==200 and tile.headers['cache-control'].startswith('public')
   image=np.array(Image.open(BytesIO(tile.content)))
   assert image.shape==(256,256,4) and (image[:,:,3]>0).any()
  outside=client.get('/api/monitoring/tiles/changes/15/0/0')
  assert np.array(Image.open(BytesIO(outside.content)))[:,:,3].max()==0
  for lang in ('ru','kk'):
   headers={'Accept-Language':lang}
   pdf=client.get('/api/monitoring/export?format=pdf',headers=headers)
   assert pdf.status_code==200
   reader=PdfReader(BytesIO(pdf.content));text='\n'.join(p.extract_text() for p in reader.pages)
   assert len(reader.pages)==3 and result['dataset_id'] in text
   assert ('Карта изменений' if lang=='ru' else 'Өзгерістер картасы') in text
   assert str(s['vegetation_2020_ha']) in text and str(s['vegetation_2026_ha']) in text
   excel=client.get('/api/monitoring/export?format=xlsx',headers=headers)
   assert excel.status_code==200
   book=load_workbook(BytesIO(excel.content))
   assert book['Мониторинг']['B5'].value==s['vegetation_2020_ha']
   assert book['Мониторинг']['B6'].value==s['vegetation_2026_ha']
   assert len(book['Карта']._images)==1 and len(book['NDVI']._charts)==1


@pytest.mark.skipif(os.getenv('MONITORING_VERIFY_REMOTE')!='1',reason='Optional actual COG re-read; set MONITORING_VERIFY_REMOTE=1')
def test_real_cog_pixel_re_read_independently_matches_observation_cache(real_products):
 manifest,arrays,grid,inside,common=real_products
 # A tiny, bounded set of pixel samples from original B04/B08/SCL, independent
 # of pipeline helpers and of the resulting seasonal composites.
 rows=np.array([200,201,202,250,251]);cols=np.array([180,181,182,230,231])
 coordinates=list(zip(*xy(grid[3],rows,cols,offset='center')))
 for year in (2020,2026):
  scene=manifest['periods'][str(year)]['scenes'][0];bands={}
  with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',GDAL_HTTP_TIMEOUT='35',GDAL_HTTP_CONNECTTIMEOUT='15'):
   for band in ('red','nir','scl'):
    with rasterio.open(scene['assets'][band]) as src:
     assert src.crs.to_epsg()==32643
     bands[band]=np.array([value[0] for value in src.sample(coordinates)]).astype(np.float32)
  red=bands['red']*scene['asset_radiometry']['red']['applied_scale']+scene['asset_radiometry']['red']['applied_offset']
  nir=bands['nir']*scene['asset_radiometry']['nir']['applied_scale']+scene['asset_radiometry']['nir']['applied_offset']
  valid=np.isin(bands['scl'],[4,5,6])&(bands['red']!=0)&(bands['nir']!=0)&(red>=0)&(nir>=0)&((red+nir)>0)
  expected=np.full(red.shape,np.nan,dtype=np.float32);expected[valid]=(nir[valid]-red[valid])/(nir[valid]+red[valid])
  with np.load(next((REAL_FOLDER/'cache').glob(scene['id']+'-*.npz')),allow_pickle=False) as cached:actual=cached['ndvi'][rows,cols]
  assert valid.any() and np.allclose(actual,expected,equal_nan=True,rtol=0,atol=1e-6)
