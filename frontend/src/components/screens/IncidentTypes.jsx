import React, { useEffect, useRef, useState } from 'react';
import SkeletonTable from '../Common/SkeletonTable';
import api from '../../api/client';
import Chart from 'chart.js/auto';
import { useAuth } from '../../context/AuthContext';
import { canManageAssignmentUnits, canManageIncidentTypes } from '../../utils/roleMapping';

const SEV_LEVEL = (val) => {
  if (val >= 1.6) return { label: 'Severe', badge: 'b-red' };
  if (val >= 1.3) return { label: 'High', badge: 'b-orange' };
  if (val >= 1.1) return { label: 'Medium', badge: 'b-blue' };
  return { label: 'Low', badge: 'b-gray' };
};

const IncidentTypes = ({ openModal, onEditIncidentType, refreshKey, wsRefreshKey, goToScreen }) => {
  const { user: me } = useAuth();
  const role = me?.role || 'officer';
  const canManage = canManageIncidentTypes(role);

  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [chartCounts, setChartCounts] = useState({});
  const [viewBy, setViewBy] = useState('incidentType');
  const [sortOrder, setSortOrder] = useState('desc');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  const chartRef = useRef(null);
  const chartInstance = useRef(null);

  const loadTypes = () => {
    setLoading(true);
    Promise.all([
      api.get('/api/v1/incident-types/?include_inactive=true'),
      api.get('/api/v1/reports/?limit=100'),
    ])
      .then(([typesRes, reportsRes]) => {
        setTypes(typesRes || []);
        buildChartCounts(reportsRes);
        setLoading(false);
      })
      .catch(() => {
        api.get('/api/v1/incident-types/?include_inactive=true')
          .then((res) => { setTypes(res || []); setLoading(false); })
          .catch(() => setLoading(false));
      });
  };

  const buildChartCounts = (reports) => {
    let arr = [];
    if (Array.isArray(reports)) arr = reports;
    else if (reports?.items) arr = reports.items;
    else if (reports?.data) arr = reports.data;
    else if (reports?.reports) arr = reports.reports;

    const byType = {};
    const bySector = {};
    const byStation = {};

    arr.forEach((r) => {
      const typeName = r.incident_type?.type_name || r.incident_type_name || 'Unknown';
      byType[typeName] = (byType[typeName] || 0) + 1;

      const sector = r.sector_name || r.sector || null;
      if (sector) bySector[sector] = (bySector[sector] || 0) + 1;

      const station = r.assigned_station?.station_name || r.station_name || r.station || null;
      if (station) byStation[station] = (byStation[station] || 0) + 1;
    });

    setChartCounts({ incidentType: byType, sector: bySector, stations: byStation });
  };

  const getChartDataset = () => {
    const raw = chartCounts[viewBy] || {};
    const entries = Object.entries(raw).sort((a, b) =>
      sortOrder === 'desc' ? b[1] - a[1] : a[1] - b[1]
    );
    return {
      labels: entries.length ? entries.map(([k]) => k) : ['No data'],
      data: entries.length ? entries.map(([, v]) => v) : [0],
    };
  };

  useEffect(() => {
    if (!chartRef.current) return;
    if (chartInstance.current) {
      chartInstance.current.destroy();
      chartInstance.current = null;
    }
    const { labels, data } = getChartDataset();

    // Read design-system colors at render time so chart matches the active theme
    const style = getComputedStyle(document.documentElement);
    const accent = style.getPropertyValue('--accent').trim() || '#3b82f6';
    const muted  = style.getPropertyValue('--muted').trim()  || '#94a3b8';
    const border = style.getPropertyValue('--border').trim() || '#e2e8f0';

    // Build per-bar colors keyed to severity thresholds when viewing by incident type
    const bgColors = data.map(() => `${accent}c0`);   // accent @ ~75% opacity
    const bdColors = data.map(() => accent);

    chartInstance.current = new Chart(chartRef.current, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Incidents',
          data,
          backgroundColor: bgColors,
          borderColor: bdColors,
          borderWidth: 1,
          borderRadius: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => ` ${ctx.parsed.y} incident${ctx.parsed.y !== 1 ? 's' : ''}` } },
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: { stepSize: 1, color: muted, font: { size: 11 } },
            grid: { color: `${border}` },
          },
          x: {
            ticks: { maxRotation: 40, font: { size: 11 }, color: muted },
            grid: { display: false },
          },
        },
      },
    });
    return () => {
      if (chartInstance.current) {
        chartInstance.current.destroy();
        chartInstance.current = null;
      }
    };
  }, [chartCounts, viewBy, sortOrder]);

  useEffect(() => {
    loadTypes();
  }, [refreshKey, wsRefreshKey]);

  const handleToggleActive = async (type) => {
    try {
      const updated = await api.put(`/api/v1/incident-types/${type.incident_type_id}`, {
        is_active: !type.is_active,
      });
      setTypes((prev) =>
        prev.map((t) => (t.incident_type_id === updated.incident_type_id ? updated : t))
      );
    } catch (e) {
      window.alert(e.message || 'Failed to update incident type status');
    }
  };

  const handleDelete = async (type) => {
    if (!window.confirm(`Delete incident type "${type.type_name}"? This cannot be undone.`)) return;
    try {
      await api.delete(`/api/v1/incident-types/${type.incident_type_id}`);
      setTypes((prev) => prev.filter((t) => t.incident_type_id !== type.incident_type_id));
    } catch (e) {
      window.alert(e.message || 'Failed to delete incident type');
    }
  };

  const filtered = types.filter((t) => {
    if (statusFilter === 'active' && !t.is_active) return false;
    if (statusFilter === 'inactive' && t.is_active) return false;
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      if (!(t.type_name || '').toLowerCase().includes(q) && !(t.description || '').toLowerCase().includes(q)) return false;
    }
    return true;
  });

  const totalActive = types.filter((t) => t.is_active).length;
  const totalInactive = types.length - totalActive;
  const maxSev = types.reduce((m, t) => Math.max(m, Number(t.severity_weight ?? 1)), 0);

  const VIEW_LABELS = { incidentType: 'By Type', sector: 'By Sector', stations: 'By Station' };

  return (
    <>
      <div className="page-header">
        <h2>Incident Types</h2>
        <p>Configure categories and priority levels for incident reporting and analysis.</p>
      </div>

      {/* Summary stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 16 }}>
        {[
          { label: 'Total Types', value: types.length, sub: 'Registered categories', cls: 'sb-blue' },
          { label: 'Active', value: totalActive, sub: 'Currently in use', cls: totalActive ? 'sb-green' : 'sb-gray' },
          { label: 'Inactive', value: totalInactive, sub: 'Disabled categories', cls: totalInactive ? 'sb-orange' : 'sb-gray' },
        ].map((s) => (
          <div key={s.label} className={`stat-btn ${s.cls}`} style={{ cursor: 'default' }}>
            <div className="stat-btn-label">{s.label}</div>
            <div className="stat-btn-value">{s.value}</div>
            <div className="stat-btn-sub">{s.sub}</div>
          </div>
        ))}
      </div>

      {/* Distribution chart */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-header" style={{ flexWrap: 'wrap', gap: 8 }}>
          <div className="card-title">Distribution Analysis</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', gap: 4 }}>
              {Object.entries(VIEW_LABELS).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  className={`btn btn-sm ${viewBy === key ? 'btn-primary' : 'btn-outline'}`}
                  onClick={() => setViewBy(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            <select
              className="select"
              style={{ width: 'auto', fontSize: 12, padding: '4px 8px', height: 'auto' }}
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value)}
            >
              <option value="desc">Highest first</option>
              <option value="asc">Lowest first</option>
            </select>
          </div>
        </div>
        <div style={{ padding: '16px 20px' }}>
          <div style={{ height: 220, position: 'relative' }}>
            <canvas ref={chartRef} />
          </div>
        </div>
      </div>

      {/* Categories table */}
      <div className="card">
        <div className="card-header" style={{ flexWrap: 'wrap', gap: 8 }}>
          <div className="card-title">Incident Categories</div>
          <div style={{ display: 'flex', gap: 8 }}>
            {canManage && goToScreen && canManageAssignmentUnits(role) && (
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={() => goToScreen('special-assignment-units', 17)}
              >
                Assignment Units
              </button>
            )}
            {canManage && (
              <button className="btn btn-primary btn-sm" onClick={() => openModal('addIncident')}>
                + Add Type
              </button>
            )}
          </div>
        </div>

        {/* Filters */}
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
          <div className="filter-row">
            <input
              className="input"
              placeholder="Search by name or description…"
              style={{ flex: 2 }}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <select
              className="select"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="all">All Statuses</option>
              <option value="active">Active only</option>
              <option value="inactive">Inactive only</option>
            </select>
          </div>
        </div>

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Name</th>
                <th>Description</th>
                <th>Severity</th>
                <th>Level</th>
                <th>Status</th>
                {canManage && <th />}
              </tr>
            </thead>
            <tbody>
              {loading && <SkeletonTable cols={canManage ? 7 : 6} rows={5} />}
              {!loading && filtered.length === 0 && (
                <tr>
                  <td colSpan={canManage ? 7 : 6} style={{ textAlign: 'center', color: 'var(--muted)', fontSize: 12, padding: 32 }}>
                    {types.length === 0 ? 'No incident types configured.' : 'No types match the current filters.'}
                    {types.length > 0 && search && (
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        style={{ marginLeft: 8 }}
                        onClick={() => { setSearch(''); setStatusFilter('all'); }}
                      >
                        Clear filters
                      </button>
                    )}
                  </td>
                </tr>
              )}
              {!loading && filtered.map((t, index) => {
                const val = Number(t.severity_weight ?? 1);
                const { label, badge } = SEV_LEVEL(val);
                const barPct = maxSev > 0 ? Math.round((val / maxSev) * 100) : 0;

                return (
                  <tr key={t.incident_type_id}>
                    <td style={{ fontSize: 12, color: 'var(--muted)', textAlign: 'center', width: 36 }}>
                      {index + 1}
                    </td>
                    <td>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{t.type_name}</div>
                    </td>
                    <td style={{ fontSize: 11, color: 'var(--muted)', maxWidth: 220 }}>
                      {t.description || <span style={{ fontStyle: 'italic' }}>No description</span>}
                    </td>
                    <td style={{ minWidth: 90 }}>
                      <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 3 }}>
                        {val.toFixed(2)}
                      </div>
                      <div style={{ background: 'var(--border)', borderRadius: 3, height: 4, width: 72 }}>
                        <div
                          style={{
                            height: 4,
                            borderRadius: 3,
                            width: `${barPct}%`,
                            background: val >= 1.6 ? 'var(--danger)' : val >= 1.3 ? 'var(--warning)' : val >= 1.1 ? 'var(--accent)' : 'var(--text-dim)',
                            transition: 'width 0.3s',
                          }}
                        />
                      </div>
                    </td>
                    <td><span className={`badge ${badge}`}>{label}</span></td>
                    <td>
                      <span className={`badge ${t.is_active ? 'b-green' : 'b-gray'}`}>
                        {t.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    {canManage && (
                      <td>
                        <div style={{ display: 'flex', gap: 4 }}>
                          <button
                            className="btn btn-outline btn-sm"
                            onClick={() => onEditIncidentType?.(t)}
                          >
                            Edit
                          </button>
                          <button
                            className="btn btn-outline btn-sm"
                            onClick={() => handleToggleActive(t)}
                          >
                            {t.is_active ? 'Deactivate' : 'Activate'}
                          </button>
                          <button
                            className="btn btn-danger btn-sm"
                            onClick={() => handleDelete(t)}
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {!loading && filtered.length > 0 && (search || statusFilter !== 'all') && (
          <div style={{ textAlign: 'right', fontSize: 12, color: 'var(--muted)', padding: '8px 16px' }}>
            Showing {filtered.length} of {types.length} type{types.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </>
  );
};

export default IncidentTypes;
