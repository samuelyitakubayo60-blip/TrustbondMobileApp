import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Layout from '../components/Layout.jsx';
import EvidenceCarousel from '../components/EvidenceCarousel.jsx';
import { useAuth } from '../contexts/AuthContext.jsx';
import { apiService } from '../services/apiService.js';
import '../styles/colors.css';

export default function ReportDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { canAssignOrReview } = useAuth();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [assignModalOpen, setAssignModalOpen] = useState(false);
  const [officerOptions, setOfficerOptions] = useState([]);
  const [assignOfficerId, setAssignOfficerId] = useState('');
  const [assignPriority, setAssignPriority] = useState('medium');
  const [assignError, setAssignError] = useState(null);
  const [assigning, setAssigning] = useState(false);
  const [reviewDecision, setReviewDecision] = useState('investigation');
  const [reviewNote, setReviewNote] = useState('');
  const [reviewError, setReviewError] = useState(null);
  const [submittingReview, setSubmittingReview] = useState(false);

  const loadReport = useCallback(() => {
    if (!id) return;
    setLoading(true);
    setError(null);
    apiService
      .getReport(id)
      .then(setReport)
      .catch((err) => setError(err.message || 'Failed to load report'))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    loadReport();
  }, [loadReport]);

  function formatDate(s) {
    if (!s) return '—';
    return new Date(s).toLocaleString();
  }

  function formatLocationSource(source) {
    if (!source) return null;
    switch (source) {
      case 'same_village_all':
        return 'reporter and all evidence are in the same village';
      case 'village_conflict':
        return 'reporter village differs from some evidence villages';
      case 'evidence_only':
        return 'based only on evidence villages';
      case 'evidence_conflict':
        return 'evidence villages disagree';
      case 'reporter_only_no_village':
        return 'reporter point outside mapped villages';
      case 'evidence_only_no_village':
        return 'evidence point outside mapped villages';
      default:
        if (source === 'reporter_only') return null;
        return source;
    }
  }

  const evidence = report?.evidence_files || [];
  const assignments = report?.assignments || [];
  const reviews = report?.reviews || [];

  const openAssignModal = () => {
    setAssignError(null);
    setAssignOfficerId('');
    setAssignPriority('medium');
    setAssignModalOpen(true);
    apiService
      .getOfficerOptions()
      .then((list) => {
        setOfficerOptions(Array.isArray(list) ? list : []);
        if (list?.length && !assignOfficerId) setAssignOfficerId(String(list[0].police_user_id));
      })
      .catch(() => setOfficerOptions([]));
  };

  const submitAssign = async (e) => {
    e.preventDefault();
    if (!id || !assignOfficerId) return;
    setAssigning(true);
    setAssignError(null);
    try {
      await apiService.assignReport(id, {
        police_user_id: Number(assignOfficerId),
        priority: assignPriority,
      });
      setAssignModalOpen(false);
      loadReport();
    } catch (err) {
      setAssignError(err.message || 'Assign failed');
    } finally {
      setAssigning(false);
    }
  };

  const submitReview = async (e) => {
    e.preventDefault();
    if (!id) return;
    setSubmittingReview(true);
    setReviewError(null);
    try {
      await apiService.addReportReview(id, { decision: reviewDecision, review_note: reviewNote || null });
      setReviewNote('');
      setReviewDecision('investigation');
      loadReport();
    } catch (err) {
      setReviewError(err.message || 'Failed to add review');
    } finally {
      setSubmittingReview(false);
    }
  };

  return (
    <Layout>
      <div className="page-report-detail">
        <button type="button" className="back-button" onClick={() => navigate('/reports')}>
          ← Back to reports
        </button>
        {loading && <p className="loading">Loading…</p>}
        {error && <p className="error-message">{error}</p>}
        {!loading && !error && report && (
          <>
            <div className="report-detail-header">
              <h2>Report details</h2>
              {canAssignOrReview && (
                <button type="button" className="btn-primary" onClick={openAssignModal}>
                  Assign to officer
                </button>
              )}
            </div>
            <dl className="detail-list">
              <dt>Type</dt>
              <dd>{report.incident_type_name || `Type ${report.incident_type_id}`}</dd>
              <dt>Status</dt>
              <dd>{report.rule_status}</dd>
              <dt>Submitted</dt>
              <dd>{formatDate(report.reported_at)}</dd>
              <dt>Location</dt>
              <dd>
                {report.incident_latitude != null && report.incident_longitude != null
                  ? `${Number(report.incident_latitude).toFixed(5)}, ${Number(report.incident_longitude).toFixed(5)}`
                  : report.latitude != null && report.longitude != null
                    ? `${Number(report.latitude).toFixed(5)}, ${Number(report.longitude).toFixed(5)}`
                    : '—'}
                {formatLocationSource(report.incident_location_source) && (
                  <span className="location-source"> ({formatLocationSource(report.incident_location_source)})</span>
                )}
              </dd>
              {report.incident_village_name && (
                <>
                  <dt>Village</dt>
                  <dd className="location-names village-exact">
                    <strong>{report.incident_village_name}</strong>
                  </dd>
                </>
              )}
              {(report.incident_sector_name || report.incident_cell_name) && report.incident_village_name && (
                <>
                  <dt>Area</dt>
                  <dd className="location-names">
                    {[report.incident_sector_name, report.incident_cell_name, report.incident_village_name]
                      .filter(Boolean)
                      .join(' › ')}
                  </dd>
                </>
              )}
              {report.description && (
                <>
                  <dt>Description</dt>
                  <dd>{report.description}</dd>
                </>
              )}
            </dl>
            {assignments.length > 0 && (
              <section className="evidence-section">
                <h3>Assignments</h3>
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
            {reviews.length > 0 && (
              <section className="evidence-section">
                <h3>Reviews</h3>
                <ul className="reviews-list">
                  {reviews.map((r) => (
                    <li key={r.review_id}>
                      <span className="review-decision">{r.decision}</span>
                      <span className="review-meta">{r.reviewer_name || `User #${r.police_user_id}`} · {formatDate(r.reviewed_at)}</span>
                      {r.review_note && <p className="review-note">{r.review_note}</p>}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {canAssignOrReview && (
              <section className="evidence-section">
                <h3>Add review</h3>
                {reviewError && <p className="error-message">{reviewError}</p>}
                <form className="review-form" onSubmit={submitReview}>
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
                    <textarea value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} rows={3} disabled={submittingReview} />
                  </div>
                  <button type="submit" disabled={submittingReview}>{submittingReview ? 'Submitting…' : 'Submit review'}</button>
                </form>
              </section>
            )}
            {evidence.length > 0 && (
              <section className="evidence-section">
                <h3>Evidence</h3>
                <EvidenceCarousel items={evidence} />
              </section>
            )}
          </>
        )}
      </div>

      {assignModalOpen && (
        <div className="modal-overlay" onClick={() => !assigning && setAssignModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>Assign report to officer</h3>
            {assignError && <p className="error-message">{assignError}</p>}
            <form onSubmit={submitAssign}>
              <div className="form-row">
                <label>Officer</label>
                <select
                  value={assignOfficerId}
                  onChange={(e) => setAssignOfficerId(e.target.value)}
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
                <button type="button" onClick={() => !assigning && setAssignModalOpen(false)} disabled={assigning}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </Layout>
  );
}
