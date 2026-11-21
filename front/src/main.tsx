import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import { startClarityRouteReporting } from './lib/clarity';
import './index.css';
import './components/common/gold-glass.css';

startClarityRouteReporting();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
