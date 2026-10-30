import {useEffect,useState,useRef} from 'react';
import {Link,useLocation} from 'react-router-dom';
import {MessagesSquare,Sprout,ArrowUpRight,MapPin,Send,LoaderCircle,Info,Pencil,Trees,Map as MapIcon} from 'lucide-react';
import type {AnalysisInput,Zone,User} from './types';
import {api,post} from './api';
import {zoneAddress,zoneOption,statusLabel,zoneKey,readStorage} from './zoneModel';
import {localizeText} from './localize';
import {Badge,Button} from './ui';
import DecisionView from './DecisionView';
import ScenarioComparison from './ScenarioComparison';
import {boundedGuestHistory} from './decisionModel';
import type {DecisionResult,ResponseKind,ScenarioSet} from './decisionModel';
import {parseMonitoringThreshold} from './monitoringState';
import './decision.css';

export type ChatDraft={id:number;zoneId:string;text:string}|null;
type Message={role:string;text:string;model?:string;zoneName?:string;decision?:DecisionResult;threshold?:number};
type Props={input:AnalysisInput|null;zone:Zone|null;zones:Zone[];kk:boolean;user:User|null;notify:(s:string)=>void;onSelect:(zone:Zone)=>void;onRename:(zone:Zone)=>void;draft:ChatDraft;onDraftUsed:()=>void};

export default function DecisionAssistant({input,zone,zones,kk,user,notify,onSelect,onRename,draft,onDraftUsed}:Props){
 const tr=(ru:string,kz:string)=>kk?kz:ru;
 const location=useLocation(),parameters=new URLSearchParams(location.search),monitoringTopic=parameters.get('topic')==='vegetation_change';
 const rawThreshold=parameters.get('threshold'),threshold=parseMonitoringThreshold(rawThreshold);
 const validThreshold=rawThreshold==null||!!rawThreshold.trim()&&Number.isFinite(Number(rawThreshold))&&Number(rawThreshold)>=.1&&Number(rawThreshold)<=.9;
 const key=zoneKey(input),storageKey=`eco-chat-v3:${user?.id||'guest'}:${key}`;
 const [text,setText]=useState(''),[busy,setBusy]=useState(false),[historyLoading,setHistoryLoading]=useState(!!user);
 const [messages,setMessages]=useState<Message[]>(()=>readStorage(sessionStorage,storageKey,readStorage(sessionStorage,`eco-chat-v2:${user?.id||'guest'}:${key}`,[])));
 const messagesBox=useRef<HTMLDivElement>(null);
 useEffect(()=>{const box=messagesBox.current,last=box?.lastElementChild;if(box&&last)box.scrollTo({top:box.scrollTop+last.getBoundingClientRect().top-box.getBoundingClientRect().top,behavior:'instant'})},[messages.length]);
 const [scenarioData,setScenarioData]=useState<ScenarioSet|null>(null),[scenarioBusy,setScenarioBusy]=useState(false),[scenarioError,setScenarioError]=useState('');
 const [showScenarios,setShowScenarios]=useState(false);
 const selectedName=zone?(kk?zone.kk:zone.ru):(input?.zone_name||'');
 useEffect(()=>{try{sessionStorage.setItem(storageKey,JSON.stringify(messages.slice(-24)))}catch{/* Signed-in history remains on the server. */}},[messages,storageKey]);
 useEffect(()=>{if(draft&&draft.zoneId===key){setText(draft.text);onDraftUsed()}},[draft?.id,key]);
 useEffect(()=>{let cancelled=false;if(!user||!zone){setHistoryLoading(false);return}
  setHistoryLoading(true);
  api<any[]>('/ai/history?zone_id='+encodeURIComponent(key)).then(rows=>{if(cancelled)return;setMessages(rows.slice(0,12).reverse().flatMap(row=>{
   const decision:DecisionResult={answer:row.answer,model:row.model,automatic_summary:row.automatic_summary,sections:row.sections,evidence:row.evidence,scenarios:row.scenarios,plan_version:row.plan_version,zone_id:row.zone_id,response_kind:row.response_kind||'question',actions:['show_losses','compare_years','open_plan','show_zone'],previous_plan_delta:row.previous_plan_delta};
   return [{role:'user',text:row.question,zoneName:row.zone_name},{role:'assistant',text:row.answer,zoneName:row.zone_name,decision,threshold:row.evidence?.find((fact:any)=>fact.threshold!=null)?.threshold??.3}];
  }))}).catch(error=>{if(!cancelled)notify(error.message)}).finally(()=>{if(!cancelled)setHistoryLoading(false)});
  return()=>{cancelled=true};
 },[user?.id,key]);
 useEffect(()=>{setScenarioData(null);setScenarioError('')},[JSON.stringify(input)]);

 async function send(message=text,kind:ResponseKind=(monitoringTopic&&!messages.some(item=>item.role==='user')?'analysis':'question'),automatic=false){
  if(!message.trim()||busy||historyLoading||!input||!zone)return;
  if(!validThreshold){notify(tr('Порог NDVI должен быть от 0,10 до 0,90.','NDVI шегі 0,10–0,90 аралығында болуы керек.'));return}
  const snapshot={...input,zone_id:key,zone_name:selectedName};
  const request={message,analysis:snapshot,language:kk?'kk':'ru',response_kind:kind,history:user?[]:boundedGuestHistory(messages),monitoring:zone.provenance==='osm'?{zone_id:key,period_start:2020,period_end:2026,threshold}:undefined};
  setMessages(current=>[...current,{role:'user',text:message,zoneName:selectedName}]);setText('');setBusy(true);
  try{
   const data=await post<DecisionResult>(automatic?'/ai/summary':'/ai/chat',request);
   setMessages(current=>[...current,{role:'assistant',text:data.answer,zoneName:selectedName,decision:data,threshold}]);
  }catch(error){setMessages(current=>[...current,{role:'error',text:(error as Error).message,zoneName:selectedName}])}
  finally{setBusy(false)}
 }
 async function calculateScenarios(){
  if(!input||scenarioBusy)return;setShowScenarios(true);setScenarioBusy(true);setScenarioError('');
  try{setScenarioData(await post<ScenarioSet>('/scenarios',input))}catch(error){setScenarioError((error as Error).message)}finally{setScenarioBusy(false)}
 }
 const prompts=kk?['Неліктен бұл аумақта өсімдік азаюы мүмкін?','Суаруды күшейтсек не өзгереді?','Алдыңғы нұсқамен салыстыр','Қандай ағаштар қолайлы?']:['Почему здесь могла сократиться растительность?','А если увеличить полив?','Сравни с предыдущим вариантом','Какие деревья лучше посадить?'];
 const disabled=busy||historyLoading||!zone;
 return <>
  <div className="page-heading"><div><div className="eyebrow">{tr('ИИ С КОНТЕКСТОМ УЧАСТКА','АУМАҚПЕН БАЙЛАНЫСҚАН AI')}</div><h1>{tr('От наблюдений — к решениям.','Бақылаудан — шешімге.')}</h1><p>{tr('Проверенные факты, варианты действий и память обсуждения по каждой зоне.','Тексерілген деректер, әрекет нұсқалары және әр аумақтың талқылау жады.')}</p></div><Badge>OpenRouter · {tr('бесплатно','тегін')}</Badge></div>
  <section className="assistant-zone-context" aria-label={tr('Выбранная зона для ИИ','Таңдалған аумақ')}>
   <div className="assistant-context-icon">{zone?.status==='existing_green'?<Trees size={23}/>:<MapPin size={23}/>}</div>
   <div className="assistant-context-main"><label htmlFor="assistant-zone-select">{tr('КАКУЮ ЗОНУ ОБСУЖДАЕМ?','ҚАЙ АУМАҚТЫ ТАЛҚЫЛАЙМЫЗ?')}</label><select id="assistant-zone-select" disabled={busy} value={zone?.id||''} onChange={event=>{const next=zones.find(item=>item.id===event.target.value);if(next)onSelect(next)}}><option value="" disabled>{tr('Выберите участок','Аумақты таңдаңыз')}</option>{['existing_green','planting_candidate'].map(status=><optgroup key={status} label={statusLabel({status:status as any},kk)}>{zones.filter(item=>(item.status||'planting_candidate')===status).map(item=><option key={item.id} value={item.id}>{zoneOption(item,kk)}</option>)}</optgroup>)}</select></div>
   {zone&&<Badge tone={zone.status==='existing_green'?'green':'orange'}>{statusLabel(zone,kk)}</Badge>}
   <div className="assistant-context-actions"><Link to={zone?`/map?zone=${encodeURIComponent(zone.id)}&scope=zone`:'/map'}><MapIcon size={15}/>{tr('Показать на карте','Картада көрсету')}</Link>{zone&&<button onClick={()=>onRename(zone)}><Pencil size={14}/>{tr('Название','Атауы')}</button>}</div>
  </section>
  <div className="decision-toolbar"><Button disabled={disabled} onClick={()=>send(tr('Выполни структурированный анализ выбранного участка и предложи дальнейшие действия.','Таңдалған аумақтың құрылымды талдауын жасап, келесі әрекеттерді ұсын.'),'analysis')}>{tr('Разобрать участок с AI','Аумақты AI арқылы талдау')}</Button><Button variant="secondary" disabled={disabled||scenarioBusy} onClick={calculateScenarios}>{tr('Сравнить три сценария','Үш сценарийді салыстыру')}</Button><Button variant="secondary" disabled={disabled} onClick={()=>send(tr('Покажи автоматическую сводку по участку.','Аумақтың автоматты қорытындысын көрсет.'),'analysis',true)}>{tr('Сводка без AI','AI қолданбай қорытынды')}</Button></div>
  {showScenarios&&<div className="card decision-scenarios-card"><ScenarioComparison data={scenarioData} loading={scenarioBusy} error={scenarioError} kk={kk} onCalculate={calculateScenarios} onExplain={()=>send(tr('Объясни различия трёх рассчитанных сценариев, ограничения бюджета и риски.','Есептелген үш сценарийдің айырмашылықтарын, бюджет шектеулері мен тәуекелдерін түсіндір.'),'scenarios')}/></div>}
  <div className="chat-layout"><section className="chat-card">
   <div className="chat-header"><div className="assistant-avatar"><Sprout size={24}/></div><div><strong>EcoLogic AI</strong><small>{zone?selectedName:tr('Участок пока не выбран','Аумақ әзірше таңдалмаған')}</small></div>{historyLoading&&<LoaderCircle className="spin" size={16}/>}</div>
   <div className="chat-messages" ref={messagesBox} aria-live="polite">
    {!messages.length?<div className="chat-welcome"><div className="assistant-avatar large"><MessagesSquare size={36}/></div><h2>{zone?tr('Разберём этот участок','Осы аумақты қарастырайық'):tr('Сначала выберите зону','Алдымен аумақты таңдаңыз')}</h2><p>{zone?selectedName:tr('Выберите зону в списке выше или на карте.','Жоғарыдағы тізімнен немесе картадан аумақты таңдаңыз.')}</p>{zone?<div className="prompt-grid">{prompts.map(prompt=><button key={prompt} disabled={disabled} onClick={()=>send(prompt,'question')}>{prompt}<ArrowUpRight size={15}/></button>)}</div>:<Link className="btn btn-primary" to="/map">{tr('Выбрать зону на карте','Картадан аумақ таңдау')}<ArrowUpRight size={16}/></Link>}</div>:messages.map((message,index)=><div key={index} className={'chat-message message-'+message.role}><small>{message.role==='user'?tr('Вы','Сіз'):message.role==='error'?tr('Статус сервиса','Қызмет мәртебесі'):'EcoLogic'}{message.zoneName&&' · '+message.zoneName}</small>{message.role==='assistant'&&message.decision?<DecisionView result={message.decision} zoneId={key} threshold={message.threshold??threshold} kk={kk}/>:<div>{message.role==='error'?localizeText(message.text,kk):message.text}</div>}</div>)}
    {busy&&<div className="recalculating"><LoaderCircle className="spin" size={16}/>{tr('Готовим разбор на основе серверных данных…','Сервер деректерінен талдау дайындалуда…')}</div>}
   </div>
   <form className="chat-input" onSubmit={event=>{event.preventDefault();send()}}><textarea aria-label={tr('Вопрос ассистенту','Көмекшіге сұрақ')} disabled={!zone} placeholder={zone?tr('Уточните вывод или измените условия плана…','Қорытындыны нақтылаңыз немесе жоспар шартын өзгертіңіз…'):tr('Сначала выберите участок','Алдымен аумақты таңдаңыз')} rows={3} maxLength={1500} value={text} onChange={event=>setText(event.target.value)}/><Button type="submit" disabled={disabled||!text.trim()||!validThreshold} aria-label={tr('Отправить','Жіберу')}><Send size={19}/></Button></form>
   <p className="chat-disclaimer">{tr('Числа рассчитывает сервер. Если бесплатная модель недоступна, показывается автоматическая сводка без AI.','Сандарды сервер есептейді. Тегін модель қолжетімсіз болса, AI қолданбай автоматты қорытынды көрсетіледі.')}</p>
  </section><aside><div className="card"><h3>{tr('Факты и контекст','Деректер мен контекст')}</h3><p>{tr('Спутниковые наблюдения, экспертный план и гипотезы обозначены отдельно. Причину изменений нельзя доказать одним NDVI.','Спутниктік бақылаулар, сараптамалық жоспар және болжамды себептер бөлек белгіленеді. Өзгеріс себебін тек NDVI арқылы дәлелдеу мүмкін емес.')}</p>{zone&&<div className="assistant-zone-facts"><span>{statusLabel(zone,kk)}</span><span>{zoneAddress(zone,kk)}</span><small>{tr('Фактическое число деревьев неизвестно. Почва и влажность — расчётные допущения до обследования.','Ағаштардың нақты саны белгісіз. Топырақ пен ылғал — зерттеуге дейінгі есептік жорамал.')}</small></div>}<Link to="/plan">{tr('Параметры плана','Жоспар параметрлері')} →</Link></div><div className="inline-note"><Info size={18}/>{user?tr('Память сохраняется на сервере отдельно для вашего аккаунта и участка. Последние реплики и предыдущая версия плана учитываются в ответах.','Жад серверде аккаунт пен аумақ бойынша бөлек сақталады. Жауаптар соңғы репликалар мен жоспардың алдыңғы нұсқасын ескереді.'):tr('Гостевая память сохраняется в этой вкладке после обновления. Для истории после повторного входа используйте аккаунт.','Қонақ жады жаңартудан кейін осы қойындыда сақталады. Қайта кіргеннен кейінгі тарих үшін аккаунт қолданыңыз.')}</div><p className="fine-print">{tr('Гостю — 4 AI-вопроса в час, пользователю — 12. Серверная сводка и сравнение сценариев не расходуют AI-квоту.','Қонаққа сағатына 4 AI сұрағы, пайдаланушыға 12. Сервер қорытындысы мен сценарийлерді салыстыру AI квотасын жұмсамайды.')}</p></aside></div>
 </>;
}
