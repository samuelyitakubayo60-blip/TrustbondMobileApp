import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';

const LAST_EMAIL_KEY = 'tb_last_login_email';

function readSavedEmail() {
  if (typeof window === 'undefined') return '';
  try {
    return localStorage.getItem(LAST_EMAIL_KEY) || '';
  } catch {
    return '';
  }
}

export default function Login({ onForgotPassword }) {
  const { login } = useAuth();
  const [email, setEmail] = useState(readSavedEmail);
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(() => {
    if (typeof window === 'undefined') return true;
    try {
      return localStorage.getItem('tb_remember_preference') !== '0';
    } catch {
      return true;
    }
  });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password, rememberMe);
    } catch (err) {
      setError(err?.data?.detail || err?.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-split">
        <div className="auth-panel auth-panel--brand">
          <div className="auth-card auth-card--brand">
            <div className="auth-brand">
              <img
                className="auth-logo auth-logo--hero"
                src="/logo.jpeg"
                alt="TrustBond"
              />
              <div className="auth-brand-text">
                <div className="auth-brand-title">TrustBond</div>
                <div className="auth-brand-subtitle">Police Portal</div>
              </div>
            </div>
          </div>
        </div>
        <div className="auth-panel auth-panel--form">
          <div className="auth-card auth-card--form">
            <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 24 }}>Sign in to continue</p>
            <form onSubmit={handleSubmit} autoComplete="on">
              <label
                htmlFor="login-email"
                style={{ display: 'block', fontSize: 12, color: 'var(--text-dim)', marginBottom: 6 }}
              >
                Email
              </label>
              <input
                id="login-email"
                name="email"
                type="email"
                autoComplete="username"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="login-auth-input"
                style={{
                  width: '100%', padding: '10px 12px', marginBottom: 14, borderRadius: 8,
                  border: '1px solid var(--border)', background: 'var(--surface2)', color: 'var(--text)',
                  fontSize: 14,
                }}
              />
              <label
                htmlFor="login-password"
                style={{ display: 'block', fontSize: 12, color: 'var(--text-dim)', marginBottom: 6 }}
              >
                Password
              </label>
              <div style={{ position: 'relative', marginBottom: 12 }}>
                <input
                  id="login-password"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="login-auth-input"
                  style={{
                    width: '100%', padding: '10px 36px 10px 12px', borderRadius: 8,
                    border: '1px solid var(--border)', background: 'var(--surface2)', color: 'var(--text)',
                    fontSize: 14,
                  }}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((s) => !s)}
                  style={{
                    position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
                    border: 'none', background: 'transparent', color: 'var(--muted)',
                    fontSize: 11, cursor: 'pointer',
                  }}
                >
                  {showPassword ? 'Hide' : 'Show'}
                </button>
              </div>
              <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                marginBottom: 12, fontSize: 12, color: 'var(--muted)',
              }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={rememberMe}
                    onChange={(e) => setRememberMe(e.target.checked)}
                    style={{ margin: 0 }}
                  />
                  <span>Remember me on this device</span>
                </label>
                <button
                  type="button"
                  onClick={onForgotPassword}
                  style={{
                    border: 'none', background: 'transparent', color: 'var(--accent)',
                    fontSize: 12, cursor: 'pointer', padding: 0,
                  }}
                >
                  Forgot password?
                </button>
              </div>
              {error && <div style={{ color: 'var(--danger)', fontSize: 12, marginBottom: 12 }}>{error}</div>}
              <button
                type="submit"
                disabled={loading}
                style={{
                  width: '100%', padding: 12, borderRadius: 8, border: 'none',
                  background: 'var(--accent)', color: '#fff', fontWeight: 600, cursor: loading ? 'wait' : 'pointer',
                }}
              >
                {loading ? 'Signing in...' : 'Sign in'}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
