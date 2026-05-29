import React, { useEffect, useState } from 'react';
import api, { getToken } from '../../api/client';

/* ── inline SVG icons (no dependency) ──────────────────────────────────── */
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

/* ── password strength ──────────────────────────────────────────────────── */
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

/* ── sub-components ─────────────────────────────────────────────────────── */
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

/* ── main component ─────────────────────────────────────────────────────── */
const ChangePassword = () => {
  const [current, setCurrent] = useState('');
  const [nextPwd, setNextPwd] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error,   setError]   = useState('');
  const [ok,      setOk]      = useState('');
  const [loading, setLoading] = useState(false);
  const [revoking, setRevoking] = useState(false);

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
    } catch (err) {
      setError(err?.data?.detail || err?.message || 'Failed to update password.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const loadMe = async () => {
      try {
        const me = await api.get('/api/v1/auth/me');
        if (cancelled) return;
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
    loadMe();
    return () => { cancelled = true; };
  }, []);

  return (
    <>
      <div className="page-header">
        <h2>Change Password</h2>
        <p>Update your account credentials. Only you can change your password.</p>
      </div>

      <div className="g2-fixed">

        {/* ── Update password ─────────────────────────────────────── */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">Update Password</div>
          </div>

          <form onSubmit={handleSubmit} autoComplete="off">
            <div className="input-group">
              <div className="input-label">Current Password *</div>
              <PasswordInput
                name="current-password"
                autoComplete="current-password"
                placeholder="Enter current password"
                value={current}
                onChange={e => setCurrent(e.target.value)}
              />
            </div>

            <div className="input-group">
              <div className="input-label">New Password *</div>
              <PasswordInput
                name="new-password"
                autoComplete="new-password"
                placeholder="Min 8 chars, uppercase, number, symbol"
                value={nextPwd}
                onChange={e => setNextPwd(e.target.value)}
              />
              <StrengthBar score={strength.score} />
            </div>

            <div className="input-group">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                <div className="input-label" style={{ margin: 0 }}>Confirm New Password *</div>
                {confirmMatch && (
                  <span style={{ fontSize: 11, color: 'var(--success)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4 }}>
                    <IconCheck size={11} /> Matches
                  </span>
                )}
                {confirmMiss && (
                  <span style={{ fontSize: 11, color: 'var(--danger)', fontWeight: 600 }}>
                    No match
                  </span>
                )}
              </div>
              <PasswordInput
                name="confirm-password"
                autoComplete="new-password"
                placeholder="Re-enter new password"
                value={confirm}
                onChange={e => setConfirm(e.target.value)}
              />
            </div>

            {error && (
              <div style={{
                padding: '9px 12px', borderRadius: 8, fontSize: 12,
                background: 'rgba(248,113,113,.07)',
                border: '1px solid rgba(248,113,113,.22)',
                color: 'var(--danger)', marginTop: 4,
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
              }}>
                {ok}
              </div>
            )}

            <button
              className="btn btn-primary btn-full"
              style={{ marginTop: 14 }}
              disabled={loading}
            >
              {loading ? 'Updating…' : 'Update Password'}
            </button>
          </form>
        </div>

        {/* ── Requirements ────────────────────────────────────────── */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">Password Requirements</div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Req met={strength.len}     typing={typing} label="At least 8 characters" />
            <Req met={strength.upper}   typing={typing} label="One uppercase letter" />
            <Req met={strength.num}     typing={typing} label="One number" />
            <Req met={strength.special} typing={typing} label="One special character" />
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              fontSize: 12, color: 'var(--muted)',
              borderTop: '1px solid var(--border)', marginTop: 6, paddingTop: 8,
            }}>
              <span style={{
                width: 16, height: 16, borderRadius: 8,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: 'var(--surface2)', border: '1px solid var(--border)', flexShrink: 0,
                fontSize: 10,
              }}>≠</span>
              Not same as last 3 passwords
            </div>
          </div>
        </div>

        {/* ── Session info ─────────────────────────────────────────── */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">Session Info</div>
          </div>
          <div>
            <SessionRow label="Last login"            value={sessionInfo.lastLogin} />
            <SessionRow label="Last password change"  value={sessionInfo.lastPasswordChange} />
            <SessionRow label="Session token expires" value={sessionInfo.jwtExpires} />
          </div>
          <button
            type="button"
            className="btn btn-danger btn-full"
            style={{ marginTop: 12, fontSize: 12 }}
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

export default ChangePassword;
