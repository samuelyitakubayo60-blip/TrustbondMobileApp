import React, { createContext, useContext, useState, useEffect } from "react";
import { api, getToken, setToken } from "../api/client";

const AuthContext = createContext(null);

const LS_TOKEN_KEY = "tb_token";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(() => {
    const token = getToken();
    return !!token;
  });

  useEffect(() => {
    const token = getToken();
    if (!token) return;

    let active = true;
    let resolved = false;

    // Avoid a blank first paint while waiting on a cold backend.
    const loadingFallbackId = setTimeout(() => {
      if (!active || resolved) return;
      setLoading(false);
    }, 4000);

    api
      .get("/api/v1/auth/me")
      .then((u) => {
        if (!active) return;
        resolved = true;
        clearTimeout(loadingFallbackId);
        setUser(u);
        setLoading(false);
      })
      .catch(() => {
        if (!active) return;
        resolved = true;
        clearTimeout(loadingFallbackId);
        setToken(null);
        setLoading(false);
      });

    return () => {
      active = false;
      clearTimeout(loadingFallbackId);
    };
  }, []);

  // When another tab logs out (or clears persistent token), stay in sync.
  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const onStorage = (e) => {
      if (e.storageArea !== localStorage || e.key !== LS_TOKEN_KEY) return;
      if (e.newValue === null && e.oldValue) {
        setToken(null);
        setUser(null);
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const login = async (email, password, remember = true) => {
    const { access_token } = await api.post(
      "/api/v1/auth/login",
      { email, password },
      { token: null },
    );
    setToken(access_token, { remember });
    try {
      localStorage.setItem("tb_remember_preference", remember ? "1" : "0");
    } catch {
      /* ignore */
    }
    const u = await api.get("/api/v1/auth/me");
    setUser(u);
    try {
      const trimmed = (email || "").trim();
      if (trimmed) localStorage.setItem("tb_last_login_email", trimmed);
    } catch {
      /* ignore */
    }
    return u;
  };

  const logout = () => {
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{ user, loading, login, logout, isAuthenticated: !!user }}
    >
      {children}
    </AuthContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
