import React, { createContext, useContext, useState, ReactNode } from 'react';
import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import Dashboard from './pages/Dashboard';
import Portfolio from './pages/Portfolio';
import Admin from './pages/Admin';
import Replay from './pages/Replay';
import Sidebar from './components/Sidebar';

import Login from './pages/Login';

/* ── WebSocket Context ── */
export interface MarketContextType {
  symbol: string;
  setSymbol: (s: string) => void;
}

export const MarketContext = createContext<MarketContextType>({
  symbol: 'AAPL',
  setSymbol: () => {},
});

export const useMarket = () => useContext(MarketContext);

/* ── Auth Context (lightweight) ── */
export interface AuthUser {
  id: string;
  email: string;
  username: string;
  is_admin: boolean;
  balance: number;
}

export interface AuthContextType {
  user: AuthUser | null;
  token: string | null;
  setAuth: (user: AuthUser, token: string) => void;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextType>({
  user: null,
  token: null,
  setAuth: () => {},
  logout: () => {},
});

export const useAuth = () => useContext(AuthContext);

function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => {
    try {
      const stored = localStorage.getItem('exchangex_user');
      return stored ? JSON.parse(stored) : null;
    } catch { return null; }
  });
  const [token, setToken] = useState<string | null>(
    () => localStorage.getItem('exchangex_token')
  );

  const setAuth = (u: AuthUser, t: string) => {
    setUser(u);
    setToken(t);
    localStorage.setItem('exchangex_user', JSON.stringify(u));
    localStorage.setItem('exchangex_token', t);
  };

  const logout = () => {
    setUser(null);
    setToken(null);
    localStorage.removeItem('exchangex_user');
    localStorage.removeItem('exchangex_token');
  };

  return (
    <AuthContext.Provider value={{ user, token, setAuth, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

/* ── Main Layout ── */
function AppLayout() {
  const { token } = useAuth();
  const [wsConnected, setWsConnected] = React.useState(false);

  if (!token) {
    return <Login />;
  }

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <Sidebar connected={wsConnected} />
      <main style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard onConnectionChange={setWsConnected} />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="/replay" element={<Replay />} />
        </Routes>
      </main>
    </div>
  );
}

/* ── Root App ── */
export default function App() {
  const [symbol, setSymbol] = useState('AAPL');

  return (
    <AuthProvider>
      <MarketContext.Provider value={{ symbol, setSymbol }}>
        <BrowserRouter>
          <AppLayout />
          <Toaster 
            position="top-right" 
            toastOptions={{ 
              duration: 4000, 
              style: { 
                background: '#15120e', 
                color: '#f5f6fa', 
                border: '1px solid rgba(243, 156, 18, 0.15)' 
              } 
            }} 
          />
        </BrowserRouter>
      </MarketContext.Provider>
    </AuthProvider>
  );
}
