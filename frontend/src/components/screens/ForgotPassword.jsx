import React, { useState } from 'react';
import api from '../../api/client';

export default function ForgotPassword({ onBack, onCodeSent }) {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const normalized = email.trim().toLowerCase();
      await api.post('/api/v1/auth/forgot-password', { email: normalized }, { token: null });
      setSent(true);
      onCodeSent?.(normalized);
    } catch (err) {
      setError(err?.data?.detail || err?.message || 'Failed to send code.');
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
        <h2 style={{ marginBottom: 8, color: 'var(--text)' }}>Forgot password?</h2>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 16 }}>
          Enter your email and we will send you a code to reset your password.
        </p>
        <form onSubmit={handleSubmit}>
          {error && (
            <div style={{ color: 'var(--danger)', fontSize: 12, marginBottom: 12 }}>
              {error}
            </div>
          )}
          <div style={{ marginBottom: 12 }}>
            <label style={{ display: 'block', fontSize: 12, marginBottom: 4, color: 'var(--muted)' }}>
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="your@email.com"
              disabled={loading}
              style={{
                width: '100%', padding: '10px 12px', borderRadius: 8,
                border: '1px solid var(--border)', background: 'var(--surface2)', color: 'var(--text)',
                fontSize: 14,
              }}
            />
          </div>
          {sent && (
            <div style={{ fontSize: 12, color: 'var(--success)', marginBottom: 12 }}>
              If an account exists with this email, you will receive a verification code shortly.
            </div>
          )}
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8,
            gap: 8,
          }}>
            <button
              type="button"
              onClick={onBack}
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
              {loading ? 'Sending...' : 'Send verification code'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

