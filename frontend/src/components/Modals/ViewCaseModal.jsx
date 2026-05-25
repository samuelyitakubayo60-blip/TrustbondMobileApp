import React, { useEffect, useState } from 'react';
import api from '../../api/client';
import { formatLocalDate, formatLocalDateTime, parseApiDate } from '../../utils/dateTime';
import {
  formatCommunityConfirmation,
  communityBadgeClass,
} from '../../utils/reportOperationalLabels';
import { caseDisplayName, caseDisplayRef } from '../../utils/caseDisplay';

// AI-only status — excludes police/officer verification
const formatAIStatus = (report) => {
  const rs = (report?.rule_status || '').trim().toLowerCase();
  const vs = (report?.verification_status || '').trim().toLowerCase();
  const parts = [];
  if      (rs === 'passed')   parts.push('AI: passed');
  else if (rs === 'flagged')  parts.push('AI: needs review');
  else if (rs === 'rejected') parts.push('AI: rejected');
  else if (rs === 'pending')  parts.push('AI: pending');
  if      (vs === 'verified') parts.push('Auto-verified');
  else if (vs === 'rejected') parts.push('Rejected');
  return parts.join(' · ') || '—';
};

const PRIORITY_BADGE = { urgent: 'b-red', high: 'b-orange', medium: 'b-yellow', low: 'b-blue' };
const STATUS_BADGE   = { open: 'b-green', closed: 'b-gray', archived: 'b-gray' };

const ViewCaseModal = ({ isOpen, onClose, caseItem, onEdit }) => {
  const [reports, setReports]               = useState([]);
  const [loading, setLoading]               = useState(false);
  const [error, setError]                   = useState('');
  const [showMoveModal, setShowMoveModal]   = useState(false);
  const [selectedReport, setSelectedReport] = useState(null);
  const [availableCases, setAvailableCases] = useState([]);
  const [casesLoading, setCasesLoading]     = useState(false);
  const [selectedTargetCase, setSelectedTargetCase] = useState('');
  const [caseSearch, setCaseSearch]         = useState('');
  const [movingReport, setMovingReport]     = useState(false);
  const [unitLabels, setUnitLabels]         = useState({});

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    api.get('/api/v1/special-assignment-units/')
      .then((res) => {
        const list = Array.isArray(res?.data) ? res.data : Array.isArray(res) ? res : [];
        if (cancelled) return;
        const map = {};
        list.forEach((u) => { if (u?.unit_code) map[u.unit_code] = u.unit_name || u.unit_code; });
        setUnitLabels(map);
      })
      .catch(() => { if (!cancelled) setUnitLabels({}); });
    return () => { cancelled = true; };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || !caseItem?.case_id) return;
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setLoading(true); setError(''); setReports([]);
    });
    api.get(`/api/v1/cases/${caseItem.case_id}/reports`)
      .then((res) => { if (!cancelled) setReports(res || []); })
      .catch(async (e) => {
        if (cancelled) return;
        if (e?.status === 405) {
          const target = String(caseItem.case_id || '').toLowerCase();
          try {
            const matched = []; let offset = 0; const limit = 100; let total = null;
            let sawCaseId = false; let anyRows = false;
            while (!cancelled) {
              const page = await api.get(`/api/v1/reports/?limit=${limit}&offset=${offset}`);
              const items = Array.isArray(page) ? page : page?.items ?? [];
              if (total === null && page && typeof page.total === 'number') total = page.total;
              if (items.length) anyRows = true;
              for (const r of items) {
                if (r && Object.prototype.hasOwnProperty.call(r, 'case_id')) sawCaseId = true;
                if (r?.case_id && String(r.case_id).toLowerCase() === target) matched.push(r);
              }
              if (items.length < limit) break;
              offset += limit;
              if (total != null && offset >= total) break;
              if (offset > 50000) break;
            }
            if (cancelled) return;
            matched.sort((a, b) => {
              const bt = parseApiDate(b.reported_at)?.getTime() || 0;
              const at = parseApiDate(a.reported_at)?.getTime() || 0;
              return bt - at;
            });
            setReports(matched);
            if (anyRows && !sawCaseId) setError('This API does not include case_id on reports yet.');
          } catch (inner) {
            if (!cancelled) setError(inner?.message || 'Failed to load reports for this case.');
          }
          return;
        }
        setError(e?.message || 'Failed to load case reports.');
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [isOpen, caseItem?.case_id]);

  if (!isOpen || !caseItem) return null;

  const caseLat = Number(caseItem?.latitude);
  const caseLon = Number(caseItem?.longitude);
  const hasCaseCoords = Number.isFinite(caseLat) && Number.isFinite(caseLon);
  const reportCoords = reports
    .map((r) => ({ lat: Number(r?.latitude), lon: Number(r?.longitude) }))
    .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  const derivedLat = reportCoords.length > 0 ? reportCoords.reduce((a, p) => a + p.lat, 0) / reportCoords.length : null;
  const derivedLon = reportCoords.length > 0 ? reportCoords.reduce((a, p) => a + p.lon, 0) / reportCoords.length : null;
  const navLat = hasCaseCoords ? caseLat : derivedLat;
  const navLon = hasCaseCoords ? caseLon : derivedLon;
  const hasUnifiedCoords = Number.isFinite(navLat) && Number.isFinite(navLon);

  const loadAvailableCases = async () => {
    setCasesLoading(true);
    try {
      const params = new URLSearchParams();
      if (caseSearch) params.append('search', caseSearch);
      if (selectedReport?.incident_type_id) params.append('incident_type_id', selectedReport.incident_type_id);
      params.append('limit', '50');
      const response = await api.get(`/api/v1/cases/?${params}`);
      let cases = Array.isArray(response) ? response : (response?.items || []);
      if (selectedReport?.incident_type_id)
        cases = cases.filter((c) => c.incident_type_id === selectedReport.incident_type_id);
      cases = cases.filter((c) => c.case_id !== caseItem.case_id);
      setAvailableCases(cases);
    } catch { setAvailableCases([]); }
    finally { setCasesLoading(false); }
  };

  const openMoveModal = (report) => {
    setSelectedReport(report); setShowMoveModal(true);
    setSelectedTargetCase(''); setCaseSearch(''); loadAvailableCases();
  };

  const moveReportToCase = async () => {
    if (!selectedTargetCase || !selectedReport?.report_id) return;
    setMovingReport(true);
    try {
      await api.post(`/api/v1/cases/reports/${selectedReport.report_id}/move`, { target_case_id: selectedTargetCase });
      setReports((prev) => prev.filter((r) => r.report_id !== selectedReport.report_id));
      setShowMoveModal(false); setSelectedReport(null); setSelectedTargetCase(''); setError('');
    } catch (e) {
      let msg = e?.message || 'Failed to move report';
      if (msg.includes('incident type mismatch')) msg = "Cannot move: incident types don't match.";
      else if (msg.includes('Access denied')) msg = "You don't have permission to move to this case.";
      setError(msg);
    } finally { setMovingReport(false); }
  };

  const hasRib = caseItem.special_assignment_unit || caseItem.rib_handed_over_at || caseItem.rib_handover_summary;

  return (
    <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 860, width: '94%' }}>

        {/* ── Header ── */}
        <div className="modal-header" style={{ flexWrap: 'wrap', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', flex: 1 }}>
            {caseDisplayRef(caseItem) && (
              <span className="badge b-blue" style={{ fontFamily: 'monospace', fontSize: 11, letterSpacing: '0.05em' }}>
                {caseDisplayRef(caseItem)}
              </span>
            )}
            <span style={{ fontWeight: 700, fontSize: 16 }}>{caseDisplayName(caseItem)}</span>
            <span className={`badge ${STATUS_BADGE[caseItem.status] || 'b-gray'}`} style={{ fontSize: 10 }}>
              {caseItem.status || 'unknown'}
            </span>
            <span className={`badge ${PRIORITY_BADGE[caseItem.priority] || 'b-gray'}`} style={{ fontSize: 10 }}>
              {caseItem.priority || '—'} priority
            </span>
          </div>
          <div className="modal-close" onClick={onClose}>✕</div>
        </div>

        <div style={{ maxHeight: '72vh', overflowY: 'auto', padding: '20px 20px 4px' }}>

          {/* ── Info tiles ── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(155px, 1fr))', gap: 10, marginBottom: 18 }}>
            {[
              { label: 'Status',          value: <span className={`badge ${STATUS_BADGE[caseItem.status] || 'b-gray'}`}>{caseItem.status || '—'}</span> },
              { label: 'Priority',        value: <span className={`badge ${PRIORITY_BADGE[caseItem.priority] || 'b-gray'}`}>{caseItem.priority || '—'}</span> },
              { label: 'Assigned Officer',value: caseItem.assigned_to_name || <span style={{ color: 'var(--muted)' }}>Unassigned</span> },
              { label: 'Linked Reports',  value: loading ? '…' : reports.length },
            ].map((f) => (
              <div key={f.label} style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '10px 14px' }}>
                <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 5 }}>{f.label}</div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{f.value}</div>
              </div>
            ))}
          </div>

          {/* ── Location ── */}
          <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '14px 16px', marginBottom: 14 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Location</div>
            <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
              {caseItem.location_name || (hasUnifiedCoords ? `${Number(navLat).toFixed(5)}, ${Number(navLon).toFixed(5)}` : <span style={{ color: 'var(--muted)', fontSize: 13 }}>Location not available</span>)}
            </div>
            {hasUnifiedCoords && (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => window.open(`https://www.google.com/maps/dir/?api=1&destination=${navLat},${navLon}`, '_blank')}
                >
                  Navigate to Case Area
                </button>
                <button
                  className="btn btn-outline btn-sm"
                  onClick={() => window.open(`https://www.google.com/maps?q=${navLat},${navLon}`, '_blank')}
                >
                  View on Map
                </button>
                {!hasCaseCoords && reportCoords.length > 0 && (
                  <span style={{ fontSize: 10, color: 'var(--muted)' }}>Using linked reports centre point</span>
                )}
              </div>
            )}
          </div>

          {/* ── Description ── */}
          <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '14px 16px', marginBottom: 14 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Description</div>
            <div style={{ fontSize: 13, color: 'var(--text)', lineHeight: 1.6 }}>
              {caseItem.description || <span style={{ color: 'var(--muted)', fontStyle: 'italic' }}>No description.</span>}
            </div>
          </div>

          {/* ── RIB / Special Assignment (only if present) ── */}
          {hasRib && (
            <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, padding: '14px 16px', marginBottom: 14 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>RIB / Special Assignment</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                {caseItem.special_assignment_unit && (
                  <div>
                    <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Unit</div>
                    <div style={{ fontSize: 13 }}>{unitLabels[caseItem.special_assignment_unit] || caseItem.special_assignment_unit}</div>
                  </div>
                )}
                {caseItem.rib_handed_over_at && (
                  <div>
                    <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Handed Over</div>
                    <div style={{ fontSize: 13 }}>{formatLocalDateTime(caseItem.rib_handed_over_at)}</div>
                  </div>
                )}
                {caseItem.rib_handover_summary && (
                  <div style={{ gridColumn: '1 / -1' }}>
                    <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>Handover Summary</div>
                    <div style={{ fontSize: 13, color: 'var(--text)' }}>{caseItem.rib_handover_summary}</div>
                  </div>
                )}
                <div style={{ gridColumn: '1 / -1' }}>
                  <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 2 }}>IO Checklist</div>
                  <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                    {caseItem.rib_handover_prerequisites_acknowledged
                      ? 'Acknowledged — manual record only'
                      : 'Not recorded yet — confirm in Edit Case'}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── Linked Reports ── */}
          <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                Linked Reports
              </div>
              <span className="badge b-blue" style={{ fontSize: 10 }}>
                {loading ? '…' : reports.length}
              </span>
            </div>

            {error && (
              <div style={{ padding: '10px 16px', fontSize: 12, color: 'var(--danger)', background: 'rgba(239,68,68,0.06)' }}>
                {error}
              </div>
            )}
            {loading && (
              <div style={{ padding: '28px 0', textAlign: 'center', fontSize: 12, color: 'var(--muted)' }}>
                Loading linked reports…
              </div>
            )}
            {!loading && !error && (
              <div className="tbl-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Report</th>
                      <th>Type</th>
                      <th>Village</th>
                      <th>AI Verification</th>
                      <th>Community</th>
                      <th>Date</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {reports.map((r) => (
                      <tr key={r.report_id}>
                        <td style={{ fontFamily: 'monospace', fontSize: 11, whiteSpace: 'nowrap' }}>
                          {r.report_number || String(r.report_id).slice(0, 8)}
                        </td>
                        <td style={{ fontSize: 12 }}>{r.incident_type_name || '—'}</td>
                        <td style={{ fontSize: 12 }}>{r.village_name || '—'}</td>
                        <td style={{ fontSize: 11, maxWidth: 180 }}>
                          <span title={formatAIStatus(r)}>{formatAIStatus(r)}</span>
                        </td>
                        <td style={{ fontSize: 11 }}>
                          <span className={`badge ${communityBadgeClass(r)}`} style={{ fontSize: 10 }}>
                            {formatCommunityConfirmation(r)}
                          </span>
                        </td>
                        <td style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
                          {formatLocalDate(r.reported_at)}
                        </td>
                        <td>
                          <button
                            className="btn btn-outline btn-sm"
                            style={{ fontSize: 10, padding: '2px 8px' }}
                            onClick={() => openMoveModal(r)}
                            title="Move report to a different case"
                          >
                            Move
                          </button>
                        </td>
                      </tr>
                    ))}
                    {!reports.length && (
                      <tr>
                        <td colSpan={7} style={{ textAlign: 'center', fontSize: 12, color: 'var(--muted)', padding: '28px 0' }}>
                          No reports linked to this case.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* ── Footer actions ── */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', padding: '16px 20px 20px' }}>
          <button className="btn btn-outline" onClick={onClose}>Close</button>
          <button className="btn btn-primary" onClick={() => onEdit?.(caseItem)}>Update Case</button>
        </div>

        {/* ── Move Report sub-modal ── */}
        {showMoveModal && (
          <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && setShowMoveModal(false)}>
            <div className="modal" style={{ maxWidth: 580, width: '90%' }}>
              <div className="modal-header">
                <div style={{ fontWeight: 700, fontSize: 15 }}>Move Report to Another Case</div>
                <div className="modal-close" onClick={() => setShowMoveModal(false)}>✕</div>
              </div>

              {/* Report info banner */}
              <div style={{ margin: '0 0 16px', padding: '10px 14px', background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.25)', borderRadius: 6, fontSize: 12 }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>Moving Report</div>
                <div style={{ color: 'var(--muted)' }}>
                  <strong>{selectedReport?.report_number || String(selectedReport?.report_id || '').slice(0, 8)}</strong>
                  {' · '}{selectedReport?.incident_type_name}
                  {' · From: '}<strong>{caseItem.case_number || 'Current Case'}</strong>
                </div>
                <div style={{ marginTop: 4, color: 'var(--muted)' }}>Only showing cases with the same incident type.</div>
              </div>

              <div className="input-group" style={{ marginBottom: 12 }}>
                <div className="input-label">Search cases</div>
                <input
                  className="input"
                  placeholder="Search by case number, title, or location…"
                  value={caseSearch}
                  onChange={(e) => { setCaseSearch(e.target.value); loadAvailableCases(); }}
                />
              </div>

              <div className="input-group">
                <div className="input-label">Select target case</div>
                {casesLoading ? (
                  <div style={{ padding: '24px 0', textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>Loading cases…</div>
                ) : availableCases.length === 0 ? (
                  <div style={{ padding: '24px 0', textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>No compatible cases found.</div>
                ) : (
                  <div style={{ maxHeight: 280, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 6 }}>
                    {availableCases.map((c) => (
                      <div
                        key={c.case_id}
                        onClick={() => setSelectedTargetCase(c.case_id)}
                        style={{
                          padding: '10px 14px',
                          borderBottom: '1px solid var(--border)',
                          cursor: 'pointer',
                          background: selectedTargetCase === c.case_id ? 'var(--primary)' : 'transparent',
                          color: selectedTargetCase === c.case_id ? 'white' : 'var(--text)',
                        }}
                      >
                        <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 2 }}>
                          {c.case_number || 'No number'} — {c.title || 'No title'}
                        </div>
                        <div style={{ fontSize: 11, opacity: 0.75, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                          <span className={`badge ${STATUS_BADGE[c.status] || 'b-gray'}`} style={{ fontSize: 9 }}>{c.status}</span>
                          <span className={`badge ${PRIORITY_BADGE[c.priority] || 'b-gray'}`} style={{ fontSize: 9 }}>{c.priority}</span>
                          <span>{c.report_count || 0} reports</span>
                          {c.location?.location_name && <span>{c.location.location_name}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
                <button className="btn btn-outline" onClick={() => setShowMoveModal(false)} disabled={movingReport}>Cancel</button>
                <button className="btn btn-primary" onClick={moveReportToCase} disabled={!selectedTargetCase || movingReport}>
                  {movingReport ? 'Moving…' : 'Move Report'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ViewCaseModal;
