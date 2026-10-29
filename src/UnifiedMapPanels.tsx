import type {ReactNode} from 'react';
import {BarChart3,ChevronDown,ChevronUp,ExternalLink,Info,Layers,MapPin,MessagesSquare,Pencil,Satellite,Save,Sprout,Trees,TrendingUp} from 'lucide-react';
import {Badge,Button} from './ui';
import {statusLabel,zoneAddress} from './zoneModel';
import type {Zone} from './types';
import type {MonitoringResult} from './monitoringTypes';
import type {UnifiedMode as UnifiedMapMode} from './unifiedMapModel';
import './unifiedMap.css';

const format=(value:number|null|undefined,digits=2)=>value==null||!Number.isFinite(value)?'—':new Intl.NumberFormat('ru-KZ',{maximumFractionDigits:digits}).format(value);
function safeSource(value:string|undefined){if(!value)return null;try{const url=new URL(value);return url.protocol==='https:'?url.href:null}catch{return null}}

type ModeBarProps={mode:UnifiedMapMode;onMode:(mode:UnifiedMapMode)=>void;kk:boolean};
export function UnifiedModeBar({mode,onMode,kk}:ModeBarProps){
 const modes:{id:UnifiedMapMode;ru:string;kk:string;icon:typeof Layers}[]=[
  {id:'territories',ru:'Территории',kk:'Аумақтар',icon:Trees},
  {id:'satellite',ru:'Спутник',kk:'Спутник',icon:Satellite},
  {id:'changes',ru:'Изменения',kk:'Өзгерістер',icon:TrendingUp},
  {id:'planning',ru:'Планирование',kk:'Жоспарлау',icon:Sprout},
  {id:'analysis',ru:'Анализ',kk:'Талдау',icon:BarChart3}
 ];
 return <nav className="unified-mode-bar" aria-label={kk?'Карта режимдері':'Режимы карты'}>{modes.map(item=><button key={item.id} type="button" aria-pressed={mode===item.id} className={mode===item.id?'active':''} onClick={()=>onMode(item.id)}><item.icon size={17}/><span>{kk?item.kk:item.ru}</span></button>)}</nav>
}

type ToolPanelProps={kk:boolean;children:ReactNode;title:string;open:boolean;onOpenChange:(open:boolean)=>void};
export function UnifiedToolPanel({kk,children,title,open,onOpenChange}:ToolPanelProps){
 return <aside className={'unified-tool-panel '+(open?'is-open':'is-collapsed')} aria-label={title}>
  <button className="unified-panel-heading" type="button" aria-expanded={open} onClick={()=>onOpenChange(!open)} title={open?(kk?'Құралдарды жию':'Свернуть инструменты'):(kk?'Құралдарды ашу':'Открыть инструменты')}><span className="unified-sheet-handle" aria-hidden="true"/><span className="unified-panel-heading-label"><Layers size={16}/><strong>{title}</strong></span><span className="unified-panel-toggle">{open?<ChevronDown size={18}/>:<ChevronUp size={18}/>}</span></button>
  <div className="unified-panel-body" hidden={!open}>{children}</div>
 </aside>
}

type ZoneCardProps={
 zone:Zone|null;monitoring:MonitoringResult|null;loading?:boolean;kk:boolean;
 onAnalyze:(zone:Zone)=>void;onPlan:(zone:Zone)=>void;onAsk:(zone:Zone)=>void;onSave:(zone:Zone)=>void;onRename?:(zone:Zone)=>void;
 hiddenSelection?:boolean;error?:string|null;
};
export function UnifiedZoneCard({zone,monitoring,loading=false,kk,onAnalyze,onPlan,onAsk,onSave,onRename,hiddenSelection=false,error}:ZoneCardProps){
 const tr=(ru:string,kz:string)=>kk?kz:ru;
 if(!zone)return <section className="unified-zone-card unified-zone-empty"><div className="unified-empty-icon"><MapPin size={25}/></div><h3>{tr('Выберите территорию','Аумақты таңдаңыз')}</h3><p>{tr('Нажмите на участок на карте или найдите его по названию. Выбор сохранится при смене режима.','Картадағы аумақты басыңыз немесе атауы бойынша табыңыз. Режимді ауыстырғанда таңдау сақталады.')}</p><small>{tr('Зелёные контуры — существующие насаждения. Оранжевый пунктир — предложения для обследования.','Жасыл контурлар — бар жасыл аумақтар. Қызғылт сары үзік сызық — тексеруге ұсынылған аумақтар.')}</small></section>;
 const matchingMonitoring=monitoring?.zone_id===zone.id?monitoring:null;
 const existing=zone.status==='existing_green',stats=matchingMonitoring?.statistics,ready=matchingMonitoring?.status==='ready';
 const area=zone.area_m2!=null&&Number.isFinite(zone.area_m2)?zone.area_m2:null;
 const source=safeSource(zone.source),address=zoneAddress(zone,kk);
 const net=stats?.net_change_ha;
 const signed=(value:number|null|undefined,digits=2)=>value==null?'—':(value>0?'+':'')+format(value,digits);
 return <section className="unified-zone-card" aria-label={tr('Карточка выбранного участка','Таңдалған аумақ карточкасы')}>
  <div className="unified-zone-heading"><span className="eyebrow">{tr('ВЫБРАННАЯ ТЕРРИТОРИЯ','ТАҢДАЛҒАН АУМАҚ')}</span>{onRename&&<button type="button" className="icon-button" onClick={()=>onRename(zone)} aria-label={tr('Изменить название','Атауын өзгерту')}><Pencil size={15}/></button>}</div>
  <Badge tone={existing?'green':'orange'}>{existing?<Trees size={12}/>:<Sprout size={12}/>} {statusLabel(zone,kk)}</Badge>
  <h3>{kk?zone.kk:zone.ru}</h3>
  {address&&<p className="unified-zone-address"><MapPin size={14}/><span>{address}<small>{tr('Ориентир по OSM, не почтовый адрес','OSM бағдары, пошта мекенжайы емес')}</small></span></p>}
  <div className="unified-zone-meta"><div><span>{tr('Площадь контура','Контур ауданы')}</span><strong>{area==null?'—':format(area/10000)} {area==null?'':tr('га','га')}</strong></div><div><span>{tr('Геометрия','Геометрия')}</span>{source?<a href={source} target="_blank" rel="noreferrer">{zone.provenance==='osm'?'OpenStreetMap':tr('Источник','Дереккөз')}<ExternalLink size={11}/></a>:<strong>{tr('Пользовательский контур','Пайдаланушы контуры')}</strong>}</div></div>
  {hiddenSelection&&<div className="unified-inline-note" role="status"><Info size={14}/><p>{tr('Выбранная территория скрыта текущим слоем. Её выбор и параметры сохранены.','Таңдалған аумақ ағымдағы қабатта жасырылған. Таңдау мен параметрлер сақталды.')}</p></div>}
  <div className="unified-satellite-summary" aria-busy={loading}>
   <div className="unified-section-label"><Satellite size={14}/><h4>{tr('Спутниковая история','Спутниктік тарих')}</h4>{loading&&<span className="unified-loading-dot" aria-label={tr('Загрузка','Жүктелуде')}/>}</div>
   {ready?<><div className="unified-year-grid">{([2020,2026] as const).map(year=><div key={year}><span>{year} · {tr('растительность','өсімдік жамылғысы')}</span><strong>{format(year===2020?stats?.vegetation_2020_ha:stats?.vegetation_2026_ha)} <small>{tr('га','га')}</small></strong><small>NDVI {format(year===2020?stats?.mean_ndvi_2020:stats?.mean_ndvi_2026,3)}</small></div>)}</div><div className={'unified-net-change '+(net==null?'':net>0?'positive':net<0?'negative':'')}><span>{tr('Чистое изменение','Таза өзгеріс')}</span><strong>{signed(net)} {net==null?'':tr('га','га')}</strong><small>{signed(stats?.change_percent)}{stats?.change_percent==null?'':'%'}</small></div><div className="unified-quality"><div><span>{tr('Пригодны для сравнения','Салыстыруға жарамды')}</span><b>{stats?.comparable_fraction==null?'—':format(stats.comparable_fraction*100,1)+'%'}</b></div><div className="unified-quality-track" aria-hidden="true"><i style={{width:`${Math.min(100,Math.max(0,(stats?.comparable_fraction||0)*100))}%`}}/></div><small>{format(stats?.comparable_pixels,0)} / {format(stats?.total_pixels,0)} {tr('пикселей · сетка 10 м','пиксель · 10 м тор')} · NDVI ≥ {format(monitoring?.threshold,2)}</small></div>{stats?.aoi_coverage_fraction!=null&&stats.aoi_coverage_fraction<.999&&<p className="unified-zone-caveat">{tr('Обработана только часть выбранной территории. Покрытие контура: ','Таңдалған аумақтың бір бөлігі ғана өңделген. Контур қамтуы: ')}{format(stats.aoi_coverage_fraction*100,1)}%.</p>}{stats?.total_pixels!=null&&stats.total_pixels<30&&<p className="unified-zone-caveat">{tr('Малая территория: каждый пиксель соответствует примерно 100 м². Границы и качество маски заметно влияют на оценку.','Шағын аумақ: әр пиксель шамамен 100 м². Шекаралар мен маска сапасы бағалауға елеулі әсер етеді.')}</p>}</>:<div className="unified-satellite-unavailable"><Info size={15}/><p>{loading?tr('Проверяем обработанные наблюдения…','Өңделген бақылаулар тексерілуде…'):error||monitoring?.reason||tr('Сопоставимые спутниковые показатели для этой территории пока недоступны.','Бұл аумақ үшін салыстырылатын спутниктік көрсеткіштер әзірше қолжетімсіз.')}</p></div>}
  </div>
  <p className="unified-zone-caveat">{tr('NDVI включает траву и кустарники. Изменение не доказывает посадку или вырубку деревьев и не меняет статус территории.','NDVI шөп пен бұталарды қамтиды. Өзгеріс ағаш отырғызылғанын немесе кесілгенін дәлелдемейді және аумақ мәртебесін өзгертпейді.')}</p>
  <div className="unified-zone-actions"><Button type="button" variant="secondary" onClick={()=>onAnalyze(zone)}><BarChart3 size={15}/>{tr('Анализировать','Талдау')}</Button><Button type="button" onClick={()=>onPlan(zone)}><Sprout size={15}/>{tr('Спланировать озеленение','Көгалдандыруды жоспарлау')}</Button><Button type="button" variant="secondary" onClick={()=>onAsk(zone)}><MessagesSquare size={15}/>{tr('Спросить ИИ','AI-дан сұрау')}</Button><Button type="button" variant="secondary" onClick={()=>onSave(zone)}><Save size={15}/>{tr('Сохранить проект','Жобаны сақтау')}</Button></div>
 </section>
}

export type UnifiedLegendItem={color:string;label:string;hatched?:boolean};
export function UnifiedLegend({items,title}:{items:UnifiedLegendItem[];title?:string}){return <div className="unified-legend">{title&&<strong>{title}</strong>}<div>{items.map(item=><span key={item.label}><i style={{backgroundColor:item.color,backgroundImage:item.hatched?'repeating-linear-gradient(135deg,transparent,transparent 3px,#7f8c7d55 3px,#7f8c7d55 5px)':undefined}}/>{item.label}</span>)}</div></div>}
