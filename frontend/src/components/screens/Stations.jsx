import React, { useCallback, useEffect, useState } from 'react';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { canManageStations } from '../../utils/roleMapping';
import SkeletonTable from '../Common/SkeletonTable';

const TYPE_LABELS = {
  police_station: 'Police Station',
  post: 'Police Post',
  outpost: 'Outpost',
};

const TYPE_BADGE = {
  police_station: 'b-blue',
  post: 'b-green',
  outpost: 'b-gray',
};

const Stations = ({ openModal, wsRefreshKey }) => {
  const { user: me } = useAuth();
  const canManage = canManageStations(me?.role);

  const [stations, setStations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [pageSize, setPageSize] = useState(20);
  const [offset, setOffset] = useState(0);

  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams();
    if (searchText.trim()) params.set('search', searchText.trim());
    if (statusFilter !== 'all') params.set('only_active', statusFilter === 'active' ? 'true' : 'false');
    api.get(`/api/v1/stations/?${params.toString()}`)
      .then((res) => { setStations(res?.items || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [searchText, statusFilter]);

  useEffect(() => { load(); }, [load, wsRefreshKey]);

  const filteredStations = stations.filter((s) =>
    typeFilter === 'all' || s.station_type === typeFilter
  );
  const totalPages = Math.max(1, Math.ceil(filteredStations.length / pageSize));
  const currentPage = Math.floor(offset / pageSize);
  const paginatedStations = filteredStations.slice(offset, offset + pageSize);

  const goToPage = (page) => setOffset(page * pageSize);

  const handleToggleActive = async (station) => {
    try {
      const updated = await api.put(`/api/v1/stations/${station.station_id}`, {
        is_active: !station.is_active,
      });
      setStations((prev) => prev.map((s) => (s.station_id === updated.station_id ? updated : s)));
    } catch (e) {
      window.alert(e.message || 'Failed to update station status');
    }
  };

  const handleDelete = async (station) => {
    if (!window.confirm(`Delete station "${station.station_name}"? This cannot be undone.`)) return;
    try {
      await api.delete(`/api/v1/stations/${station.station_id}`);
      setStations((prev) => prev.filter((s) => s.station_id !== station.station_id));
    } catch (e) {
      window.alert(e.message || 'Failed to delete station');
    }
  };

  const totalActive = stations.filter((s) => s.is_active).length;
  const totalCells = stations.reduce((n, s) => n + (s.covered_cell_names?.length || 0), 0);
  const hasFilters = searchText.trim() || typeFilter !== 'all' || statusFilter !== 'all';

  return (
    <>
      <div className="page-header">
        <h2>Stations</h2>
        <p>Manage police stations and posts mapped to Musanze locations.</p>
      </div>

      {/* Summary stat cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 16 }}>
        {[
          { label: 'Total Stations', value: stations.length, sub: 'Registered stations', cls: 'sb-blue' },
          { label: 'Active', value: totalActive, sub: 'Currently operational', cls: totalActive ? 'sb-green' : 'sb-gray' },
          { label: 'Cells Covered', value: totalCells, sub: 'Geographic coverage', cls: 'sb-purple' },
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
          <div className="card-title">Registered Stations</div>
          {canManage && (
            <button className="btn btn-primary btn-sm" onClick={() => openModal('addStation')}>
              + Add Station
            </button>
          )}
        </div>

        {/* Filters */}
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
          <div className="filter-row">
            <input
              className="input"
              placeholder="Search by name, code, or location…"
              style={{ flex: 2 }}
              value={searchText}
              onChange={(e) => { setSearchText(e.target.value); setOffset(0); }}
            />
            <select
              className="select"
              value={typeFilter}
              onChange={(e) => { setTypeFilter(e.target.value); setOffset(0); }}
            >
              <option value="all">All Types</option>
              <option value="police_station">Police Station</option>
              <option value="post">Police Post</option>
              <option value="outpost">Outpost</option>
            </select>
            <select
              className="select"
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setOffset(0); }}
            >
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
                <th>Code</th>
                <th>Name</th>
                <th>Type</th>
                <th>Coverage (cells)</th>
                <th>Contact</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {loading && <SkeletonTable cols={8} rows={5} />}
              {!loading && paginatedStations.length === 0 && (
                <tr>
                  <td colSpan={8} style={{ textAlign: 'center', color: 'var(--muted)', fontSize: 12, padding: 40 }}>
                    {stations.length === 0 ? (
                      <>
                        <div style={{ fontSize: 28, marginBottom: 8 }}>🏢</div>
                        <div style={{ fontWeight: 600, marginBottom: 4 }}>No stations registered</div>
                        <div style={{ fontSize: 11 }}>Add a station to get started.</div>
                      </>
                    ) : (
                      <>
                        No stations match the current filters.{' '}
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          style={{ marginLeft: 8 }}
                          onClick={() => { setSearchText(''); setTypeFilter('all'); setStatusFilter('all'); }}
                        >
                          Clear filters
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              )}
              {!loading && paginatedStations.map((s, index) => {
                const typeBadge = TYPE_BADGE[s.station_type] || 'b-gray';
                const typeLabel = TYPE_LABELS[s.station_type] || s.station_type;
                const cells = s.covered_cell_names || [];

                return (
                  <tr key={s.station_id}>
                    <td style={{ fontSize: 12, color: 'var(--muted)', textAlign: 'center', width: 36 }}>
                      {offset + index + 1}
                    </td>
                    <td>
                      <span className={`badge ${typeBadge}`} style={{ fontFamily: 'monospace', letterSpacing: '0.5px' }}>
                        {s.station_code}
                      </span>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{s.station_name}</div>
                    </td>
                    <td>
                      <span className={`badge ${typeBadge}`} style={{ fontSize: 10 }}>{typeLabel}</span>
                    </td>
                    <td>
                      {cells.length > 0 ? (
                        <>
                          <div style={{ fontWeight: 600, fontSize: 12 }}>{cells.length} cell{cells.length !== 1 ? 's' : ''}</div>
                          <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>
                            {cells.slice(0, 3).join(', ')}{cells.length > 3 ? ` +${cells.length - 3} more` : ''}
                          </div>
                        </>
                      ) : (
                        <span style={{ color: 'var(--muted)', fontSize: 12 }}>—</span>
                      )}
                    </td>
                    <td style={{ fontSize: 11 }}>
                      {s.phone_number && <div>{s.phone_number}</div>}
                      {s.email && <div style={{ color: 'var(--muted)' }}>{s.email}</div>}
                      {!s.phone_number && !s.email && <span style={{ color: 'var(--muted)' }}>—</span>}
                    </td>
                    <td>
                      <span className={`badge ${s.is_active ? 'b-green' : 'b-gray'}`}>
                        {s.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: 4 }}>
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => openModal('viewStation', s)}
                        >
                          View
                        </button>
                        {canManage && (
                          <>
                            <button
                              className="btn btn-outline btn-sm"
                              onClick={() => openModal('editStation', s)}
                            >
                              Edit
                            </button>
                            <button
                              className="btn btn-outline btn-sm"
                              onClick={() => handleToggleActive(s)}
                            >
                              {s.is_active ? 'Deactivate' : 'Activate'}
                            </button>
                            <button
                              className="btn btn-danger btn-sm"
                              onClick={() => handleDelete(s)}
                            >
                              Delete
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {!loading && filteredStations.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', flexWrap: 'wrap', gap: 8 }}>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>
              Showing {Math.min(offset + 1, filteredStations.length)}–{Math.min(offset + pageSize, filteredStations.length)} of {filteredStations.length} station{filteredStations.length !== 1 ? 's' : ''}
              {hasFilters && stations.length !== filteredStations.length && ` (filtered from ${stations.length})`}
            </div>
            {totalPages > 1 && (
              <div className="pagination">
                <button
                  className="page-btn"
                  onClick={() => goToPage(currentPage - 1)}
                  disabled={currentPage === 0}
                >
                  ‹
                </button>
                {Array.from({ length: totalPages }, (_, i) => (
                  <button
                    key={i}
                    className={`page-btn ${i === currentPage ? 'current' : ''}`}
                    onClick={() => goToPage(i)}
                  >
                    {i + 1}
                  </button>
                ))}
                <button
                  className="page-btn"
                  onClick={() => goToPage(currentPage + 1)}
                  disabled={currentPage >= totalPages - 1}
                >
                  ›
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
};

export default Stations;
