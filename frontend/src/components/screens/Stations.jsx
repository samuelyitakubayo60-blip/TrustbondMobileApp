import React, { useEffect, useState, useCallback } from 'react';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { canManageStations } from '../../utils/roleMapping';

const PAGE_SIZE = 20;

const TYPE_LABELS = {
  headquarters: 'HQ',
  police_station: 'Station',
  post: 'Post',
  outpost: 'Outpost',
};

const TYPE_BADGE = {
  headquarters: 'b-purple',
  police_station: 'b-blue',
  post: 'b-green',
  outpost: 'b-orange',
};

const Stations = ({ openModal, wsRefreshKey }) => {
  const { user: me } = useAuth();
  const canManage = canManageStations(me?.role);
  const [stations, setStations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [offset, setOffset] = useState(0);

  const load = useCallback(() => {
    Promise.resolve().then(() => setLoading(true));
    const params = new URLSearchParams();
    if (searchText.trim()) params.set('search', searchText.trim());
    if (statusFilter !== 'all') params.set('only_active', statusFilter === 'active' ? 'true' : 'false');
    api.get(`/api/v1/stations/?${params.toString()}`)
      .then((res) => {
        setStations(res?.items || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [searchText, statusFilter]);

  useEffect(() => { load(); }, [load, wsRefreshKey]);

  const filteredStations = stations.filter((s) =>
    typeFilter === 'all' || s.station_type === typeFilter
  );
  const paginatedStations = filteredStations.slice(offset, offset + pageSize);
  const totalPages = Math.ceil(filteredStations.length / pageSize);

  // Stat card values
  const activeCount = stations.filter((s) => s.is_active).length;
  const inactiveCount = stations.length - activeCount;
  const totalCells = stations.reduce((sum, s) => sum + (s.covered_cell_names?.length || 0), 0);

  const handleToggleActive = async (station) => {
    try {
      const updated = await api.put(`/api/v1/stations/${station.station_id}`, { is_active: !station.is_active });
      setStations((prev) => prev.map((s) => s.station_id === updated.station_id ? updated : s));
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

  return (
    <>
      {/* ── Page header ── */}
      <div className="card" style={{ marginBottom: 20, padding: '20px 24px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
          <div>
            <h2 style={{ margin: 0, marginBottom: 4, fontSize: 22 }}>Stations</h2>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: 13 }}>
              Police stations and posts mapped to Musanze district locations.
            </p>
          </div>
          {canManage && (
            <button className="btn btn-primary btn-sm" style={{ alignSelf: 'center' }} onClick={() => openModal('addStation')}>
              + Add Station
            </button>
          )}
        </div>

        {/* Stat cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {[
            { label: 'Total Stations',    value: stations.length, cls: 'sb-blue'  },
            { label: 'Active',            value: activeCount,     cls: 'sb-green' },
            { label: 'Inactive',          value: inactiveCount,   cls: 'sb-red'   },
            { label: 'Cells Covered',     value: totalCells,      cls: 'sb-blue'  },
          ].map((s) => (
            <div key={s.label} className={`stat-btn ${s.cls}`} style={{ cursor: 'default' }}>
              <div className="stat-btn-label">{s.label}</div>
              <div className="stat-btn-value">{loading ? '…' : s.value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Table card ── */}
      <div className="card">
        <div className="filter-row">
          <input
            className="input"
            placeholder="Search by name, code, or location…"
            style={{ flex: 2 }}
            value={searchText}
            onChange={(e) => { setSearchText(e.target.value); setOffset(0); }}
          />
          <select className="select" value={typeFilter} onChange={(e) => { setTypeFilter(e.target.value); setOffset(0); }}>
            <option value="all">All Types</option>
            <option value="headquarters">Headquarters</option>
            <option value="police_station">Police Station</option>
            <option value="post">Police Post</option>
            <option value="outpost">Outpost</option>
          </select>
          <select className="select" value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setOffset(0); }}>
            <option value="all">All Status</option>
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

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Code</th>
                <th>Name</th>
                <th>Type</th>
                <th>Coverage</th>
                <th>Contact</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {paginatedStations.map((s, index) => (
                <tr key={s.station_id}>
                  <td style={{ fontSize: 12, color: 'var(--muted)', textAlign: 'center' }}>
                    {offset + index + 1}
                  </td>
                  <td>
                    <span className="badge b-blue" style={{ fontFamily: 'monospace', letterSpacing: '0.04em' }}>
                      {s.station_code}
                    </span>
                  </td>
                  <td>
                    <div style={{ fontWeight: 600, fontSize: 13 }}>{s.station_name}</div>
                    {s.address_text && (
                      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{s.address_text}</div>
                    )}
                  </td>
                  <td>
                    <span className={`badge ${TYPE_BADGE[s.station_type] || 'b-gray'}`} style={{ fontSize: 10 }}>
                      {TYPE_LABELS[s.station_type] || s.station_type || '—'}
                    </span>
                  </td>
                  <td>
                    {s.covered_cell_names?.length > 0 ? (
                      <>
                        <div style={{ fontWeight: 600, fontSize: 12 }}>
                          {s.covered_cell_names.length} cell{s.covered_cell_names.length !== 1 ? 's' : ''}
                        </div>
                        <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 1 }}>
                          {s.covered_cell_names.slice(0, 3).join(', ')}{s.covered_cell_names.length > 3 ? '…' : ''}
                        </div>
                      </>
                    ) : (
                      <span style={{ fontSize: 11, color: 'var(--muted)' }}>—</span>
                    )}
                  </td>
                  <td style={{ fontSize: 11 }}>
                    {s.phone_number ? (
                      <div>{s.phone_number}</div>
                    ) : null}
                    {s.email ? (
                      <div style={{ color: 'var(--muted)', marginTop: 1 }}>{s.email}</div>
                    ) : null}
                    {!s.phone_number && !s.email && <span style={{ color: 'var(--muted)' }}>—</span>}
                  </td>
                  <td>
                    <span className={`badge ${s.is_active ? 'b-green' : 'b-red'}`}>
                      {s.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={() => openModal('viewStation', s)}
                      >
                        View Details
                      </button>
                      {canManage && (
                        <>
                          <button className="btn btn-outline btn-sm" onClick={() => openModal('editStation', s)}>
                            Edit
                          </button>
                          <button className="btn btn-warn btn-sm" onClick={() => handleToggleActive(s)}>
                            {s.is_active ? 'Deactivate' : 'Activate'}
                          </button>
                          <button className="btn btn-danger btn-sm" onClick={() => handleDelete(s)}>
                            Delete
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {!paginatedStations.length && !loading && (
                <tr>
                  <td colSpan={8} style={{ textAlign: 'center', fontSize: 12, color: 'var(--muted)', padding: '32px 0' }}>
                    No stations found.
                  </td>
                </tr>
              )}
              {loading && (
                <tr>
                  <td colSpan={8} style={{ textAlign: 'center', fontSize: 12, color: 'var(--muted)', padding: '32px 0' }}>
                    Loading stations…
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 14, flexWrap: 'wrap', gap: 8 }}>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
            Showing {filteredStations.length === 0 ? 0 : offset + 1}–{Math.min(offset + pageSize, filteredStations.length)} of {filteredStations.length} station{filteredStations.length !== 1 ? 's' : ''}
          </div>
          <div className="pagination">
            <button className="page-btn" onClick={() => setOffset(Math.max(0, offset - pageSize))} disabled={offset === 0}>‹</button>
            {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
              const pageNum = i + 1;
              const isCurrent = Math.floor(offset / pageSize) === i;
              return (
                <button
                  key={pageNum}
                  className={`page-btn ${isCurrent ? 'current' : ''}`}
                  onClick={() => setOffset(i * pageSize)}
                >
                  {pageNum}
                </button>
              );
            })}
            <button className="page-btn" onClick={() => setOffset(Math.min((totalPages - 1) * pageSize, offset + pageSize))} disabled={offset + pageSize >= filteredStations.length}>›</button>
          </div>
        </div>
      </div>
    </>
  );
};

export default Stations;
