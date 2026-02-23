import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { authService } from '../services/authService.js';
import logoImage from '../assets/images/logo.jpeg';
import './Login.css';

export default function ResetPassword() {
  const location = useLocation();
  const navigate = useNavigate();
  const [email, setEmail] = useState(location.state?.email ?? '');
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await authService.resetPassword(email, code, newPassword);
      navigate('/login', { state: { message: 'Password has been reset. You can now log in with your new password.' } });
    } catch (err) {
      setError(err.message || 'Failed to reset password.');
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
          <h1>Set new password</h1>
          <p className="login-subtitle">
            Enter the code we sent to your email and choose a new password.
          </p>
          <form onSubmit={handleSubmit}>
            {error && (
              <div className="error-message" role="alert">
                {error}
              </div>
            )}
            <div className="form-group">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="your@email.com"
                disabled={loading}
              />
            </div>
            <div className="form-group">
              <label htmlFor="code">Verification code</label>
              <input
                id="code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                required
                placeholder="000000"
                disabled={loading}
                maxLength={6}
              />
            </div>
            <div className="form-group">
              <label htmlFor="newPassword">New password</label>
              <div className="password-wrapper">
                <input
                  id="newPassword"
                  type={showPassword ? 'text' : 'password'}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  minLength={6}
                  placeholder="At least 6 characters"
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
              <button type="submit" disabled={loading} className="login-button">
                {loading ? 'Resetting...' : 'Reset password'}
              </button>
              <Link to="/login" className="forgot-password-link">
                Back to login
              </Link>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
