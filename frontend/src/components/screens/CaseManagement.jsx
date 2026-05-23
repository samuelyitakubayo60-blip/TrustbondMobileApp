import React, { useEffect, useState } from 'react';
import SkeletonTable from '../Common/SkeletonTable';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import EditCaseModal from '../Modals/EditCaseModal';
import ViewCaseModal from '../Modals/ViewCaseModal';
import {
  getRoleDisplayName,
  canHandoverToRib,
  canCreateCases,
  canDeleteCases,
  canManageCases,
} from '../../utils/roleMapping';
import { caseDisplayName, caseDisplayRef } from '../../utils/caseDisplay';

const CaseManagement = ({ goToScreen, openModal, wsRefreshKey }) => {
  const { user: me } = useAuth();
  const role = me?.role || 'officer';
  const canCreate = canCreateCases(role);
  const canDelete = canDeleteCases(role);
  const canUpdateCase = (c) =>
    canManageCases(role) &&
    (role === 'admin' || role === 'supervisor' || c.assigned_to_id === me?.police_user_id);
  const [cases, setCases] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editingCase, setEditingCase] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  const [viewingCase, setViewingCase] = useState(null);
  const [viewOpen, setViewOpen] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [priorityFilter, setPriorityFilter] = useState('all');
  const [stationsById, setStationsById] = useState({});
  const [stationFilter, setStationFilter] = useState('all');

  useEffect(() => {
    reload();
  }, [wsRefreshKey]);

  const reload = async () => {
    let mounted = true;
    setLoading(true);
    try {
      const [list, s] = await Promise.all([
        api.get(statusFilter === 'all' ? '/api/v1/cases/?limit=50&offset=0' : `/api/v1/cases/?limit=50&offset=0&status=${encodeURIComponent(statusFilter)}`),
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

  // Load stations so we can filter/group by station.
  useEffect(() => {
    let cancelled = false;
    api.get('/api/v1/stations/?only_active=true')
      .then((res) => {
        if (cancelled) return;
        const map = {};
        (res?.items || []).forEach((st) => {
          map[st.station_id] = st;
        });
        setStationsById(map);
      })
      .catch(() => {
        if (cancelled) return;
        setStationsById({});
      });
    return () => {
      cancelled = true;
    };
  }, [wsRefreshKey]);

  const openCount = stats?.open ?? 0;
  const inProgress = stats?.in_progress ?? 0;
  const closed30 = stats?.closed ?? 0;  // simple
  const merged = stats?.reports_merged ?? 0;

  const filteredCases = cases.filter((c) => {
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      const id = (c.case_number || String(c.case_id)).toLowerCase();
      const title = (c.title || '').toLowerCase();
      const loc = (c.location_name || '').toLowerCase();
      if (!id.includes(q) && !title.includes(q) && !loc.includes(q)) {
        return false;
      }
    }
    if (priorityFilter !== 'all' && c.priority !== priorityFilter) {
      return false;
    }
    if (stationFilter !== 'all') {
      const sid = Number(stationFilter);
      const caseStation = c.station_id ?? c.assigned_to_station_id;
      if (!caseStation || Number(caseStation) !== sid) {
        return false;
      }
    }
    return true;
  });

  const closedCases = filteredCases.filter(c => c.status === 'closed').slice(0, 3);

  const stationOptions = Object.values(stationsById).sort((a, b) =>
    (a.station_name || '').localeCompare(b.station_name || '')
  );

  return (
    <>
      {/* ── Case Management header card ── */}
      <div className="card" style={{ marginBottom: 20, padding: '20px 24px 16px' }}>
        {/* Title + subtitle + actions row */}
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 12,
            marginBottom: 16,
          }}
        >
          <div>
            <h2 style={{ margin: 0, marginBottom: 4, fontSize: 22 }}>Case Management</h2>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: 13 }}>
              Multiple verified reports grouped into a single coordinated investigation.
            </p>
          </div>
          {canCreate && (
            <button
              className="btn btn-primary"
              style={{ whiteSpace: 'nowrap', alignSelf: 'center' }}
              onClick={() => openModal('newCase')}
            >
              + New Case
            </button>
          )}
        </div>

        {/* Stats — clickable to filter */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {[
            { label: 'Open Cases',      sub: 'Awaiting action',    value: openCount,  cls: 'sb-orange', filter: 'open'         },
            { label: 'In Progress',     sub: 'Being investigated', value: inProgress, cls: 'sb-blue',   filter: 'investigating' },
            { label: 'Closed',          sub: 'Resolved cases',     value: closed30,   cls: 'sb-green',  filter: 'closed'       },
            { label: 'Reports Merged',  sub: 'Across all cases',   value: merged,     cls: 'sb-purple', filter: null           },
          ].map((s) => (
            <button
              key={s.label}
              onClick={() => {
                if (!s.filter) return;
                const next = statusFilter === s.filter ? 'all' : s.filter;
                setStatusFilter(next);
                setTimeout(() => reload(), 0);
              }}
              className={`stat-btn ${s.cls}${statusFilter === s.filter ? ' active' : ''}`}
              style={{ cursor: s.filter ? 'pointer' : 'default' }}
            >
              <div className="stat-btn-label">{s.label}</div>
              <div className="stat-btn-value">{s.value}</div>
              <div className="stat-btn-sub">{s.sub}</div>
            </button>
          ))}
        </div>
      </div>

      <div className="card" style={{ marginBottom: '14px' }}>
        <div className="filter-row">
          <input
            className="input"
            placeholder="Search by case ID, title, or location..."
            style={{ flex: 2 }}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
          <select
            className="select"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              // Reload from backend whenever status changes
              setTimeout(() => reload(), 0);
            }}
          >
            <option value="all">All Statuses</option>
            <option value="open">Open</option>
            <option value="investigating">Investigating</option>
            <option value="closed">Closed</option>
          </select>
          <select
            className="select"
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value)}
          >
            <option value="all">All Priorities</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <select
            className="select"
            value={stationFilter}
            onChange={(e) => setStationFilter(e.target.value)}
          >
            <option value="all">All Stations</option>
            {stationOptions.map((st) => (
              <option key={st.station_id} value={st.station_id}>
                {st.station_name}
                {st.covered_cell_names?.length ? ` (${st.covered_cell_names.length} cells)` : ''}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '14px', marginBottom: '14px' }}>
        {filteredCases.map((c) => {
          const pri = c.priority || 'medium';
          const statusLabel =
            c.status === 'open'         ? 'Open'        :
            c.status === 'investigating' ? 'In Progress' :
            c.status === 'closed'        ? 'Closed'      :
            (c.status || 'open');

          return (
            <div key={c.case_id} className={`case-card p-${pri}`}>
              {/* Header: title + inline badges */}
              <div style={{ marginBottom: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
                  <span style={{ fontWeight: 700, fontSize: 14 }}>{caseDisplayName(c)}</span>
                  <span className={`p-badge p-${pri}`}>
                    {pri.charAt(0).toUpperCase() + pri.slice(1)} priority
                  </span>
                  <span className={`s-badge s-${c.status || 'open'}`}>
                    {statusLabel}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.4 }}>
                  {caseDisplayRef(c) ? `${caseDisplayRef(c)} · ` : ''}
                  {c.location_name || 'Unknown'} · {c.incident_type_name || 'Mixed'} · {c.report_count} reports
                  {typeof c.average_trust_score === 'number' && (
                    <span style={{ marginLeft: 6 }}>· avg trust <strong>{Math.round(c.average_trust_score)}</strong>/100</span>
                  )}
                </div>
              </div>

              {/* Description */}
              <div style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.5, marginBottom: 10 }}>
                {c.description || 'Case created from grouped reports.'}
              </div>

              {/* Assigned + date */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11, color: 'var(--muted)', marginBottom: 8 }}>
                <span>Assigned: <strong style={{ color: 'var(--text)' }}>{c.assigned_to_name || 'Unassigned'}</strong></span>
                <span>Opened {c.opened_at ? new Date(c.opened_at).toLocaleDateString() : '—'}</span>
              </div>

              {/* Reports linked bar */}
              <div style={{ marginBottom: 2 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
                  <span>Reports linked</span>
                  <span>{c.report_count} total</span>
                </div>
                <div style={{ height: 5, borderRadius: 3, background: 'var(--border)', overflow: 'hidden' }}>
                  <div className={`prog-fill-${pri}`} style={{ height: '100%', borderRadius: 3, width: `${Math.min(100, c.report_count * 20)}%`, transition: 'width 0.4s' }} />
                </div>
              </div>

              {/* Actions */}
              <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
                <button className="btn btn-primary btn-sm" onClick={() => { setViewingCase(c); setViewOpen(true); }}>
                  View Case
                </button>
                {canUpdateCase(c) && (
                  <button className="btn btn-outline btn-sm" onClick={() => { setEditingCase(c); setEditOpen(true); }}>
                    Update
                  </button>
                )}
                {canHandoverToRib(role) && c.status === 'closed' && !c.rib_handed_over_at && (
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={async () => {
                      const confirmed = window.confirm('Hand over this case to RIB? This will mark the case as transferred to the Rwanda Investigation Bureau.');
                      if (!confirmed) return;
                      try {
                        await api.put(`/api/v1/cases/${c.case_id}`, {
                          rib_handed_over_at: new Date().toISOString(),
                          rib_handover_summary: 'Case handed over to RIB for further investigation',
                          status: 'handed_to_rib',
                        });
                        reload();
                      } catch (e) {
                        window.alert(e?.message || 'Failed to hand over case to RIB.');
                      }
                    }}
                  >
                    Hand to RIB
                  </button>
                )}
                {canDelete && (
                  <button
                    className="btn btn-outline btn-sm"
                    style={{ color: 'var(--danger)', borderColor: 'transparent' }}
                    onClick={async () => {
                      const confirmed = window.confirm('Delete this case? This will unlink all associated reports.');
                      if (!confirmed) return;
                      try {
                        await api.delete(`/api/v1/cases/${c.case_id}`);
                        reload();
                      } catch (e) {
                        window.alert(e?.message || 'Failed to delete case.');
                      }
                    }}
                  >
                    Delete
                  </button>
                )}
              </div>
            </div>
          );
        })}
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
                <th>#</th>
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
              {closedCases.map((c, index) => (
                <tr key={c.case_id}>
                  <td style={{ fontSize: "12px", color: "var(--muted)", textAlign: "center" }}>
                    {index + 1}
                  </td>
                  <td style={{ fontWeight: 600, fontSize: '11px' }}>{caseDisplayName(c)}</td>
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
                  <td colSpan={9} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    No closed cases.
                  </td>
                </tr>
              )}
              {loading && <SkeletonTable cols={9} rows={6} />}
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
      <ViewCaseModal
        isOpen={viewOpen}
        onClose={() => setViewOpen(false)}
        caseItem={viewingCase}
        onEdit={(item) => {
          setViewOpen(false);
          setEditingCase(item);
          setEditOpen(true);
        }}
      />
    </>
  );
};

export default CaseManagement;