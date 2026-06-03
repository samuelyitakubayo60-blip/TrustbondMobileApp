import React, { useEffect, useState } from 'react';
import api, { getToken } from '../../api/client';

/* ── inline SVG icons ──────────────────────────────────────────────── */
const IconEye = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>
  </svg>
);
const IconEyeOff = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/>
  </svg>
);
const IconCheck = ({ size = 12 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12"/>
  </svg>
);
const IconShield = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
  </svg>
);
const IconMail = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/>
  </svg>
);
const IconUser = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/>
  </svg>
);

/* ── password strength ──────────────────────────────────────────────── */
const LEVELS = [
  { label: '',       color: 'var(--border)' },
  { label: 'Weak',   color: 'var(--danger)' },
  { label: 'Fair',   color: 'var(--warning)' },
  { label: 'Good',   color: 'var(--accent)' },
  { label: 'Strong', color: 'var(--success)' },
];

function calcStrength(v) {
  if (!v) return { score: 0, len: false, upper: false, num: false, special: false };
  const len     = v.length >= 8;
  const upper   = /[A-Z]/.test(v);
  const num     = /[0-9]/.test(v);
  const special = /[^A-Za-z0-9]/.test(v);
  return { score: [len, upper, num, special].filter(Boolean).length, len, upper, num, special };
}

/* ── sub-components ────────────────────────────────────────────────── */
function PasswordInput({ value, onChange, placeholder, name, autoComplete }) {
  const [show, setShow] = useState(false);
  return (
    <div style={{ position: 'relative' }}>
      <input
        className="input"
        type={show ? 'text' : 'password'}
        name={name}
        autoComplete={autoComplete}
        placeholder={placeholder}
        value={value}
        onChange={onChange}
        style={{ paddingRight: 38 }}
      />
      <button
        type="button"
        tabIndex={-1}
        aria-label={show ? 'Hide password' : 'Show password'}
        onClick={() => setShow(s => !s)}
        style={{
          position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)',
          background: 'none', border: 'none', cursor: 'pointer',
          color: 'var(--muted)', display: 'flex', padding: 4,
        }}
      >
        {show ? <IconEyeOff /> : <IconEye />}
      </button>
    </div>
  );
}

function StrengthBar({ score }) {
  const level = LEVELS[score] || LEVELS[0];
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: 'flex', gap: 4 }}>
        {[1, 2, 3, 4].map(i => (
          <div key={i} style={{
            flex: 1, height: 3, borderRadius: 3,
            background: i <= score ? level.color : 'var(--surface3)',
            transition: 'background 0.2s',
          }} />
        ))}
      </div>
      {score > 0 && (
        <div style={{ textAlign: 'right', fontSize: 11, color: level.color, marginTop: 3, fontWeight: 600 }}>
          {level.label}
        </div>
      )}
    </div>
  );
}

function Req({ met, typing, label }) {
  const color = !typing ? 'var(--muted)' : met ? 'var(--success)' : 'var(--text-dim)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color, padding: '3px 0' }}>
      <span style={{
        width: 16, height: 16, borderRadius: 8, flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: typing && met ? 'rgba(52,211,153,.12)' : 'var(--surface2)',
        border: `1px solid ${typing && met ? 'rgba(52,211,153,.3)' : 'var(--border)'}`,
      }}>
        {typing && met
          ? <IconCheck size={9} />
          : <span style={{ width: 4, height: 4, borderRadius: '50%', background: 'var(--border)', display: 'block' }} />
        }
      </span>
      {label}
    </div>
  );
}

function SessionRow({ label, value }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '8px 0', borderBottom: '1px solid var(--border)', fontSize: 12,
    }}>
      <span style={{ color: 'var(--text-dim)' }}>{label}</span>
      <span style={{ color: 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>{value || '—'}</span>
    </div>
  );
}

/* ── main component ────────────────────────────────────────────────── */
const AccountSettings = () => {
  const [current, setCurrent] = useState('');
  const [nextPwd, setNextPwd] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error,   setError]   = useState('');
  const [ok,      setOk]      = useState('');
  const [loading, setLoading] = useState(false);
  const [revoking, setRevoking] = useState(false);

  // 2FA state
  const [mfaEnabled, setMfaEnabled] = useState(false);
  const [mfaStep, setMfaStep] = useState('idle'); // idle | sending | code_sent | verifying | disabling
  const [mfaCode, setMfaCode] = useState('');
  const [mfaMsg, setMfaMsg] = useState('');
  const [mfaError, setMfaError] = useState('');
  const [disablePassword, setDisablePassword] = useState('');

  // Profile info
  const [profile, setProfile] = useState(null);

  const strength     = calcStrength(nextPwd);
  const typing       = nextPwd.length > 0;
  const confirmMatch = confirm.length > 0 && confirm === nextPwd;
  const confirmMiss  = confirm.length > 0 && confirm !== nextPwd;

  const [sessionInfo, setSessionInfo] = useState({
    lastLogin: null,
    lastPasswordChange: null,
    jwtExpires: null,
  });

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setOk('');
    if (!current)           { setError('Enter your current password.'); return; }
    if (nextPwd !== confirm) { setError('New passwords do not match.'); return; }
    if (strength.score < 1) { setError('Choose a stronger password.'); return; }
    setLoading(true);
    try {
      await api.post('/api/v1/auth/change-password', {
        current_password: current,
        new_password: nextPwd,
      });
      setOk('Password updated successfully.');
      setCurrent('');
      setNextPwd('');
      setConfirm('');
      // Refresh session info
      loadProfile();
    } catch (err) {
      setError(err?.data?.detail || err?.message || 'Failed to update password.');
    } finally {
      setLoading(false);
    }
  };

  const loadProfile = async () => {
    try {
      const me = await api.get('/api/v1/auth/me');
      setProfile(me);
      setMfaEnabled(!!me.mfa_enabled);
      const token = getToken();
      let jwtExpires = null;
      if (token) {
        try {
          const [, payload] = token.split('.');
          const decoded = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
          if (decoded.exp) jwtExpires = new Date(decoded.exp * 1000).toLocaleString();
        } catch { /* ignore */ }
      }
      setSessionInfo({
        lastLogin: me.last_login_at ? new Date(me.last_login_at).toLocaleString() : null,
        lastPasswordChange: me.last_password_change ? new Date(me.last_password_change).toLocaleString() : null,
        jwtExpires,
      });
    } catch { /* ignore */ }
  };

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (cancelled) return;
      await loadProfile();
    };
    load();
    return () => { cancelled = true; };
  }, []);

  // 2FA handlers
  const handleEnable2FA = async () => {
    setMfaStep('sending');
    setMfaError('');
    setMfaMsg('');
    setMfaCode('');
    try {
      const res = await api.post('/api/v1/auth/enable-2fa', {});
      setMfaMsg(res.message || 'Verification code sent to your email.');
      setMfaStep('code_sent');
    } catch (err) {
      setMfaError(err?.data?.detail || err?.message || 'Failed to send verification code.');
      setMfaStep('idle');
    }
  };

  const handleVerify2FA = async () => {
    if (!mfaCode.trim()) { setMfaError('Enter the verification code.'); return; }
    setMfaStep('verifying');
    setMfaError('');
    try {
      const token = getToken();
      await api.post('/api/v1/auth/confirm-enable-2fa', {
        mfa_token: token,
        code: mfaCode.trim(),
      });
      setMfaEnabled(true);
      setMfaStep('idle');
      setMfaMsg('Two-factor authentication has been enabled successfully.');
      setMfaCode('');
    } catch (err) {
      setMfaError(err?.data?.detail || err?.message || 'Invalid verification code.');
      setMfaStep('code_sent');
    }
  };

  const handleDisable2FA = async () => {
    if (!disablePassword) { setMfaError('Enter your password to disable 2FA.'); return; }
    setMfaStep('disabling');
    setMfaError('');
    try {
      await api.post('/api/v1/auth/disable-2fa', {
        current_password: disablePassword,
        new_password: 'unused',
      });
      setMfaEnabled(false);
      setMfaStep('idle');
      setMfaMsg('Two-factor authentication has been disabled.');
      setDisablePassword('');
    } catch (err) {
      setMfaError(err?.data?.detail || err?.message || 'Failed to disable 2FA.');
      setMfaStep('idle');
    }
  };

  const maskedEmail = profile?.email
    ? profile.email.replace(/^(.{2})(.*)(@.*)$/, (_, a, b, c) => a + '*'.repeat(Math.min(b.length, 6)) + c)
    : '—';

  // Auto-dismiss success messages after 5 seconds
  useEffect(() => {
    if (!ok) return;
    const t = setTimeout(() => setOk(''), 5000);
    return () => clearTimeout(t);
  }, [ok]);

  useEffect(() => {
    if (!mfaMsg) return;
    const t = setTimeout(() => setMfaMsg(''), 6000);
    return () => clearTimeout(t);
  }, [mfaMsg]);

  const canSubmitPwd = current && nextPwd && confirm && confirmMatch && strength.score >= 2 && !loading;

  return (
    <>
      <div className="page-header">
        <h2>Account Settings</h2>
        <p>Manage your account security, password, and two-factor authentication.</p>
      </div>

      {/* ── Profile Overview ──────────────────────────────────────── */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-header">
          <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <IconUser /> Profile Information
          </div>
          <span style={{
            fontSize: 10, fontWeight: 700, padding: '3px 10px', borderRadius: 10,
            background: mfaEnabled ? 'rgba(52,211,153,.10)' : 'rgba(248,113,113,.06)',
            color: mfaEnabled ? 'var(--success)' : 'var(--muted)',
            border: `1px solid ${mfaEnabled ? 'rgba(52,211,153,.25)' : 'var(--border)'}`,
            transition: 'all 0.3s ease',
          }}>
            {mfaEnabled ? '2FA ACTIVE' : '2FA OFF'}
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16 }}>
          {[
            { label: 'Full Name', value: profile ? `${profile.first_name} ${profile.last_name}` : '—', bold: true },
            { label: 'Email', value: profile?.email || '—' },
            { label: 'Role', value: profile?.role || '—', capitalize: true },
            { label: 'Rank', value: profile?.rank || '—' },
            { label: 'Badge Number', value: profile?.badge_number || '—' },
          ].map(({ label, value, bold, capitalize }) => (
            <div key={label}>
              <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--muted)', marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 14, fontWeight: bold ? 600 : 400, color: 'var(--text)', textTransform: capitalize ? 'capitalize' : 'none' }}>{value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Password + 2FA side by side ───────────────────────────── */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))',
        gap: 14,
        marginBottom: 14,
      }}>

        {/* ── Update password ─────────────────────────────────────── */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
          <div className="card-header">
            <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
              </svg>
              Update Password
            </div>
            {sessionInfo.lastPasswordChange && (
              <span style={{ fontSize: 10, color: 'var(--muted)' }}>
                Last changed: {sessionInfo.lastPasswordChange}
              </span>
            )}
          </div>

          <form onSubmit={handleSubmit} autoComplete="off" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
            <div className="input-group">
              <div className="input-label">Current Password *</div>
              <PasswordInput
                name="current-password"
                autoComplete="current-password"
                placeholder="Enter current password"
                value={current}
                onChange={e => { setCurrent(e.target.value); setError(''); }}
              />
            </div>

            <div className="input-group">
              <div className="input-label">New Password *</div>
              <PasswordInput
                name="new-password"
                autoComplete="new-password"
                placeholder="Min 8 chars, uppercase, number, symbol"
                value={nextPwd}
                onChange={e => { setNextPwd(e.target.value); setError(''); }}
              />
              <StrengthBar score={strength.score} />

              {/* Inline requirements — compact row */}
              <div style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 12px', marginTop: 8,
              }}>
                <Req met={strength.len}     typing={typing} label="8+ characters" />
                <Req met={strength.upper}   typing={typing} label="Uppercase letter" />
                <Req met={strength.num}     typing={typing} label="Number" />
                <Req met={strength.special} typing={typing} label="Special char" />
              </div>
            </div>

            <div className="input-group">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                <div className="input-label" style={{ margin: 0 }}>Confirm New Password *</div>
                {confirmMatch && (
                  <span style={{
                    fontSize: 11, color: 'var(--success)', fontWeight: 600,
                    display: 'flex', alignItems: 'center', gap: 4,
                    animation: 'fadeIn 0.2s ease',
                  }}>
                    <IconCheck size={11} /> Matches
                  </span>
                )}
                {confirmMiss && (
                  <span style={{
                    fontSize: 11, color: 'var(--danger)', fontWeight: 600,
                    animation: 'fadeIn 0.2s ease',
                  }}>
                    No match
                  </span>
                )}
              </div>
              <PasswordInput
                name="confirm-password"
                autoComplete="new-password"
                placeholder="Re-enter new password"
                value={confirm}
                onChange={e => { setConfirm(e.target.value); setError(''); }}
              />
            </div>

            {error && (
              <div style={{
                padding: '9px 12px', borderRadius: 8, fontSize: 12,
                background: 'rgba(248,113,113,.07)',
                border: '1px solid rgba(248,113,113,.22)',
                color: 'var(--danger)', marginTop: 4,
                animation: 'fadeIn 0.25s ease',
              }}>
                {error}
              </div>
            )}
            {ok && (
              <div style={{
                padding: '9px 12px', borderRadius: 8, fontSize: 12,
                background: 'rgba(52,211,153,.07)',
                border: '1px solid rgba(52,211,153,.22)',
                color: 'var(--success)', marginTop: 4,
                display: 'flex', alignItems: 'center', gap: 8,
                animation: 'fadeIn 0.25s ease',
              }}>
                <IconCheck size={14} /> {ok}
              </div>
            )}

            <div style={{ flex: 1 }} />
            <button
              className="btn btn-primary btn-full"
              style={{
                marginTop: 14,
                opacity: canSubmitPwd ? 1 : 0.55,
                transition: 'opacity 0.2s, transform 0.1s',
              }}
              disabled={!canSubmitPwd}
            >
              {loading ? 'Updating…' : 'Update Password'}
            </button>
          </form>
        </div>

        {/* ── Two-Factor Authentication ──────────────────────────── */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
          <div className="card-header">
            <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <IconShield /> Two-Factor Authentication
            </div>
            <span style={{
              fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 10,
              background: mfaEnabled ? 'rgba(52,211,153,.12)' : 'rgba(248,113,113,.07)',
              color: mfaEnabled ? 'var(--success)' : 'var(--muted)',
              border: `1px solid ${mfaEnabled ? 'rgba(52,211,153,.3)' : 'var(--border)'}`,
              transition: 'all 0.3s ease',
            }}>
              {mfaEnabled ? 'ENABLED' : 'DISABLED'}
            </span>
          </div>

          <p style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.6, margin: '0 0 16px' }}>
            Add an extra layer of security to your account. When enabled, you will receive a
            verification code via email each time you log in.
          </p>

          {/* How it works — visual steps */}
          {!mfaEnabled && mfaStep === 'idle' && (
            <div style={{
              background: 'var(--surface2)', borderRadius: 10, padding: '14px 16px',
              marginBottom: 16, border: '1px solid var(--border)',
            }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-dim)', marginBottom: 10 }}>How it works</div>
              {[
                { step: '1', text: 'Click enable below to receive a verification code' },
                { step: '2', text: 'Enter the 6-digit code from your email' },
                { step: '3', text: 'Future logins will require email verification' },
              ].map(({ step, text }) => (
                <div key={step} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 0' }}>
                  <span style={{
                    width: 22, height: 22, borderRadius: '50%', flexShrink: 0,
                    background: 'rgba(59,130,246,.08)', border: '1px solid rgba(59,130,246,.2)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 11, fontWeight: 700, color: 'var(--accent)',
                  }}>{step}</span>
                  <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>{text}</span>
                </div>
              ))}
            </div>
          )}

          {mfaMsg && (
            <div style={{
              padding: '10px 14px', borderRadius: 8, fontSize: 12, marginBottom: 12,
              background: 'rgba(52,211,153,.07)',
              border: '1px solid rgba(52,211,153,.22)',
              color: 'var(--success)',
              display: 'flex', alignItems: 'center', gap: 8,
              animation: 'fadeIn 0.25s ease',
            }}>
              <IconCheck size={14} /> {mfaMsg}
            </div>
          )}
          {mfaError && (
            <div style={{
              padding: '10px 14px', borderRadius: 8, fontSize: 12, marginBottom: 12,
              background: 'rgba(248,113,113,.07)',
              border: '1px solid rgba(248,113,113,.22)',
              color: 'var(--danger)',
              animation: 'fadeIn 0.25s ease',
            }}>
              {mfaError}
            </div>
          )}

          <div style={{ flex: 1 }} />

          {!mfaEnabled ? (
            // ENABLE 2FA flow
            <>
              {mfaStep === 'idle' && (
                <div>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px',
                    background: 'var(--surface2)', borderRadius: 8, marginBottom: 14,
                  }}>
                    <IconMail />
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>Email Verification</div>
                      <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                        A 6-digit code will be sent to {maskedEmail}
                      </div>
                    </div>
                  </div>
                  <button
                    className="btn btn-primary btn-full"
                    onClick={handleEnable2FA}
                  >
                    Enable Two-Factor Authentication
                  </button>
                </div>
              )}
              {mfaStep === 'sending' && (
                <div style={{
                  textAlign: 'center', padding: 20, color: 'var(--muted)', fontSize: 13,
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10,
                }}>
                  <div className="acct-spinner" />
                  Sending verification code...
                </div>
              )}
              {(mfaStep === 'code_sent' || mfaStep === 'verifying') && (
                <div style={{ animation: 'fadeIn 0.3s ease' }}>
                  <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 8 }}>
                    Enter the 6-digit code sent to your email:
                  </div>
                  <input
                    className="input"
                    type="text"
                    maxLength={6}
                    placeholder="000000"
                    value={mfaCode}
                    onChange={e => { setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6)); setMfaError(''); }}
                    style={{
                      textAlign: 'center', fontSize: 24, letterSpacing: 8,
                      fontFamily: 'Consolas, monospace', fontWeight: 700, marginBottom: 12,
                    }}
                    autoFocus
                  />
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      className="btn btn-outline btn-full"
                      onClick={() => { setMfaStep('idle'); setMfaCode(''); setMfaError(''); setMfaMsg(''); }}
                      disabled={mfaStep === 'verifying'}
                    >
                      Cancel
                    </button>
                    <button
                      className="btn btn-primary btn-full"
                      onClick={handleVerify2FA}
                      disabled={mfaStep === 'verifying' || mfaCode.length < 6}
                      style={{
                        opacity: mfaCode.length < 6 ? 0.55 : 1,
                        transition: 'opacity 0.2s',
                      }}
                    >
                      {mfaStep === 'verifying' ? 'Verifying…' : 'Verify & Enable'}
                    </button>
                  </div>
                  <div style={{ textAlign: 'center', marginTop: 10 }}>
                    <button
                      type="button"
                      onClick={handleEnable2FA}
                      disabled={mfaStep === 'verifying'}
                      style={{
                        border: 'none', background: 'none', color: 'var(--accent)',
                        fontSize: 11, cursor: 'pointer', padding: 0,
                        textDecoration: 'underline', textUnderlineOffset: 2,
                      }}
                    >
                      Resend code
                    </button>
                    <span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 8 }}>
                      Expires in 10 min
                    </span>
                  </div>
                </div>
              )}
            </>
          ) : (
            // DISABLE 2FA flow
            <div>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px',
                background: 'rgba(52,211,153,.06)', borderRadius: 8, marginBottom: 14,
                border: '1px solid rgba(52,211,153,.15)',
              }}>
                <IconCheck size={16} />
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--success)' }}>2FA is active</div>
                  <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                    Verification codes are sent to {maskedEmail} on each login.
                  </div>
                </div>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 8 }}>
                Enter your password to disable two-factor authentication:
              </div>
              <PasswordInput
                name="disable-2fa-password"
                autoComplete="current-password"
                placeholder="Current password"
                value={disablePassword}
                onChange={e => { setDisablePassword(e.target.value); setMfaError(''); }}
              />
              <button
                className="btn btn-danger btn-full"
                style={{
                  marginTop: 12, fontSize: 12,
                  opacity: !disablePassword ? 0.55 : 1,
                  transition: 'opacity 0.2s',
                }}
                onClick={handleDisable2FA}
                disabled={mfaStep === 'disabling' || !disablePassword}
              >
                {mfaStep === 'disabling' ? 'Disabling…' : 'Disable Two-Factor Authentication'}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── Session & Security (full-width below) ─────────────────── */}
      <div className="card" style={{ marginBottom: 14 }}>
        <div className="card-header">
          <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
            </svg>
            Session & Security
          </div>
        </div>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '0 24px',
        }}>
          <SessionRow label="Last login"            value={sessionInfo.lastLogin} />
          <SessionRow label="Last password change"  value={sessionInfo.lastPasswordChange} />
          <SessionRow label="Session token expires" value={sessionInfo.jwtExpires} />
          <SessionRow label="Two-factor auth"       value={mfaEnabled ? 'Enabled (Email)' : 'Disabled'} />
        </div>
        <div style={{ marginTop: 14, display: 'flex', justifyContent: 'flex-end' }}>
          <button
            type="button"
            className="btn btn-danger"
            style={{ fontSize: 12, minWidth: 220 }}
            disabled={revoking}
            onClick={async () => {
              if (!window.confirm('This will sign out all other active sessions. Continue?')) return;
              setRevoking(true);
              try {
                await api.post('/api/v1/auth/revoke-other-sessions', {});
                window.alert('All other sessions have been signed out.');
              } catch (e) {
                window.alert(e?.message || 'Failed to revoke other sessions.');
              } finally {
                setRevoking(false);
              }
            }}
          >
            {revoking ? 'Revoking…' : 'Sign out all other sessions'}
          </button>
        </div>
      </div>
    </>
  );
};

export default AccountSettings;
