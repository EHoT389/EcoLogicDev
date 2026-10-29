"""Analytical test fixtures only. They are never copied to the production data folder."""
from io import BytesIO
import json
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader
from PIL import Image
from backend.monitoring.api import router
from backend.monitoring import service

@pytest.fixture
def products(tmp_path,monkeypatch):
 monkeypatch.setenv('MONITORING_DATA_DIR',str(tmp_path))
 manifest={'status':'ready','version':'test-fixture','dataset_id':'unit-test-not-satellite-data','bbox_wgs84':[76.95,52.28,76.951,52.281],'periods':{str(y):{'start':f'{y}-06-01','end':f'{y}-08-31','scenes':[{'id':f'analytical-fixture-{y}-{i}','date':f'{y}-06-0{i+1}','source':'https://example.invalid/test-fixture','cloud_cover':0} for i in range(2)]} for y in (2020,2026)}}
 bounds=transform_bounds('EPSG:32643','EPSG:4326',633000,5793980,633020,5794000)
 manifest['bbox_wgs84']=[bounds[0]-.00001,bounds[1]-.00001,bounds[2]+.00001,bounds[3]+.00001]
 (tmp_path/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
 values={'ndvi_2020':np.array([[.7,.1],[.6,.2]],dtype='float32'),'ndvi_2026':np.array([[.8,.8],[.1,.4]],dtype='float32'),'count_2020':np.array([[2,2],[2,1]],dtype='uint16'),'count_2026':np.array([[2,2],[2,2]],dtype='uint16')}
 for name,array in values.items():
  with rasterio.open(tmp_path/(name+'.tif'),'w',driver='GTiff',width=2,height=2,count=1,dtype=array.dtype,crs='EPSG:32643',transform=from_origin(633000,5794000,10,10),nodata=-9999 if name.startswith('ndvi') else 0) as destination:destination.write(array,1)
 service._load.cache_clear();service._tile.cache_clear()
 return tmp_path

@pytest.fixture
def client():
 app=FastAPI();app.include_router(router)
 with TestClient(app) as c:yield c

def test_no_dataset_never_returns_fake_measurements(client,tmp_path,monkeypatch):
 monkeypatch.setenv('MONITORING_DATA_DIR',str(tmp_path))
 result=client.get('/api/monitoring/changes').json()
 assert result['status']=='unavailable'
 assert all(v is None for v in result['statistics'].values())
 assert client.get('/api/monitoring/export').status_code==409
 assert client.get('/api/monitoring/zones/missing').status_code==404

def test_common_mask_areas_means_and_threshold(client,products):
 result=client.get('/api/monitoring/changes').json();s=result['statistics']
 assert result['status']=='ready'
 assert s['comparable_pixels']==3 and s['total_pixels']==4 and s['comparable_fraction']==.75
 assert s['vegetation_2020_ha']==.02 and s['vegetation_2026_ha']==.02
 assert s['gain_ha']==.01 and s['loss_ha']==.01 and s['net_change_ha']==0
 assert s['mean_ndvi_2020']==pytest.approx((.7+.1+.6)/3)
 high=client.get('/api/monitoring/changes?threshold=.75').json()['statistics']
 assert high['vegetation_2020_ha']==0 and high['change_percent'] is None
 assert client.get('/api/monitoring/changes?threshold=nan').status_code==422
 assert client.get('/api/monitoring/changes?threshold=2').status_code==422

def test_grid_mismatch_is_unavailable_not_miscompared(client,products):
 with rasterio.open(products/'count_2026.tif','r+') as output:output.transform=from_origin(633001,5794000,10,10)
 result=client.get('/api/monitoring/changes').json()
 assert result['status']=='unavailable' and result['statistics']['gain_ha'] is None

def test_zero_common_pixels_keep_means_and_areas_null(client,products):
 with rasterio.open(products/'count_2026.tif','r+') as output:output.write(np.zeros((2,2),dtype='uint16'),1)
 result=client.get('/api/monitoring/changes').json()
 assert result['status']=='no_data'
 assert result['statistics']['vegetation_2020_ha'] is None
 assert result['statistics']['mean_ndvi_difference'] is None

def test_tiles_are_png_and_bounds_are_validated(client,products):
 assert client.get('/api/monitoring/tiles/changes/10/0/0').status_code==422
 assert client.get('/api/monitoring/tiles/changes/15/-1/0').status_code==422
 result=client.get('/api/monitoring/tiles/changes/15/0/0')
 assert result.status_code==200 and result.headers['content-type']=='image/png'
 image=Image.open(BytesIO(result.content));assert image.size==(256,256) and image.mode=='RGBA'
 assert np.array(image)[:,:,3].max()==0

def test_bilingual_exports_use_actual_fixture_values(client,products):
 r=client.get('/api/monitoring/export?format=pdf',headers={'Accept-Language':'kk'})
 assert r.status_code==200 and r.content.startswith(b'%PDF')
 reader=PdfReader(BytesIO(r.content));content='\n'.join(p.extract_text() for p in reader.pages)
 assert 'Өзгерістер картасы' in content and 'unit-test-not-satellite-data' in content
 excel=client.get('/api/monitoring/export?format=xlsx',headers={'Accept-Language':'kk'})
 assert excel.status_code==200
 workbook=load_workbook(BytesIO(excel.content))
 assert workbook['Мониторинг']['B5'].value==.02
 assert len(workbook['Карта']._images)==1 and len(workbook['NDVI']._charts)==1
 assert workbook['Дереккөздер']['B1'].value=='unit-test-not-satellite-data'
