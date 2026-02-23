import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { authService } from '../services/authService.js';
import logoImage from '../assets/images/logo.jpeg';
import './Login.css';

export default function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await authService.forgotPassword(email);
      setSent(true);
    } catch (err) {
      setError(err.message || 'Failed to send code.');
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
          <h1>Forgot password?</h1>
          <p className="login-subtitle">
            Enter your email and we will send you a code to reset your password.
          </p>
          {sent ? (
            <div className="forgot-password-sent">
              <p className="success-message">
                If an account exists with this email, you will receive a verification code shortly. Check your inbox.
              </p>
              <button
                type="button"
                className="login-button"
                onClick={() => navigate('/reset-password', { state: { email: email.trim().toLowerCase() } })}
              >
                Enter code and set new password
              </button>
              <Link to="/login" className="forgot-password-link" style={{ marginTop: 8 }}>
                Back to login
              </Link>
            </div>
          ) : (
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
              <div className="login-form-footer">
                <button type="submit" disabled={loading} className="login-button">
                  {loading ? 'Sending...' : 'Send verification code'}
                </button>
                <Link to="/login" className="forgot-password-link">
                  Back to login
                </Link>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
