import csv, io, json, zipfile
import xml.etree.ElementTree as ET
from fastapi import HTTPException
from shapely.geometry import shape, mapping
from shapely.ops import transform
from pyproj import CRS, Transformer

def import_layer(name,content):
 if len(content)>5_000_000: raise HTTPException(413,'Файл больше 5 МБ')
 suffix=name.lower().rsplit('.',1)[-1]
 try:
  if suffix in ('geojson','json'):
   data=json.loads(content)
   if data.get('type')=='FeatureCollection': features=data['features']
   elif data.get('type')=='Feature': features=[data]
   else: features=[{'type':'Feature','geometry':data,'properties':{}}]
  elif suffix=='csv':
   rows=csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
   features=[{'type':'Feature','geometry':{'type':'Point','coordinates':[float(r['longitude']),float(r['latitude'])]},'properties':{k:v for k,v in r.items() if k not in ('longitude','latitude')}} for r in rows]
  elif suffix=='kml':
   if b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper(): raise ValueError('DTD запрещены')
   root=ET.fromstring(content);features=[]
   ns={'k':'http://www.opengis.net/kml/2.2'}
   for mark in root.findall('.//k:Placemark',ns):
    title=mark.findtext('k:name',default='',namespaces=ns)
    for poly in mark.findall('.//k:Polygon',ns):
     rings=[]
     for node in poly.findall('.//k:LinearRing/k:coordinates',ns): rings.append([[float(v) for v in p.split(',')[:2]] for p in node.text.strip().split()])
     features.append({'type':'Feature','geometry':{'type':'Polygon','coordinates':rings},'properties':{'name':title}})
    for node in mark.findall('.//k:Point/k:coordinates',ns):
     features.append({'type':'Feature','geometry':{'type':'Point','coordinates':[float(v) for v in node.text.strip().split(',')[:2]]},'properties':{'name':title}})
  elif suffix=='zip':
   import shapefile
   with zipfile.ZipFile(io.BytesIO(content)) as z:
    if sum(i.file_size for i in z.infolist())>20_000_000 or len(z.infolist())>20: raise ValueError('Слишком большой архив')
    names=z.namelist()
    if any('..' in n or n.startswith(('/','\\')) or ':' in n for n in names): raise ValueError('Недопустимый путь в архиве')
    shp=[n for n in names if n.lower().endswith('.shp')]
    if len(shp)!=1: raise ValueError('Нужен один Shapefile')
    base=shp[0][:-4];lookup={n.lower():n for n in names}
    def read(ext):
     key=lookup.get((base+ext).lower())
     return io.BytesIO(z.read(key)) if key else None
    if not read('.dbf') or not read('.prj'): raise ValueError('Нужны .dbf и .prj')
    reader=shapefile.Reader(shp=read('.shp'),shx=read('.shx'),dbf=read('.dbf'),encoding='utf-8')
    crs=CRS.from_wkt(read('.prj').read().decode('utf-8-sig'))
    transformer=Transformer.from_crs(crs,4326,always_xy=True)
    features=[]
    for record in reader.iterShapeRecords():
     geom=transform(transformer.transform,shape(record.shape.__geo_interface__))
     features.append({'type':'Feature','geometry':mapping(geom),'properties':record.record.as_dict()})
  else: raise ValueError('Допустимы GeoJSON, KML, CSV и ZIP Shapefile')
  if not features or len(features)>1000: raise ValueError('Нужно от 1 до 1000 объектов')
  polygons=[]
  for f in features:
   geom=shape(f['geometry'])
   if not geom.is_valid or geom.is_empty: raise ValueError('Невалидная геометрия')
   a,b,c,d=geom.bounds
   if not (76.5<=a<=c<=77.5 and 51.9<=b<=d<=52.7): raise ValueError('Координаты вне Павлодара')
   if geom.geom_type in ('Polygon','MultiPolygon'): polygons.append(geom)
   f['properties']={**(f.get('properties') or {}),'provenance':'imported_unverified','source_file':name}
  overlaps=sum(a.intersects(b) and a.intersection(b).area>1e-12 for i,a in enumerate(polygons) for b in polygons[i+1:])
  return {'type':'FeatureCollection','features':features,'overlap_pairs':overlaps,'status':'unverified','source':name}
 except HTTPException: raise
 except Exception as e:
  from .localization import MESSAGES
  detail=str(e)
  raise HTTPException(422,'Ошибка импорта: '+(detail if detail in MESSAGES else 'Проверьте структуру файла и систему координат WGS84.'))
