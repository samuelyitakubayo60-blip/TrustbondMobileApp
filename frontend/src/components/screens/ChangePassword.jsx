import React, { useEffect, useState } from 'react';
import api, { getToken } from '../../api/client';

const ChangePassword = () => {
  const [passwordStrength, setPasswordStrength] = useState(0);
  const [strengthLabel, setStrengthLabel] = useState('—');
  const [strengthColor, setStrengthColor] = useState('#f87171');
  const [current, setCurrent] = useState('');
  const [nextPwd, setNextPwd] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [ok, setOk] = useState('');
  const [loading, setLoading] = useState(false);
  const [reqLen, setReqLen] = useState(false);
  const [reqUpper, setReqUpper] = useState(false);
  const [reqNumber, setReqNumber] = useState(false);
  const [reqSpecial, setReqSpecial] = useState(false);
  const [sessionInfo, setSessionInfo] = useState({
    lastLogin: null,
    lastPasswordChange: null,
    activeSessions: 1,
    jwtExpires: null,
  });

  const checkStrength = (value) => {
    let strength = 0;
    const hasLen = value.length >= 8;
    const hasUpper = /[A-Z]/.test(value);
    const hasNumber = /[0-9]/.test(value);
    const hasSpecial = /[^A-Za-z0-9]/.test(value);

    if (hasLen) strength++;
    if (hasUpper) strength++;
    if (hasNumber) strength++;
    if (hasSpecial) strength++;

    setReqLen(hasLen);
    setReqUpper(hasUpper);
    setReqNumber(hasNumber);
    setReqSpecial(hasSpecial);

    setPasswordStrength(strength);

    const cols = ['#f87171', '#f87171', '#fbbf24', '#38bdf8', '#34d399'];
    const labs = ['', 'Weak', 'Fair', 'Good', 'Strong'];

    setStrengthColor(cols[strength]);
    setStrengthLabel(labs[strength]);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setOk('');
    if (nextPwd !== confirm) {
      setError('New passwords do not match.');
      return;
    }
    setLoading(true);
    try {
      await api.post('/api/v1/auth/change-password', {
        current_password: current,
        new_password: nextPwd,
      });
      setOk('Password updated.');
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
            if (decoded.exp) {
              const date = new Date(decoded.exp * 1000);
              jwtExpires = date.toLocaleString();
            }
          } catch {
            jwtExpires = null;
          }
        }
        setSessionInfo({
          lastLogin: me.last_login_at ? new Date(me.last_login_at).toLocaleString() : null,
          lastPasswordChange: me.last_password_change ? new Date(me.last_password_change).toLocaleString() : null,
          activeSessions: 1,
          jwtExpires,
        });
      } catch {
        // ignore – leave defaults
      }
    };

    loadMe();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <div className="page-header">
        <h2>Change Password</h2>
        <p>Update your account credentials. Only you can change your password.</p>
      </div>

      <div className="g2-fixed">
        <div className="card">
          <div className="card-header">
            <div className="card-title">Update Password</div>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="input-group">
              <div className="input-label">Current Password *</div>
              <input
                className="input"
                type="password"
                placeholder="Enter current password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
              />
            </div>

            <div className="input-group">
              <div className="input-label">New Password *</div>
              <input
                className="input"
                type="password"
                placeholder="Min 8 chars, number + symbol"
                value={nextPwd}
                onChange={(e) => { setNextPwd(e.target.value); checkStrength(e.target.value); }}
              />
              <div style={{ marginTop: '5px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--muted)', marginBottom: '3px' }}>
                  <span>Strength</span>
                  <span id="strengthLabel" style={{ color: strengthColor }}>{strengthLabel}</span>
                </div>
                <div className="prog-bar">
                  <div
                    className="prog-fill"
                    style={{
                      width: `${[0, 25, 50, 75, 100][passwordStrength]}%`,
                      background: strengthColor,
                    }}
                  ></div>
                </div>
              </div>
            </div>

            <div className="input-group">
              <div className="input-label">Confirm New Password *</div>
              <input
                className="input"
                type="password"
                placeholder="Re-enter new password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </div>

            {error && (
              <div style={{ color: 'var(--danger)', fontSize: '12px', marginTop: '6px' }}>
                {error}
              </div>
            )}
            {ok && (
              <div style={{ color: 'var(--success)', fontSize: '12px', marginTop: '6px' }}>
                {ok}
              </div>
            )}

            <button className="btn btn-primary btn-full" style={{ marginTop: '6px' }} disabled={loading}>
              {loading ? 'Updating...' : 'Update Password'}
            </button>
          </form>
        </div>

        <div className="card">
          <div className="card-header">
            <div className="card-title">Password Requirements</div>
          </div>
          <div style={{ fontSize: '12px', lineHeight: 1.6 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ color: reqLen ? 'var(--success)' : 'var(--muted)' }}>●</span>
              <span>At least 8 characters</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ color: reqUpper ? 'var(--success)' : 'var(--muted)' }}>●</span>
              <span>One uppercase letter</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ color: reqNumber ? 'var(--success)' : 'var(--muted)' }}>●</span>
              <span>One number</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ color: reqSpecial ? 'var(--success)' : 'var(--muted)' }}>●</span>
              <span>One special character</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px' }}>
              <span style={{ color: 'var(--muted)' }}>○</span>
              <span>Not same as last 3 passwords</span>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <div className="card-title">Session Info</div>
          </div>
          <div style={{ fontSize: '12px', lineHeight: 1.8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Last login</span>
              <span>{sessionInfo.lastLogin || '—'}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Last password change</span>
              <span>{sessionInfo.lastPasswordChange || '—'}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Active sessions</span>
              <span>{sessionInfo.activeSessions}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>JWT expires</span>
              <span>{sessionInfo.jwtExpires || '—'}</span>
            </div>
          </div>
          <button
            type="button"
            className="btn btn-ghost"
            style={{ color: 'var(--danger)', marginTop: '8px', fontSize: '12px' }}
            onClick={async () => {
              try {
                await api.post('/api/v1/auth/revoke-other-sessions', {});
                window.alert('All other sessions have been revoked.');
              } catch (e) {
                window.alert(e?.message || 'Failed to revoke other sessions.');
              }
            }}
          >
            Revoke All Other Sessions
          </button>
        </div>
      </div>
    </>
  );
};

export default ChangePassword;