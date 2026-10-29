import {useEffect,useState} from 'react';
import {Pencil,Check,LoaderCircle} from 'lucide-react';
import type {Zone} from './types';
import {NAME_SUGGESTIONS} from './zoneModel';
import {Dialog,Button} from './ui';
export default function ZoneRenameDialog({zone,kk,account,onClose,onSave}:{zone:Zone|null;kk:boolean;account:boolean;onClose:()=>void;onSave:(zone:Zone,names:{ru:string;kk:string})=>Promise<void>}){
 const [ru,setRu]=useState(''),[kz,setKz]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>{if(zone){setRu(zone.ru);setKz(zone.kk);setError('')}},[zone]);
 const suggestions=zone?[{ru:zone.original_name||zone.ru,kk:zone.kk},...NAME_SUGGESTIONS]:[];
 return <Dialog open={!!zone} onOpenChange={v=>{if(!v&&!busy)onClose()}} title={kk?'Аумақ атауын өзгерту':'Изменить название зоны'}>
  <p className="muted">{kk?'Картада, жобада және AI диалогында қолданылатын атау.':'Название будет видно на карте, в проекте и диалоге с ИИ.'}</p>
  <form onSubmit={async e=>{e.preventDefault();if(!zone)return;setBusy(true);setError('');try{await onSave(zone,{ru:ru.trim(),kk:kz.trim()});onClose()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}}>
   <label className="field-label" htmlFor="zone-name-ru">{kk?'Орысша атауы':'Название на русском'}</label><input id="zone-name-ru" autoFocus required maxLength={120} value={ru} onChange={e=>setRu(e.target.value)}/>
   <label className="field-label" htmlFor="zone-name-kk">{kk?'Қазақша атауы':'Название на казахском'}</label><input id="zone-name-kk" required maxLength={120} value={kz} onChange={e=>setKz(e.target.value)}/>
   <label className="field-label">{kk?'Атау нұсқалары':'Варианты названия'}</label><div className="zone-name-suggestions">{suggestions.map((s,i)=><button type="button" key={i} onClick={()=>{setRu(s.ru);setKz(s.kk)}}>{kk?s.kk:s.ru}</button>)}</div>
   {error&&<p className="form-error" role="alert">{error}</p>}
   <p className="fine-print">{account?(kk?'Жеке атау аккаунтыңызда сақталады. OSM-дегі бастапқы атау өзгермейді.':'Личное название сохраняется в вашем аккаунте. Исходное название OpenStreetMap остаётся в источнике.'):(kk?'Жеке атау осы браузерде сақталады. Тіркелген соң атаулар аккаунтта сақталады.':'Личное название сохраняется в этом браузере. После входа названия можно сохранять в аккаунте.')}</p>
   <Button type="submit" disabled={busy||!ru.trim()||!kz.trim()}>{busy?<LoaderCircle className="spin" size={16}/>:<Check size={16}/>} {kk?'Атауды сақтау':'Сохранить название'}</Button>
  </form>
 </Dialog>
}
