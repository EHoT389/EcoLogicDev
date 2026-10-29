import {useEffect,useRef,useState} from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import 'leaflet-draw';
import 'leaflet-draw/dist/leaflet.draw.css';
import {Layers,LocateFixed,Search,PenTool,ChevronDown,Trees,Sprout,Check} from 'lucide-react';
import type {Analysis,Geometry,Zone} from './types';
import {statusLabel,zoneAddress} from './zoneModel';

type Props={zones:Zone[];selected:Geometry|null;analysis:Analysis|null;onZone:(z:Zone)=>void;onDraw:(g:Geometry)=>void;onAskAI:(z:Zone)=>void;onRename:(z:Zone)=>void;kk:boolean;expanded?:boolean;imported?:any[];showPlantings?:boolean};
export default function MapView({zones,selected,analysis,onZone,onDraw,onAskAI,onRename,kk,expanded,imported=[],showPlantings=false}:Props){
 const node=useRef<HTMLDivElement>(null),map=useRef<L.Map|null>(null),drawing=useRef<any>(null);
 const callback=useRef({onZone,onDraw,onAskAI,onRename});callback.current={onZone,onDraw,onAskAI,onRename};
 const popup=useRef<L.Popup|null>(null),popupZone=useRef<string|null>(null);
 const [layers,setLayers]=useState({existing:true,candidates:true,soil:false,priority:false,plantings:showPlantings,imported:true});
 const [panel,setPanel]=useState(false),[query,setQuery]=useState(''),[searching,setSearching]=useState(false),[searchError,setSearchError]=useState(''),[labelsVisible,setLabelsVisible]=useState(false),[drawingNow,setDrawingNow]=useState(false);
 const lastSearch=useRef(0);
 useEffect(()=>{
  const local=(L as any).drawLocal.draw.handlers;
  local.polygon.tooltip={start:kk?'Аумақты сызу үшін картаны басыңыз.':'Нажмите на карту, чтобы начать контур.',cont:kk?'Келесі нүктені басыңыз.':'Нажмите, чтобы добавить точку.',end:kk?'Аяқтау үшін бірінші нүктені басыңыз.':'Нажмите первую точку, чтобы завершить контур.'};
  local.polyline.error=kk?'Шекара өзімен қиылыспауы керек.':'Граница не должна пересекать сама себя.';
  node.current?.querySelector('.leaflet-control-zoom-in')?.setAttribute('title',kk?'Жақындату':'Приблизить');
  node.current?.querySelector('.leaflet-control-zoom-out')?.setAttribute('title',kk?'Алыстату':'Отдалить');
 },[kk]);
 useEffect(()=>{
  if(!node.current||map.current)return;
  const m=L.map(node.current,{center:[52.285,76.951],zoom:14,zoomControl:false,scrollWheelZoom:true});map.current=m;
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(m);
  L.control.zoom({position:'bottomright',zoomInTitle:kk?'Жақындату':'Приблизить',zoomOutTitle:kk?'Алыстату':'Отдалить'}).addTo(m);
  drawing.current=new L.Draw.Polygon(m,{allowIntersection:false,showArea:true,shapeOptions:{color:'#bf7b36',fillOpacity:.15}});
  m.on(L.Draw.Event.CREATED,(event:any)=>{callback.current.onDraw(event.layer.toGeoJSON().geometry);setDrawingNow(false)});
  m.on('draw:drawstop',()=>setDrawingNow(false));
  m.on('zoomend',()=>setLabelsVisible(m.getZoom()>=15));setLabelsVisible(m.getZoom()>=15);
  m.on('popupclose',()=>{popup.current=null;popupZone.current=null});
  const resize=new ResizeObserver(()=>m.invalidateSize());resize.observe(node.current);
  return()=>{resize.disconnect();m.remove();map.current=null};
 },[]);
 useEffect(()=>{
  const m=map.current;if(!m)return;
  const group=L.layerGroup().addTo(m);
  function content(z:Zone){
   const box=document.createElement('div');box.className='zone-popup';
   const badge=document.createElement('span');badge.className='zone-popup-status '+(z.status==='existing_green'?'is-existing':'is-candidate');badge.textContent=statusLabel(z,kk);box.append(badge);
   const title=document.createElement('strong');title.textContent=kk?z.kk:z.ru;box.append(title);
   if(zoneAddress(z,kk)){const address=document.createElement('p');address.className='popup-address';address.textContent='⌖ '+zoneAddress(z,kk);box.append(address);const label=document.createElement('small');label.textContent=kk?'OSM бағдары, пошта мекенжайы емес':'Ориентир OSM, не почтовый адрес';box.append(label)}
   const area=document.createElement('p');area.textContent=(z.area_m2?new Intl.NumberFormat('ru-KZ',{maximumFractionDigits:2}).format(z.area_m2/10000)+' га · ':'')+(z.provenance==='osm'?(kk?'OSM контуры':'Контур OSM'):(kk?'Сіздің аумағыңыз':'Ваш участок'));box.append(area);
   const note=document.createElement('small');note.textContent=z.status==='existing_green'?(kk?'Бар жасыл аумақ. Ағаш саны мен жағдайы белгісіз.':'Существующая зелёная территория. Число и состояние деревьев неизвестны.'):(kk?'Отырғызу ұсынысы. Аумақты зерттеу қажет.':'Кандидат для дополнительных посадок. Требует обследования.');box.append(note);
   const ask=document.createElement('button');ask.className='popup-ask-ai';ask.textContent=kk?'AI-дан сұрау ↗':'Спросить ИИ ↗';ask.onclick=()=>callback.current.onAskAI(z);box.append(ask);
   const rename=document.createElement('button');rename.className='popup-rename';rename.textContent=kk?'Атауын өзгерту':'Изменить название';rename.onclick=()=>callback.current.onRename(z);box.append(rename);
   const history=document.createElement('a');history.className='popup-rename';history.href='/monitoring?zone='+encodeURIComponent(z.id);history.textContent=kk?'2020–2026 өзгерістерін талдау ↗':'Анализ изменений 2020–2026 ↗';box.append(history);
   L.DomEvent.disableClickPropagation(box);return box;
  }
  function open(z:Zone,latlng:L.LatLng){
   if(drawing.current?.enabled())return;
   callback.current.onZone(z);
   popup.current=L.popup({maxWidth:300,minWidth:235,className:'zone-leaflet-popup',autoPanPadding:[25,85]}).setLatLng(latlng).setContent(content(z)).openOn(m!);
   popup.current.getElement()?.querySelector('.leaflet-popup-close-button')?.setAttribute('aria-label',kk?'Жабу':'Закрыть');
   popupZone.current=z.id;
  }
  zones.forEach(z=>{
   const existing=z.status==='existing_green';if(existing?!layers.existing:!layers.candidates)return;
   const chosen=selected&&JSON.stringify(selected)===JSON.stringify(z.geometry);
   const color=existing?'#3d8157':'#c38238';
   const poly=L.geoJSON(z.geometry as any,{style:{color:chosen?(existing?'#225d3a':'#a45f1d'):color,weight:chosen?3:1.8,fillColor:color,fillOpacity:chosen?.27:existing?.18:.13,dashArray:existing?undefined:'7 5'}}).addTo(group);
   poly.bindTooltip(kk?z.kk:z.ru,{direction:'top',sticky:true});poly.on('click',(event:any)=>open(z,event.latlng));
   const center=(z as Zone&{center?:number[]}).center;const position=center?L.latLng(center[1],center[0]):poly.getBounds().getCenter();
   const markerNode=document.createElement('div');markerNode.className='zone-marker-content '+(existing?'existing':'candidate');
   const dot=document.createElement('span');dot.textContent=existing?'♣':'+';markerNode.append(dot);
   if(labelsVisible||chosen){const label=document.createElement('b');label.textContent=kk?z.kk:z.ru;if(zoneAddress(z,kk)){const address=document.createElement('small');address.textContent=zoneAddress(z,kk);label.append(address)}markerNode.append(label)}
   const marker=L.marker(position,{keyboard:true,title:kk?z.kk:z.ru,icon:L.divIcon({className:'zone-status-marker',html:markerNode,iconSize:[26,26],iconAnchor:[13,13]})}).addTo(group).on('click',()=>open(z,position));
   marker.getElement()?.setAttribute('aria-label',(kk?z.kk:z.ru)+' · '+statusLabel(z,kk));
   if(layers.soil)L.geoJSON(z.geometry as any,{interactive:false,style:{color:'#ad8c61',weight:1,fillOpacity:.12,dashArray:'3 6'}}).addTo(group);
   if(layers.priority&&!existing)L.circleMarker(position,{radius:18,color:'#bb7140',weight:2,fillOpacity:.05}).addTo(group);
  });
  if(layers.plantings&&analysis)analysis.positions.forEach(p=>L.circleMarker([p.coordinates[1],p.coordinates[0]],{radius:3,color:'#fff',weight:1,fillColor:'#4776a0',fillOpacity:.9,interactive:false}).addTo(group));
  if(layers.imported)imported.filter(x=>x.status==='published').forEach(layer=>L.geoJSON(layer,{style:{color:'#8271ad',weight:2},pointToLayer:(_,latlng)=>L.circleMarker(latlng,{radius:5,color:'#8271ad'})}).addTo(group));
  if(popup.current&&popupZone.current){const z=zones.find(z=>z.id===popupZone.current);if(z)popup.current.setContent(content(z));popup.current.getElement()?.querySelector('.leaflet-popup-close-button')?.setAttribute('aria-label',kk?'Жабу':'Закрыть')}
  return()=>{group.remove()};
 },[zones,selected,analysis,layers,kk,imported,labelsVisible]);
 useEffect(()=>{if(selected&&map.current&&!popup.current){map.current.fitBounds(L.geoJSON(selected as any).getBounds(),{padding:[65,100],maxZoom:16,animate:false})}},[selected]);
 async function search(event:React.FormEvent){event.preventDefault();if(query.trim().length<3||searching||Date.now()-lastSearch.current<1100)return;lastSearch.current=Date.now();setSearching(true);setSearchError('');try{const params=new URLSearchParams({q:`${query}, Павлодар, Казахстан`,format:'json',limit:'1',countrycodes:'kz',viewbox:'76.5,52.7,77.5,51.9',bounded:'1'});const r=await fetch('https://nominatim.openstreetmap.org/search?'+params);if(!r.ok)throw new Error();const data=await r.json();if(!data.length){setSearchError(kk?'Мекенжай табылмады':'Адрес не найден');return}map.current?.flyTo([Number(data[0].lat),Number(data[0].lon)],16)}catch{setSearchError(kk?'Іздеу қолжетімсіз':'Поиск временно недоступен')}finally{setSearching(false)}}
 function overview(){map.current?.closePopup();if(zones.length)map.current?.fitBounds(L.featureGroup(zones.map(z=>L.geoJSON(z.geometry as any))).getBounds(),{padding:[35,85],maxZoom:14,animate:false})}
 const labels:Record<string,string>={existing:kk?'Бар жасыл аумақтар':'Уже озеленено',candidates:kk?'Отырғызу ұсыныстары':'Предлагается посадка',soil:kk?'Топырақ · демо':'Почвы · демо',priority:kk?'Басымдықтар · демо':'Приоритеты · демо',plantings:kk?'Жоспардағы өсімдіктер':'Растения из плана',imported:kk?'Импортталған қабаттар':'Импортированные слои'};
 return <div className={'map-wrap '+(expanded?'map-expanded':'')}>
  <div ref={node} className="map-canvas"/>
  <form className="map-search" onSubmit={search}><Search size={17}/><input aria-label={kk?'Мекенжай іздеу':'Поиск адреса'} value={query} onChange={e=>setQuery(e.target.value)} placeholder={kk?'Павлодарда мекенжай табу':'Найти адрес в Павлодаре'}/><button disabled={searching} type="submit" aria-label={kk?'Іздеу':'Искать'}>{searching?'…':'↵'}</button></form>
  {searchError&&<div className="map-search-error">{searchError}</div>}
  <div className="map-tools"><button className="map-tool" aria-label={kk?'Қабаттар':'Слои'} onClick={()=>setPanel(!panel)}><Layers size={18}/><span>{kk?'Қабаттар':'Слои'}</span><ChevronDown size={13}/></button><button className="map-tool" aria-label={kk?'Жаңа отырғызу аумағын сызу':'Нарисовать участок для посадки'} onClick={()=>{map.current?.closePopup();drawing.current?.enable();setDrawingNow(true)}}><PenTool size={17}/><span>{kk?'Аумақ сызу':'Нарисовать участок'}</span></button><button className="map-tool" onClick={overview} aria-label={kk?'Барлық аумақтарды көрсету':'Показать все зоны'}><LocateFixed size={18}/></button></div>
  <div className="zone-status-filters"><button className={layers.existing?'active filter-existing':'filter-existing'} aria-pressed={layers.existing} onClick={()=>setLayers({...layers,existing:!layers.existing})}><Trees size={15}/>{kk?'Бар жасыл аумақтар':'Уже озеленено'}<b>{zones.filter(z=>z.status==='existing_green').length}</b>{layers.existing&&<Check size={12}/>}</button><button className={layers.candidates?'active filter-candidate':'filter-candidate'} aria-pressed={layers.candidates} onClick={()=>setLayers({...layers,candidates:!layers.candidates})}><Sprout size={15}/>{kk?'Отырғызу ұсынысы':'Предлагается посадка'}<b>{zones.filter(z=>z.status!=='existing_green').length}</b>{layers.candidates&&<Check size={12}/>}</button></div>
  {panel&&<div className="layer-panel">{Object.entries(layers).map(([k,v])=><label key={k}><input type="checkbox" checked={v} onChange={e=>setLayers({...layers,[k]:e.target.checked})}/>{labels[k]}</label>)}<small>{kk?'Контурлар — OSM. Топырақ пен басымдықтар — демо.':'Контуры — OSM. Почвы и приоритеты — демо.'}</small></div>}
  <div className="map-legend zone-map-legend"><span><i className="legend-existing"/>{kk?'Бар жасыл аумақ':'Озеленено'}</span><span><i className="legend-candidate"/>{kk?'Отырғызу ұсынысы':'Посадка · предложение'}</span>{layers.plantings&&<span><i className="legend-plan"/>{kk?'Жоспар':'План'}</span>}</div>
  {drawingNow?<div className="map-hint draw-hint">{kk?'Контур нүктелерін белгілеңіз. Аяқтау үшін бірінші нүктені басыңыз.':'Отметьте границы участка. Нажмите первую точку, чтобы закончить.'}<button onClick={()=>{drawing.current?.disable();setDrawingNow(false)}}>{kk?'Болдырмау':'Отмена'}</button></div>:!selected&&<div className="map-hint zone-map-hint">{kk?'Аумақты басыңыз → қысқаша мәлімет → AI-дан сұрау':'Нажмите на зону → краткая информация → «Спросить ИИ»'}</div>}
 </div>
}
