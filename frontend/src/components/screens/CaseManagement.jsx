import React, { useEffect, useState } from 'react';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import EditCaseModal from '../Modals/EditCaseModal';

const CaseManagement = ({ openModal }) => {
  const { user: me } = useAuth();
  const role = me?.role || 'officer';
  const isAdminOrSupervisor = role === 'admin' || role === 'supervisor';
  const [cases, setCases] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editingCase, setEditingCase] = useState(null);
  const [editOpen, setEditOpen] = useState(false);

  useEffect(() => {
    reload();
  }, []);

  const reload = async () => {
    let mounted = true;
    setLoading(true);
    try {
      const [list, s] = await Promise.all([
        api.get('/api/v1/cases?limit=50&offset=0'),
        api.get('/api/v1/cases/stats'),
      ]);
      if (!mounted) return;
      setCases(list.items || []);
      setStats(s || null);
    } catch {
      if (!mounted) return;
    } finally {
      if (mounted) setLoading(false);
    }
    return () => {
      mounted = false;
    };
  };

  const openCount = stats?.open ?? 0;
  const inProgress = stats?.in_progress ?? 0;
  const closed30 = stats?.closed ?? 0;  // simple
  const merged = stats?.reports_merged ?? 0;

  const closedCases = cases.filter(c => c.status === 'closed').slice(0, 3);

  return (
    <>
      <div className="page-header">
        <h2>Case Management</h2>
        <p>Unified cases — multiple reports grouped into a single coordinated investigation.</p>
      </div>

      <div className="stats-row">
        <div className="stat-card c-orange">
          <div className="stat-label">Open Cases</div>
          <div className="stat-value sv-orange">{openCount}</div>
          <div className="stat-change">Awaiting action</div>
        </div>
        <div className="stat-card c-blue">
          <div className="stat-label">In Progress</div>
          <div className="stat-value sv-blue">{inProgress}</div>
          <div className="stat-change">Being investigated</div>
        </div>
        <div className="stat-card c-green">
          <div className="stat-label">Closed</div>
          <div className="stat-value sv-green">{closed30}</div>
          <div className="stat-change"><span className="up">recent</span></div>
        </div>
        <div className="stat-card c-purple">
          <div className="stat-label">Reports Merged</div>
          <div className="stat-value sv-purple">{merged}</div>
          <div className="stat-change">Across all cases</div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: '14px' }}>
        <div className="filter-row">
          <input className="input" placeholder="Search cases..." style={{ flex: 2 }} />
          <select className="select">
            <option>All Statuses</option>
            <option>open</option>
            <option>investigating</option>
            <option>closed</option>
          </select>
          <select className="select">
            <option>All Priorities</option>
            <option>high</option>
            <option>medium</option>
            <option>low</option>
          </select>
          <select className="select">
            <option>All Sectors</option>
          </select>
          {isAdminOrSupervisor && (
            <button className="btn btn-primary" onClick={() => openModal('newCase')}>+ New Case</button>
          )}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '14px', marginBottom: '14px' }}>
        {cases.map((c) => (
          <div className="case-card" key={c.case_id}>
            <div className="case-card-header">
              <div>
                <div className="case-id">{c.case_number || String(c.case_id).slice(0, 8)}</div>
                <div className="case-meta">
                  {c.location_name || 'Unknown'} · {c.incident_type_name || 'Mixed'} · {c.report_count} reports
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px' }}>
                <span className={`badge ${
                  c.priority === 'high' ? 'b-red' :
                  c.priority === 'medium' ? 'b-orange' :
                  'b-gray'
                }`}>
                  {c.priority || 'medium'} Priority
                </span>
                <span className={`badge ${
                  c.status === 'open' ? 'b-orange' :
                  c.status === 'investigating' ? 'b-blue' :
                  'b-green'
                }`}>
                  {c.status}
                </span>
              </div>
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-dim)', lineHeight: 1.5, marginBottom: '10px' }}>
              {c.description || 'Case created from grouped reports.'}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '11px', color: 'var(--muted)', marginBottom: '8px' }}>
              <span>Assigned: <strong style={{ color: 'var(--text)' }}>{c.assigned_to_name || 'Unassigned'}</strong></span>
              <span>Opened {c.opened_at ? new Date(c.opened_at).toLocaleDateString() : '—'}</span>
            </div>
            <div className="case-progress">
              <div className="case-progress-label">
                <span>Reports linked</span>
                <span>{c.report_count} total</span>
              </div>
              <div className="prog-bar">
                <div className="prog-fill" style={{ width: `${Math.min(100, c.report_count * 20)}%`, background: 'var(--accent)' }}></div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '6px', marginTop: '10px', flexWrap: 'wrap' }}>
              <button className="btn btn-primary btn-sm">View Case</button>
              {(isAdminOrSupervisor || (role === 'officer' && c.assigned_to_id === me?.police_user_id)) && (
                <button
                  className="btn btn-outline btn-sm"
                  onClick={() => {
                    setEditingCase(c);
                    setEditOpen(true);
                  }}
                >
                  Update
                </button>
              )}
            </div>
          </div>
        ))}
        {(!cases.length && !loading) && (
          <div style={{ fontSize: '12px', color: 'var(--muted)' }}>No cases yet.</div>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <div className="card-title">Recently Closed Cases</div>
        </div>
        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>Case ID</th>
                <th>Type</th>
                <th>Location</th>
                <th>Reports</th>
                <th>Assigned Officer</th>
                <th>Opened</th>
                <th>Closed</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              {closedCases.map((c) => (
                <tr key={c.case_id}>
                  <td style={{ fontWeight: 600, fontSize: '11px' }}>{c.case_number}</td>
                  <td>{c.incident_type_name || '—'}</td>
                  <td>{c.location_name || '—'}</td>
                  <td>{c.report_count}</td>
                  <td>{c.assigned_to_name || '—'}</td>
                  <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                    {c.opened_at ? new Date(c.opened_at).toLocaleDateString() : '—'}
                  </td>
                  <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                    {c.closed_at ? new Date(c.closed_at).toLocaleDateString() : '—'}
                  </td>
                  <td><span className="badge b-green">{c.outcome || 'Resolved'}</span></td>
                </tr>
              ))}
              {(!closedCases.length && !loading) && (
                <tr>
                  <td colSpan={8} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    No closed cases yet.
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
      </div>

      <EditCaseModal
        isOpen={editOpen}
        onClose={() => setEditOpen(false)}
        caseItem={editingCase}
        onSaved={reload}
      />
    </>
  );
};

export default CaseManagement;