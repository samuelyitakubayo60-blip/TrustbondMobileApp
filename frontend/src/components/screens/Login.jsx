import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(err?.data?.detail || err?.message || 'Login failed');
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
        width: '100%', maxWidth: 360, padding: 24,
        background: 'var(--surface, #1a1d22)', borderRadius: 12,
        border: '1px solid var(--border, #2a2d35)',
      }}>
        <h2 style={{ marginBottom: 8, color: 'var(--text)' }}>TrustBond Police Dashboard</h2>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 24 }}>Sign in to continue</p>
        <form onSubmit={handleSubmit}>
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            style={{
              width: '100%', padding: '10px 12px', marginBottom: 12, borderRadius: 8,
              border: '1px solid var(--border)', background: 'var(--surface2)', color: 'var(--text)',
              fontSize: 14,
            }}
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            style={{
              width: '100%', padding: '10px 12px', marginBottom: 16, borderRadius: 8,
              border: '1px solid var(--border)', background: 'var(--surface2)', color: 'var(--text)',
              fontSize: 14,
            }}
          />
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
  );
}
