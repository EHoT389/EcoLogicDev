"""Small, explicit analytical fixtures; never production satellite products."""
from io import BytesIO
import hashlib
import json
import math

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin,array_bounds
from rasterio.warp import transform_bounds
from pyproj import Transformer
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from backend.monitoring import service
from backend.monitoring.api import router


@pytest.fixture
def city(tmp_path,monkeypatch):
 folder=tmp_path/'city';folder.mkdir()
 affine=from_origin(633000,5794000,10,10)
 bounds=transform_bounds('EPSG:32643','EPSG:4326',*array_bounds(2,2,affine))
 # An analytical geometry supplied through a test-only canonical boundary path.
 project=Transformer.from_crs(32643,4326,always_xy=True)
 geometry={'type':'Polygon','coordinates':[[list(project.transform(x,y)) for x,y in ((633000,5793980),(633020,5793980),(633020,5794000),(633000,5794000),(633000,5793980))]]}
 boundary=tmp_path/'test-boundary.json';boundary.write_text(json.dumps({'type':'Feature','geometry':geometry,'properties':{'id':'test-fixture-administrative'}}))
 values={'ndvi_2020':np.array([[.7,.1],[.6,.2]],dtype='float32'),'ndvi_2026':np.array([[.8,.8],[.1,.4]],dtype='float32'),'count_2020':np.array([[4,2],[3,1]],dtype='uint16'),'count_2026':np.array([[4,2],[3,3]],dtype='uint16')}
 artifacts={}
 for name,array in values.items():
  path=folder/(name+'.tif')
  with rasterio.open(path,'w',driver='GTiff',height=2,width=2,count=1,dtype=array.dtype,crs='EPSG:32643',transform=affine,nodata=-9999 if name.startswith('ndvi') else 0) as out:out.write(array,1)
  artifacts[path.name]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
 manifest={'status':'ready','scope':'administrative_city','dataset_id':'test-only-not-satellite','version':'analytical-fixture','bbox_wgs84':bounds,'width':2,'height':2,'transform':list(affine)[:6],
  'aoi':{'id':'test-fixture-administrative','geometry':geometry,'name_ru':'Test fixture','name_kk':'Test fixture','source':'https://example.invalid/fixture'},'artifacts':artifacts,
  'periods':{str(y):{'start':f'{y}-06-01','end':f'{y}-08-31','scenes':[{'id':f'explicit-analytical-fixture-{y}-{n}','date':f'{y}-06-0{n+1}'} for n in range(2)]} for y in (2020,2026)}}
 (folder/'manifest.json').write_text(json.dumps(manifest))
 monkeypatch.setenv('MONITORING_DATA_DIR',str(folder));monkeypatch.setattr(service,'BOUNDARY_FILE',boundary)
 service._load.cache_clear();service._tile.cache_clear();service._city_statistics.cache_clear()
 yield folder
 service._load.cache_clear();service._tile.cache_clear();service._city_statistics.cache_clear()


@pytest.fixture
def client():
 app=FastAPI();app.include_router(router)
 with TestClient(app) as c:yield c


def test_city_is_lazy_and_stats_match_common_native_pixels(city,client):
 loaded=service.dataset()
 assert loaded['lazy'] is True and loaded['arrays']=={}
 result=client.get('/api/monitoring/changes').json();stats=result['statistics']
 assert result['scope']=='administrative_city' and result['status']=='ready'
 assert stats['total_pixels']==4 and stats['comparable_pixels']==3 and stats['comparable_fraction']==.75
 assert stats['vegetation_2020_ha']==stats['vegetation_2026_ha']==.02
 assert stats['gain_ha']==stats['loss_ha']==.01 and stats['net_change_ha']==0
 assert stats['valid_2020_fraction']==.75 and stats['valid_2026_fraction']==1
 high=service.get_vegetation_change(threshold=.75)['statistics']
 assert high['vegetation_2020_ha']==0 and high['change_percent'] is None


def test_city_capabilities_aoi_and_new_layers(city,client):
 meta=client.get('/api/monitoring/metadata').json()
 assert meta['available_layers']==['vegetation','ndvi','quality'] and meta['aoi']['geometry']['type']=='Polygon'
 assert 'центром' not in ' '.join(meta['warnings'])
 z=19;lon,lat=Transformer.from_crs(32643,4326,always_xy=True).transform(633010,5793990);x=int((lon+180)/360*2**z);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)
 images=[]
 for layer in ('vegetation','ndvi','quality'):
  response=client.get(f'/api/monitoring/tiles/2020/{z}/{x}/{y}?layer={layer}')
  assert response.status_code==200
  images.append(np.asarray(Image.open(BytesIO(response.content))))
 assert any((v[:,:,3]>0).any() for v in images)
 assert not np.array_equal(images[0],images[1]) and not np.array_equal(images[1],images[2])
 assert client.get(f'/api/monitoring/tiles/2020/{z}/{x}/{y}?layer=fake').status_code==422


def test_city_wrong_boundary_or_tampered_raster_is_unavailable(city,client):
 manifest=json.loads((city/'manifest.json').read_text());manifest['aoi']['id']='wrong-id'
 (city/'manifest.json').write_text(json.dumps(manifest))
 result=client.get('/api/monitoring/changes').json()
 assert result['status']=='unavailable' and result['statistics']['gain_ha'] is None
 manifest['aoi']['id']='test-fixture-administrative';(city/'manifest.json').write_text(json.dumps(manifest))
 with rasterio.open(city/'ndvi_2020.tif','r+') as writer:writer.write(np.zeros((2,2),dtype='float32'),1)
 assert client.get('/api/monitoring/metadata').json()['status']=='unavailable'


def test_default_uses_only_ready_valid_city_and_explicit_override_wins(city,monkeypatch,tmp_path):
 monkeypatch.delenv('MONITORING_DATA_DIR');monkeypatch.setattr(service,'CITY_FOLDER',city);monkeypatch.setattr(service,'PILOT_FOLDER',tmp_path/'pilot')
 assert service.data_directory()==city.resolve()
 manifest=json.loads((city/'manifest.json').read_text());manifest['status']='processing';(city/'manifest.json').write_text(json.dumps(manifest))
 assert service.data_directory()==(tmp_path/'pilot').resolve()
 monkeypatch.setenv('MONITORING_DATA_DIR',str(city))
 assert service.data_directory()==city.resolve() and service.metadata()['status']=='unavailable'
