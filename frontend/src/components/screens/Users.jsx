import React, { useEffect, useState, useCallback } from 'react';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';

const PAGE_SIZE = 20;

const Users = ({ openModal, onEditUser, refreshKey = 0, wsRefreshKey, isMobile }) => {
  const { user: me } = useAuth();
  const role = me?.role || 'officer';
  const isAdmin = role === 'admin';
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [reviewCounts, setReviewCounts] = useState({});
  const [stationsById, setStationsById] = useState({});
  const [searchText, setSearchText] = useState('');
  const [roleFilter, setRoleFilter] = useState('all');
  const [stationFilter, setStationFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);

  const loadUsers = useCallback(() => {
    let mounted = true;
    Promise.resolve().then(() => setLoading(true));
    
    const params = new URLSearchParams();
    params.set("skip", String(offset));
    params.set("limit", String(pageSize));
    
    api.get(`/api/v1/police-users/?${params.toString()}`)
      .then((res) => { 
        if (mounted) { 
          setUsers(res || []); 
          // Backend doesn't return total count, so we'll estimate
          setTotal(res?.length || 0);
          setLoading(false); 
        } 
      })
      .catch(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [offset, pageSize]);

  useEffect(() => {
    loadUsers();
  }, [loadUsers, refreshKey, wsRefreshKey]);

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
  }, [refreshKey, wsRefreshKey]);

  // Load stations so we can group/filter users by station.
  useEffect(() => {
    let cancelled = false;
    api
      .get('/api/v1/stations?only_active=true')
      .then((res) => {
        if (cancelled) return;
        const map = {};
        (res?.items || []).forEach((st) => {
          map[st.station_id] = st;
        });
        setStationsById(map);
      })
      .catch(() => {
        if (cancelled) return;
        setStationsById({});
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

  const totalCount = total;
  const admins = users.filter(u => u.role === 'admin').length;
  const supervisors = users.filter(u => u.role === 'supervisor').length;
  const officers = users.filter(u => u.role === 'officer').length;

  const stationOptions = Object.values(stationsById).sort((a, b) =>
    (a.station_name || '').localeCompare(b.station_name || '')
  );

  const filteredUsers = users.filter((u) => {
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      const name = `${u.first_name || ''} ${u.last_name || ''}`.toLowerCase();
      const email = (u.email || '').toLowerCase();
      const badge = (u.badge_number || '').toLowerCase();
      if (!name.includes(q) && !email.includes(q) && !badge.includes(q)) {
        return false;
      }
    }
    if (roleFilter !== 'all' && u.role !== roleFilter) {
      return false;
    }
    if (stationFilter !== 'all') {
      const sid = Number(stationFilter);
      if (!u.station_id || u.station_id !== sid) {
        return false;
      }
    }
    if (statusFilter !== 'all') {
      const isActive = statusFilter === 'active';
      if (u.is_active !== isActive) {
        return false;
      }
    }
    return true;
  });

  return (
    <>
      {!isMobile && (
        <div className="page-header">
          <h2>User Management</h2>
          <p>Manage police officers and admin accounts with role-based access control.</p>
        </div>
      )}

      <div className="stats-row">
        <div className="stat-card c-blue">
          <div className="stat-label">Total Accounts</div>
          <div className="stat-value sv-blue">{totalCount}</div>
        </div>
        <div className="stat-card c-orange">
          <div className="stat-label">Admins</div>
          <div className="stat-value sv-orange">{admins}</div>
        </div>
        <div className="stat-card c-green">
          <div className="stat-label">Supervisors</div>
          <div className="stat-value sv-green">{supervisors}</div>
        </div>
        <div className="stat-card c-cyan">
          <div className="stat-label">Officers</div>
          <div className="stat-value sv-cyan">{officers}</div>
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
          <input
            className="input"
            placeholder="Search by name, email, or badge..."
            style={{ flex: 2 }}
            value={searchText}
            onChange={(e) => {
              setSearchText(e.target.value);
              setOffset(0);
            }}
          />
          <select
            className="select"
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value);
              setOffset(0);
            }}
          >
            <option value="all">All Roles</option>
            <option value="admin">Admin</option>
            <option value="supervisor">Supervisor</option>
            <option value="officer">Officer</option>
          </select>
          <select
            className="select"
            value={stationFilter}
            onChange={(e) => {
              setStationFilter(e.target.value);
              setOffset(0);
            }}
          >
            <option value="all">All Stations</option>
            {stationOptions.map((st) => (
              <option key={st.station_id} value={st.station_id}>
                {st.station_name}
              </option>
            ))}
          </select>
          <select
            className="select"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setOffset(0);
            }}
          >
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
          <input
            type="number"
            min="5"
            max="100"
            placeholder="Rows"
            style={{ minWidth: "80px" }}
            value={pageSize}
            onChange={(e) => {
              const newSize = Math.max(5, Math.min(100, parseInt(e.target.value) || 20));
              setPageSize(newSize);
              setOffset(0);
            }}
          />
        </div>

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Badge</th>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Station</th>
                <th>Reviews</th>
                <th>Status</th>
                <th>Last Login</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((u, index) => (
                <tr key={u.police_user_id}>
                  <td style={{ fontSize: "12px", color: "var(--muted)", textAlign: "center" }}>
                    {offset + index + 1}
                  </td>
                  <td><span className={`badge ${u.role === 'admin' ? 'b-purple' : 'b-blue'}`}>{u.badge_number || `ID-${u.police_user_id}`}</span></td>
                  <td><strong>{u.first_name} {u.last_name}</strong></td>
                  <td style={{ fontSize: '10px' }}>{u.email}</td>
                  <td><span className={`badge ${u.role === 'admin' ? 'b-red' : 'b-blue'}`}>{u.role}</span></td>
                  <td style={{ color: 'var(--muted)' }}>
                    {u.station_id && stationsById[u.station_id]
                      ? stationsById[u.station_id].station_name
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
              {!filteredUsers.length && !loading && (
                <tr>
                  <td colSpan={10} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    No users found.
                  </td>
                </tr>
              )}
              {loading && (
                <tr>
                  <td colSpan={10} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    Loading...
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '14px', flexWrap: 'wrap', gap: '8px' }}>
          <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
            Showing {Math.min(offset + 1, filteredUsers.length)}-{Math.min(offset + pageSize, filteredUsers.length)} of {filteredUsers.length} users
          </div>
          <div className="pagination">
            <button 
              className="page-btn" 
              onClick={() => setOffset(Math.max(0, offset - pageSize))}
              disabled={offset === 0}
            >
              ‹
            </button>
            {Array.from({ length: Math.min(5, Math.ceil(filteredUsers.length / pageSize)) }, (_, i) => {
              const pageNum = i + 1;
              const pageOffset = (pageNum - 1) * pageSize;
              const isCurrent = Math.floor(offset / pageSize) === pageNum - 1;
              return (
                <button
                  key={pageNum}
                  className={`page-btn ${isCurrent ? 'current' : ''}`}
                  onClick={() => setOffset(pageOffset)}
                >
                  {pageNum}
                </button>
              );
            })}
            <button 
              className="page-btn" 
              onClick={() => setOffset(Math.min(filteredUsers.length - pageSize, offset + pageSize))}
              disabled={offset + pageSize >= filteredUsers.length}
            >
              ›
            </button>
          </div>
        </div>
      </div>
    </>
  );
};

export default Users;