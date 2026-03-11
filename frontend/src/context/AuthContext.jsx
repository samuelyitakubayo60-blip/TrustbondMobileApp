import React, { createContext, useContext, useState, useEffect } from 'react';
import { api, getToken, setToken } from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setLoading(false);
      return;
    }
    api.get('/api/v1/auth/me').then((u) => {
      setUser(u);
      setLoading(false);
    }).catch(() => {
      setToken(null);
      setLoading(false);
    });
  }, []);

  const login = async (email, password, remember = true) => {
    const { access_token } = await api.post('/api/v1/auth/login', { email, password }, { token: null });
    setToken(access_token, { remember });
    const u = await api.get('/api/v1/auth/me');
    setUser(u);
    return u;
  };

  const logout = () => {
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, isAuthenticated: !!user }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
