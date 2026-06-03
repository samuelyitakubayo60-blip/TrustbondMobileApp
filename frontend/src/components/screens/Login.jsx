import React, { useState, useRef, useEffect } from 'react';
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
  const { login, verifyMfa } = useAuth();
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

  // MFA state
  const [mfaToken, setMfaToken] = useState(null);
  const [mfaCode, setMfaCode] = useState('');

  // Transition state: 'login' | 'transitioning-out' | 'transitioning-in' | 'mfa'
  const [view, setView] = useState('login');
  const mfaInputRef = useRef(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password, rememberMe);
    } catch (err) {
      if (err.message === 'MFA_REQUIRED' && err.mfa_token) {
        setMfaToken(err.mfa_token);
        // Start the transition animation
        setView('transitioning-out');
      } else {
        setError(err?.data?.detail || err?.message || 'Login failed');
      }
    } finally {
      setLoading(false);
    }
  };

  // Handle the transition sequence
  useEffect(() => {
    if (view === 'transitioning-out') {
      const t = setTimeout(() => setView('transitioning-in'), 400);
      return () => clearTimeout(t);
    }
    if (view === 'transitioning-in') {
      const t = setTimeout(() => {
        setView('mfa');
        // Focus the MFA input after transition completes
        setTimeout(() => mfaInputRef.current?.focus(), 50);
      }, 400);
      return () => clearTimeout(t);
    }
  }, [view]);

  const handleMfaSubmit = async (e) => {
    e.preventDefault();
    if (!mfaCode.trim()) { setError('Enter the verification code.'); return; }
    setError('');
    setLoading(true);
    try {
      await verifyMfa(mfaToken, mfaCode.trim(), rememberMe);
    } catch (err) {
      setError(err?.data?.detail || err?.message || 'Invalid verification code');
    } finally {
      setLoading(false);
    }
  };

  const handleBackToLogin = () => {
    setView('transitioning-out');
    setTimeout(() => {
      setMfaToken(null);
      setMfaCode('');
      setError('');
      setView('login');
    }, 400);
  };

  const maskedEmail = email
    ? email.replace(/^(.{2})(.*)(@.*)$/, (_, a, b, c) => a + '*'.repeat(Math.min(b.length, 6)) + c)
    : '';

  const showMfa = view === 'mfa' || view === 'transitioning-in';

  // Determine animation class for the form card
  const getFormAnimClass = () => {
    if (view === 'transitioning-out') return 'auth-form-exit';
    if (view === 'transitioning-in') return 'auth-form-enter';
    return '';
  };

  /* ── Logo block (reused in both panels and form card) ─────────── */
  const LogoSmall = () => (
    <div className="auth-form-logo">
      <img src="/logo.jpeg" alt="TrustBond" className="auth-form-logo-img" />
      <div className="auth-form-logo-text">
        <span className="auth-form-logo-title">TrustBond</span>
        <span className="auth-form-logo-sub">Police Portal</span>
      </div>
    </div>
  );

  return (
    <div className="auth-shell">
      <div className="auth-split">
        {/* ── Brand panel (left side) ──────────────────────────────── */}
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

        {/* ── Form panel (right side) ──────────────────────────────── */}
        <div className="auth-panel auth-panel--form">
          <div className={`auth-card auth-card--form ${getFormAnimClass()}`}>

            {/* Logo at the top of every form card */}
            <LogoSmall />

            {!showMfa ? (
              /* ── Login form ──────────────────────────────────────── */
              <>
                <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 24, textAlign: 'center' }}>
                  Sign in to continue
                </p>
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
                    onChange={(e) => { setEmail(e.target.value); setError(''); }}
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
                      onChange={(e) => { setPassword(e.target.value); setError(''); }}
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
                  {error && (
                    <div className="auth-alert auth-alert--error">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
                      </svg>
                      {error}
                    </div>
                  )}
                  <button
                    type="submit"
                    disabled={loading}
                    className="auth-submit-btn"
                    style={{ opacity: loading ? 0.7 : 1 }}
                  >
                    {loading ? (
                      <span className="auth-btn-loading">
                        <span className="auth-btn-spinner" />
                        Signing in...
                      </span>
                    ) : 'Sign in'}
                  </button>
                </form>
              </>
            ) : (
              /* ── MFA verification form ──────────────────────────── */
              <>
                {/* Shield icon */}
                <div style={{ textAlign: 'center', marginBottom: 16 }}>
                  <div className="auth-mfa-shield">
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                    </svg>
                  </div>
                  <h3 style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', margin: '0 0 6px' }}>
                    Two-Factor Verification
                  </h3>
                  <p style={{ fontSize: 13, color: 'var(--muted)', margin: 0, lineHeight: 1.5 }}>
                    A 6-digit code has been sent to <strong style={{ color: 'var(--text-dim)' }}>{maskedEmail}</strong>.
                    Enter it below to complete sign-in.
                  </p>
                </div>

                <form onSubmit={handleMfaSubmit} autoComplete="off">
                  <label
                    htmlFor="mfa-code"
                    style={{ display: 'block', fontSize: 12, color: 'var(--text-dim)', marginBottom: 6 }}
                  >
                    Verification Code
                  </label>

                  {/* Individual digit boxes */}
                  <div className="auth-mfa-code-wrap">
                    <input
                      ref={mfaInputRef}
                      id="mfa-code"
                      type="text"
                      inputMode="numeric"
                      maxLength={6}
                      placeholder="------"
                      value={mfaCode}
                      onChange={(e) => { setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6)); setError(''); }}
                      className="auth-mfa-input"
                    />
                    {/* Visual digit cells overlay */}
                    <div className="auth-mfa-cells" aria-hidden="true">
                      {[0,1,2,3,4,5].map(i => (
                        <div key={i} className={`auth-mfa-cell ${mfaCode[i] ? 'filled' : ''} ${mfaCode.length === i ? 'active' : ''}`}>
                          {mfaCode[i] || ''}
                        </div>
                      ))}
                    </div>
                  </div>

                  {error && (
                    <div className="auth-alert auth-alert--error" style={{ marginTop: 12 }}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
                      </svg>
                      {error}
                    </div>
                  )}

                  <button
                    type="submit"
                    disabled={loading || mfaCode.length < 6}
                    className="auth-submit-btn"
                    style={{
                      marginTop: 16,
                      opacity: mfaCode.length < 6 ? 0.55 : 1,
                    }}
                  >
                    {loading ? (
                      <span className="auth-btn-loading">
                        <span className="auth-btn-spinner" />
                        Verifying...
                      </span>
                    ) : (
                      <>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 6 }}>
                          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                        </svg>
                        Verify & Sign In
                      </>
                    )}
                  </button>
                </form>

                {/* Footer links */}
                <div style={{ textAlign: 'center', marginTop: 18, display: 'flex', justifyContent: 'center', gap: 16, flexWrap: 'wrap' }}>
                  <button
                    type="button"
                    onClick={handleBackToLogin}
                    className="auth-mfa-link"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>
                    </svg>
                    Back to login
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      // Re-trigger MFA code send
                      setError('');
                      setLoading(true);
                      login(email, password, rememberMe)
                        .catch(err => {
                          if (err.message === 'MFA_REQUIRED' && err.mfa_token) {
                            setMfaToken(err.mfa_token);
                            setMfaCode('');
                          }
                        })
                        .finally(() => setLoading(false));
                    }}
                    disabled={loading}
                    className="auth-mfa-link"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/>
                    </svg>
                    Resend code
                  </button>
                </div>

                <div className="auth-mfa-hint">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
                  </svg>
                  Code expires in 10 minutes. Check your email inbox and spam folder.
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
