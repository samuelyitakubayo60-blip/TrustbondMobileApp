import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { staffRoleLabel } from '../../utils/roleLabels';
import { canCreateUsers, canDeleteUsers, canEditUsers } from '../../utils/roleMapping';
import { getRoleDisplayName } from '../../utils/roleMapping';

const PAGE_SIZE = 20;

// ── Module-level cache ─────────────────────────────────────────────────────
// Survives navigation away and back; cleared when a real refresh is triggered.
let _usersCache = null; // { users, stationsById }
let _usersCacheRefreshKey = undefined; // the refreshKey / wsRefreshKey that produced this cache

// ── Component ──────────────────────────────────────────────────────────────

const Users = ({ openModal, onEditUser, refreshKey = 0, wsRefreshKey, isMobile }) => {
  const { user: me } = useAuth();
  const role = me?.role || 'officer';
  const canAdd = canCreateUsers(role);
  const canEdit = canEditUsers(role);
  const canDelete = canDeleteUsers(role);

  // Initialise state from cache immediately so returning to this screen is instant.
  const [users, setUsers] = useState(_usersCache?.users ?? []);
  const [stationsById, setStationsById] = useState(_usersCache?.stationsById ?? {});
  const [loading, setLoading] = useState(_usersCache === null);
  const [bgRefreshing, setBgRefreshing] = useState(false);

  const [searchText, setSearchText] = useState('');
  const [roleFilter, setRoleFilter] = useState('all');
  const [stationFilter, setStationFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [offset, setOffset] = useState(0);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const fetchAll = useCallback(async ({ silent = false } = {}) => {
    if (silent) {
      setBgRefreshing(true);
    } else {
      setLoading(true);
    }
    try {
      // Fetch ALL users at once (large limit) and ALL stations in parallel.
      const [usersRes, stationsRes] = await Promise.all([
        api.get('/api/v1/police-users/?limit=500'),
        api.get('/api/v1/stations/'),
      ]);
      if (!mountedRef.current) return;

      const newUsers = usersRes || [];
      const stationsMap = {};
      (stationsRes?.items || []).forEach((st) => {
        stationsMap[st.station_id] = st;
      });

      _usersCache = { users: newUsers, stationsById: stationsMap };
      _usersCacheRefreshKey = refreshKey ?? wsRefreshKey;

      setUsers(newUsers);
      setStationsById(stationsMap);
    } catch (e) {
      // On background refresh keep showing stale data; only clear on hard load.
      if (!mountedRef.current) return;
      if (!silent) {
        setUsers([]);
        setStationsById({});
      }
    } finally {
      if (!mountedRef.current) return;
      setLoading(false);
      setBgRefreshing(false);
    }
  }, [refreshKey, wsRefreshKey]);

  useEffect(() => {
    if (_usersCache === null) {
      // Truly first load (no cache) — show spinner.
      fetchAll({ silent: false });
    } else {
      // Cache exists (including WS-triggered refresh) — stay silent.
      fetchAll({ silent: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey, wsRefreshKey]);

  const deleteUser = async (user) => {
    if (!canDelete) return;
    const confirmed = window.confirm(`Delete user "${user.first_name} ${user.last_name}"? This cannot be undone.`);
    if (!confirmed) return;
    try {
      await api.delete(`/api/v1/police-users/${user.police_user_id}`);
      _usersCache = null;
      fetchAll({ silent: false });
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
      _usersCache = null;
      fetchAll({ silent: false });
      // Optimistic local update while fetch is in flight
      setUsers((prev) =>
        prev.map((u) => (u.police_user_id === updated.police_user_id ? updated : u))
      );
    } catch (e) {
      window.alert(e?.message || 'Failed to update user status.');
    }
  };

  // ── Stat values (computed from full unfiltered list) ────────────────────
  const totalCount = users.length;
  const admins = users.filter((u) => u.role === 'admin').length;
  const supervisors = users.filter((u) => u.role === 'supervisor').length;
  const officers = users.filter((u) => u.role === 'officer').length;

  const stationOptions = useMemo(
    () => Object.values(stationsById).sort((a, b) => (a.station_name || '').localeCompare(b.station_name || '')),
    [stationsById]
  );

  // ── Client-side filtering ───────────────────────────────────────────────
  const filteredUsers = useMemo(() => {
    return users.filter((u) => {
      if (searchText.trim()) {
        const q = searchText.trim().toLowerCase();
        const name = `${u.first_name || ''} ${u.last_name || ''}`.toLowerCase();
        const email = (u.email || '').toLowerCase();
        const badge = (u.badge_number || '').toLowerCase();
        const rank = (u.rank || '').toLowerCase();
        if (!name.includes(q) && !email.includes(q) && !badge.includes(q) && !rank.includes(q)) {
          return false;
        }
      }
      if (roleFilter !== 'all' && u.role !== roleFilter) return false;
      if (stationFilter !== 'all') {
        const sid = Number(stationFilter);
        if (!u.station_id || u.station_id !== sid) return false;
      }
      if (statusFilter !== 'all') {
        const isActive = statusFilter === 'active';
        if (u.is_active !== isActive) return false;
      }
      return true;
    });
  }, [users, searchText, roleFilter, stationFilter, statusFilter]);

  const paginatedUsers = useMemo(
    () => filteredUsers.slice(offset, offset + pageSize),
    [filteredUsers, offset, pageSize]
  );

  return (
    <>
      {!isMobile && (
        <div className="page-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <h2 style={{ margin: 0 }}>User Management</h2>
            {bgRefreshing && (
              <span style={{ fontSize: 11, color: 'var(--muted)', fontStyle: 'italic' }}>
                refreshing…
              </span>
            )}
          </div>
          <p>Manage officers, IOs, and DPC accounts with role-based access control.</p>
        </div>
      )}

      <div className="stats-row">
        <div className="stat-card c-blue">
          <div className="stat-label">Total Accounts</div>
          <div className="stat-value sv-blue">{loading ? '…' : totalCount}</div>
        </div>
        <div className="stat-card c-orange">
          <div className="stat-label">DPC</div>
          <div className="stat-value sv-orange">{loading ? '…' : admins}</div>
        </div>
        <div className="stat-card c-green">
          <div className="stat-label">IO</div>
          <div className="stat-value sv-green">{loading ? '…' : supervisors}</div>
        </div>
        <div className="stat-card c-cyan">
          <div className="stat-label">Officers</div>
          <div className="stat-value sv-cyan">{loading ? '…' : officers}</div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <div className="card-title">Officer Roster</div>
          {canAdd && (
            <button className="btn btn-primary btn-sm" onClick={() => openModal('addUser')}>Add User</button>
          )}
        </div>

        <div className="filter-row">
          <input
            className="input"
            placeholder="Search by name, email, badge, or rank..."
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
            <option value="admin">DPC</option>
            <option value="supervisor">IO</option>
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
            style={{ minWidth: '80px' }}
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
                <th>Rank</th>
                <th>Email</th>
                <th>Role</th>
                <th>Station</th>
                <th>Status</th>
                <th>Last Login</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={11} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    Loading...
                  </td>
                </tr>
              ) : paginatedUsers.length === 0 ? (
                <tr>
                  <td colSpan={11} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    No users found.
                  </td>
                </tr>
              ) : (
                paginatedUsers.map((u, index) => (
                  <tr key={u.police_user_id}>
                    <td style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                      {offset + index + 1}
                    </td>
                    <td><span className={`badge ${u.role === 'admin' ? 'b-purple' : 'b-blue'}`}>{u.badge_number || `ID-${u.police_user_id}`}</span></td>
                    <td><strong>{u.first_name} {u.last_name}</strong></td>
                    <td style={{ fontSize: '11px' }}>{u.rank || '—'}</td>
                    <td style={{ fontSize: '10px' }}>{u.email}</td>
                    <td><span className={`badge ${u.role === 'admin' ? 'b-red' : 'b-blue'}`}>{staffRoleLabel(u.role)}</span></td>
                    <td style={{ color: 'var(--muted)' }}>
                      {u.station_id && stationsById[u.station_id]
                        ? stationsById[u.station_id].station_name
                        : '—'}
                    </td>
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
                        {canEdit && (
                          <button className="btn btn-outline btn-sm" onClick={() => onEditUser?.(u)}>Edit</button>
                        )}
                        {canEdit && (
                          <button
                            className="btn btn-outline btn-sm"
                            style={{ color: u.is_active ? 'var(--danger)' : 'var(--success)', borderColor: 'transparent' }}
                            onClick={() => toggleActive(u)}
                          >
                            {u.is_active ? 'Deactivate' : 'Activate'}
                          </button>
                        )}
                        {canDelete && (
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
                ))
              )}
            </tbody>
          </table>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '14px', flexWrap: 'wrap', gap: '8px' }}>
          <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
            Showing {Math.min(offset + 1, filteredUsers.length)}–{Math.min(offset + pageSize, filteredUsers.length)} of {filteredUsers.length} users
          </div>
          <div className="pagination">
            <button
              className="page-btn"
              onClick={() => setOffset(Math.max(0, offset - pageSize))}
              disabled={offset === 0}
            >
              ‹
            </button>
            {Array.from({ length: Math.min(5, Math.ceil(filteredUsers.length / pageSize) || 1) }, (_, i) => {
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
              onClick={() => setOffset(Math.min(Math.max(filteredUsers.length - pageSize, 0), offset + pageSize))}
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
