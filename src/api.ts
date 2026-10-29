import type {AnalysisInput} from './types';
import i18n from './i18n';
import {localizeText} from './localize';
export const API = (import.meta as any).env.VITE_API_URL || '';
let csrf='';
export const setCsrf=(value:string)=>{csrf=value||''};
export async function api<T=any>(path:string, options:RequestInit={}):Promise<T>{
 const headers:Record<string,string>={'Accept-Language':i18n.language,...(options.body instanceof FormData?{}:{'Content-Type':'application/json'}),...(options.headers as Record<string,string>||{})};
 if(csrf) headers['X-CSRF-Token']=csrf;
 let response:Response;
 try{response=await fetch(API+'/api'+path,{credentials:'include',...options,headers})}catch{throw new Error(localizeText('Сервер недоступен',i18n.language==='kk'))}
 if(!response.ok){const data=await response.json().catch(()=>({detail:'Сервер недоступен'}));throw new Error(localizeText(typeof data.detail==='string'?data.detail:'Проверьте введённые данные',i18n.language==='kk'));}
 return response.json();
}
export const post=<T=any>(path:string,data:unknown)=>api<T>(path,{method:'POST',body:JSON.stringify(data)});
export async function downloadReport(id:string,format:string){
 const response=await fetch(`${API}/api/reports/${id}/${format}`,{credentials:'include',headers:{'Accept-Language':i18n.language}});
 if(!response.ok)throw new Error(localizeText('Не удалось выгрузить отчёт',i18n.language==='kk'));
 const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download=`EcoLogicDev.${format}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export const defaultSite:AnalysisInput['site']={soil:'loam',moisture:.4,salinity:.2,traffic:.5,temperature:-38,light:'sun',purpose:'public',provenance:'user_input'};
