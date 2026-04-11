/**
 * TrustBond API client – uses fetch with base URL and optional Bearer token.
 *
 * Token storage:
 * - "Remember me" → localStorage + short-lived first-party cookie (mirror), Max-Age aligned to JWT exp.
 * - No remember → sessionStorage only (tab/window session); localStorage + auth cookie cleared.
 *
 * Note: API still uses Authorization: Bearer (not HttpOnly cookies). Cookie is only for reload fallback
 * on the same origin when localStorage is cleared by extensions; primary store remains localStorage.
 */
const BASE =
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE_URL) ||
  "https://trustbondmobileapp.onrender.com";

const TOKEN_KEY = "tb_token";
/** Cookie name must match Path=/ for SPA */
const AUTH_COOKIE_NAME = "tb_token";

/** Seconds until JWT exp, or fallback (8h — keep in sync with backend ACCESS_TOKEN_EXPIRE_MINUTES). */
function jwtMaxAgeSeconds(token) {
  if (!token || typeof token !== "string") return 8 * 3600;
  try {
    const parts = token.split(".");
    if (parts.length < 2) return 8 * 3600;
    const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const pad = b64.length % 4 ? "=".repeat(4 - (b64.length % 4)) : "";
    const payload = JSON.parse(atob(b64 + pad));
    if (payload && typeof payload.exp === "number") {
      const left = payload.exp - Math.floor(Date.now() / 1000);
      return Math.min(Math.max(left, 60), 365 * 24 * 3600);
    }
  } catch {
    /* ignore */
  }
  return 8 * 3600;
}

function setAuthCookie(token) {
  if (typeof document === "undefined") return;
  const maxAge = jwtMaxAgeSeconds(token);
  const enc = encodeURIComponent(token);
  let c = `${AUTH_COOKIE_NAME}=${enc}; Path=/; SameSite=Lax; Max-Age=${maxAge}`;
  if (typeof location !== "undefined" && location.protocol === "https:")
    c += "; Secure";
  document.cookie = c;
}

function clearAuthCookie() {
  if (typeof document === "undefined") return;
  let c = `${AUTH_COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax`;
  document.cookie = c;
  if (typeof location !== "undefined" && location.protocol === "https:") {
    document.cookie = `${AUTH_COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax; Secure`;
  }
}

function getAuthCookie() {
  if (typeof document === "undefined" || !document.cookie) return null;
  const prefix = `${AUTH_COOKIE_NAME}=`;
  const chunks = document.cookie.split(";");
  for (const raw of chunks) {
    const p = raw.trim();
    if (p.startsWith(prefix)) {
      try {
        return decodeURIComponent(p.slice(prefix.length));
      } catch {
        return null;
      }
    }
  }
  return null;
}

export function getToken() {
  if (typeof window === "undefined") return null;
  // Session login (this tab): wins over leftover localStorage from an old "remember" session.
  const sessionTok = sessionStorage.getItem(TOKEN_KEY);
  if (sessionTok) return sessionTok;

  const localTok = localStorage.getItem(TOKEN_KEY);
  if (localTok) return localTok;

  // Fallback if localStorage was blocked/cleared but cookie remains (remember-me only).
  const cookieTok = getAuthCookie();
  if (cookieTok) {
    try {
      localStorage.setItem(TOKEN_KEY, cookieTok);
    } catch {
      /* quota / private mode */
    }
    return cookieTok;
  }

  return null;
}

export function setToken(token, { remember = true } = {}) {
  if (typeof window === "undefined") return;

  clearAuthCookie();
  try {
    sessionStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }

  if (!token) {
    return;
  }

  if (remember) {
    try {
      localStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* if localStorage fails, still try cookie */
    }
    setAuthCookie(token);
  } else {
    try {
      sessionStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* rare: sessionStorage full */
    }
  }
}

async function request(method, path, body = null, { token = getToken() } = {}) {
  const url = path.startsWith("http")
    ? path
    : `${BASE}${path.startsWith("/") ? "" : "/"}${path}`;
  const opts = {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  };
  if (body && method !== "GET") opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    // Handle auth expiry: force logout on 401 so user is prompted to log in again
    if (res.status === 401) {
      setToken(null);
      // Optional: simple reload to show login screen
      if (typeof window !== "undefined") {
        window.alert(data?.detail || "Session expired. Please log in again.");
        window.location.reload();
      }
    }
    const err = new Error(data?.detail || res.statusText || "Request failed");
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export const api = {
  get: (path, opts) => request("GET", path, null, opts),
  post: (path, body, opts) => request("POST", path, body, opts),
  put: (path, body, opts) => request("PUT", path, body, opts),
  patch: (path, body, opts) => request("PATCH", path, body, opts),
  delete: (path, opts) => request("DELETE", path, null, opts),
};

export default api;
