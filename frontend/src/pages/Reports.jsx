import { useMemo, useState, useEffect, useCallback } from 'react';
import Layout from '../components/Layout.jsx';
import { useAuth } from '../contexts/AuthContext.jsx';
import { apiService } from '../services/apiService.js';
import '../styles/colors.css';
import './Pages.css';

const PAGE_SIZE = 20;

export default function Reports() {
  const { isOfficer, canAssignOrReview } = useAuth();
  const [data, setData] = useState({ items: [], total: 0, limit: PAGE_SIZE, offset: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filterStatus, setFilterStatus] = useState('');
  const [filterFrom, setFilterFrom] = useState('');
  const [filterTo, setFilterTo] = useState('');
  const [expanded, setExpanded] = useState(() => new Set());
  const [evidenceIndex, setEvidenceIndex] = useState(() => ({}));
  const [selectedId, setSelectedId] = useState(null);
  const [selectedReport, setSelectedReport] = useState(null);
  const [panelLoading, setPanelLoading] = useState(false);
  const [panelError, setPanelError] = useState(null);
  const [officerOptions, setOfficerOptions] = useState([]);
  const [assignOfficerId, setAssignOfficerId] = useState('');
  const [assignPriority, setAssignPriority] = useState('medium');
  const [assignError, setAssignError] = useState(null);
  const [assigning, setAssigning] = useState(false);
  const [reviewDecision, setReviewDecision] = useState('investigation');
  const [reviewNote, setReviewNote] = useState('');
  const [reviewError, setReviewError] = useState(null);
  const [submittingReview, setSubmittingReview] = useState(false);

  const loadReports = useCallback((offset = 0) => {
    setLoading(true);
    setError(null);
    const params = { limit: PAGE_SIZE, offset };
    if (filterStatus) params.rule_status = filterStatus;
    if (filterFrom) params.from_date = new Date(filterFrom).toISOString();
    if (filterTo) params.to_date = new Date(filterTo + 'T23:59:59.999Z').toISOString();
    apiService
      .getReports(params)
      .then((res) => {
        if (res.items !== undefined) {
          setData((prev) => {
            const nextItems = res.items || [];
            const merged = offset > 0 ? [...(prev.items || []), ...nextItems] : nextItems;
            return { items: merged, total: res.total ?? 0, limit: res.limit ?? PAGE_SIZE, offset: res.offset ?? 0 };
          });
        } else {
          const list = Array.isArray(res) ? res : [];
          setData({ items: list, total: list.length, limit: PAGE_SIZE, offset: 0 });
        }
      })
      .catch((err) => setError(err.message || 'Failed to load reports'))
      .finally(() => setLoading(false));
  }, [filterStatus, filterFrom, filterTo]);

  useEffect(() => {
    loadReports(0);
  }, [loadReports]);

  const applyFilters = () => {
    setExpanded(new Set());
    setEvidenceIndex({});
    setSelectedId(null);
    setSelectedReport(null);
    loadReports(0);
  };
  const reports = data.items || [];
  const total = data.total ?? 0;
  const offset = data.offset ?? 0;
  const hasMore = offset + reports.length < total;
  const hasPrev = offset > 0;

  function statusColor(status) {
    switch (String(status).toLowerCase()) {
      case 'passed': return '#16a34a';
      case 'flagged': return '#ea580c';
      case 'rejected': return '#dc2626';
      default: return 'var(--nav-blue, #2563eb)';
    }
  }

  const statusMeta = useMemo(() => ({
    pending: { label: 'Pending', bg: '#eff6ff', fg: '#1d4ed8' },
    passed: { label: 'Passed', bg: '#dcfce7', fg: '#166534' },
    flagged: { label: 'Flagged', bg: '#ffedd5', fg: '#9a3412' },
    rejected: { label: 'Rejected', bg: '#fee2e2', fg: '#991b1b' },
  }), []);

  const toggleExpanded = (reportId) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(reportId)) next.delete(reportId);
      else next.add(reportId);
      return next;
    });
  };

  const goEvidence = (reportId, delta, count) => {
    if (count <= 1) return;
    setEvidenceIndex((prev) => {
      const current = prev[reportId] ?? 0;
      const next = Math.max(0, Math.min(count - 1, current + delta));
      return { ...prev, [reportId]: next };
    });
  };

  const renderLocation = (r) => {
    if (r.village_name) return r.village_name;
    if (r.latitude != null && r.longitude != null) return `${Number(r.latitude).toFixed(4)}, ${Number(r.longitude).toFixed(4)}`;
    return '—';
  };

  const loadSelectedReport = useCallback((reportId) => {
    if (!reportId) return;
    setPanelLoading(true);
    setPanelError(null);
    apiService
      .getReport(reportId)
      .then((rep) => {
        setSelectedReport(rep);
      })
      .catch((err) => setPanelError(err.message || 'Failed to load report details'))
      .finally(() => setPanelLoading(false));
  }, []);

  const openPanel = (reportId) => {
    setSelectedId(reportId);
    loadSelectedReport(reportId);
  };

  const formatDate = (s) => {
    if (!s) return '—';
    const d = new Date(s);
    return d.toLocaleString();
  };

  const formatLocationSource = (source) => {
    if (!source) return null;
    switch (source) {
      case 'same_village_all':
        return 'Reporter and all evidence are in the same village';
      case 'village_conflict':
        return 'Reporter village differs from some evidence villages';
      case 'evidence_only':
        return 'Based only on evidence villages';
      case 'evidence_conflict':
        return 'Evidence villages disagree';
      case 'reporter_only_no_village':
        return 'Reporter point outside mapped villages';
      case 'evidence_only_no_village':
        return 'Evidence point outside mapped villages';
      default:
        if (source === 'reporter_only') return null;
        return source;
    }
  };

  const assignments = selectedReport?.assignments || [];
  const reviews = selectedReport?.reviews || [];

  const loadOfficerOptions = () => {
    apiService
      .getOfficerOptions()
      .then((list) => {
        setOfficerOptions(Array.isArray(list) ? list : []);
        if (list?.length && !assignOfficerId) setAssignOfficerId(String(list[0].police_user_id));
      })
      .catch(() => setOfficerOptions([]));
  };

  const handleAssignSubmit = async (e) => {
    e.preventDefault();
    if (!selectedId || !assignOfficerId) return;
    setAssigning(true);
    setAssignError(null);
    try {
      await apiService.assignReport(selectedId, {
        police_user_id: Number(assignOfficerId),
        priority: assignPriority,
      });
      loadSelectedReport(selectedId);
    } catch (err) {
      setAssignError(err.message || 'Assign failed');
    } finally {
      setAssigning(false);
    }
  };

  const handleReviewSubmit = async (e) => {
    e.preventDefault();
    if (!selectedId) return;
    setSubmittingReview(true);
    setReviewError(null);
    try {
      await apiService.addReportReview(selectedId, { decision: reviewDecision, review_note: reviewNote || null });
      setReviewNote('');
      setReviewDecision('investigation');
      loadSelectedReport(selectedId);
    } catch (err) {
      setReviewError(err.message || 'Failed to add review');
    } finally {
      setSubmittingReview(false);
    }
  };

  return (
    <Layout>
      <div className="page-reports">
        <h2>{isOfficer ? 'My assignments' : 'Reports'}</h2>
        <div className="reports-filters">
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className="filter-select">
            <option value="">All statuses</option>
            <option value="pending">Pending</option>
            <option value="passed">Passed</option>
            <option value="flagged">Flagged</option>
            <option value="rejected">Rejected</option>
          </select>
          <input type="date" value={filterFrom} onChange={(e) => setFilterFrom(e.target.value)} className="filter-date" placeholder="From" />
          <input type="date" value={filterTo} onChange={(e) => setFilterTo(e.target.value)} className="filter-date" placeholder="To" />
          <button type="button" className="btn-primary" onClick={applyFilters}>Apply</button>
        </div>
        {loading && <p className="loading">Loading reports…</p>}
        {error && <p className="error-message">{error}</p>}
        {!loading && !error && reports.length === 0 && (
          <p className="empty">No reports yet.</p>
        )}
        {!loading && !error && reports.length > 0 && (
          <>
            <div className="reports-layout">
              <div className="reports-main">
                <p className="reports-count">Showing {reports.length} of {total}</p>
                <div className="reports-feed" role="list">
                  {reports.map((r) => {
                const id = String(r.report_id);
                const s = String(r.rule_status || '').toLowerCase();
                const sm = statusMeta[s] || { label: r.rule_status || 'Unknown', bg: '#eff6ff', fg: statusColor(r.rule_status) };
                const desc = r.description || '';
                const isLong = desc.length > 180;
                const isExpanded = expanded.has(id);
                const preview = Array.isArray(r.evidence_preview) ? r.evidence_preview : [];
                const showPreview = preview.slice(0, 3);
                const extraCount = Math.max(0, (Number(r.evidence_count || preview.length) || 0) - showPreview.length);

                return (
                  <div
                    key={id}
                    className={`report-card ${selectedId === id ? 'selected' : ''}`}
                    role="listitem"
                    tabIndex={0}
                    onClick={() => openPanel(id)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') openPanel(id); }}
                    aria-label={`Open report ${id}`}
                  >
                    <div className="report-card-header">
                      <div className="report-card-title">
                        <span className="report-type">{r.incident_type_name || `Type ${r.incident_type_id}`}</span>
                        <span className="report-time">· {formatDate(r.reported_at)}</span>
                      </div>
                      <span className="report-status" style={{ background: sm.bg, color: sm.fg }}>
                        {sm.label}
                      </span>
                    </div>

                    <div className="report-card-meta">
                      <span className="report-location" title={r.latitude != null && r.longitude != null ? `${Number(r.latitude).toFixed(5)}, ${Number(r.longitude).toFixed(5)}` : ''}>
                        {renderLocation(r)}
                      </span>
                      {Number(r.evidence_count || 0) > 0 && (
                        <span className="report-attachments">
                          {Number(r.evidence_count || 0)} attachment{Number(r.evidence_count || 0) === 1 ? '' : 's'}
                        </span>
                      )}
                    </div>

                    {desc && (
                      <div className="report-card-body">
                        <p className={`report-description ${isExpanded ? 'expanded' : ''}`}>
                          {isExpanded || !isLong ? desc : `${desc.slice(0, 180)}…`}
                        </p>
                        {isLong && (
                          <button
                            type="button"
                            className="report-see-more"
                            onClick={(e) => { e.stopPropagation(); toggleExpanded(id); }}
                          >
                            {isExpanded ? 'See less' : 'See more'}
                          </button>
                        )}
                      </div>
                    )}

                    {showPreview.length > 0 && (
                      <div className="report-media report-media-carousel" onClick={(e) => e.stopPropagation()} role="presentation">
                        <div className="report-media-inner">
                          {showPreview.length > 1 && (
                            <button
                              type="button"
                              className="report-media-arrow report-media-arrow-prev"
                              aria-label="Previous evidence"
                              onClick={(e) => { e.stopPropagation(); goEvidence(id, -1, showPreview.length); }}
                            >
                              ‹
                            </button>
                          )}
                          <div className="report-media-slide">
                            {(() => {
                              const idx = Math.min(evidenceIndex[id] ?? 0, showPreview.length - 1);
                              const p = showPreview[idx];
                              const type = String(p?.file_type || '').toLowerCase();
                              const isPhoto = type === 'photo';
                              const isVideo = type === 'video';
                              return (
                                <div key={p?.evidence_id ?? idx} className="report-media-tile">
                                  {isPhoto ? (
                                    <img src={p.file_url} alt="" loading="lazy" />
                                  ) : isVideo ? (
                                    <video
                                      src={p.file_url}
                                      controls
                                      className="report-media-video"
                                    />
                                  ) : (
                                    <audio
                                      src={p.file_url}
                                      controls
                                      className="report-media-audio"
                                    />
                                  )}
                                  {idx === showPreview.length - 1 && extraCount > 0 && (
                                    <div className="report-media-more">+{extraCount}</div>
                                  )}
                                </div>
                              );
                            })()}
                          </div>
                          {showPreview.length > 1 && (
                            <button
                              type="button"
                              className="report-media-arrow report-media-arrow-next"
                              aria-label="Next evidence"
                              onClick={(e) => { e.stopPropagation(); goEvidence(id, 1, showPreview.length); }}
                            >
                              ›
                            </button>
                          )}
                        </div>
                        {showPreview.length > 1 && (
                          <div className="report-media-dots">
                            {showPreview.map((_, i) => (
                              <button
                                key={i}
                                type="button"
                                className={`report-media-dot ${(evidenceIndex[id] ?? 0) === i ? 'active' : ''}`}
                                aria-label={`Evidence ${i + 1} of ${showPreview.length}`}
                                onClick={(e) => { e.stopPropagation(); setEvidenceIndex((prev) => ({ ...prev, [id]: i })); }}
                              />
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                  </div>
                );
                  })}
                </div>

                <div className="pagination feed-pagination">
                  <button type="button" disabled={!hasPrev || loading} onClick={() => loadReports(Math.max(0, offset - PAGE_SIZE))}>
                    Previous
                  </button>
                  <span className="pagination-info">{offset + 1}–{offset + reports.length} of {total}</span>
                  <button type="button" disabled={!hasMore || loading} onClick={() => loadReports(offset + PAGE_SIZE)}>
                    Load more
                  </button>
                </div>
              </div>

              <aside className="report-side-panel">
                <h3 className="side-panel-title">Report actions</h3>
                {!selectedId && <p className="side-panel-empty">Select a report to view details, assign, or review.</p>}
                {selectedId && (
                  <>
                    {panelLoading && <p className="loading">Loading…</p>}
                    {panelError && <p className="error-message">{panelError}</p>}
                    {!panelLoading && !panelError && selectedReport && (
                      <>
                        <div className="side-panel-summary">
                          <div className="side-panel-line">
                            <span className="side-label">Type</span>
                            <span>{selectedReport.incident_type_name || `Type ${selectedReport.incident_type_id}`}</span>
                          </div>
                          <div className="side-panel-line">
                            <span className="side-label">Status</span>
                            <span>{selectedReport.rule_status}</span>
                          </div>
                          <div className="side-panel-line">
                            <span className="side-label">Submitted</span>
                            <span>{formatDate(selectedReport.reported_at)}</span>
                          </div>
                          <div className="side-panel-line">
                            <span className="side-label">Location</span>
                            <span>
                              {selectedReport.incident_latitude != null && selectedReport.incident_longitude != null
                                ? `${Number(selectedReport.incident_latitude).toFixed(5)}, ${Number(selectedReport.incident_longitude).toFixed(5)}`
                                : selectedReport.latitude != null && selectedReport.longitude != null
                                  ? `${Number(selectedReport.latitude).toFixed(5)}, ${Number(selectedReport.longitude).toFixed(5)}`
                                  : '—'}
                              {formatLocationSource(selectedReport.incident_location_source) && (
                                <span className="location-source"> ({formatLocationSource(selectedReport.incident_location_source)})</span>
                              )}
                            </span>
                          </div>
                          {selectedReport.incident_village_name && (
                            <div className="side-panel-line">
                              <span className="side-label">Village</span>
                              <span>{selectedReport.incident_village_name}</span>
                            </div>
                          )}
                          {(selectedReport.incident_sector_name || selectedReport.incident_cell_name) && selectedReport.incident_village_name && (
                            <div className="side-panel-line">
                              <span className="side-label">Area</span>
                              <span>
                                {[selectedReport.incident_sector_name, selectedReport.incident_cell_name, selectedReport.incident_village_name]
                                  .filter(Boolean)
                                  .join(' › ')}
                              </span>
                            </div>
                          )}
                          {selectedReport.description && (
                            <div className="side-panel-description">
                              <span className="side-label">Description</span>
                              <p>{selectedReport.description}</p>
                            </div>
                          )}
                        </div>

                        {canAssignOrReview && (
                          <section className="side-panel-section">
                            <h4>Assign to officer</h4>
                            {assignError && <p className="error-message">{assignError}</p>}
                            <form onSubmit={handleAssignSubmit}>
                              <div className="form-row">
                                <label>Officer</label>
                                <select
                                  value={assignOfficerId}
                                  onChange={(e) => setAssignOfficerId(e.target.value)}
                                  onFocus={() => { if (!officerOptions.length) loadOfficerOptions(); }}
                                  required
                                  disabled={assigning}
                                >
                                  <option value="">Select officer</option>
                                  {officerOptions.map((o) => (
                                    <option key={o.police_user_id} value={o.police_user_id}>
                                      {[o.first_name, o.last_name].filter(Boolean).join(' ')} ({o.email})
                                    </option>
                                  ))}
                                </select>
                              </div>
                              <div className="form-row">
                                <label>Priority</label>
                                <select
                                  value={assignPriority}
                                  onChange={(e) => setAssignPriority(e.target.value)}
                                  disabled={assigning}
                                >
                                  <option value="low">Low</option>
                                  <option value="medium">Medium</option>
                                  <option value="high">High</option>
                                  <option value="urgent">Urgent</option>
                                </select>
                              </div>
                              <div className="form-actions">
                                <button type="submit" disabled={assigning || !assignOfficerId}>
                                  {assigning ? 'Assigning…' : 'Assign'}
                                </button>
                              </div>
                            </form>
                          </section>
                        )}

                        {assignments.length > 0 && (
                          <section className="side-panel-section">
                            <h4>Assignments</h4>
                            <ul className="assignments-list">
                              {assignments.map((a) => (
                                <li key={a.assignment_id}>
                                  <span className="assignment-officer">{a.officer_name || `Officer #${a.police_user_id}`}</span>
                                  <span className="assignment-meta">
                                    {a.priority} · {a.status} · {formatDate(a.assigned_at)}
                                  </span>
                                </li>
                              ))}
                            </ul>
                          </section>
                        )}

                        {canAssignOrReview && (
                          <section className="side-panel-section">
                            <h4>Add review</h4>
                            {reviewError && <p className="error-message">{reviewError}</p>}
                            <form onSubmit={handleReviewSubmit}>
                              <div className="form-row">
                                <label>Decision</label>
                                <select value={reviewDecision} onChange={(e) => setReviewDecision(e.target.value)} disabled={submittingReview}>
                                  <option value="investigation">Investigation</option>
                                  <option value="confirmed">Confirmed</option>
                                  <option value="rejected">Rejected</option>
                                </select>
                              </div>
                              <div className="form-row">
                                <label>Note (optional)</label>
                                <textarea
                                  value={reviewNote}
                                  onChange={(e) => setReviewNote(e.target.value)}
                                  rows={3}
                                  disabled={submittingReview}
                                />
                              </div>
                              <div className="form-actions">
                                <button type="submit" disabled={submittingReview}>
                                  {submittingReview ? 'Submitting…' : 'Submit review'}
                                </button>
                              </div>
                            </form>
                          </section>
                        )}

                        {reviews.length > 0 && (
                          <section className="side-panel-section">
                            <h4>Reviews</h4>
                            <ul className="reviews-list">
                              {reviews.map((rv) => (
                                <li key={rv.review_id}>
                                  <span className="review-decision">{rv.decision}</span>
                                  <span className="review-meta">
                                    {rv.reviewer_name || `User #${rv.police_user_id}`} · {formatDate(rv.reviewed_at)}
                                  </span>
                                  {rv.review_note && <p className="review-note">{rv.review_note}</p>}
                                </li>
                              ))}
                            </ul>
                          </section>
                        )}
                      </>
                    )}
                  </>
                )}
              </aside>
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}
