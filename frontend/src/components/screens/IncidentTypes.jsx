import React, { useCallback, useEffect, useRef, useState } from 'react';
import api from '../../api/client';
import Chart from 'chart.js/auto';
import ChartDataLabels from 'chartjs-plugin-datalabels';
import { useAuth } from '../../context/AuthContext';
import { canManageAssignmentUnits, canManageIncidentTypes } from '../../utils/roleMapping';

// Ranked palette: most common = system primary (navy), stepping through sky/teal/green/amber/slate
const RANKED_PALETTE = [
  '#0f1f3d', // navy  - highest
  '#1e3a8a', // deep blue
  '#2563eb', // blue
  '#0ea5e9', // sky
  '#06b6d4', // cyan
  '#10b981', // emerald
  '#16a34a', // green
  '#d97706', // amber
  '#94a3b8', // slate
  '#64748b', // slate-dark - lowest
];
const paletteColor = (i) => RANKED_PALETTE[Math.min(i, RANKED_PALETTE.length - 1)];

// ── Module-level cache ─────────────────────────────────────────────────────
// Survives navigation away and back; cleared when a mutation occurs.
let _itCache = null; // { types, chartData }
let _itCacheRefreshKey = undefined; // the refreshKey value that produced this cache

// ── Component ──────────────────────────────────────────────────────────────

const IncidentTypes = ({ openModal, onEditIncidentType, refreshKey, wsRefreshKey, goToScreen }) => {
  const { user: me } = useAuth();
  const role     = me?.role || 'officer';
  const canManage = canManageIncidentTypes(role);

  // Initialise from cache immediately so returning to this screen is instant.
  const [types, setTypes]           = useState(_itCache?.types ?? []);
  const [chartData, setChartData]   = useState(_itCache?.chartData ?? {});
  const [loading, setLoading]       = useState(_itCache === null);
  const [bgRefreshing, setBgRefreshing] = useState(false);
  const [sortBy, setSortBy]         = useState('incidentType');
  const [sortOrder, setSortOrder]   = useState('desc');
  const [viewType, setViewType]     = useState(null);   // popup detail card
  const chartRef  = useRef(null);
  const chartInst = useRef(null);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  /* ── fetchTypes ── */
  const fetchTypes = useCallback(async ({ silent = false } = {}) => {
    if (silent) {
      setBgRefreshing(true);
    } else {
      setLoading(true);
    }
    try {
      const [typesRes, distRes] = await Promise.all([
        api.get('/api/v1/incident-types/?include_inactive=true'),
        api.get('/api/v1/incident-types/distribution'),
      ]);
      if (!mountedRef.current) return;
      const newTypes = typesRes || [];
      // Distribution endpoint returns pre-aggregated counts — no need to iterate reports
      const newChartData = {
        incidentTypes: distRes?.incident_types ?? {},
        sectors:       distRes?.sectors ?? {},
        stations:      distRes?.stations ?? {},
      };
      _itCache = { types: newTypes, chartData: newChartData };
      _itCacheRefreshKey = refreshKey;
      setTypes(newTypes);
      setChartData(newChartData);
    } catch {
      if (!mountedRef.current) return;
      // On background refresh keep stale data; on hard load try types-only fallback.
      if (!silent) {
        try {
          const r = await api.get('/api/v1/incident-types/?include_inactive=true');
          if (!mountedRef.current) return;
          setTypes(r || []);
        } catch { /* ignore */ }
      }
    } finally {
      if (!mountedRef.current) return;
      setLoading(false);
      setBgRefreshing(false);
    }
  }, [refreshKey]);

  /* ── Mount / key-change effect ── */
  useEffect(() => {
    if (_itCache === null) {
      // Truly first load (no cache) — show spinner.
      fetchTypes({ silent: false });
    } else {
      // Cache exists (including WS-triggered refresh) — stay silent.
      fetchTypes({ silent: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsRefreshKey, refreshKey]);

  /* ── Sorted chart entries ── */
  const getSorted = () => {
    const raw = sortBy === 'sector'    ? chartData.sectors
              : sortBy === 'stations'  ? chartData.stations
              : chartData.incidentTypes || {};
    const entries = Object.entries(raw || {}).sort((a, b) =>
      sortOrder === 'desc' ? b[1] - a[1] : a[1] - b[1]
    );
    return {
      labels: entries.map(([k]) => k),
      data:   entries.map(([, v]) => v),
    };
  };

  /* ── Chart render ── */
  useEffect(() => {
    if (!chartRef.current || !Object.keys(chartData).length) return;

    if (chartInst.current) { chartInst.current.destroy(); chartInst.current = null; }

    const { labels, data } = getSorted();
    const displayLabels = labels.length ? labels : ['No Data'];
    const displayData   = data.length   ? data   : [0];

    const bgColors     = displayLabels.map((_, i) => paletteColor(i));
    const borderColors = bgColors;

    const CHART_TITLES = {
      incidentType: 'Incident Type Distribution',
      sector:       'Incidents by Sector',
      stations:     'Incidents by Police Station',
    };

    chartInst.current = new Chart(chartRef.current.getContext('2d'), {
      type: 'bar',
      plugins: [ChartDataLabels],
      data: {
        labels: displayLabels,
        datasets: [{
          label: 'Incidents',
          data: displayData,
          backgroundColor: bgColors,
          borderColor: borderColors,
          borderWidth: 1,
          borderRadius: 4,
        }],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          title: {
            display: true,
            text: CHART_TITLES[sortBy] || CHART_TITLES.incidentType,
            font: { size: 13, weight: '600' },
            color: '#374151',
            padding: { bottom: 12 },
          },
          datalabels: {
            anchor: 'end',
            align: 'end',
            color: '#374151',
            font: { size: 11, weight: '600' },
            formatter: (v) => (v > 0 ? v : ''),
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { font: { size: 11 }, maxRotation: 35 },
          },
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(0,0,0,0.06)' },
            ticks: { font: { size: 11 }, precision: 0 },
            title: { display: true, text: 'Incidents', font: { size: 11 } },
          },
        },
        layout: { padding: { top: 20 } },
      },
    });

    return () => {
      if (chartInst.current) { chartInst.current.destroy(); chartInst.current = null; }
    };
  }, [chartData, sortBy, sortOrder]);

  /* ── Derived stats ── */
  const activeCount   = types.filter((t) => t.is_active).length;
  const inactiveCount = types.length - activeCount;
  const sorted = getSorted();
  const mostCommon = sorted.labels[0] || '-';
  const highestSev = types.reduce((best, t) =>
    (Number(t.severity_weight || 0) > Number(best?.severity_weight || 0)) ? t : best, null
  );

  /* ── Mutations ── */
  const handleToggleActive = async (type) => {
    try {
      const updated = await api.put(`/api/v1/incident-types/${type.incident_type_id}`, { is_active: !type.is_active });
      // Optimistic local update + bust cache so next navigation re-fetches.
      _itCache = null;
      setTypes((prev) => prev.map((t) => t.incident_type_id === updated.incident_type_id ? updated : t));
    } catch (e) { window.alert(e.message || 'Failed to update'); }
  };

  const handleDelete = async (type) => {
    if (!window.confirm(`Delete "${type.type_name}"? This cannot be undone.`)) return;
    try {
      await api.delete(`/api/v1/incident-types/${type.incident_type_id}`);
      _itCache = null;
      fetchTypes({ silent: false });
    } catch (e) { window.alert(e.message || 'Failed to delete'); }
  };

  return (
    <>
      {/* ── Page header + stat cards ── */}
      <div className="card" style={{ marginBottom: 20, padding: '20px 24px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
              <h2 style={{ margin: 0, fontSize: 22 }}>Incident Types</h2>
              {bgRefreshing && (
                <span style={{ fontSize: 11, color: 'var(--muted)', fontStyle: 'italic' }}>
                  refreshing…
                </span>
              )}
            </div>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: 13 }}>
              Configure categories and severity levels for incident reporting and analysis.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {canManage && goToScreen && canManageAssignmentUnits(role) && (
              <button type="button" className="btn btn-outline btn-sm" onClick={() => goToScreen('special-assignment-units', 17)}>
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

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {[
            { label: 'Total Types',     value: loading ? '...' : types.length, cls: 'sb-blue'  },
            { label: 'Active',          value: loading ? '...' : activeCount,  cls: 'sb-green' },
            { label: 'Inactive',        value: loading ? '...' : inactiveCount, cls: 'sb-red'  },
            { label: 'Most Reported',   value: loading ? '...' : mostCommon,   cls: 'sb-blue'  },
          ].map((s) => (
            <div key={s.label} className={`stat-btn ${s.cls}`} style={{ cursor: 'default' }}>
              <div className="stat-btn-label">{s.label}</div>
              <div className="stat-btn-value" style={{ fontSize: s.label === 'Most Reported' ? 13 : undefined, fontWeight: 700 }}>
                {s.value}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Distribution chart ── */}
      <div className="card" style={{ marginBottom: 20 }}>
        <div className="card-header" style={{ paddingBottom: 0 }}>
          <div className="card-title">Incident Distribution Analysis</div>
        </div>
        <div style={{ padding: '16px 20px' }}>
          {/* Controls */}
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <label style={{ fontSize: 13, color: 'var(--muted)' }}>View by:</label>
              <select className="select" value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                <option value="incidentType">Incident Type</option>
                <option value="sector">Sector</option>
                <option value="stations">Police Station</option>
              </select>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <label style={{ fontSize: 13, color: 'var(--muted)' }}>Order:</label>
              <select className="select" value={sortOrder} onChange={(e) => setSortOrder(e.target.value)}>
                <option value="desc">Highest First</option>
                <option value="asc">Lowest First</option>
              </select>
            </div>
            {/* Color legend */}
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center', fontSize: 11, color: 'var(--muted)' }}>
              <span style={{ width: 10, height: 10, borderRadius: 2, background: '#0f1f3d', display: 'inline-block' }} /> Highest
              <span style={{ width: 10, height: 10, borderRadius: 2, background: '#06b6d4', display: 'inline-block', marginLeft: 6 }} /> Mid
              <span style={{ width: 10, height: 10, borderRadius: 2, background: '#94a3b8', display: 'inline-block', marginLeft: 6 }} /> Lowest
            </div>
          </div>

          <canvas ref={chartRef} height={160} />
        </div>
      </div>

      {/* ── Categories table ── */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">Incident Categories</div>
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
                <th style={{ width: 60 }}></th>
                {canManage && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {types.map((t, index) => {
                const val = Number(t.severity_weight ?? 1);
                const sev = val.toFixed(2);
                let level = 'Low'; let badge = 'b-gray';
                if      (val >= 1.6) { level = 'Severe'; badge = 'b-red';    }
                else if (val >= 1.3) { level = 'High';   badge = 'b-orange'; }
                else if (val >= 1.1) { level = 'Medium'; badge = 'b-blue';   }
                return (
                  <tr key={t.incident_type_id}>
                    <td style={{ fontSize: 12, color: 'var(--muted)', textAlign: 'center' }}>{index + 1}</td>
                    <td>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{t.type_name}</div>
                    </td>
                    <td style={{ fontSize: 11, color: 'var(--muted)', maxWidth: 220 }}>{t.description || '-'}</td>
                    <td>
                      <span style={{ fontWeight: 700, fontSize: 13 }}>{sev}</span>
                    </td>
                    <td><span className={`badge ${badge}`}>{level}</span></td>
                    <td>
                      <span className={`badge ${t.is_active ? 'b-green' : 'b-red'}`}>
                        {t.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td>
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={() => setViewType(t)}
                        style={{ fontSize: 11, padding: '2px 10px' }}
                      >
                        View
                      </button>
                    </td>
                    {canManage && (
                      <td>
                        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                          <button className="btn btn-outline btn-sm" onClick={() => onEditIncidentType?.(t)}>Edit</button>
                          <button className="btn btn-warn btn-sm" onClick={() => handleToggleActive(t)}>
                            {t.is_active ? 'Deactivate' : 'Activate'}
                          </button>
                          <button className="btn btn-danger btn-sm" onClick={() => handleDelete(t)}>Delete</button>
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
              {!types.length && !loading && (
                <tr><td colSpan={canManage ? 8 : 7} style={{ textAlign: 'center', fontSize: 12, color: 'var(--muted)', padding: '32px 0' }}>No incident types found.</td></tr>
              )}
              {loading && (
                <tr><td colSpan={canManage ? 8 : 7} style={{ textAlign: 'center', fontSize: 12, color: 'var(--muted)', padding: '32px 0' }}>Loading...</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── View Detail Popup ── */}
      {viewType && (() => {
        const vt = viewType;
        const val = Number(vt.severity_weight ?? 1);
        const sev = val.toFixed(2);
        let level = 'Low', badge = 'b-gray', levelColor = '#64748b';
        if      (val >= 1.6) { level = 'Severe'; badge = 'b-red';    levelColor = '#dc2626'; }
        else if (val >= 1.3) { level = 'High';   badge = 'b-orange'; levelColor = '#d97706'; }
        else if (val >= 1.1) { level = 'Medium'; badge = 'b-blue';   levelColor = '#2563eb'; }
        const reportCount = (chartData.incidentTypes || {})[vt.type_name] || 0;

        return (
          <div
            className="modal-overlay open"
            onClick={(e) => e.target === e.currentTarget && setViewType(null)}
            style={{ zIndex: 1000 }}
          >
            <div style={{
              background: 'var(--bg, #fff)',
              borderRadius: 14,
              maxWidth: 560,
              width: '94%',
              maxHeight: '88vh',
              overflowY: 'auto',
              boxShadow: '0 20px 60px rgba(0,0,0,0.18)',
              animation: 'fadeIn 0.2s ease-out',
            }}>
              {/* Header band */}
              <div style={{
                background: 'linear-gradient(135deg, #0f1f3d 0%, #1e3a8a 100%)',
                padding: '22px 28px 18px',
                borderRadius: '14px 14px 0 0',
                color: '#fff',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>{vt.type_name}</div>
                    <div style={{ fontSize: 12, opacity: 0.75 }}>Incident Type Details</div>
                  </div>
                  <button
                    onClick={() => setViewType(null)}
                    style={{
                      background: 'rgba(255,255,255,0.15)',
                      border: 'none',
                      color: '#fff',
                      width: 32,
                      height: 32,
                      borderRadius: 8,
                      cursor: 'pointer',
                      fontSize: 16,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    ✕
                  </button>
                </div>

                {/* Quick stat pills */}
                <div style={{ display: 'flex', gap: 10, marginTop: 14, flexWrap: 'wrap' }}>
                  <span style={{
                    background: 'rgba(255,255,255,0.15)',
                    padding: '4px 12px',
                    borderRadius: 20,
                    fontSize: 11,
                    fontWeight: 600,
                  }}>
                    Severity: {sev}
                  </span>
                  <span style={{
                    background: levelColor,
                    padding: '4px 12px',
                    borderRadius: 20,
                    fontSize: 11,
                    fontWeight: 600,
                  }}>
                    {level}
                  </span>
                  <span style={{
                    background: vt.is_active ? 'rgba(22,163,74,0.8)' : 'rgba(220,38,38,0.8)',
                    padding: '4px 12px',
                    borderRadius: 20,
                    fontSize: 11,
                    fontWeight: 600,
                  }}>
                    {vt.is_active ? 'Active' : 'Inactive'}
                  </span>
                  <span style={{
                    background: 'rgba(255,255,255,0.15)',
                    padding: '4px 12px',
                    borderRadius: 20,
                    fontSize: 11,
                    fontWeight: 600,
                  }}>
                    {reportCount} report{reportCount !== 1 ? 's' : ''}
                  </span>
                </div>
              </div>

              {/* Body */}
              <div style={{ padding: '20px 28px 24px' }}>
                {/* Description */}
                <div style={{ marginBottom: 20 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--muted)', marginBottom: 6 }}>
                    Description
                  </div>
                  <p style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--text)', margin: 0 }}>
                    {vt.description || 'No description provided.'}
                  </p>
                </div>

                {/* Semantic Definition */}
                <div style={{ marginBottom: 20 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--muted)', marginBottom: 6 }}>
                    AI Semantic Definition
                  </div>
                  {vt.semantic_definition ? (
                    <div style={{
                      background: 'var(--bg-secondary, #f8fafc)',
                      border: '1px solid var(--border, #e2e8f0)',
                      borderRadius: 10,
                      padding: '14px 16px',
                    }}>
                      <p style={{ fontSize: 13, lineHeight: 1.7, color: 'var(--text)', margin: 0 }}>
                        {vt.semantic_definition}
                      </p>
                      <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 8, textAlign: 'right' }}>
                        {vt.semantic_definition.length} characters
                      </div>
                    </div>
                  ) : (
                    <p style={{ fontSize: 12, fontStyle: 'italic', color: 'var(--muted)', margin: 0, padding: '12px 0' }}>
                      No semantic definition configured. The AI pipeline will fall back to the short description for verification matching.
                    </p>
                  )}
                </div>

                {/* Info grid */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  gap: 12,
                  marginBottom: 6,
                }}>
                  {[
                    { label: 'Severity Weight', value: sev },
                    { label: 'Severity Level', value: level, color: levelColor },
                    { label: 'Status', value: vt.is_active ? 'Active' : 'Inactive', color: vt.is_active ? '#16a34a' : '#dc2626' },
                    { label: 'Total Reports', value: reportCount },
                  ].map((item) => (
                    <div key={item.label} style={{
                      background: 'var(--bg-secondary, #f8fafc)',
                      borderRadius: 8,
                      padding: '10px 14px',
                    }}>
                      <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.4, color: 'var(--muted)', marginBottom: 3 }}>
                        {item.label}
                      </div>
                      <div style={{ fontSize: 15, fontWeight: 700, color: item.color || 'var(--text)' }}>
                        {item.value}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Footer */}
              <div style={{
                padding: '14px 28px',
                borderTop: '1px solid var(--border, #e2e8f0)',
                display: 'flex',
                justifyContent: 'flex-end',
                gap: 8,
              }}>
                {canManage && (
                  <button
                    className="btn btn-outline btn-sm"
                    onClick={() => { setViewType(null); onEditIncidentType?.(vt); }}
                    style={{ padding: '6px 16px' }}
                  >
                    Edit
                  </button>
                )}
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => setViewType(null)}
                  style={{ padding: '6px 20px' }}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        );
      })()}
    </>
  );
};

export default IncidentTypes;
