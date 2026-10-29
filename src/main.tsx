import React from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter} from 'react-router-dom';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import './i18n';
import App from './App';
import './styles.css';
const client=new QueryClient({defaultOptions:{queries:{retry:1,refetchOnWindowFocus:false,staleTime:60000}}});
createRoot(document.getElementById('root')!).render(<React.StrictMode><QueryClientProvider client={client}><BrowserRouter><App/></BrowserRouter></QueryClientProvider></React.StrictMode>);
