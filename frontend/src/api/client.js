/**
 * TrustBond API client – uses fetch with base URL and optional Bearer token.
 */
const BASE = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE_URL) || 'http://localhost:8000';

export function getToken() {
  if (typeof window === 'undefined') return null;
  return (
    sessionStorage.getItem('tb_token') ||
    localStorage.getItem('tb_token')
  );
}

export function setToken(token, { remember = true } = {}) {
  if (typeof window === 'undefined') return;
  if (!token) {
    sessionStorage.removeItem('tb_token');
    localStorage.removeItem('tb_token');
    return;
  }
  // Clear both and set according to remember flag
  sessionStorage.removeItem('tb_token');
  localStorage.removeItem('tb_token');
  if (remember) {
    localStorage.setItem('tb_token', token);
  } else {
    sessionStorage.setItem('tb_token', token);
  }
}

async function request(method, path, body = null, { token = getToken() } = {}) {
  const url = path.startsWith('http') ? path : `${BASE}${path.startsWith('/') ? '' : '/'}${path}`;
  const opts = {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  };
  if (body && method !== 'GET') opts.body = JSON.stringify(body);
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
      if (typeof window !== 'undefined') {
        window.alert(data?.detail || 'Session expired. Please log in again.');
        window.location.reload();
      }
    }
    const err = new Error(data?.detail || res.statusText || 'Request failed');
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export const api = {
  get: (path, opts) => request('GET', path, null, opts),
  post: (path, body, opts) => request('POST', path, body, opts),
  put: (path, body, opts) => request('PUT', path, body, opts),
  patch: (path, body, opts) => request('PATCH', path, body, opts),
  delete: (path, opts) => request('DELETE', path, null, opts),
};

export default api;
