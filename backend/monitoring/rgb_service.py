"""Integrity gate for optional RGB products; missing imagery is never substituted."""
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import rasterio


def signature(folder):
    paths=[Path(folder)/name for name in ('rgb-manifest.json','rgb_2020.tif','rgb_2026.tif')]
    return tuple((str(path),path.stat().st_size,path.stat().st_mtime_ns) if path.exists() else (str(path),None,None) for path in paths)


@lru_cache(maxsize=2)
def _load(stamp,source_dataset_id,grid,periods):
    paths=[Path(item[0]) for item in stamp]
    if not paths[0].exists():return {'status':'unavailable','reason':'RGB products have not been prepared'}
    try:
        manifest=json.loads(paths[0].read_text(encoding='utf-8'))
        if manifest.get('status')!='ready':return {'status':manifest.get('status','unavailable'),'reason':manifest.get('reason','RGB processing incomplete')}
        if manifest.get('source_dataset_id')!=source_dataset_id:raise ValueError('RGB source dataset differs')
        if manifest.get('bands')!=['B04','B03','B02']:raise ValueError('RGB band order differs')
        for year,start,end,ids in periods:
            rgb_period=manifest['periods'][year]
            if rgb_period['start']!=start or rgb_period['end']!=end or set(rgb_period['scene_ids'])!=set(ids):raise ValueError('RGB periods or source scenes differ')
        width,height,crs,affine=grid
        for path in paths[1:]:
            record=manifest['artifacts'][path.name]
            with path.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
            if checksum!=record['sha256'] or path.stat().st_size!=record['bytes']:raise ValueError('RGB checksum differs')
            with rasterio.open(path) as source:
                if (source.width,source.height,source.crs,source.transform)!=(width,height,crs,affine) or source.count!=3 or source.dtypes!=('uint8','uint8','uint8'):raise ValueError('RGB grid differs')
        return {'status':'ready','dataset_id':manifest['dataset_id'],'method':manifest['method'],'periods':manifest['periods'],
                'paths':{str(year):paths[index] for index,year in enumerate((2020,2026),1)}}
    except (OSError,ValueError,KeyError,TypeError):return {'status':'unavailable','reason':'RGB products failed integrity or grid checks'}


def info(folder,source_dataset_id,grid,periods):
    expected=tuple((str(year),periods[str(year)]['start'],periods[str(year)]['end'],tuple(sorted(scene['id'] for scene in periods[str(year)]['scenes']))) for year in (2020,2026))
    return _load(signature(folder),source_dataset_id,grid,expected)
