import type {AnalysisInput,Zone} from './types';
export const ZONE_SELECTION_KEY='eco-selected-zone-v2';
export const CUSTOM_ZONES_KEY='eco-custom-zones-v2';
export function zoneAddress(zone:Zone|null,kk=false):string{return zone?(kk?zone.address_kk:zone.address_ru)||'':''}
export function zoneOption(zone:Zone,kk=false):string{return (kk?zone.kk:zone.ru)+(zoneAddress(zone,kk)?' · '+zoneAddress(zone,kk):'')}
export function readStorage<T>(storage:Pick<Storage,'getItem'>,key:string,fallback:T):T{
 try{return JSON.parse(storage.getItem(key)||'null')??fallback}catch{return fallback}
}
export function geometryKey(geometry:AnalysisInput['geometry']):string{
 let hash=2166136261;for(const c of JSON.stringify(geometry))hash=Math.imul(hash^c.charCodeAt(0),16777619);
 return 'custom-'+(hash>>>0).toString(16);
}
export function zoneKey(input:AnalysisInput|null):string{return input?(input.zone_id||geometryKey(input.geometry)):'none'}
export function statusLabel(zone:Pick<Zone,'status'>|null,kk=false):string{
 return zone?.status==='existing_green'?(kk?'Бар жасыл аумақ':'Уже озеленено'):(kk?'Отырғызуға ұсынылған':'Предлагается посадка');
}
export function applyZoneNames(zones:Zone[],names:Record<string,{ru:string;kk:string}>):Zone[]{
 return zones.map(zone=>({...zone,original_name:zone.original_name||zone.ru,...names[zone.id]}));
}
export function zonePrompt(zone:Zone,kk:boolean):string{
 const name=kk?zone.kk:zone.ru;
 return zone.status==='existing_green'?(kk?`«${name}» жасыл аумағы үшін күтім мен қосымша отырғызу жөнінде кеңес бер. Бар ағаштарды сақтау және деректердің шектеулерін ескер.`:`Подскажи, какой уход и дополнительные посадки стоит рассмотреть для зелёной территории «${name}». Учти сохранение существующих деревьев и ограничения исходных данных.`):(kk?`«${name}» аумағында отырғызуды жоспарлауға көмектес. Қандай өсімдіктерді қарастыруға болады және алдымен нені тексеру керек?`:`Помоги спланировать озеленение участка «${name}»: какие растения рассмотреть и что проверить на месте до посадки?`);
}
export function inputForZone(zone:Zone,previous:AnalysisInput|null,kk:boolean):AnalysisInput{
 const name=kk?zone.kk:zone.ru;
 if(previous&&zoneKey(previous)===zone.id&&JSON.stringify(previous.geometry)===JSON.stringify(zone.geometry))return {...previous,zone_id:zone.id,zone_name:name};
 return {geometry:zone.geometry,zone_id:zone.id,zone_name:name,site:{soil:zone.soil,moisture:zone.moisture,salinity:zone.salinity,traffic:zone.traffic,temperature:zone.temperature,light:zone.light,purpose:'public',provenance:zone.assessment_provenance||'synthetic'},budget:previous?.budget??5_000_000,years:3,plantable:zone.status==='existing_green'?.15:.45,irrigation:true,maintenance:.8,plants:null};
}
export const NAME_SUGGESTIONS=[{ru:'Зелёный двор',kk:'Жасыл аула'},{ru:'Сквер у дома',kk:'Үй жанындағы сквер'},{ru:'Зелёная полоса вдоль дороги',kk:'Жол бойындағы жасыл белдеу'},{ru:'Новый участок озеленения',kk:'Жаңа көгалдандыру аумағы'}];
