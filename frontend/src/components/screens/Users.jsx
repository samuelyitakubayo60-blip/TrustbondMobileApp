import React, { useCallback, useEffect, useState } from 'react';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { staffRoleLabel } from '../../utils/roleLabels';
import { canCreateUsers, canDeleteUsers, canEditUsers } from '../../utils/roleMapping';
import SkeletonTable from '../Common/SkeletonTable';

// Role → badge color (no purple)
const ROLE_BADGE = {
  admin: 'b-orange',
  supervisor: 'b-green',
  officer: 'b-blue',
};

const Users = ({ openModal, onEditUser, refreshKey = 0, wsRefreshKey, isMobile }) => {
  const { user: me } = useAuth();
  const role = me?.role || 'officer';
  const canAdd    = canCreateUsers(role);
  const canEdit   = canEditUsers(role);
  const canDelete = canDeleteUsers(role);

  const [users, setUsers]             = useState([]);
  const [loading, setLoading]         = useState(true);
  const [stationsById, setStationsById] = useState({});
  const [searchText, setSearchText]   = useState('');
  const [roleFilter, setRoleFilter]   = useState('all');
  const [stationFilter, setStationFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [pageSize, setPageSize]       = useState(20);
  const [offset, setOffset]           = useState(0);

  const loadUsers = useCallback(() => {
    let mounted = true;
    setLoading(true);
    const params = new URLSearchParams();
    params.set('skip', String(offset));
    params.set('limit', String(pageSize));
    // Fetch users and stations in parallel
    Promise.all([
      api.get(`/api/v1/police-users/?${params.toString()}`),
      api.get('/api/v1/stations/?only_active=true'),
    ])
      .then(([usersRes, stationsRes]) => {
        if (!mounted) return;
        setUsers(usersRes || []);
        const map = {};
        (stationsRes?.items || []).forEach((st) => { map[st.station_id] = st; });
        setStationsById(map);
        setLoading(false);
      })
      .catch(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [offset, pageSize]);

  useEffect(() => { loadUsers(); }, [loadUsers, refreshKey, wsRefreshKey]);

  const deleteUser = async (u) => {
    if (!canDelete) return;
    if (!window.confirm(`Delete "${u.first_name} ${u.last_name}"? This cannot be undone.`)) return;
    try {
      await api.delete(`/api/v1/police-users/${u.police_user_id}`);
      setUsers((prev) => prev.filter((x) => x.police_user_id !== u.police_user_id));
    } catch (e) {
      window.alert(e?.message || 'Failed to delete user.');
    }
  };

  const toggleActive = async (u) => {
    try {
      const updated = await api.put(`/api/v1/police-users/${u.police_user_id}`, { is_active: !u.is_active });
      setUsers((prev) => prev.map((x) => (x.police_user_id === updated.police_user_id ? updated : x)));
    } catch (e) {
      window.alert(e?.message || 'Failed to update user status.');
    }
  };

  // Summary counts
  const admins      = users.filter((u) => u.role === 'admin').length;
  const supervisors = users.filter((u) => u.role === 'supervisor').length;
  const officers    = users.filter((u) => u.role === 'officer').length;

  const stationOptions = Object.values(stationsById).sort((a, b) =>
    (a.station_name || '').localeCompare(b.station_name || '')
  );

  const filteredUsers = users.filter((u) => {
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      const name  = `${u.first_name || ''} ${u.last_name || ''}`.toLowerCase();
      const email = (u.email || '').toLowerCase();
      const badge = (u.badge_number || '').toLowerCase();
      if (!name.includes(q) && !email.includes(q) && !badge.includes(q)) return false;
    }
    if (roleFilter !== 'all' && u.role !== roleFilter) return false;
    if (stationFilter !== 'all' && u.station_id !== Number(stationFilter)) return false;
    if (statusFilter !== 'all' && u.is_active !== (statusFilter === 'active')) return false;
    return true;
  });

  const totalPages  = Math.max(1, Math.ceil(filteredUsers.length / pageSize));
  const currentPage = Math.floor(offset / pageSize);
  const paged       = filteredUsers.slice(offset, offset + pageSize);
  const goToPage    = (p) => setOffset(p * pageSize);

  const hasFilters = searchText.trim() || roleFilter !== 'all' || stationFilter !== 'all' || statusFilter !== 'all';

  return (
    <>
      {!isMobile && (
        <div className="page-header">
          <h2>User Management</h2>
          <p>Manage officers, IOs, and DPC accounts with role-based access control.</p>
        </div>
      )}

      {/* Summary stat cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        {[
          { label: 'Total Accounts', value: users.length, sub: 'All registered users', cls: 'sb-blue' },
          { label: 'DPC',            value: admins,       sub: 'Administrators',        cls: 'sb-orange' },
          { label: 'IO',             value: supervisors,  sub: 'Investigating Officers', cls: 'sb-green' },
          { label: 'Officers',       value: officers,     sub: 'Field officers',         cls: 'sb-blue' },
        ].map((s) => (
          <div key={s.label} className={`stat-btn ${s.cls}`} style={{ cursor: 'default' }}>
            <div className="stat-btn-label">{s.label}</div>
            <div className="stat-btn-value">{s.value}</div>
            <div className="stat-btn-sub">{s.sub}</div>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="card-header">
          <div className="card-title">Officer Roster</div>
          {canAdd && (
            <button className="btn btn-primary btn-sm" onClick={() => openModal('addUser')}>
              + Add User
            </button>
          )}
        </div>

        {/* Filters */}
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
          <div className="filter-row">
            <input
              className="input"
              placeholder="Search by name, email, or badge…"
              style={{ flex: 2 }}
              value={searchText}
              onChange={(e) => { setSearchText(e.target.value); setOffset(0); }}
            />
            <select className="select" value={roleFilter} onChange={(e) => { setRoleFilter(e.target.value); setOffset(0); }}>
              <option value="all">All Roles</option>
              <option value="admin">DPC</option>
              <option value="supervisor">IO</option>
              <option value="officer">Officer</option>
            </select>
            <select className="select" value={stationFilter} onChange={(e) => { setStationFilter(e.target.value); setOffset(0); }}>
              <option value="all">All Stations</option>
              {stationOptions.map((st) => (
                <option key={st.station_id} value={st.station_id}>{st.station_name}</option>
              ))}
            </select>
            <select className="select" value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setOffset(0); }}>
              <option value="all">All Statuses</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
            <select
              className="select"
              style={{ width: 'auto' }}
              value={pageSize}
              onChange={(e) => { setPageSize(Number(e.target.value)); setOffset(0); }}
            >
              <option value={10}>10 / page</option>
              <option value={20}>20 / page</option>
              <option value={50}>50 / page</option>
            </select>
          </div>
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
                <th>Status</th>
                <th>Last Login</th>
                {(canEdit || canDelete) && <th />}
              </tr>
            </thead>
            <tbody>
              {loading && <SkeletonTable cols={9} rows={7} />}
              {!loading && paged.length === 0 && (
                <tr>
                  <td colSpan={9} style={{ textAlign: 'center', color: 'var(--muted)', fontSize: 12, padding: 40 }}>
                    {users.length === 0 ? 'No users registered.' : (
                      <>
                        No users match the current filters.{' '}
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          style={{ marginLeft: 8 }}
                          onClick={() => { setSearchText(''); setRoleFilter('all'); setStationFilter('all'); setStatusFilter('all'); }}
                        >
                          Clear filters
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              )}
              {!loading && paged.map((u, index) => {
                const roleBadge = ROLE_BADGE[u.role] || 'b-blue';
                const station   = u.station_id ? stationsById[u.station_id] : null;

                return (
                  <tr key={u.police_user_id}>
                    <td style={{ fontSize: 12, color: 'var(--muted)', textAlign: 'center', width: 36 }}>
                      {offset + index + 1}
                    </td>
                    <td>
                      <span className={`badge ${roleBadge}`} style={{ fontFamily: 'monospace', letterSpacing: '0.5px' }}>
                        {u.badge_number || `ID-${u.police_user_id}`}
                      </span>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{u.first_name} {u.last_name}</div>
                    </td>
                    <td style={{ fontSize: 11, color: 'var(--muted)' }}>{u.email}</td>
                    <td>
                      <span className={`badge ${roleBadge}`}>{staffRoleLabel(u.role)}</span>
                    </td>
                    <td style={{ fontSize: 12 }}>
                      {station ? (
                        <span>{station.station_name}</span>
                      ) : (
                        <span style={{ color: 'var(--muted)' }}>—</span>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${u.is_active ? 'b-green' : 'b-gray'}`}>
                        {u.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td style={{ fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                      {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : '—'}
                    </td>
                    {(canEdit || canDelete) && (
                      <td>
                        <div style={{ display: 'flex', gap: 4 }}>
                          {canEdit && (
                            <button className="btn btn-outline btn-sm" onClick={() => onEditUser?.(u)}>
                              Edit
                            </button>
                          )}
                          {canEdit && (
                            <button className="btn btn-outline btn-sm" onClick={() => toggleActive(u)}>
                              {u.is_active ? 'Deactivate' : 'Activate'}
                            </button>
                          )}
                          {canDelete && (
                            <button className="btn btn-danger btn-sm" onClick={() => deleteUser(u)}>
                              Delete
                            </button>
                          )}
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {!loading && filteredUsers.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', flexWrap: 'wrap', gap: 8 }}>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>
              Showing {Math.min(offset + 1, filteredUsers.length)}–{Math.min(offset + pageSize, filteredUsers.length)} of {filteredUsers.length} user{filteredUsers.length !== 1 ? 's' : ''}
              {hasFilters && users.length !== filteredUsers.length && ` (filtered from ${users.length})`}
            </div>
            {totalPages > 1 && (
              <div className="pagination">
                <button className="page-btn" onClick={() => goToPage(currentPage - 1)} disabled={currentPage === 0}>‹</button>
                {Array.from({ length: totalPages }, (_, i) => (
                  <button
                    key={i}
                    className={`page-btn ${i === currentPage ? 'current' : ''}`}
                    onClick={() => goToPage(i)}
                  >
                    {i + 1}
                  </button>
                ))}
                <button className="page-btn" onClick={() => goToPage(currentPage + 1)} disabled={currentPage >= totalPages - 1}>›</button>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
};

export default Users;
