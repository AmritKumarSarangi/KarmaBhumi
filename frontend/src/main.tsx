import React from 'react';
import ReactDOM from 'react-dom/client';
import { Toaster } from 'react-hot-toast';
import App from './App';
import './styles/globals.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
    <Toaster
      position="top-right"
      toastOptions={{
        style: {
          background: 'rgba(20, 22, 30, 0.95)',
          color: '#e8eaf0',
          border: '1px solid rgba(255,255,255,0.1)',
          backdropFilter: 'blur(12px)',
          fontFamily: "'Inter', sans-serif",
          fontSize: '13px',
        },
        success: {
          iconTheme: { primary: '#00d4aa', secondary: '#0a0b0f' },
        },
        error: {
          iconTheme: { primary: '#ff4757', secondary: '#0a0b0f' },
        },
        duration: 4000,
      }}
    />
  </React.StrictMode>
);
