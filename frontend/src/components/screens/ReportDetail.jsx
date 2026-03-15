import React, { useEffect, useState } from 'react';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';

const ReportDetail = ({ goToScreen, openModal, reportId }) => {
  const { user: me } = useAuth();
  const role = me?.role || 'officer';
  const canTriage = role === 'admin' || role === 'supervisor';

  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [savingDecision, setSavingDecision] = useState('');
  const [mlPrediction, setMlPrediction] = useState(null);
  const [mlLoading, setMlLoading] = useState(false);
  const [relatedReports, setRelatedReports] = useState([]);
  const [relatedLoading, setRelatedLoading] = useState(false);

  useEffect(() => {
    if (!reportId) {
      setError('No report selected.');
      setLoading(false);
      return;
    }
    let mounted = true;
    setLoading(true);
    api
      .get(`/api/v1/reports/${reportId}`)
      .then((res) => {
        if (!mounted) return;
        setReport(res);
        setLoading(false);
      })
      .catch((err) => {
        if (!mounted) return;
        setError(err?.data?.detail || err?.message || 'Failed to load report.');
        setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [reportId]);

  // Load ML prediction for this report
  useEffect(() => {
    if (!report || !report.report_id || !report.device_id) return;
    let cancelled = false;
    setMlLoading(true);
    api
      .get(
        `/api/v1/devices/reports/${report.report_id}/prediction?device_id=${report.device_id}`,
      )
      .then((res) => {
        if (cancelled) return;
        setMlPrediction(res);
      })
      .catch(() => {
        if (cancelled) return;
        setMlPrediction(null);
      })
      .finally(() => {
        if (!cancelled) setMlLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [report]);

  // Load related reports
  useEffect(() => {
    if (!report || !report.report_id) return;
    let cancelled = false;
    setRelatedLoading(true);
    api
      .get(`/api/v1/reports/${report.report_id}/related`)
      .then((res) => {
        if (cancelled) return;
        setRelatedReports(res || []);
      })
      .catch(() => {
        if (cancelled) return;
        setRelatedReports([]);
      })
      .finally(() => {
        if (!cancelled) setRelatedLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [report]);

  const reload = async () => {
    if (!reportId) return;
    setLoading(true);
    setError('');
    try {
      const res = await api.get(`/api/v1/reports/${reportId}`);
      setReport(res);
    } catch (err) {
      setError(err?.data?.detail || err?.message || 'Failed to load report.');
    } finally {
      setLoading(false);
    }
  };

  const submitReview = async (decision) => {
    if (!reportId) return;
    setSavingDecision(decision);
    setError('');
    try {
      await api.post(`/api/v1/reports/${reportId}/reviews`, {
        decision,
        review_note: '',
      });
      await reload();
    } catch (e) {
      setError(e?.message || 'Failed to submit review.');
    } finally {
      setSavingDecision('');
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 16, fontSize: 13, color: 'var(--muted)' }}>
        Loading report…
      </div>
    );
  }

  if (error || !report) {
    return (
      <div style={{ padding: 16 }}>
        <button
          className="btn btn-outline btn-sm"
          onClick={() => goToScreen('reports', 1)}
        >
          Back to Reports
        </button>
        <div style={{ marginTop: 12, color: 'var(--danger)', fontSize: 13 }}>
          {error || 'Report not found.'}
        </div>
      </div>
    );
  }

  const idLabel = report.report_number || String(report.report_id).slice(0, 8);
  const deviceShort = report.device_id ? String(report.device_id).slice(0, 4) : 'DEV';
  const trustScore = report.trust_score ?? 0;
  const createdAt = report.reported_at
    ? new Date(report.reported_at).toLocaleString()
    : '—';
  const assignments = report.assignments || [];

  return (
    <>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          marginBottom: '16px',
          flexWrap: 'wrap',
        }}
      >
        <button
          className="btn btn-outline btn-sm"
          onClick={() => goToScreen('reports', 1)}
        >
          Back to Reports
        </button>
        <div
          style={{
            fontFamily: '"Syne", sans-serif',
            fontWeight: 800,
            fontSize: '18px',
          }}
        >
          {idLabel}
        </div>
        <span
          className="badge b-green"
          style={{ fontSize: '12px', padding: '4px 10px' }}
        >
          {report.rule_status}
        </span>
        <div
          style={{
            marginLeft: 'auto',
            display: 'flex',
            gap: '6px',
            flexWrap: 'wrap',
          }}
        >
          {canTriage && (
            <>
              <button
                className="btn btn-success btn-sm"
                onClick={() => submitReview('confirmed')}
                disabled={!!savingDecision}
              >
                {savingDecision === 'confirmed' ? 'Saving…' : 'Confirm'}
              </button>
              <button
                className="btn btn-danger btn-sm"
                onClick={() => submitReview('rejected')}
                disabled={!!savingDecision}
              >
                {savingDecision === 'rejected' ? 'Saving…' : 'Flag'}
              </button>
              <button
                className="btn btn-outline btn-sm"
                onClick={() => openModal('assign')}
              >
                Assign Officer
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={() => openModal('newCase')}
              >
                Create Case
              </button>
              <button
                className="btn btn-warn btn-sm"
                onClick={() => openModal('linkCase')}
              >
                Link to Case
              </button>
            </>
          )}
        </div>
      </div>

      <div className="detail-layout">
        <div className="detail-col">
          <div className="card">
            <div className="card-header">
              <div className="card-title">Incident Details</div>
            </div>
            <div className="detail-grid">
              <div className="detail-field">
                <div className="dfl">Incident Type</div>
                <div className="dfv" style={{ color: 'var(--danger)' }}>
                  {report.incident_type_name || '—'}
                </div>
              </div>
              <div className="detail-field">
                <div className="dfl">Location</div>
                <div className="dfv">
                  {report.incident_village_name ||
                    report.village_name ||
                    '—'}
                </div>
              </div>
              <div className="detail-field">
                <div className="dfl">GPS Coords</div>
                <div
                  className="dfv"
                  style={{ fontSize: '11px', fontFamily: 'monospace' }}
                >
                  {report.latitude}, {report.longitude}
                </div>
              </div>
              <div className="detail-field">
                <div className="dfl">Submitted At</div>
                <div className="dfv" style={{ fontSize: '12px' }}>
                  {createdAt}
                </div>
              </div>
              <div className="detail-field">
                <div className="dfl">Device</div>
                <div
                  className="dfv"
                  style={{ fontSize: '11px', fontFamily: 'monospace' }}
                >
                  {deviceShort}
                </div>
              </div>
            </div>
            <div
              style={{
                background: 'var(--surface2)',
                borderRadius: 'var(--rs)',
                padding: '11px',
                border: '1px solid var(--border2)',
              }}
            >
              <div
                style={{
                  fontSize: '10px',
                  color: 'var(--muted)',
                  marginBottom: '5px',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                }}
              >
                Description
              </div>
              <div style={{ fontSize: '12px', lineHeight: 1.6 }}>
                {report.description || 'No description.'}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <div className="card-title">Evidence Attachments</div>
              <span className="badge b-blue">
                {report.evidence_files?.length || 0} files
              </span>
            </div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '10px',
              }}
            >
              {(report.evidence_files || []).map((ef) => (
                <div
                  key={ef.evidence_id}
                  style={{
                    background: 'var(--surface2)',
                    borderRadius: 'var(--rs)',
                    border: '1px solid var(--border2)',
                    padding: '12px',
                    textAlign: 'center',
                  }}
                >
                  <div
                    style={{
                      fontSize: '11px',
                      fontWeight: 700,
                      marginBottom: '4px',
                      color: 'var(--muted)',
                      textTransform: 'uppercase',
                      letterSpacing: '1px',
                    }}
                  >
                    {ef.file_type}
                  </div>
                  <div style={{ fontSize: '11px', fontWeight: 600 }}>
                    {ef.file_url}
                  </div>
                  <div
                    style={{
                      fontSize: '10px',
                      color: 'var(--muted)',
                      margin: '3px 0',
                    }}
                  >
                    {ef.uploaded_at
                      ? new Date(ef.uploaded_at).toLocaleString()
                      : ''}
                  </div>
                  {(ef.ai_quality_label || ef.blur_score || ef.tamper_score) && (
                    <div
                      style={{
                        marginTop: '6px',
                        fontSize: '10px',
                        color: 'var(--muted)',
                      }}
                    >
                      {ef.ai_quality_label && (
                        <div>
                          <strong>Quality:</strong> {ef.ai_quality_label}
                        </div>
                      )}
                      {typeof ef.blur_score !== 'undefined' && ef.blur_score !== null && (
                        <div>
                          <strong>Blur:</strong> {Number(ef.blur_score).toFixed(2)}
                        </div>
                      )}
                      {typeof ef.tamper_score !== 'undefined' && ef.tamper_score !== null && (
                        <div>
                          <strong>Tamper:</strong> {Number(ef.tamper_score).toFixed(2)}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
              {(!report.evidence_files ||
                report.evidence_files.length === 0) && (
                <div
                  style={{ fontSize: '12px', color: 'var(--muted)' }}
                >
                  No evidence uploaded.
                </div>
              )}
            </div>
          </div>

          {assignments.length > 0 && (
            <div className="card">
              <div className="card-header">
                <div className="card-title">Assignments</div>
                <span className="badge b-blue">
                  {assignments.length} active
                </span>
              </div>
              <div
                style={{
                  display: 'grid',
                  gap: '8px',
                }}
              >
                {assignments.map((a) => {
                  const isMine =
                    me?.police_user_id &&
                    a.police_user_id === me.police_user_id;
                  const statusBadge =
                    a.status === 'closed'
                      ? 'b-green'
                      : a.status === 'resolved'
                      ? 'b-green'
                      : a.status === 'investigating'
                      ? 'b-blue'
                      : 'b-orange';
                  const priorityBadge =
                    a.priority === 'high'
                      ? 'b-red'
                      : a.priority === 'medium'
                      ? 'b-orange'
                      : 'b-gray';
                  return (
                    <div
                      key={a.assignment_id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '8px 10px',
                        borderRadius: 'var(--rs)',
                        border: '1px solid var(--border2)',
                        background: isMine
                          ? 'rgba(79, 142, 247, 0.06)'
                          : 'var(--surface2)',
                        fontSize: '11px',
                      }}
                    >
                      <div>
                        <div
                          style={{
                            fontWeight: 600,
                            marginBottom: 2,
                          }}
                        >
                          {a.officer_name || 'Officer'}
                          {isMine && (
                            <span
                              style={{
                                marginLeft: 6,
                                fontSize: '10px',
                                color: 'var(--primary)',
                              }}
                            >
                              (you)
                            </span>
                          )}
                        </div>
                        <div
                          style={{
                            color: 'var(--muted)',
                          }}
                        >
                          Assigned{' '}
                          {a.assigned_at
                            ? new Date(a.assigned_at).toLocaleString()
                            : '—'}
                          {a.completed_at && (
                            <>
                              {' · '}Completed{' '}
                              {new Date(
                                a.completed_at,
                              ).toLocaleString()}
                            </>
                          )}
                        </div>
                      </div>
                      <div
                        style={{
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'flex-end',
                          gap: 4,
                        }}
                      >
                        <span
                          className={`badge ${priorityBadge}`}
                          style={{ fontSize: '10px' }}
                        >
                          {a.priority}
                        </span>
                        <span
                          className={`badge ${statusBadge}`}
                          style={{ fontSize: '10px' }}
                        >
                          {a.status}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <div className="detail-col">
          <div className="card">
            <div className="card-header">
              <div className="card-title">Trust Scores</div>
            </div>
            <div style={{ marginBottom: '12px' }}>
              {/* Report-level ML trust */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  marginBottom: '4px',
                }}
              >
                <span
                  style={{ fontSize: '11px', color: 'var(--muted)' }}
                >
                  Report Trust Score
                </span>
                <span
                  style={{
                    fontFamily: '"Syne", sans-serif',
                    fontWeight: 800,
                    fontSize: '17px',
                    color: 'var(--success)',
                  }}
                >
                  {mlPrediction
                    ? Math.round(mlPrediction.trust_score ?? 0)
                    : '—'}
                </span>
              </div>
              <div className="prog-bar" style={{ marginBottom: '8px' }}>
                <div
                  className="prog-fill"
                  style={{
                    width: `${
                      mlPrediction
                        ? Math.max(
                            0,
                            Math.min(
                              100,
                              mlPrediction.trust_score ?? 0,
                            ),
                          )
                        : 0
                    }%`,
                    background: 'var(--success)',
                  }}
                ></div>
              </div>

              {/* Device trust (from DB) */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  marginBottom: '4px',
                }}
              >
                <span
                  style={{ fontSize: '11px', color: 'var(--muted)' }}
                >
                  Device Trust Score
                </span>
                <span
                  style={{
                    fontFamily: '"Syne", sans-serif',
                    fontWeight: 800,
                    fontSize: '17px',
                    color: 'var(--success)',
                  }}
                >
                  {Math.round(trustScore)}
                </span>
              </div>
              <div className="prog-bar">
                <div
                  className="prog-fill"
                  style={{
                    width: `${Math.max(
                      0,
                      Math.min(100, trustScore),
                    )}%`,
                    background: 'var(--success)',
                  }}
                ></div>
              </div>
              {mlLoading && (
                <div
                  style={{
                    fontSize: '10px',
                    color: 'var(--muted)',
                    marginTop: 6,
                  }}
                >
                  Loading ML prediction…
                </div>
              )}
              {mlPrediction && !mlLoading && (
                <div
                  style={{
                    marginTop: 6,
                    fontSize: '10px',
                    color: 'var(--muted)',
                  }}
                >
                  <div>
                    Label:{' '}
                    <strong>{mlPrediction.prediction_label}</strong>{' '}
                    · Confidence{' '}
                    {Math.round((mlPrediction.confidence ?? 0) * 100)}%
                  </div>
                  <div>
                    Model: {mlPrediction.model_version}{' '}
                    {mlPrediction.evaluated_at &&
                      `· ${new Date(
                        mlPrediction.evaluated_at,
                      ).toLocaleString()}`}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Related reports card */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">Related Reports</div>
            </div>
            <div style={{ padding: '10px 14px', fontSize: '12px' }}>
              {relatedLoading && (
                <div
                  style={{ fontSize: '12px', color: 'var(--muted)' }}
                >
                  Loading related reports…
                </div>
              )}
              {!relatedLoading && relatedReports.length === 0 && (
                <div
                  style={{ fontSize: '12px', color: 'var(--muted)' }}
                >
                  No similar reports found in the last few days.
                </div>
              )}
              {relatedReports.map((r) => (
                <div
                  key={r.report_id}
                  style={{
                    padding: '8px 0',
                    borderBottom: '1px solid var(--border2)',
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      marginBottom: 2,
                    }}
                  >
                    <span
                      style={{
                        fontSize: '11px',
                        fontFamily: 'monospace',
                        color: 'var(--muted)',
                      }}
                    >
                      {r.report_number ||
                        String(r.report_id).slice(0, 8)}
                    </span>
                    <span
                      className={`badge ${
                        r.rule_status === 'passed'
                          ? 'b-green'
                          : r.rule_status === 'pending'
                          ? 'b-orange'
                          : 'b-red'
                      }`}
                      style={{ fontSize: '10px' }}
                    >
                      {r.rule_status}
                    </span>
                  </div>
                  <div style={{ fontSize: '11px' }}>
                    {r.incident_type_name || '—'} ·{' '}
                    {r.village_name || '—'}
                  </div>
                  <div
                    style={{
                      fontSize: '10px',
                      color: 'var(--muted)',
                      marginTop: 2,
                    }}
                  >
                    {r.reported_at
                      ? new Date(
                          r.reported_at,
                        ).toLocaleString()
                      : '—'}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  );
};

export default ReportDetail;