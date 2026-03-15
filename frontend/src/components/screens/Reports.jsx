import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const Reports = ({ onOpenReport }) => {
  const [data, setData] = useState({ items: [], total: 0, limit: 20, offset: 0 });
  const [loading, setLoading] = useState(true);

  const [searchText, setSearchText] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [sectorFilter, setSectorFilter] = useState('all');
  const [priorityFilter, setPriorityFilter] = useState('all');
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [incidentTypes, setIncidentTypes] = useState([]);
  const [locations, setLocations] = useState([]);

  const loadFilters = () => {
    // Load incident types for Types dropdown
    api.get('/api/v1/incident-types?include_inactive=true')
      .then((res) => setIncidentTypes(res || []))
      .catch(() => setIncidentTypes([]));
    // Load locations (sectors) – only sectors for dropdown
    api.get('/api/v1/locations')
      .then((res) => {
        const sectors = (res || []).filter((loc) => loc.location_type === 'sector');
        setLocations(sectors);
      })
      .catch(() => setLocations([]));
  };

  const buildQuery = () => {
    const params = new URLSearchParams();
    params.set('limit', '50');
    params.set('offset', '0');
    if (statusFilter !== 'all') {
      // Map UI labels to rule_status values used by backend
      let ruleStatus = null;
      if (statusFilter === 'pending') ruleStatus = 'pending';
      if (statusFilter === 'verified') ruleStatus = 'passed';
      if (statusFilter === 'flagged') ruleStatus = 'flagged';
      if (ruleStatus) params.set('rule_status', ruleStatus);
    }
    if (typeFilter !== 'all') {
      params.set('incident_type_id', String(typeFilter));
    }
    if (sectorFilter !== 'all') {
      params.set('village_location_id', String(sectorFilter));
    }
    if (priorityFilter !== 'all') {
      params.set('priority', String(priorityFilter));
    }
    if (fromDate) {
      params.set('from_date', new Date(fromDate).toISOString());
    }
    if (toDate) {
      // include the whole day by going to end of day
      const end = new Date(toDate);
      end.setHours(23, 59, 59, 999);
      params.set('to_date', end.toISOString());
    }
    return `/api/v1/reports?${params.toString()}`;
  };

  const loadReports = () => {
    setLoading(true);
    api.get(buildQuery())
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  useEffect(() => {
    loadFilters();
    loadReports();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  let items = data.items || [];

  // Client-side text search (ID, type, location)
  if (searchText.trim()) {
    const q = searchText.trim().toLowerCase();
    items = items.filter((r) => {
      const id = (r.report_number || String(r.report_id)).toLowerCase();
      const type = (r.incident_type_name || '').toLowerCase();
      const loc = (r.village_name || '').toLowerCase();
      return id.includes(q) || type.includes(q) || loc.includes(q);
    });
  }
  const total = data.total || items.length;
  const pending = items.filter(r => r.rule_status === 'pending').length;
  const verified = items.filter(r => r.rule_status === 'passed').length;
  const flagged = items.filter(r => r.rule_status === 'flagged' || r.rule_status === 'rejected').length;

  return (
    <>
      <div className="page-header">
        <h2>Reports</h2>
        <p>All citizen-submitted incident reports — filter, sort, and take action.</p>
      </div>

      <div className="stats-row">
        <div className="stat-card c-blue">
          <div className="stat-label">All Reports</div>
          <div className="stat-value sv-blue">{total}</div>
        </div>
        <div className="stat-card c-orange">
          <div className="stat-label">Pending</div>
          <div className="stat-value sv-orange">{pending}</div>
        </div>
        <div className="stat-card c-green">
          <div className="stat-label">Verified</div>
          <div className="stat-value sv-green">{verified}</div>
        </div>
        <div className="stat-card c-red">
          <div className="stat-label">Flagged</div>
          <div className="stat-value sv-red">{flagged}</div>
        </div>
      </div>

      <div className="card">
        <div className="filter-row">
          <input
            className="input"
            placeholder="Search by ID, type, or location..."
            style={{ flex: 2, minWidth: '140px' }}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
          <select
            className="select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="all">All Statuses</option>
            <option value="pending">Pending</option>
            <option value="verified">Verified</option>
            <option value="flagged">Flagged</option>
          </select>
          <select
            className="select"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
          >
            <option value="all">All Types</option>
            {incidentTypes.map((t) => (
              <option key={t.incident_type_id} value={t.incident_type_id}>
                {t.type_name}
              </option>
            ))}
          </select>
          <select
            className="select"
            value={sectorFilter}
            onChange={(e) => setSectorFilter(e.target.value)}
          >
            <option value="all">All Sectors</option>
            {locations.map((loc) => (
              <option key={loc.location_id} value={loc.location_id}>
                {loc.location_name}
              </option>
            ))}
          </select>
          <select
            className="select"
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value)}
          >
            <option value="all">All Priorities</option>
            <option value="high">High priority</option>
            <option value="medium">Medium priority</option>
            <option value="low">Low priority</option>
          </select>
          <input
            className="input"
            type="date"
            style={{ minWidth: '130px' }}
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
          />
          <input
            className="input"
            type="date"
            style={{ minWidth: '130px' }}
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
          />
          <button className="btn btn-primary" onClick={loadReports}>Apply</button>
          <button
            className="btn btn-outline"
            onClick={() => {
              // Simple CSV export using current filtered results on the client
              if (!items.length) {
                window.alert('No reports to export.');
                return;
              }
              const header = ['report_number', 'incident_type', 'village', 'trust_score', 'assignment_priority', 'rule_status', 'reported_at'];
              const rows = items.map((r) => [
                r.report_number || String(r.report_id),
                r.incident_type_name || '',
                r.village_name || '',
                r.trust_score ?? '',
                r.assignment_priority || '',
                r.rule_status ?? '',
                r.reported_at || '',
              ]);
              const csv = [header.join(','), ...rows.map((row) =>
                row.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')
              )].join('\n');
              const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url;
              a.download = 'reports.csv';
              a.click();
              URL.revokeObjectURL(url);
            }}
          >
            Export CSV
          </button>
        </div>

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th><input type="checkbox" /></th>
                <th>Report ID</th>
                <th>Type</th>
                <th>Location</th>
                <th>Trust Score</th>
                <th>AI Result</th>
                <th>Priority</th>
                <th>Status</th>
                <th>Date</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => {
                const score = r.trust_score ?? 0;
                const width = Math.max(0, Math.min(100, Number(score)));
                const status = r.rule_status;
                const assignmentPriority = (r.assignment_priority || '').toLowerCase();
                return (
                  <tr key={r.report_id}>
                    <td><input type="checkbox" /></td>
                    <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                      {r.report_number || String(r.report_id).slice(0, 8)}
                    </td>
                    <td><strong>{r.incident_type_name || '—'}</strong></td>
                    <td>{r.village_name || '—'}</td>
                    <td>
                      <div className="trust-wrap">
                        <div className="trust-track">
                          <div className="trust-fill" style={{ width: `${width}%`, background: score >= 70 ? 'var(--success)' : score >= 40 ? 'var(--warning)' : 'var(--danger)' }}></div>
                        </div>
                        <div className="trust-val">{Math.round(score)}</div>
                      </div>
                    </td>
                    <td>
                      {score === null || score === undefined ? (
                        <span className="badge b-gray">No ML</span>
                      ) : (
                        <span
                          className={`badge ${
                            score >= 70
                              ? 'b-green'
                              : score >= 40
                              ? 'b-orange'
                              : 'b-red'
                          }`}
                        >
                          {score >= 70
                            ? 'Likely real'
                            : score >= 40
                            ? 'Uncertain'
                            : 'Suspicious'}
                        </span>
                      )}
                    </td>
                    <td>
                      {assignmentPriority ? (
                        <span
                          className={`badge ${
                            assignmentPriority === 'urgent' ||
                            assignmentPriority === 'high'
                              ? 'b-red'
                              : assignmentPriority === 'medium'
                              ? 'b-orange'
                              : 'b-gray'
                          }`}
                        >
                          {assignmentPriority}
                        </span>
                      ) : (
                        <span className="badge b-gray">—</span>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${
                        status === 'pending' ? 'b-orange'
                          : status === 'passed' ? 'b-green'
                          : 'b-red'
                      }`}>
                        {status}
                      </span>
                    </td>
                    <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                      {r.reported_at ? new Date(r.reported_at).toLocaleDateString() : '—'}
                    </td>
                    <td>
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={() => onOpenReport(r.report_id)}
                      >
                        View
                      </button>
                    </td>
                  </tr>
                );
              })}
              {(!items.length && !loading) && (
                <tr>
                  <td colSpan={10} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    No reports found.
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
            Showing {items.length} of {total} reports
          </div>
          {/* keep simple static pagination UI for now */}
          <div className="pagination">
            <div className="page-btn">‹</div>
            <div className="page-btn current">1</div>
            <div className="page-btn">2</div>
            <div className="page-btn">3</div>
            <div className="page-btn">›</div>
          </div>
        </div>
      </div>
    </>
  );
};

export default Reports;