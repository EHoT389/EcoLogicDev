export function parseMonitoringThreshold(value:string|null|undefined):number{
 if(value==null||!value.trim())return .3;
 const parsed=Number(value);
 return Number.isFinite(parsed)&&parsed>=.1&&parsed<=.9?parsed:.3;
}

// Preserve the selected zone and unrelated query state during slider updates.
// A null zone explicitly selects the processed city centre; undefined keeps the current zone.
export function monitoringSearch(search:string,threshold:number,zoneId?:string|null):string{
 const params=new URLSearchParams(search);
 params.set('threshold',String(parseMonitoringThreshold(String(threshold))));
 if(zoneId!==undefined){if(zoneId)params.set('zone',zoneId);else params.delete('zone')}
 return '?'+params.toString();
}
