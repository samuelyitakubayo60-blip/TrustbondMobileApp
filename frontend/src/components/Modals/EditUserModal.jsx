import React, { useEffect, useMemo, useState } from 'react';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';

const EditUserModal = ({ isOpen, onClose, user, onSaved }) => {
  if (!isOpen || !user) return null;

  const { user: me } = useAuth();
  const role = me?.role || 'officer';
  const isAdmin = role === 'admin';
  const isSupervisor = role === 'supervisor';

  const [form, setForm] = useState({
    first_name: user.first_name || '',
    last_name: user.last_name || '',
    phone_number: user.phone_number || '',
    badge_number: user.badge_number || '',
    role: user.role || 'officer',
    station_id: user.station_id || '',
    is_active: user.is_active,
  });
  const [stations, setStations] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');

  const stationName = useMemo(() => {
    const id = user.station_id;
    if (!id) return 'None';
    const st = stations.find((s) => s.station_id === id || s.station_id === Number(id));
    return st?.station_name || `Station #${id}`;
  }, [stations, user.station_id]);

  useEffect(() => {
    setForm({
      first_name: user.first_name || '',
      last_name: user.last_name || '',
      phone_number: user.phone_number || '',
      badge_number: user.badge_number || '',
      role: user.role || 'officer',
      station_id: user.station_id || '',
      is_active: user.is_active,
    });
    setError('');
    setInfo('');
    setSaving(false);
  }, [user, isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    const load = async () => {
      try {
        const res = await api.get('/api/v1/stations?only_active=true');
        if (!cancelled) setStations(res?.items || []);
      } catch {
        if (!cancelled) setStations([]);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [isOpen]);

  const handleChange = (field) => (e) => {
    const value = field === 'is_active' ? e.target.checked : e.target.value;
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const submit = async () => {
    setError('');

    const base = {
      first_name: form.first_name.trim() || undefined,
      last_name: form.last_name.trim() || undefined,
      phone_number: form.phone_number.trim() || undefined,
      is_active: !!form.is_active,
    };

    // Supervisors can only update basic fields; admin can update all.
    const payload = isAdmin
      ? {
          ...base,
          badge_number: form.badge_number.trim() || undefined,
          role: form.role,
          station_id: form.station_id ? Number(form.station_id) : null,
        }
      : base;
    setSaving(true);
    try {
      await api.put(`/api/v1/police-users/${user.police_user_id}`, payload);
      onSaved?.();
      onClose?.();
    } catch (e) {
      setError(e?.message || 'Failed to update user.');
    } finally {
      setSaving(false);
    }
  };

  const deleteUser = async () => {
    if (!isAdmin) return;
    if (!window.confirm('Delete this user account? This cannot be undone.')) return;
    setSaving(true);
    try {
      await api.delete(`/api/v1/police-users/${user.police_user_id}`);
      onSaved?.();
      onClose?.();
    } catch (e) {
      setError(e?.message || 'Failed to delete user.');
    } finally {
      setSaving(false);
    }
  };

  const resetPassword = async () => {
    if (!isAdmin) return;
    if (!window.confirm('Reset this user password and email a new temporary password?')) return;
    setSaving(true);
    setError('');
    setInfo('');
    try {
      const res = await api.post(`/api/v1/police-users/${user.police_user_id}/reset-password`, {});
      setInfo(res?.message || 'Temporary password sent to user email.');
    } catch (e) {
      setError(e?.message || 'Failed to reset password.');
    } finally {
      setSaving(false);
    }
  };

  const revokeSessions = async () => {
    if (!isAdmin) return;
    if (!window.confirm('Force log out this user from all active sessions?')) return;
    setSaving(true);
    setError('');
    setInfo('');
    try {
      const res = await api.post(`/api/v1/police-users/${user.police_user_id}/revoke-sessions`, {});
      setInfo(res?.message || 'All active sessions revoked for this user.');
    } catch (e) {
      setError(e?.message || 'Failed to revoke user sessions.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">Edit Officer — {user.first_name} {user.last_name}</div>
          <div className="modal-close" onClick={onClose}>✕</div>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ marginBottom: '10px' }}>
            <span className="alert-icon">!</span>
            <div>{error}</div>
          </div>
        )}
        {info && (
          <div className="alert alert-success" style={{ marginBottom: '10px' }}>
            <span className="alert-icon">✓</span>
            <div>{info}</div>
          </div>
        )}
        
        <div className="form-grid" style={{ marginBottom: '12px' }}>
          <div className="input-group">
            <div className="input-label">First Name</div>
            <input
              className="input"
              value={form.first_name}
              onChange={handleChange('first_name')}
            />
          </div>
          <div className="input-group">
            <div className="input-label">Last Name</div>
            <input
              className="input"
              value={form.last_name}
              onChange={handleChange('last_name')}
            />
          </div>
        </div>
        
        <div className="form-grid" style={{ marginBottom: '12px' }}>
          <div className="input-group">
            <div className="input-label">Badge</div>
            <input
              className="input"
              value={form.badge_number}
              onChange={handleChange('badge_number')}
              disabled={!isAdmin}
            />
          </div>
          <div className="input-group">
            <div className="input-label">Phone</div>
            <input
              className="input"
              value={form.phone_number}
              onChange={handleChange('phone_number')}
            />
          </div>
        </div>
        
        <div className="form-grid" style={{ marginBottom: '12px' }}>
          <div className="input-group">
            <div className="input-label">Role</div>
            {isAdmin ? (
              <select className="select" value={form.role} onChange={handleChange('role')}>
                <option value="admin">Admin</option>
                <option value="officer">Officer</option>
                <option value="supervisor">Supervisor</option>
              </select>
            ) : (
              <input className="input" value={user.role} disabled />
            )}
          </div>
          <div className="input-group">
            <div className="input-label">Assigned Station</div>
            {isAdmin ? (
              <select
                className="select"
                value={form.station_id || ''}
                onChange={handleChange('station_id')}
              >
                <option value="">None</option>
                {stations.map((s) => (
                  <option key={s.station_id} value={s.station_id}>
                    {s.station_name}
                  </option>
                ))}
              </select>
            ) : (
              <input className="input" value={stationName} disabled />
            )}
          </div>
        </div>

        <div className="input-group" style={{ marginBottom: '12px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--muted)' }}>
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={handleChange('is_active')}
            />
            Active
          </label>
        </div>
        
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {isAdmin && (
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'space-between' }}>
              <button className="btn btn-outline" onClick={deleteUser} disabled={saving}>
                Delete User
              </button>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button className="btn btn-outline" onClick={resetPassword} disabled={saving}>
                  Reset Password
                </button>
                <button className="btn btn-outline" onClick={revokeSessions} disabled={saving}>
                  Force Logout
                </button>
              </div>
            </div>
          )}
          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
            <button className="btn btn-outline" onClick={onClose}>Cancel</button>
            <button className="btn btn-primary" onClick={submit} disabled={saving}>
              {saving ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default EditUserModal;