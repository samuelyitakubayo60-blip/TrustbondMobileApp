import React, { useEffect, useState, useCallback } from 'react';
import api from '../../api/client';

const PAGE_SIZE = 20;

const Stations = ({ openModal, wsRefreshKey }) => {
  const [stations, setStations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);

  const load = useCallback(() => {
    Promise.resolve().then(() => setLoading(true));
    
    const params = new URLSearchParams();
    if (searchText.trim()) {
      params.set("search", searchText.trim());
    }
    if (statusFilter !== "all") {
      params.set("only_active", statusFilter === "active" ? "true" : "false");
    }
    
    api.get(`/api/v1/stations/?${params.toString()}`)
      .then((res) => {
        setStations(res?.items || []);
        setTotal(res?.total || 0);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [searchText, statusFilter]);

  useEffect(() => {
    load();
  }, [load, wsRefreshKey]);

  // Client-side filtering for type filter since backend doesn't support it
  const filteredStations = stations.filter((s) => {
    if (typeFilter !== "all" && s.station_type !== typeFilter) {
      return false;
    }
    return true;
  });

  // Client-side pagination for filtered stations
  const paginatedStations = filteredStations.slice(offset, offset + pageSize);

  const handleToggleActive = async (station) => {
    try {
      const updated = await api.put(`/api/v1/stations/${station.station_id}`, {
        is_active: !station.is_active,
      });
      setStations((prev) =>
        prev.map((s) =>
          s.station_id === updated.station_id ? updated : s
        )
      );
    } catch (e) {
      window.alert(e.message || 'Failed to update station status');
    }
  };

  const handleDelete = async (station) => {
    if (!window.confirm(`Delete station "${station.station_name}"? This cannot be undone.`)) {
      return;
    }
    try {
      await api.delete(`/api/v1/stations/${station.station_id}`);
      setStations((prev) =>
        prev.filter((s) => s.station_id !== station.station_id)
      );
    } catch (e) {
      window.alert(e.message || 'Failed to delete station');
    }
  };

  return (
    <>
      <div className="page-header">
        <h2>Stations</h2>
        <p>Manage police stations and posts mapped to Musanze locations.</p>
      </div>

      <div className="card">
        <div className="card-header">
          <div className="card-title">Registered Stations</div>
          <button className="btn btn-primary btn-sm" onClick={() => openModal('addStation')}>Add Station</button>
        </div>

        <div className="filter-row">
          <input
            className="input"
            placeholder="Search by name, code, or location..."
            style={{ flex: 2 }}
            value={searchText}
            onChange={(e) => {
              setSearchText(e.target.value);
              setOffset(0);
            }}
          />
          <select
            className="select"
            value={typeFilter}
            onChange={(e) => {
              setTypeFilter(e.target.value);
              setOffset(0);
            }}
          >
            <option value="all">All Types</option>
            <option value="police_station">Police Station</option>
            <option value="post">Police Post</option>
            <option value="outpost">Outpost</option>
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
                <th>Code</th>
                <th>Name</th>
                <th>Type</th>
                <th>Sector / Location</th>
                <th>Contact</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {paginatedStations.map((s, index) => (
                <tr key={s.station_id}>
                  <td style={{ fontSize: "12px", color: "var(--muted)", textAlign: "center" }}>
                    {offset + index + 1}
                  </td>
                  <td><span className="badge b-blue">{s.station_code}</span></td>
                  <td><strong>{s.station_name}</strong></td>
                  <td style={{ fontSize: '11px', color: 'var(--muted)' }}>{s.station_type}</td>
                  <td style={{ fontSize: '11px', color: 'var(--muted)' }}>
                    {s.location_name || '—'}
                    {s.sector2_name && (
                      <div style={{ fontSize: '10px', color: 'var(--muted)', marginTop: '2px' }}>
                        + {s.sector2_name}
                      </div>
                    )}
                  </td>
                  <td style={{ fontSize: '11px', color: 'var(--muted)' }}>
                    {s.phone_number || '—'}
                    {s.email ? ` · ${s.email}` : ''}
                  </td>
                  <td>
                    <span className={`badge ${s.is_active ? 'b-green' : 'b-red'}`}>
                      {s.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: '4px' }}>
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={() => openModal('viewStation', s)}
                      >
                        View Details
                      </button>
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
                    </div>
                  </td>
                </tr>
              ))}
              {(!paginatedStations.length && !loading) && (
                <tr>
                  <td colSpan={8} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    No stations found.
                  </td>
                </tr>
              )}
              {loading && (
                <tr>
                  <td colSpan={8} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    Loading...
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '14px', flexWrap: 'wrap', gap: '8px' }}>
          <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
            Showing {Math.min(offset + 1, filteredStations.length)}-{Math.min(offset + pageSize, filteredStations.length)} of {filteredStations.length} stations
          </div>
          <div className="pagination">
            <button 
              className="page-btn" 
              onClick={() => setOffset(Math.max(0, offset - pageSize))}
              disabled={offset === 0}
            >
              ‹
            </button>
            {Array.from({ length: Math.min(5, Math.ceil(filteredStations.length / pageSize)) }, (_, i) => {
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
              onClick={() => setOffset(Math.min(filteredStations.length - pageSize, offset + pageSize))}
              disabled={offset + pageSize >= filteredStations.length}
            >
              ›
            </button>
          </div>
        </div>
      </div>
    </>
  );
};

export default Stations;

