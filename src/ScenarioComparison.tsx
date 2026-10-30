import type {ScenarioSet} from './decisionModel';
import {Button} from './ui';
import {localizeText} from './localize';
const number=(value:number|null|undefined)=>value==null?'—':new Intl.NumberFormat('ru-KZ',{maximumFractionDigits:1}).format(value);
export default function ScenarioComparison({data,loading,error,kk,onCalculate,onExplain}:{data:ScenarioSet|null;loading?:boolean;error?:string;kk:boolean;onCalculate?:()=>void;onExplain?:()=>void}){
 const tr=(ru:string,kz:string)=>kk?kz:ru;
 return <section className="scenario-comparison"><div className="scenario-title"><h3>{tr('Три сценария','Үш сценарий')}</h3>{onCalculate&&<Button variant="secondary" disabled={loading} onClick={onCalculate}>{loading?tr('Расчёт…','Есептелуде…'):tr('Рассчитать сценарии','Сценарийлерді есептеу')}</Button>}</div>
  {error&&<p className="form-error" role="alert">{error}</p>}
  {data&&<><div className="scenario-table-wrap"><table><thead><tr><th>{tr('Показатель','Көрсеткіш')}</th>{data.scenarios.map(s=><th key={s.id}>{kk?s.kk:s.ru}</th>)}</tr></thead><tbody>
   {([['total_plants',tr('Новые растения, шт.','Жаңа өсімдіктер, дана')],['planting_cost',tr('Посадка, ₸','Отырғызу, ₸')],['care_cost',tr('Уход, полив и резерв, ₸','Күтім, суару, резерв, ₸')],['total_cost',tr('Итого, ₸','Барлығы, ₸')]] as const).map(([key,label])=><tr key={key}><td>{label}</td>{data.scenarios.map(s=><td key={s.id}>{number(s[key])}</td>)}</tr>)}
   {[0,1,2].map(index=><tr key={index}><td>{tr('Приживаемость','Жерсіну')} · {index+1} {tr('год, %','жыл, %')}</td>{data.scenarios.map(s=><td key={s.id}>{s.survival[index]==null?tr('Нет данных','Дерек жоқ'):number(s.survival[index])}</td>)}</tr>)}
   <tr><td>{tr('К базовому, ₸','Негізгіге қатысты, ₸')}</td>{data.scenarios.map(s=><td key={s.id}>{s.delta.total_cost>0?'+':''}{number(s.delta.total_cost)}</td>)}</tr>
   <tr><td>{tr('Бюджет и площадь','Бюджет пен аудан')}</td>{data.scenarios.map(s=><td key={s.id} className={!s.within_budget||!s.within_area?'scenario-warning':''}>{s.within_budget&&s.within_area?tr('В пределах','Шекте'):!s.within_budget?tr('Превышен бюджет','Бюджеттен асады'):tr('Превышена площадь','Ауданнан асады')}</td>)}</tr>
  </tbody></table></div><p className="fine-print">{kk?data.limitation.kk:data.limitation.ru}</p><details><summary>{tr('Условия, риски и источники','Шарттар, тәуекелдер, дереккөздер')}</summary><p>{kk?data.method.kk:data.method.ru}</p><p>{tr('Общий бюджет','Ортақ бюджет')}: {number(data.conditions.budget)} ₸ · {data.conditions.years} {tr('г.','ж.')}</p><p>{data.source.rates} · {data.source.formula_version}</p>{data.scenarios.map(s=><div key={s.id}><strong>{kk?s.kk:s.ru}</strong>{s.warnings.concat(s.risks).map((warning,i)=><p key={i}>{localizeText(warning,kk)}</p>)}</div>)}</details>{onExplain&&<Button variant="secondary" onClick={onExplain}>{tr('Объяснить различия с AI','Айырмашылықтарды AI арқылы түсіндіру')}</Button>}</>}
 </section>;
}
