import { useState } from 'react';
import Layout from '../components/Layout.jsx';
import { authService } from '../services/authService.js';

export default function ChangePassword() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSuccess(false);
    if (newPassword !== confirmPassword) {
      setError('New password and confirmation do not match.');
      return;
    }
    if (newPassword.length < 6) {
      setError('New password must be at least 6 characters.');
      return;
    }
    try {
      await authService.changePassword(currentPassword, newPassword);
      setSuccess(true);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err) {
      setError(err.message || 'Failed to change password.');
    }
  };

  return (
    <Layout>
      <div className="page-change-password">
        <h2>Change password</h2>
        <p className="form-hint">Change your password in your dashboard. Only you can update it.</p>
        {error && <p className="error-message">{error}</p>}
        {success && <p className="success-message">Password updated successfully.</p>}
        <form className="user-form" onSubmit={handleSubmit}>
          <div className="form-row">
            <label>Current password *</label>
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </div>
          <div className="form-row">
            <label>New password *</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={6}
              autoComplete="new-password"
            />
          </div>
          <div className="form-row">
            <label>Confirm new password *</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={6}
              autoComplete="new-password"
            />
          </div>
          <div className="form-actions">
            <button type="submit">Update password</button>
          </div>
        </form>
      </div>
    </Layout>
  );
}
