import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext.jsx';
import { testBackendConnection } from '../utils/testConnection.js';
import logoImage from '../assets/images/logo.jpeg';
import './Login.css';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [backendConnected, setBackendConnected] = useState(null);
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const successMessage = location.state?.message;

  useEffect(() => {
    // Test backend connection on mount
    testBackendConnection().then((result) => {
      setBackendConnected(result.success);
      if (!result.success) {
        setError('Cannot connect to backend. Make sure the server is running at http://localhost:8000');
      }
    });
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      console.log('[Login] Attempting login with email:', email);
      await login(email, password);
      console.log('[Login] Login successful, redirecting...');
      navigate('/dashboard');
    } catch (err) {
      console.error('[Login] Login error:', err);
      setError(err.message || 'Login failed. Please check your credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-panel login-panel-left">
        <img src={logoImage} alt="TrustBond" className="login-hero-image" />
      </div>
      <div className="login-panel login-panel-right">
        <div className="login-card">
          <h1>TrustBond</h1>
          <h2>Police Dashboard</h2>
          <p className="login-subtitle">Log in to the system</p>
          <form onSubmit={handleSubmit}>
          {successMessage && (
            <div className="success-message" role="status">{successMessage}</div>
          )}
          {backendConnected === false && (
            <div className="error-message" role="alert">
              Backend connection failed. Make sure the server is running at http://localhost:8000
            </div>
          )}
          {backendConnected === true && error && (
            <div className="error-message" role="alert">{error}</div>
          )}
          <div className="form-group">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="you@example.com"
              disabled={loading}
            />
          </div>
          <div className="form-group">
            <label htmlFor="password">Password</label>
            <div className="password-wrapper">
              <input
                id="password"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                placeholder="Enter your password"
                disabled={loading}
              />
              <button
                type="button"
                className="password-toggle"
                onClick={() => setShowPassword((v) => !v)}
                title={showPassword ? 'Hide password' : 'Show password'}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                tabIndex={-1}
              >
                {showPassword ? (
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
                  </svg>
                ) : (
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                )}
              </button>
            </div>
          </div>
          <div className="login-form-footer">
            <button type="button" className="forgot-password-link" onClick={() => navigate('/forgot-password')}>
              Forgot password?
            </button>
            <button type="submit" disabled={loading} className="login-button">
              {loading ? 'Logging in...' : 'Login'}
            </button>
          </div>
        </form>
        </div>
      </div>
    </div>
  );
}
