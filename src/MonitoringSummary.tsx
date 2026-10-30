import {Info,LoaderCircle} from 'lucide-react';
import type {MonitoringResult} from './monitoringTypes';

type Props={result:MonitoringResult|null;loading:boolean;kk:boolean;territory:string;threshold:number;unavailable?:string};
const format=(value:number|null|undefined,kk:boolean,digits=2)=>value==null||!Number.isFinite(value)?(kk?'Дерек жоқ':'Нет данных'):new Intl.NumberFormat('ru-KZ',{maximumFractionDigits:digits}).format(value);
export default function MonitoringSummary({result,loading,kk,territory,threshold,unavailable}:Props){
 const tr=(ru:string,kz:string)=>kk?kz:ru,stats=result?.status==='ready'?result.statistics:null;
 const values=[
  {label:tr('Растительность · 2020','Өсімдік жамылғысы · 2020'),value:stats?.vegetation_2020_ha,unit:'га',hint:tr('На общей пригодной площади','Ортақ жарамды ауданда')},
  {label:tr('Растительность · 2026','Өсімдік жамылғысы · 2026'),value:stats?.vegetation_2026_ha,unit:'га',hint:tr('На той же площади сравнения','Сол салыстыру ауданында')},
  {label:tr('Вероятный прирост','Ықтимал өсім'),value:stats?.gain_ha,unit:'га',hint:tr('Переход выше порога NDVI','NDVI шегінен жоғары өту'),className:'gain'},
  {label:tr('Вероятные потери','Ықтимал жоғалу'),value:stats?.loss_ha,unit:'га',hint:tr('Переход ниже порога NDVI','NDVI шегінен төмен өту'),className:'loss'},
  {label:tr('Чистое изменение','Таза өзгеріс'),value:stats?.net_change_ha,unit:'га',hint:stats?.change_percent==null?tr('Процент не определён','Пайыз анықталмаған'):format(stats.change_percent,kk)+'% '+tr('к растительности 2020','2020 өсімдік ауданына қатысты')},
  {label:tr('Пригодные пиксели','Жарамды пиксельдер'),value:stats?.comparable_fraction==null?null:stats.comparable_fraction*100,unit:'%',hint:tr('Не доказательство причины изменений','Өзгеріс себебінің дәлелі емес')}
 ];
 return <section className="monitoring-summary" aria-label={tr('Спутниковая сводка','Спутниктік қорытынды')} aria-busy={loading}>
  <div className="monitoring-summary-heading"><strong>{territory}</strong><small>{tr('Спутниковое наблюдение','Спутниктік бақылау')} · Sentinel-2 · 2020/2026 · NDVI ≥ {format(threshold,kk)}{loading&&<LoaderCircle size={12} className="spin"/>}</small></div>
  <div className="monitoring-summary-grid">{values.map(item=><div className={'monitoring-summary-cell '+(item.className||'')} key={item.label} title={item.hint}><span>{item.label}</span><strong>{loading?tr('Загрузка…','Жүктелуде…'):format(item.value,kk)}{!loading&&item.value!=null&&<small> {item.unit}</small>}</strong><small>{item.hint}</small></div>)}</div>
  {!loading&&!stats&&<p className="monitoring-summary-note"><Info size={13}/>{unavailable||result?.reason||tr('Сопоставимые наблюдения отсутствуют. Значения не заменены нулями.','Салыстырылатын бақылаулар жоқ. Мәндер нөлмен алмастырылмайды.')}</p>}
 </section>;
}
