import {Link} from 'react-router-dom';
import type {DecisionResult} from './decisionModel';
import {decisionActionTarget} from './decisionModel';
import ScenarioComparison from './ScenarioComparison';
import {Badge} from './ui';

export default function DecisionView({result,zoneId,threshold,kk}:{result:DecisionResult;zoneId:string;threshold:number;kk:boolean}){
 const tr=(ru:string,kz:string)=>kk?kz:ru;
 const types:Record<string,string>={observed_satellite:tr('Спутниковое наблюдение','Спутниктік бақылау'),expert_calculation:tr('Экспертный расчёт','Сараптамалық есеп'),forecast:tr('Прогноз','Болжам'),hypothesis:tr('Гипотеза','Болжамды себеп')};
 const labels:Record<string,string>={show_losses:tr('Показать потери','Жоғалуды көрсету'),compare_years:tr('Сравнить 2020/2026','2020/2026 салыстыру'),open_plan:tr('К плану озеленения','Көгалдандыру жоспарына'),show_zone:tr('Показать участок','Аумақты көрсету')};
 return <div className="decision-response">
  <Badge tone={result.automatic_summary?'amber':'green'}>{result.automatic_summary?tr('Автоматическая сводка без AI','AI қолданбай автоматты қорытынды'):tr('Объяснение AI · серверные показатели','AI түсіндірмесі · сервер көрсеткіштері')}</Badge>
  {result.reason&&<p className="decision-reason">{result.reason}</p>}
  {(result.automatic_summary||result.response_kind==='analysis')&&result.sections?<div className="decision-sections">{result.sections.map(section=><section key={section.id}><h4>{section.title}</h4><small className="decision-type">{types[section.data_type]}</small><p>{section.text}</p>{section.commentary&&<p className="decision-model-note">AI: {section.commentary}</p>}</section>)}</div>:<p className="decision-answer">{result.answer}</p>}
  {result.previous_plan_delta&&<p className="decision-version-note">{tr('К предыдущему обсуждённому плану','Алдыңғы талқыланған жоспарға қатысты')}: {result.previous_plan_delta.total_plants>0?'+':''}{result.previous_plan_delta.total_plants} {tr('растений','өсімдік')}; {new Intl.NumberFormat('ru-KZ').format(result.previous_plan_delta.total_cost)} ₸.</p>}
  {!!result.evidence?.length&&<details className="decision-evidence" open={result.response_kind==='analysis'||result.automatic_summary}><summary>{tr('Показатели и обоснование','Көрсеткіштер мен негіздеме')}</summary><div className="decision-facts">{result.evidence.map(fact=><article key={fact.id}><span>{fact.label}</span><strong>{fact.value==null?tr('Нет данных','Дерек жоқ'):new Intl.NumberFormat('ru-KZ',{maximumFractionDigits:3}).format(fact.value)+' '+(fact.unit==='plants'?tr('шт.','дана'):fact.unit==='ha'?'га':fact.unit==='pixels'?tr('пикс.','пикс.'):fact.unit==='KZT'?'₸':fact.unit)}</strong><small>{types[fact.data_type]}</small><details><summary>{tr('Источник и метод','Дереккөз бен әдіс')}</summary><p>{fact.source}</p>{fact.period&&<p>{fact.period}</p>}<p>{fact.method}</p>{fact.threshold!=null&&<p>NDVI ≥ {fact.threshold}</p>}</details></article>)}</div></details>}
  {result.scenarios&&(result.response_kind==='scenarios'||result.response_kind==='analysis'||result.automatic_summary)&&<ScenarioComparison data={result.scenarios} kk={kk}/>}
  <div className="decision-map-actions">{(result.actions||[]).map(action=>{const target=decisionActionTarget(action,zoneId,threshold);return target?<Link key={action} className="btn btn-secondary" to={target}>{labels[action]}</Link>:null})}</div>
  {result.model&&<small className="fine-print">{result.model} · $0</small>}
 </div>;
}
