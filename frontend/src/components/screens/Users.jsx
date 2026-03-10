import React, { useEffect, useState } from 'react';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';

const Users = ({ openModal, onEditUser, refreshKey = 0 }) => {
  const { user: me } = useAuth();
  const role = me?.role || 'officer';
  const isAdmin = role === 'admin';
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [locationsById, setLocationsById] = useState({});
  const [reviewCounts, setReviewCounts] = useState({});

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    api.get('/api/v1/police-users?skip=0&limit=100')
      .then((res) => { if (mounted) { setUsers(res || []); setLoading(false); } })
      .catch(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [refreshKey]);

  // Load all locations so we can resolve sector names from any assigned_location_id.
  useEffect(() => {
    let cancelled = false;
    api
      .get('/api/v1/locations')
      .then((res) => {
        if (cancelled) return;
        const map = {};
        (res || []).forEach((loc) => {
          map[loc.location_id] = loc;
        });
        setLocationsById(map);
      })
      .catch(() => {
        if (cancelled) return;
        setLocationsById({});
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Load per-officer review counts for Reviews column
  useEffect(() => {
    let cancelled = false;
    api
      .get('/api/v1/police-users/review-stats')
      .then((res) => {
        if (cancelled) return;
        setReviewCounts(res || {});
      })
      .catch(() => {
        if (cancelled) return;
        setReviewCounts({});
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const resolveSectorName = (locationId) => {
    if (!locationId || !locationsById[locationId]) return null;
    let current = locationsById[locationId];
    const guard = new Set();
    while (current && !guard.has(current.location_id)) {
      guard.add(current.location_id);
      if (current.location_type === 'sector') {
        return current.location_name;
      }
      if (!current.parent_location_id) break;
      current = locationsById[current.parent_location_id];
    }
    return null;
  };

  const deleteUser = async (user) => {
    if (!isAdmin) return;
    const confirmed = window.confirm(`Delete user "${user.first_name} ${user.last_name}"? This cannot be undone.`);
    if (!confirmed) return;

    try {
      await api.delete(`/api/v1/police-users/${user.police_user_id}`);
      setUsers((prev) => prev.filter((u) => u.police_user_id !== user.police_user_id));
    } catch (e) {
      window.alert(e?.message || 'Failed to delete user.');
    }
  };

  const toggleActive = async (user) => {
    const next = !user.is_active;
    try {
      const updated = await api.put(`/api/v1/police-users/${user.police_user_id}`, {
        is_active: next,
      });
      setUsers((prev) =>
        prev.map((u) => (u.police_user_id === updated.police_user_id ? updated : u))
      );
    } catch (e) {
      // Keep it simple for now; in UI you could show a toast instead.
      window.alert(e?.message || 'Failed to update user status.');
    }
  };

  const total = users.length;
  const active = users.filter(u => u.is_active).length;
  const admins = users.filter(u => u.role === 'admin').length;
  const sectors = new Set(users.map(u => u.assigned_location_id).filter(Boolean)).size;

  return (
    <>
      <div className="page-header">
        <h2>User Management</h2>
        <p>Manage police officers and admin accounts with role-based access control.</p>
      </div>

      <div className="stats-row">
        <div className="stat-card c-blue">
          <div className="stat-label">Total Officers</div>
          <div className="stat-value sv-blue">{total}</div>
        </div>
        <div className="stat-card c-green">
          <div className="stat-label">Active</div>
          <div className="stat-value sv-green">{active}</div>
        </div>
        <div className="stat-card c-orange">
          <div className="stat-label">Admins</div>
          <div className="stat-value sv-orange">{admins}</div>
        </div>
        <div className="stat-card c-cyan">
          <div className="stat-label">Sectors Covered</div>
          <div className="stat-value sv-cyan">{sectors}</div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <div className="card-title">Officer Roster</div>
          {isAdmin && (
            <button className="btn btn-primary btn-sm" onClick={() => openModal('addUser')}>Add User</button>
          )}
        </div>

        <div className="filter-row">
          <input className="input" placeholder="Search officers..." style={{ flex: 2 }} />
          <select className="select">
            <option>All Roles</option>
            <option>Admin</option>
            <option>Officer</option>
            <option>Supervisor</option>
          </select>
          <select className="select">
            <option>All Sectors</option>
          </select>
        </div>

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>Badge</th>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Sector</th>
                <th>Reviews</th>
                <th>Status</th>
                <th>Last Login</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.police_user_id}>
                  {(() => {
                    // compute sector name once per row
                    return null;
                  })()}
                  <td><span className={`badge ${u.role === 'admin' ? 'b-purple' : 'b-blue'}`}>{u.badge_number || `ID-${u.police_user_id}`}</span></td>
                  <td><strong>{u.first_name} {u.last_name}</strong></td>
                  <td style={{ fontSize: '10px' }}>{u.email}</td>
                  <td><span className={`badge ${u.role === 'admin' ? 'b-red' : 'b-blue'}`}>{u.role}</span></td>
                  <td style={{ color: 'var(--muted)' }}>
                    {u.assigned_location_id
                      ? (resolveSectorName(u.assigned_location_id) || '—')
                      : '—'}
                  </td>
                  <td>{reviewCounts[u.police_user_id] ?? '—'}</td>
                  <td>
                    <span className={`badge ${u.is_active ? 'b-green' : 'b-red'}`}>
                      {u.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                    {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : '—'}
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: '4px' }}>
                      <button className="btn btn-outline btn-sm" onClick={() => onEditUser?.(u)}>Edit</button>
                      <button
                        className="btn btn-outline btn-sm"
                        style={{ color: u.is_active ? 'var(--danger)' : 'var(--success)', borderColor: 'transparent' }}
                        onClick={() => toggleActive(u)}
                      >
                        {u.is_active ? 'Deactivate' : 'Activate'}
                      </button>
                      {isAdmin && (
                        <button
                          className="btn btn-outline btn-sm"
                          style={{ color: 'var(--danger)', borderColor: 'transparent' }}
                          onClick={() => deleteUser(u)}
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {(!users.length && !loading) && (
                <tr>
                  <td colSpan={9} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    No users found.
                  </td>
                </tr>
              )}
              {loading && (
                <tr>
                  <td colSpan={9} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    Loading...
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
};

export default Users;