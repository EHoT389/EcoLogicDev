"""Real imagery acceptance checks and deliberately isolated integrity fixtures."""
from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
import hashlib
import json
import math
import warnings

import numpy as np
import pytest
import rasterio
from rasterio.windows import Window, transform as window_transform
from rasterio.vrt import WarpedVRT
from PIL import Image
from backend.monitoring import service, rgb_service

FOLDER=Path(__file__).resolve().parents[1]/'backend/storage/monitoring-city'


def digest(path):
    with path.open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


@pytest.fixture
def real_rgb(monkeypatch):
    if not (FOLDER/'rgb-manifest.json').exists():pytest.skip('Real RGB products not prepared; no substitute')
    monkeypatch.setenv('MONITORING_DATA_DIR',str(FOLDER))
    manifest=json.loads((FOLDER/'rgb-manifest.json').read_text(encoding='utf-8'))
    assert manifest['status']=='ready'
    return manifest


def test_real_rgb_integrity_periods_grid_and_all_source_bands(real_rgb):
    data=service.dataset();base=data['manifest']
    assert real_rgb['bands']==['B04','B03','B02']
    assert real_rgb['source_dataset_id']==base['dataset_id']
    assert rgb_service.info(FOLDER,base['dataset_id'],data['grid'],base['periods'])['status']=='ready'
    for name,record in base['artifacts'].items():
        assert digest(FOLDER/name)==record['sha256'], 'RGB must not modify original NDVI products'
    catalog=json.loads((FOLDER/'selected-scenes.stac.json').read_text(encoding='utf-8'))
    for year in ('2020','2026'):
        assert real_rgb['periods'][year]['start']==base['periods'][year]['start']
        assert real_rgb['periods'][year]['end']==base['periods'][year]['end']
        assert set(real_rgb['periods'][year]['scene_ids'])=={s['id'] for s in base['periods'][year]['scenes']}
        for scene in catalog[year]['features']:
            for band in ('red','green','blue','scl'):
                paths=list((FOLDER/'source-crops').glob(f'{scene["id"]}-{band}-*.json'))
                assert len(paths)==1
                record=json.loads(paths[0].read_text(encoding='utf-8'));path=paths[0].with_suffix('.tif')
                assert record['raw_dn'] and record['href']==scene['assets'][band]['href']
                assert record['href'].startswith('https://sentinel-cogs.s3.us-west-2.amazonaws.com/')
                assert path.stat().st_size==record['bytes'] and digest(path)==record['sha256']
        with rasterio.open(FOLDER/f'rgb_{year}.tif') as source:
            assert (source.width,source.height,source.crs,source.transform)==data['grid']
            count=sum(int((source.read(window=window)>0).all(axis=0).sum()) for _,window in source.block_windows(1))
            assert count==real_rgb['usable_pixels'][year]>6_000_000
    assert 'rgb' in service.metadata()['available_layers']
    assert 'paths' not in service.metadata()['rgb']


def test_real_rgb_independent_samples_from_original_dn(real_rgb):
    catalog=json.loads((FOLDER/'selected-scenes.stac.json').read_text(encoding='utf-8'))
    # Windows in both northern and southern Sentinel tiles, including vegetation/urban land.
    for year in ('2020','2026'):
        with rasterio.open(FOLDER/f'rgb_{year}.tif') as ref:
            for column,row in ((2100,600),(2100,2600)):
                window=Window(column,row,16,16);observations={}
                for scene in sorted(catalog[year]['features'],key=lambda item:item['id']):
                    props=scene['properties'];key=(props['datetime'][:10],props['platform']);bands={}
                    for band in ('red','green','blue','scl'):
                        path=next((FOLDER/'source-crops').glob(f'{scene["id"]}-{band}-*.tif'))
                        with rasterio.open(path) as raw, WarpedVRT(raw,crs=ref.crs,
                            transform=window_transform(window,ref.transform),width=16,height=16,
                            src_nodata=0,nodata=0,resampling=rasterio.enums.Resampling.nearest) as view:
                            bands[band]=view.read(1).astype('float32')
                    raw=np.stack([bands[b] for b in ('red','green','blue')])
                    offset=0 if float(props['s2:processing_baseline'])<4 or props.get('earthsearch:boa_offset_applied') else -.1
                    values=raw*.0001+offset
                    valid=np.isin(bands['scl'],(4,5,6))&(raw>0).all(axis=0)&(values>=0).all(axis=0)
                    observation=observations.setdefault(key,np.full((3,16,16),np.nan,dtype='float32'))
                    accept=valid&~np.isfinite(observation[0]);observation[:,accept]=values[:,accept]
                stack=np.stack(list(observations.values()))
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore',RuntimeWarning);median=np.nanmedian(stack,axis=0)
                good=(np.isfinite(stack[:,0]).sum(axis=0)>=2)&np.isfinite(median).all(axis=0)
                actual=ref.read(window=window);inside=(actual>0).all(axis=0)
                assert inside.any() and good[inside].all()
                expected=np.maximum(1,np.rint(np.power(np.clip(np.nan_to_num(median)/.30,0,1),1/2.2)*255)).astype('uint8')
                np.testing.assert_array_equal(actual[:,inside],expected[:,inside])


@pytest.mark.parametrize('year',('2020','2026'))
def test_rgb_tiles_real_not_coloured_ndvi_and_common_mask(real_rgb,year):
    data=service.dataset()
    # Read a bounded native window to independently verify alpha and RGB channels.
    affine=window_transform(Window(2100,2600,32,32),data['grid'][3])
    actual=service._render(data,year,affine,data['grid'][2],32,32,.3,'rgb')
    assert (actual[:,:,3]>0).any()
    with rasterio.open(FOLDER/f'rgb_{year}.tif') as source:
        expected=source.read(window=Window(2100,2600,32,32))
    np.testing.assert_array_equal(actual[:,:,:3],np.moveaxis(expected,0,-1))
    for period in ('2020','2026'):
        with rasterio.open(FOLDER/f'count_{period}.tif') as source:count=source.read(1,window=Window(2100,2600,32,32))
        assert not actual[:,:,3][count<2].any()
    x=int((76.95+180)/360*2**10);y=int((1-math.asinh(math.tan(math.radians(52.285)))/math.pi)/2*2**10)
    image=np.asarray(Image.open(BytesIO(service.tile_png(year,10,x,y,layer='rgb'))))
    assert image.shape==(256,256,4) and (image[:,:,3]>0).any()


def test_rgb_rejects_other_periods_dataset_band_order_and_corruption(real_rgb,tmp_path):
    data=service.dataset();base=data['manifest']
    for year in ('2020','2026'):
        # Small valid three-band fixture on the production grid; independent from real products.
        with rasterio.open(tmp_path/f'rgb_{year}.tif','w',driver='GTiff',width=data['grid'][0],height=data['grid'][1],
                           count=3,dtype='uint8',crs=data['grid'][2],transform=data['grid'][3],tiled=True,compress='deflate'):
            pass
    manifest=json.loads(json.dumps(real_rgb))
    manifest['artifacts']={path.name:{'bytes':path.stat().st_size,'sha256':digest(path)} for path in tmp_path.glob('*.tif')}
    def info():
        (tmp_path/'rgb-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        rgb_service._load.cache_clear()
        return rgb_service.info(tmp_path,base['dataset_id'],data['grid'],base['periods'])['status']
    assert info()=='ready'
    manifest['bands']=['B02','B03','B04'];assert info()=='unavailable'
    manifest['bands']=['B04','B03','B02'];manifest['source_dataset_id']='other';assert info()=='unavailable'
    manifest['source_dataset_id']=base['dataset_id'];manifest['periods']['2026']['start']='2026-01-01';assert info()=='unavailable'
    manifest['periods']=real_rgb['periods'];manifest['artifacts']['rgb_2026.tif']['sha256']='0'*64;assert info()=='unavailable'


def test_real_satellite_ranking_preserves_actual_zone_values(real_rgb):
    ranking=service.zone_ranking(.3)
    assert ranking['data_type']=='observed_satellite' and len(ranking['rows'])==12
    for row in ranking['rows']:
        stats=service.get_vegetation_change(row['zone_id'])['statistics']
        assert row['loss_ha']==stats['loss_ha'] and row['net_change_ha']==stats['net_change_ha']
        assert row['comparable_fraction']==stats['comparable_fraction']
        assert row['loss_fraction']==pytest.approx(stats['loss_ha']/stats['comparable_area_ha'])
        if stats['comparable_pixels']<30:assert row['survey_priority']=='data_check'
    assert [r['loss_fraction'] for r in ranking['rows']]==sorted([r['loss_fraction'] for r in ranking['rows']],reverse=True)


def test_change_filter_is_actual_loss_mask(real_rgb):
    data=service.dataset()
    with rasterio.open(FOLDER/'changes.tif') as source:
        window=next(window for _,window in source.block_windows(1) if (source.read(1,window=window)==2).sum()>10)
    affine=window_transform(window,data['grid'][3]);width,height=int(window.width),int(window.height)
    all_changes=service._render(data,'changes',affine,data['grid'][2],width,height,.3,'vegetation')
    losses=service._render(data,'changes',affine,data['grid'][2],width,height,.3,'vegetation',change_filter='loss')
    # Palette itself is server-defined; filtering must retain only class 2, never gains.
    from backend.monitoring.service import rgba_changes
    loss_colour=rgba_changes(np.array([[2]],dtype='uint8'))[0,0]
    expected=(all_changes==loss_colour).all(axis=2)
    assert expected.any()
    np.testing.assert_array_equal(losses[:,:,3]>0,expected)
