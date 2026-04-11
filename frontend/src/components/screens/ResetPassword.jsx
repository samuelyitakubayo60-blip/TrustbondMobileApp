import React, { useState } from 'react';
import api from '../../api/client';

export default function ResetPassword({ email, onBackToLogin }) {
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (password.length < 6) {
      setError('New password must be at least 6 characters.');
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    setLoading(true);
    try {
      await api.post(
        '/api/v1/auth/reset-password',
        {
          email: email.trim().toLowerCase(),
          code: code.trim(),
          new_password: password,
        },
        { token: null }
      );
      setDone(true);
    } catch (err) {
      setError(err?.data?.detail || err?.message || 'Failed to reset password.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg, #0f1114)', fontFamily: 'inherit',
    }}>
      <div style={{
        width: '100%', maxWidth: 400, padding: 24,
        background: 'var(--surface, #1a1d22)', borderRadius: 12,
        border: '1px solid var(--border, #2a2d35)',
      }}>
        <h2 style={{ marginBottom: 8, color: 'var(--text)' }}>Reset password</h2>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 16 }}>
          Enter the code sent to <strong>{email}</strong> and choose a new password.
        </p>
        {done ? (
          <div>
            <div style={{ fontSize: 13, color: 'var(--success)', marginBottom: 16 }}>
              Your password has been updated. You can now sign in with the new password.
            </div>
            <button
              type="button"
              onClick={onBackToLogin}
              style={{
                padding: '10px 16px', borderRadius: 8, border: 'none',
                background: 'var(--accent)', color: '#fff', fontWeight: 600, cursor: 'pointer',
              }}
            >
              Back to login
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            {error && (
              <div style={{ color: 'var(--danger)', fontSize: 12, marginBottom: 12 }}>
                {error}
              </div>
            )}
            <div style={{ marginBottom: 12 }}>
              <label style={{ display: 'block', fontSize: 12, marginBottom: 4, color: 'var(--muted)' }}>
                Verification code
              </label>
              <input
                type="text"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
                placeholder="6-digit code"
                disabled={loading}
                style={{
                  width: '100%', padding: '10px 12px', borderRadius: 8,
                  border: '1px solid var(--border)', background: 'var(--surface2)', color: 'var(--text)',
                  fontSize: 14,
                }}
              />
            </div>
            <div style={{ marginBottom: 12 }}>
              <label style={{ display: 'block', fontSize: 12, marginBottom: 4, color: 'var(--muted)' }}>
                New password
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  placeholder="New password"
                  disabled={loading}
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
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', fontSize: 12, marginBottom: 4, color: 'var(--muted)' }}>
                Confirm password
              </label>
              <input
                type={showPassword ? 'text' : 'password'}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                placeholder="Repeat new password"
                disabled={loading}
                style={{
                  width: '100%', padding: '10px 12px', borderRadius: 8,
                  border: '1px solid var(--border)', background: 'var(--surface2)', color: 'var(--text)',
                  fontSize: 14,
                }}
              />
            </div>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8,
            }}>
              <button
                type="button"
                onClick={onBackToLogin}
                style={{
                  padding: '10px 14px', borderRadius: 8, border: '1px solid var(--border)',
                  background: 'transparent', color: 'var(--text)', fontSize: 13, cursor: 'pointer',
                }}
              >
                Back to login
              </button>
              <button
                type="submit"
                disabled={loading}
                style={{
                  padding: '10px 16px', borderRadius: 8, border: 'none',
                  background: 'var(--accent)', color: '#fff', fontWeight: 600, cursor: loading ? 'wait' : 'pointer',
                }}
              >
                {loading ? 'Updating…' : 'Reset password'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

