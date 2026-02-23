import { useState, useEffect } from 'react';
import Layout from '../components/Layout.jsx';
import { useAuth } from '../contexts/AuthContext.jsx';
import { apiService } from '../services/apiService.js';
import '../styles/colors.css';

export default function Users() {
  const { isAdmin, canManageUsers } = useAuth();
  const [users, setUsers] = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [togglingId, setTogglingId] = useState(null);
  const [form, setForm] = useState({
    first_name: '',
    middle_name: '',
    last_name: '',
    email: '',
    password: '',
    phone_number: '',
    badge_number: '',
    role: 'officer',
    assigned_location_id: null,
    is_active: true,
  });

  const loadUsers = () => {
    setLoading(true);
    apiService
      .getPoliceUsers()
      .then(setUsers)
      .catch((err) => setError(err.message || 'Failed to load users'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (canManageUsers) loadUsers();
  }, [canManageUsers]);

  useEffect(() => {
    if (canManageUsers) {
      apiService.getLocations({ limit: 500 }).then(setLocations).catch(() => setLocations([]));
    }
  }, [canManageUsers]);

  const resetForm = () => {
    setForm({
      first_name: '',
      middle_name: '',
      last_name: '',
      email: '',
      password: '',
      phone_number: '',
      badge_number: '',
      role: 'officer',
      assigned_location_id: null,
      is_active: true,
    });
    setEditing(null);
    setShowForm(false);
  };

  const locationById = (id) => locations.find((l) => l.location_id === id);

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!form.first_name?.trim() || !form.last_name?.trim() || !form.email?.trim()) {
      setError('First name, last name and email are required.');
      return;
    }
    setError(null);
    try {
      await apiService.createPoliceUser({
        first_name: form.first_name.trim(),
        middle_name: form.middle_name?.trim() || null,
        last_name: form.last_name.trim(),
        email: form.email.trim(),
        phone_number: form.phone_number?.trim() || null,
        role: form.role,
        assigned_location_id: form.assigned_location_id || null,
        is_active: form.is_active,
      });
      resetForm();
      loadUsers();
    } catch (err) {
      setError(err.message || 'Failed to create user');
    }
  };

  const handleUpdate = async (e) => {
    e.preventDefault();
    if (!editing) return;
    setError(null);
    try {
      const payload = {
        first_name: form.first_name?.trim(),
        middle_name: form.middle_name?.trim() || null,
        last_name: form.last_name?.trim(),
        phone_number: form.phone_number?.trim() || null,
        badge_number: form.badge_number?.trim() || null,
        role: form.role,
        assigned_location_id: form.assigned_location_id ?? null,
        is_active: form.is_active,
      };
      if (form.password?.trim()) payload.password = form.password.trim();
      await apiService.updatePoliceUser(editing.police_user_id, payload);
      resetForm();
      loadUsers();
    } catch (err) {
      setError(err.message || 'Failed to update user');
    }
  };

  const startEdit = (u) => {
    setEditing(u);
    setForm({
      first_name: u.first_name || '',
      middle_name: u.middle_name || '',
      last_name: u.last_name || '',
      email: u.email || '',
      password: '',
      phone_number: u.phone_number || '',
      badge_number: u.badge_number || '',
      role: u.role || 'officer',
      assigned_location_id: u.assigned_location_id ?? null,
      is_active: u.is_active ?? true,
    });
    setShowForm(true);
  };

  const handleToggleActive = async (u) => {
    setError(null);
    setTogglingId(u.police_user_id);
    try {
      await apiService.updatePoliceUser(u.police_user_id, { is_active: !u.is_active });
      loadUsers();
    } catch (err) {
      setError(err.message || 'Failed to update user');
    } finally {
      setTogglingId(null);
    }
  };

  const handleDelete = async (u) => {
    if (!window.confirm(`Delete user ${u.first_name} ${u.last_name}? This cannot be undone.`)) return;
    setError(null);
    try {
      await apiService.deletePoliceUser(u.police_user_id);
      loadUsers();
      if (editing?.police_user_id === u.police_user_id) resetForm();
    } catch (err) {
      setError(err.message || 'Failed to delete user');
    }
  };

  if (!canManageUsers) {
    return (
      <Layout>
        <div className="page-users">
          <p className="error-message">You do not have access to user management. You can only change your password in your dashboard.</p>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="page-users">
        <div className="users-header">
          <h2>User management</h2>
          {isAdmin && (
            <button type="button" className="btn-primary" onClick={() => { resetForm(); setShowForm(true); }}>
              Add user
            </button>
          )}
        </div>
        {error && <p className="error-message">{error}</p>}
        {showForm && (
          <form className="user-form" onSubmit={editing ? handleUpdate : handleCreate}>
            <h3>{editing ? 'Edit user' : 'New user'}</h3>
            <div className="form-row">
              <label>First name *</label>
              <input
                value={form.first_name}
                onChange={(e) => setForm((f) => ({ ...f, first_name: e.target.value }))}
                required
              />
            </div>
            <div className="form-row">
              <label>Middle name</label>
              <input
                value={form.middle_name}
                onChange={(e) => setForm((f) => ({ ...f, middle_name: e.target.value }))}
              />
            </div>
            <div className="form-row">
              <label>Last name *</label>
              <input
                value={form.last_name}
                onChange={(e) => setForm((f) => ({ ...f, last_name: e.target.value }))}
                required
              />
            </div>
            <div className="form-row">
              <label>Email *</label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                required
                disabled={!!editing}
              />
            </div>
            {editing && (
              <>
                <div className="form-row">
                  <label>Password (leave blank to keep)</label>
                  <input
                    type="password"
                    value={form.password}
                    onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                    minLength={6}
                  />
                </div>
                <div className="form-row">
                  <label>Badge number</label>
                  <input value={form.badge_number} readOnly disabled className="form-input-readonly" />
                </div>
              </>
            )}
            {!editing && (
              <p className="form-hint">A random password and badge number (in order) will be generated and sent to the user&apos;s email.</p>
            )}
            <div className="form-row">
              <label>Phone</label>
              <input
                value={form.phone_number}
                onChange={(e) => setForm((f) => ({ ...f, phone_number: e.target.value }))}
              />
            </div>
            <div className="form-row">
              <label>Role</label>
              <select
                value={form.role}
                onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
              >
                <option value="officer">Officer</option>
                <option value="supervisor">Supervisor</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div className="form-row">
              <label>Assigned location</label>
              <select
                value={form.assigned_location_id ?? ''}
                onChange={(e) => setForm((f) => ({ ...f, assigned_location_id: e.target.value ? parseInt(e.target.value, 10) : null }))}
              >
                <option value="">— None —</option>
                {locations.map((loc) => (
                  <option key={loc.location_id} value={loc.location_id}>
                    {loc.location_name} ({loc.location_type})
                  </option>
                ))}
              </select>
            </div>
            <div className="form-row checkbox-row">
              <label>
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
                />
                Active
              </label>
            </div>
            <div className="form-actions">
              <button type="submit">{editing ? 'Update' : 'Create'}</button>
              <button type="button" onClick={resetForm}>Cancel</button>
            </div>
          </form>
        )}
        {loading && <p className="loading">Loading users…</p>}
        {!loading && users.length === 0 && !showForm && <p className="empty">No users.</p>}
        {!loading && users.length > 0 && (
          <div className="table-wrap">
            <table className="users-table">
              <thead>
                <tr>
                  <th>Badge</th>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Assigned location</th>
                  <th>Active</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.police_user_id}>
                    <td>{u.badge_number || '—'}</td>
                    <td>{[u.first_name, u.middle_name, u.last_name].filter(Boolean).join(' ')}</td>
                    <td>{u.email}</td>
                    <td>{u.role}</td>
                    <td>{(locationById(u.assigned_location_id)?.location_name) || '—'}</td>
                    <td>
                      {u.role !== 'admin' ? (
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => handleToggleActive(u)}
                          disabled={togglingId === u.police_user_id}
                        >
                          {u.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                      ) : (
                        (u.is_active ? 'Yes' : 'No')
                      )}
                    </td>
                    <td>
                      {isAdmin && (
                        <>
                          <button type="button" className="link-button" onClick={() => startEdit(u)}>
                            Edit
                          </button>
                          {' '}
                          <button
                            type="button"
                            className="link-button danger"
                            onClick={() => handleDelete(u)}
                          >
                            Delete
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Layout>
  );
}
