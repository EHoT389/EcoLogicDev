import type {AnalysisInput,PlanGoal} from './types';
export type WizardSettings={goal:PlanGoal;budget:number;years:number;irrigation:boolean;maintenance:number};
export function settingsFor(input:AnalysisInput|null):WizardSettings{
 return {goal:input?.goal||(input?.site.purpose==='children'?'children':input?.site.purpose==='road'?'road':'shade'),budget:input?.budget??1_000_000,years:input?.years??3,irrigation:input?.irrigation??true,maintenance:input?.maintenance??.8};
}
export function wizardInput(input:AnalysisInput,settings:WizardSettings):AnalysisInput{
 if(!Number.isFinite(settings.budget)||settings.budget<0||settings.budget>1_000_000_000)throw new Error('budget');
 if(![1,2,3].includes(settings.years))throw new Error('years');
 return {...input,...settings,site:{...input.site,purpose:settings.goal==='children'?'children':settings.goal==='road'?'road':'public'},plants:null};
}
export function sameCalculation(a:AnalysisInput,b:AnalysisInput|null):boolean{
 if(!b)return false;
 const snapshot=(p:AnalysisInput)=>({geometry:p.geometry,site:p.site,budget:p.budget,years:p.years,plantable:p.plantable,irrigation:p.irrigation,maintenance:p.maintenance,plants:p.plants??null,goal:p.goal??null,zone_id:p.zone_id??null});
 return JSON.stringify(snapshot(a))===JSON.stringify(snapshot(b));
}
