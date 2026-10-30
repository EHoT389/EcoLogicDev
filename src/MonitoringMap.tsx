import {useEffect,useRef,useState} from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {LocateFixed,Info} from 'lucide-react';
import {API} from './api';
import type {Zone} from './types';
import type {MonitoringMetadata,MonitoringMode} from './monitoringTypes';

type Props={metadata:MonitoringMetadata|undefined;zones:Zone[];selectedZone:Zone|null;mode:MonitoringMode;opacity:number;swipe:number;threshold:number;kk:boolean;onSelect:(zone:Zone)=>void};
export default function MonitoringMap({metadata,zones,selectedZone,mode,opacity,swipe,threshold,kk,onSelect}:Props){
 const container=useRef<HTMLDivElement>(null),map=useRef<L.Map|null>(null),tileLayers=useRef<L.TileLayer[]>([]),onSelectRef=useRef(onSelect);
 const opacityRef=useRef(opacity),swipeRef=useRef(swipe),modeRef=useRef(mode);
 onSelectRef.current=onSelect;opacityRef.current=opacity;swipeRef.current=swipe;modeRef.current=mode;
 const [tileError,setTileError]=useState(false);
 const ready=metadata?.status==='ready';
 function clipLayers(customSwipe?:number){
  const instance=map.current;if(!instance)return;
  const isSwipe=modeRef.current==='swipe';
  if(!isSwipe||tileLayers.current.length<2){
   tileLayers.current.forEach(layer=>{
    const node=layer.getContainer();
    if(node){
     node.style.clipPath='';
     (node.style as any).webkitClipPath='';
     node.style.clip='auto';
    }
   });
   return;
  }
  const size=instance.getSize();if(size.x<=0||size.y<=0)return;
  const nw=instance.containerPointToLayerPoint([0,0]),se=instance.containerPointToLayerPoint(size);
  const swipeVal=customSwipe!==undefined?customSwipe:swipeRef.current;
  const splitX=Math.round(nw.x+(se.x-nw.x)*(swipeVal/100));
  const pad=200;
  const topY=Math.round(nw.y)-pad,bottomY=Math.round(se.y)+pad,leftX=Math.round(nw.x)-pad,rightX=Math.round(se.x)+pad;
  tileLayers.current.forEach((layer,index)=>{
   const node=layer.getContainer();if(!node)return;
   const poly=index===0
    ?`polygon(${leftX}px ${topY}px, ${splitX}px ${topY}px, ${splitX}px ${bottomY}px, ${leftX}px ${bottomY}px)`
    :`polygon(${splitX}px ${topY}px, ${rightX}px ${topY}px, ${rightX}px ${bottomY}px, ${splitX}px ${bottomY}px)`;
   node.style.clipPath=poly;
   (node.style as any).webkitClipPath=poly;
   node.style.clip='auto';
  });
 }
 useEffect(()=>{
  if(!container.current||map.current)return;
  const instance=L.map(container.current,{center:[52.287,76.955],zoom:14,minZoom:8,maxZoom:19,zoomControl:false});map.current=instance;
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(instance);
  L.control.zoom({position:'bottomright',zoomInTitle:kk?'Жақындату':'Приблизить',zoomOutTitle:kk?'Алыстату':'Отдалить'}).addTo(instance);
  L.control.scale({imperial:false,position:'bottomleft'}).addTo(instance);
  instance.on('move zoom zoomanim viewreset resize',()=>clipLayers());
  const resize=new ResizeObserver(()=>{instance.invalidateSize();clipLayers()});resize.observe(container.current);
  return()=>{resize.disconnect();instance.remove();map.current=null};
 },[]);
 useEffect(()=>{
  for(const attribute of ['title','aria-label']){
   container.current?.querySelector('.leaflet-control-zoom-in')?.setAttribute(attribute,kk?'Жақындату':'Приблизить');
   container.current?.querySelector('.leaflet-control-zoom-out')?.setAttribute(attribute,kk?'Алыстату':'Отдалить');
  }
 },[kk]);
 useEffect(()=>{
  const instance=map.current;if(!instance)return;
  const layer=L.layerGroup().addTo(instance);
  if(metadata?.bbox_wgs84){const [west,south,east,north]=metadata.bbox_wgs84;L.rectangle([[south,west],[north,east]],{color:'#758876',weight:1,dashArray:'6 6',fill:false,interactive:false}).addTo(layer)}
  zones.forEach(zone=>{
   const selected=zone.id===selectedZone?.id;
   const outline=L.geoJSON(zone.geometry as any,{style:{color:selected?'#173d2c':'#526c54',weight:selected?3:1.3,fillColor:'#fff',fillOpacity:selected?.04:0,dashArray:zone.status==='planting_candidate'?'4 4':undefined}}).addTo(layer);
   const label=document.createElement('span');label.textContent=kk?zone.kk:zone.ru;
   outline.bindTooltip(label,{sticky:true});outline.on('click',()=>onSelectRef.current(zone));
  });
  return()=>{layer.remove()};
 },[zones,selectedZone?.id,kk,metadata?.version,metadata?.dataset_id]);
 useEffect(()=>{
  const instance=map.current;if(!instance)return;
  if(selectedZone)instance.fitBounds(L.geoJSON(selectedZone.geometry as any).getBounds(),{padding:[45,65],maxZoom:17,animate:false});
  else if(metadata?.bbox_wgs84){const [west,south,east,north]=metadata.bbox_wgs84;instance.fitBounds([[south,west],[north,east]],{padding:[30,35],animate:false})}
 },[selectedZone?.id,metadata?.dataset_id,metadata?.version]);
 useEffect(()=>{
  const instance=map.current;if(!instance)return;
  setTileError(false);tileLayers.current.forEach(layer=>layer.remove());tileLayers.current=[];
  if(ready){
   const years=mode==='swipe'?['2020','2026']:[mode];
   years.forEach((year,index)=>{
    const params=new URLSearchParams({threshold:String(threshold),v:metadata?.dataset_id||metadata?.version||''});
    const layer=L.tileLayer(`${API}/api/monitoring/tiles/${year}/{z}/{x}/{y}?${params}`,{minZoom:8,maxZoom:19,maxNativeZoom:19,opacity:opacityRef.current,attribution:index===0?'Contains modified Copernicus Sentinel data (2020, 2026)':''});
    layer.on('tileerror',()=>setTileError(true));layer.on('load tileload',()=>clipLayers());layer.addTo(instance);tileLayers.current.push(layer);
   });clipLayers();
  }
  return()=>{tileLayers.current.forEach(layer=>layer.remove());tileLayers.current=[]};
 },[ready,mode,threshold,metadata?.version,metadata?.dataset_id]);
 useEffect(()=>{tileLayers.current.forEach(layer=>layer.setOpacity(opacity))},[opacity]);
 useEffect(clipLayers,[swipe,mode]);
 function overview(){if(!map.current||!metadata?.bbox_wgs84)return;const [west,south,east,north]=metadata.bbox_wgs84;map.current.fitBounds([[south,west],[north,east]],{padding:[30,35],animate:false})}
 return <div className="monitoring-map-shell"><div ref={container} className="monitoring-map-canvas" aria-label={kk?'Өсімдік жамылғысының спутниктік картасы':'Спутниковая карта растительного покрова'}/>
  <div className="monitoring-map-top"><span>{kk?'Павлодар · өңделген орталық бөлік':'Павлодар · обработанная центральная часть'}</span><button className="icon-button" onClick={overview} aria-label={kk?'Бүкіл өңделген аумақты көрсету':'Показать всю обработанную область'} disabled={!metadata?.bbox_wgs84}><LocateFixed size={18}/></button></div>
  {ready&&mode==='swipe'&&<><div className="monitoring-swipe-line" style={{left:swipe+'%'}} aria-hidden="true"><span>↔</span></div><div className="monitoring-swipe-label left">2020</div><div className="monitoring-swipe-label right">2026</div></>}
  {!ready&&<div className="monitoring-map-status"><Info size={18}/><span>{kk?'Спутниктік қабат әзірше қолжетімсіз. Негізгі карта ғана көрсетілген.':'Спутниковый слой пока недоступен. Показана только базовая карта.'}</span></div>}
  {tileError&&ready&&<div className="monitoring-map-status error" role="alert"><Info size={18}/><span>{kk?'Қабаттың бір бөлігі жүктелмеді.':'Часть слоя не загрузилась.'}</span><button type="button" className="monitoring-tile-retry" onClick={()=>{setTileError(false);tileLayers.current.forEach(layer=>layer.redraw())}}>{kk?'Қайталау':'Повторить'}</button></div>}
 </div>
}
