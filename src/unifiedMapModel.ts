import {parseMonitoringThreshold} from './monitoringState.ts';
import type {MonitoringMetadata} from './monitoringTypes';

export const UNIFIED_MODES=['territories','satellite','changes','planning','analysis'] as const;
export type UnifiedMode=typeof UNIFIED_MODES[number];
export type UnifiedRasterLayer='vegetation'|'ndvi'|'quality'|'rgb';
export type UnifiedMapState={mode:UnifiedMode;year:'2020'|'2026';threshold:number;compare:boolean;layer:UnifiedRasterLayer;opacity:number;swipe:number;scope:'zone'|'city';lat:number|null;lon:number|null;zoom:number|null;change_filter:'all'|'loss'|'gain'};
export type SavedMapState=Omit<UnifiedMapState,'lat'|'lon'>&{version:1;zone_id:string|null;center:[number,number]|null};
export type UnifiedMapUpdate=Partial<UnifiedMapState>&{zone?:string|null};
export type UnifiedMonitoringMetadata=MonitoringMetadata&{
 available_layers?:string[];
 aoi?:{geometry?:GeoJSON.Geometry;name_ru?:string;name_kk?:string;area_km2?:number;source?:string};
 coverage?:Record<string,unknown>;
 rgb?:{status:string;dataset_id?:string;reason?:string;method?:string};
};
export function parseUnifiedMapState(search:string):UnifiedMapState{
 const query=new URLSearchParams(search);
 const mode=query.get('mode');const layer=query.get('layer');
 const bounded=(value:string|null,fallback:number,min:number,max:number)=>{const parsed=value==null||!value.trim()?NaN:Number(value);return Number.isFinite(parsed)?Math.min(max,Math.max(min,parsed)):fallback};
 const optional=(key:string,min:number,max:number)=>{const raw=query.get(key),value=raw?.trim()?Number(raw):NaN;return Number.isFinite(value)&&value>=min&&value<=max?value:null};
 const lat=optional('lat',-85,85),lon=optional('lon',-180,180),zoom=optional('zoom',8,19);
 return {mode:UNIFIED_MODES.includes(mode as UnifiedMode)?mode as UnifiedMode:'territories',year:query.get('year')==='2020'?'2020':'2026',threshold:parseMonitoringThreshold(query.get('threshold')),compare:query.get('compare')==='1',layer:layer==='ndvi'||layer==='quality'||layer==='rgb'?layer:'vegetation',opacity:bounded(query.get('opacity'),.8,0,1),swipe:bounded(query.get('swipe'),50,0,100),scope:query.get('scope')==='city'?'city':'zone',lat:lat!=null&&lon!=null?lat:null,lon:lat!=null&&lon!=null?lon:null,zoom:zoom!=null?Math.round(zoom):null,change_filter:query.get('change_filter')==='loss'?'loss':query.get('change_filter')==='gain'?'gain':'all'};
}
export function unifiedMapSearch(search:string,update:UnifiedMapUpdate):string{
 const query=new URLSearchParams(search);
 for(const [key,value] of Object.entries(update)){
  if(value===undefined)continue;
  if(value===null)query.delete(key);
  else query.set(key,key==='compare'?(value?'1':'0'):String(value));
 }
 return '?'+query.toString();
}
export function savedMapState(search:string,zoneId:string|null):SavedMapState{
 const {lat,lon,...state}=parseUnifiedMapState(search);
 return {...state,version:1,zone_id:zoneId,center:lat!=null&&lon!=null?[lat,lon]:null};
}
export function restoreMapSearch(saved:SavedMapState|null|undefined,zoneId:string|null):string{
 if(!saved)return unifiedMapSearch('',{mode:'planning',zone:zoneId});
 const {center,zone_id,version,...state}=saved;
 return unifiedMapSearch('',{...state,zone:zoneId,lat:center?.[0]??null,lon:center?.[1]??null});
}
export function legacyUnifiedLocation(pathname:string,search:string):string|null{
 const mode:UnifiedMode|undefined=({'/monitoring':'changes','/problems':'analysis','/priorities':'analysis'} as Record<string,UnifiedMode>)[pathname];
 return mode?'/map'+unifiedMapSearch(search,{mode}):null;
}
