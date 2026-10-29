"""Shared, explicit translations of application text; never translate user content."""
import json
from pathlib import Path

MESSAGES=json.loads((Path(__file__).parent.parent/'shared'/'messages.json').read_text(encoding='utf-8'))
def language(request):
 return 'kk' if request.headers.get('accept-language','ru').split(',')[0].strip().lower().startswith('kk') else 'ru'
def text(value,lang='ru'):
 if lang!='kk' or not isinstance(value,str): return value
 if value in MESSAGES: return MESSAGES[value]
 for prefix in ['Ошибка импорта: ','Недопустимый параметр ','Неверная строка ','Нужно логическое значение: ','Неверное число: ','Неверная строка: ']:
  if value.startswith(prefix): return MESSAGES[prefix]+value[len(prefix):]
 return value

FIELD_NAMES={
 'budget':('Бюджет','Бюджет'),'years':('Период, лет','Мерзім, жыл'),'plantable':('Доступная доля площади','Қолжетімді аудан үлесі'),
 'maintenance':('Интенсивность ухода','Күтім қарқындылығы'),'geometry':('Граница участка','Аумақ шекарасы'),'soil':('Почва','Топырақ'),
 'temperature':('Температура','Температура'),'moisture':('Влажность','Ылғалдылық'),'salinity':('Засоление','Тұздану'),'traffic':('Транспортная нагрузка','Көлік жүктемесі'),
 'name':('Название','Атау'),'password':('Пароль','Құпиясөз'),'email':('Email','Email'),'message':('Вопрос','Сұрақ'),'goal':('Цель','Мақсат'),
 'ru':('Название на русском','Орысша атауы'),'kk':('Название на казахском','Қазақша атауы'),'count':('Количество','Саны')}
def validation_message(error,lang):
 index=1 if lang=='kk' else 0
 field=FIELD_NAMES.get(str(error['loc'][-1]),('Данные','Деректер'))[index]
 kind=error['type'];ctx=error.get('ctx',{})
 if kind=='missing': reason=text('Обязательное поле',lang)
 elif kind in ('greater_than_equal','less_than_equal'):
  bound=ctx.get('ge',ctx.get('le'));sign='≥' if kind=='greater_than_equal' else '≤';reason=f'{sign} {bound}'
 elif kind in ('string_too_short','string_too_long'):
  bound=ctx.get('min_length',ctx.get('max_length'));sign='≥' if kind=='string_too_short' else '≤'
  reason=f'{sign} {bound} '+('таңба' if lang=='kk' else 'символов')
 elif kind=='value_error': reason=text(str(ctx.get('error','Недопустимое значение')),lang)
 elif kind=='json_invalid': reason=text('Некорректный формат JSON',lang)
 else: reason=text('Недопустимое значение',lang)
 return field+': '+reason
