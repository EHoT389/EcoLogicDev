import messages from '../shared/messages.json' with {type:'json'};

const catalog:Record<string,string>=messages;
const reverse=Object.fromEntries(Object.entries(catalog).map(([ru,kk])=>[kk,ru]));
// Only application-owned explanatory text goes through this function. Names and chat history stay verbatim.
export function localizeText(text:string|undefined,kk:boolean):string{
 if(!text)return '';
 const dictionary=kk?catalog:reverse;
 if(dictionary[text])return dictionary[text];
 for(const prefix of ['Ошибка импорта: ','Недопустимый параметр ','Неверная строка ','Нужно логическое значение: ','Неверное число: ','Неверная строка: ']){
  const from=kk?prefix:catalog[prefix],to=kk?catalog[prefix]:prefix;
  if(text.startsWith(from))return to+text.slice(from.length);
 }
 return text;
}
