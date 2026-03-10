import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const Reports = ({ onOpenReport }) => {
  const [data, setData] = useState({ items: [], total: 0, limit: 20, offset: 0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    api.get('/api/v1/reports?limit=50&offset=0')
      .then((res) => { if (mounted) { setData(res); setLoading(false); } })
      .catch(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  const items = data.items || [];
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
        {/* keep filter row mostly static for now */}
        <div className="filter-row">
          <input className="input" placeholder="Search reports..." style={{ flex: 2, minWidth: '140px' }} />
          <select className="select">
            <option>All Statuses</option>
            <option>Pending</option>
            <option>Verified</option>
            <option>Flagged</option>
          </select>
          <select className="select">
            <option>All Types</option>
            <option>Assault</option>
            <option>Theft</option>
            <option>Drug Activity</option>
            <option>Vandalism</option>
            <option>Harassment</option>
            <option>Fraud/Scam</option>
          </select>
          <select className="select">
            <option>All Sectors</option>
            <option>Muhoza</option>
            <option>Kinigi</option>
            <option>Cyuve</option>
            <option>Busogo</option>
          </select>
          <input className="input" type="date" style={{ minWidth: '130px' }} />
          <input className="input" type="date" style={{ minWidth: '130px' }} />
          <button className="btn btn-primary">Apply</button>
          <button className="btn btn-outline">Export CSV</button>
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
                    <td><span className="badge b-green">Rule</span></td>
                    <td><span className="badge b-gray">—</span></td>
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