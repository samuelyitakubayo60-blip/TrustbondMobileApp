import { createContext, useContext, useState, useEffect } from 'react';
import { authService } from '../services/authService.js';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check if user is already logged in
    const token = authService.getToken();
    if (token) {
      authService
        .getMe()
        .then((userData) => {
          setUser(userData);
        })
        .catch(() => {
          authService.logout();
        })
        .finally(() => {
          setLoading(false);
        });
    } else {
      setLoading(false);
    }
  }, []);

  const login = async (email, password) => {
    await authService.login(email, password);
    const userData = await authService.getMe();
    setUser(userData);
    return userData;
  };

  const logout = () => {
    authService.logout();
    setUser(null);
  };

  const value = {
    user,
    loading,
    login,
    logout,
    isAuthenticated: !!user,
    isAdmin: user?.role === 'admin',
    isSupervisor: user?.role === 'supervisor',
    isOfficer: user?.role === 'officer',
    canManageUsers: user?.role === 'admin' || user?.role === 'supervisor',
    canAssignOrReview: user?.role === 'admin' || user?.role === 'supervisor',
    canSeeHotspots: user?.role === 'admin' || user?.role === 'supervisor',
    canSeeAudit: user?.role === 'admin',
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}
