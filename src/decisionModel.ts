import {unifiedMapSearch} from './unifiedMapModel.ts';
export type ResponseKind='analysis'|'question'|'scenarios';
export type DecisionAction='show_losses'|'compare_years'|'open_plan'|'show_zone';
export const DECISION_ACTIONS:DecisionAction[]=['show_losses','compare_years','open_plan','show_zone'];
export function decisionActionTarget(action:string,zoneId:string,threshold:number):string|null{
 if(!DECISION_ACTIONS.includes(action as DecisionAction)||!zoneId)return null;
 const scope={zone:zoneId,scope:'zone' as const,threshold};
 if(action==='open_plan')return '/map'+unifiedMapSearch('',{...scope,mode:'planning'});
 if(action==='compare_years')return '/map'+unifiedMapSearch('',{...scope,mode:'satellite',compare:true,swipe:50,layer:'vegetation'});
 if(action==='show_losses')return '/map'+unifiedMapSearch('',{...scope,mode:'changes',change_filter:'loss'});
 return '/map'+unifiedMapSearch('',{...scope,mode:'territories'});
}
export type Scenario={id:string;ru:string;kk:string;total_plants:number;planting_cost:number;care_cost:number;total_cost:number;within_budget:boolean;within_area:boolean;survival:(number|null)[];delta:{total_plants:number;total_cost:number;survival:(number|null)[]};warnings:string[];risks:string[]};
export type ScenarioSet={plan_version:string;zone_id:string|null;scenarios:Scenario[];conditions:{budget:number;years:number};method:{ru:string;kk:string};limitation:{ru:string;kk:string};source:{rates:string;formula_version:string}};
export type EvidenceFact={id:string;label:string;value:number|null;unit:string;data_type:string;source:string;period:string|null;method:string;threshold?:number|null};
export type DecisionResult={answer:string;model?:string|null;cloud?:boolean;automatic_summary?:boolean;reason?:string;sections?:{id:string;title:string;text:string;commentary?:string;data_type:string}[];evidence?:EvidenceFact[];scenarios?:ScenarioSet;plan_version?:string;zone_id?:string|null;actions?:string[];response_kind?:ResponseKind;previous_plan_delta?:{total_cost:number;total_plants:number;survival:(number|null)[]}};
export function boundedGuestHistory(messages:{role:string;text:string}[]){return messages.filter(message=>message.role==='user'||message.role==='assistant').slice(-8).map(message=>({role:message.role,text:message.text.slice(0,2000)}));}
