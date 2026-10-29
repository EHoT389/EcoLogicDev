from fastapi import APIRouter,Query,Request,HTTPException
from fastapi.responses import Response
from ..localization import language
from . import service

router=APIRouter(prefix='/api/monitoring',tags=['Monitoring'])

@router.get('/periods')
def periods(request:Request):
 meta=service.metadata(language(request))
 return {'status':meta['status'],'reason':meta['reason'],'period_start':2020,'period_end':2026,'season':{'start':'06-01','end':'08-31'},'periods':meta['periods']}

@router.get('/metadata')
def metadata(request:Request): return service.metadata(language(request))

@router.get('/changes')
def changes(request:Request,threshold:float=Query(.3,ge=.1,le=.9)):
 return service.get_vegetation_change(threshold=threshold,language=language(request))

@router.get('/zones/{zone_id}')
def zone_changes(zone_id:str,request:Request,threshold:float=Query(.3,ge=.1,le=.9)):
 return service.get_vegetation_change(zone_id,threshold=threshold,language=language(request))

@router.get('/tiles/{year}/{z}/{x}/{y}')
def tiles(year:str,z:int,x:int,y:int,threshold:float=Query(.3,ge=.1,le=.9),layer:str=Query('vegetation',pattern='^(vegetation|ndvi|quality)$')):
 data=service.tile_png(year,z,x,y,threshold,layer)
 return Response(data,media_type='image/png',headers={'Cache-Control':'public, max-age=300','X-Content-Type-Options':'nosniff'})

@router.get('/export')
def export(request:Request,format:str=Query('pdf',pattern='^(pdf|xlsx)$'),zone_id:str|None=None,threshold:float=Query(.3,ge=.1,le=.9)):
 from .reports import export_pdf,export_xlsx
 lang=language(request);result=service.get_vegetation_change(zone_id,threshold=threshold,language=lang)
 if result['status']!='ready': raise HTTPException(409,result['reason'])
 image=service.change_map_png(zone_id,threshold)
 data=export_pdf(result,image,lang) if format=='pdf' else export_xlsx(result,image,lang)
 mime='application/pdf' if format=='pdf' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
 return Response(data,media_type=mime,headers={'Content-Disposition':f'attachment; filename="EcoLogicDev-monitoring-2020-2026.{format}"','Cache-Control':'no-store'})
