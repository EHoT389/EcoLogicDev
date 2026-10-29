import {parseMonitoringThreshold} from './monitoringState.ts';
import type {MonitoringMetadata} from './monitoringTypes';

export const UNIFIED_MODES=['territories','satellite','changes','planning','analysis'] as const;
export type UnifiedMode=typeof UNIFIED_MODES[number];
export type UnifiedRasterLayer='vegetation'|'ndvi'|'quality';
export type UnifiedMapState={mode:UnifiedMode;year:'2020'|'2026';threshold:number;compare:boolean;layer:UnifiedRasterLayer;opacity:number;swipe:number};
export type UnifiedMonitoringMetadata=MonitoringMetadata&{
 available_layers?:string[];
 aoi?:{geometry?:GeoJSON.Geometry;name_ru?:string;name_kk?:string;area_km2?:number;source?:string};
 coverage?:Record<string,unknown>;
};
export function parseUnifiedMapState(search:string):UnifiedMapState{
 const query=new URLSearchParams(search);
 const mode=query.get('mode');const layer=query.get('layer');
 const bounded=(value:string|null,fallback:number,min:number,max:number)=>{const parsed=value==null||!value.trim()?NaN:Number(value);return Number.isFinite(parsed)?Math.min(max,Math.max(min,parsed)):fallback};
 return {mode:UNIFIED_MODES.includes(mode as UnifiedMode)?mode as UnifiedMode:'territories',year:query.get('year')==='2020'?'2020':'2026',threshold:parseMonitoringThreshold(query.get('threshold')),compare:query.get('compare')==='1',layer:layer==='ndvi'||layer==='quality'?layer:'vegetation',opacity:bounded(query.get('opacity'),.8,0,1),swipe:bounded(query.get('swipe'),50,0,100)};
}
export function unifiedMapSearch(search:string,update:Partial<UnifiedMapState>&{zone?:string|null}):string{
 const query=new URLSearchParams(search);
 for(const [key,value] of Object.entries(update)){
  if(value===undefined)continue;
  if(value===null)query.delete(key);
  else query.set(key,key==='compare'?(value?'1':'0'):String(value));
 }
 return '?'+query.toString();
}
export function legacyUnifiedLocation(pathname:string,search:string):string|null{
 const mode:UnifiedMode|undefined=({'/monitoring':'changes','/problems':'analysis','/priorities':'analysis'} as Record<string,UnifiedMode>)[pathname];
 return mode?'/map'+unifiedMapSearch(search,{mode}):null;
}
