// Explicit month names also work in browsers built without Kazakh Intl locale data.
const months={ru:['январь','февраль','март','апрель','май','июнь','июль','август','сентябрь','октябрь','ноябрь','декабрь'],kk:['қаңтар','ақпан','наурыз','сәуір','мамыр','маусым','шілде','тамыз','қыркүйек','қазан','қараша','желтоқсан']};
export function monthName(month:number,kk:boolean):string{return months[kk?'kk':'ru'][month-1]||''}
