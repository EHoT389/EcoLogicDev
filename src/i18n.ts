import i18n from 'i18next';
import {initReactI18next} from 'react-i18next';
i18n.use(initReactI18next).init({resources:{ru:{translation:{}},kk:{translation:{}}},lng:localStorage.getItem('eco-language')||'ru',fallbackLng:'ru',interpolation:{escapeValue:false}});
export default i18n;
