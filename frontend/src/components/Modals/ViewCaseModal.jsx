import React, { useEffect, useState } from 'react';
import api from '../../api/client';
import { formatLocalDate, parseApiDate } from '../../utils/dateTime';

const ViewCaseModal = ({ isOpen, onClose, caseItem, onEdit }) => {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isOpen || !caseItem?.case_id) return;
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      setLoading(true);
      setError('');
      setReports([]);
    });
    api
      .get(`/api/v1/cases/${caseItem.case_id}/reports`)
      .then((res) => {
        if (cancelled) return;
        setReports(res || []);
      })
      .catch(async (e) => {
        if (cancelled) return;
        // Older backends: only POST /cases/{id}/reports — paginate /reports (limit ≤ 100) and filter by case_id.
        if (e?.status === 405) {
          const target = String(caseItem.case_id || '').toLowerCase();
          try {
            const matched = [];
            let offset = 0;
            const limit = 100;
            let total = null;
            let sawCaseId = false;
            let anyRows = false;
            while (!cancelled) {
              const page = await api.get(`/api/v1/reports?limit=${limit}&offset=${offset}`);
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
            if (anyRows && !sawCaseId) {
              setError(
                'This API does not include case_id on reports yet. Deploy the latest backend for linked reports.',
              );
            }
          } catch (inner) {
            if (!cancelled) {
              setError(inner?.message || 'Failed to load reports for this case.');
            }
          }
          return;
        }
        setError(e?.message || 'Failed to load case reports.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, caseItem?.case_id]);

  if (!isOpen || !caseItem) return null;

  const caseLat = Number(caseItem?.latitude);
  const caseLon = Number(caseItem?.longitude);
  const hasCaseCoords = Number.isFinite(caseLat) && Number.isFinite(caseLon);
  const reportCoords = reports
    .map((r) => ({
      lat: Number(r?.latitude),
      lon: Number(r?.longitude),
    }))
    .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  const derivedLat =
    reportCoords.length > 0
      ? reportCoords.reduce((acc, p) => acc + p.lat, 0) / reportCoords.length
      : null;
  const derivedLon =
    reportCoords.length > 0
      ? reportCoords.reduce((acc, p) => acc + p.lon, 0) / reportCoords.length
      : null;
  const navLat = hasCaseCoords ? caseLat : derivedLat;
  const navLon = hasCaseCoords ? caseLon : derivedLon;
  const hasUnifiedCoords = Number.isFinite(navLat) && Number.isFinite(navLon);

  return (
    <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 820 }}>
        <div className="modal-header">
          <div className="modal-title">
            Case Details - {caseItem.case_number || String(caseItem.case_id).slice(0, 8)}
          </div>
          <div className="modal-close" onClick={onClose}>x</div>
        </div>

        <div className="form-grid" style={{ marginBottom: 10 }}>
          <div className="input-group">
            <div className="input-label">Title</div>
            <div>{caseItem.title || 'Untitled Case'}</div>
          </div>
          <div className="input-group">
            <div className="input-label">Status</div>
            <div>{caseItem.status || '-'}</div>
          </div>
          <div className="input-group">
            <div className="input-label">Priority</div>
            <div>{caseItem.priority || '-'}</div>
          </div>
          <div className="input-group">
            <div className="input-label">Assigned Officer</div>
            <div>{caseItem.assigned_to_name || 'Unassigned'}</div>
          </div>
          <div className="input-group">
            <div className="input-label">Location</div>
            <div>
              {caseItem.location_name || hasUnifiedCoords ? (
                <div>
                  <div style={{ fontSize: '13px', marginBottom: '4px', color: 'var(--text)' }}>
                    {caseItem.location_name || 
                      `${Number(navLat).toFixed(6)}, ${Number(navLon).toFixed(6)}`
                    }
                  </div>
                  {hasUnifiedCoords && (
                    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                      <button
                        onClick={() => {
                          window.open(
                            `https://www.google.com/maps/dir/?api=1&destination=${navLat},${navLon}`,
                            '_blank'
                          );
                        }}
                        style={{
                          padding: '4px 8px',
                          fontSize: '10px',
                          backgroundColor: 'var(--primary)',
                          color: 'white',
                          border: 'none',
                          borderRadius: '3px',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '3px'
                        }}
                      >
                        🚗 Navigate to Case Area
                      </button>
                      <button
                        onClick={() => {
                          window.open(
                            `https://www.google.com/maps?q=${navLat},${navLon}`,
                            '_blank'
                          );
                        }}
                        style={{
                          padding: '4px 8px',
                          fontSize: '10px',
                          backgroundColor: 'var(--secondary)',
                          color: 'white',
                          border: 'none',
                          borderRadius: '3px',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '3px'
                        }}
                      >
                        📍 View Map
                      </button>
                      {!hasCaseCoords && reportCoords.length > 0 && (
                        <span style={{ fontSize: '10px', color: 'var(--muted)', alignSelf: 'center' }}>
                          Using linked reports center point
                        </span>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <span style={{ color: 'var(--muted)', fontSize: '12px' }}>
                  Location not available
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="input-group" style={{ marginBottom: 10 }}>
          <div className="input-label">Description</div>
          <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>
            {caseItem.description || 'No description yet.'}
          </div>
        </div>

        <div className="input-group">
          <div className="input-label">Linked Reports ({reports.length})</div>
          {loading && <div style={{ fontSize: 12, color: 'var(--muted)' }}>Loading reports...</div>}
          {error && <div style={{ fontSize: 12, color: 'var(--danger)' }}>{error}</div>}
          {!loading && !error && (
            <div className="tbl-wrap" style={{ maxHeight: 260 }}>
              <table>
                <thead>
                  <tr>
                    <th>Report</th>
                    <th>Type</th>
                    <th>Village</th>
                    <th>Status</th>
                    <th>Date</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.map((r) => (
                    <tr key={r.report_id}>
                      <td style={{ fontFamily: 'monospace', fontSize: 11 }}>
                        {r.report_number || String(r.report_id).slice(0, 8)}
                      </td>
                      <td>{r.incident_type_name || '-'}</td>
                      <td>{r.village_name || '-'}</td>
                      <td>{r.rule_status || r.status || '-'}</td>
                      <td style={{ fontSize: 11 }}>{formatLocalDate(r.reported_at)}</td>
                    </tr>
                  ))}
                  {!reports.length && (
                    <tr>
                      <td colSpan={5} style={{ textAlign: 'center', fontSize: 12, color: 'var(--muted)' }}>
                        No reports linked to this case.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 10 }}>
          <button className="btn btn-outline" onClick={onClose}>Close</button>
          <button className="btn btn-primary" onClick={() => onEdit?.(caseItem)}>
            Update Case
          </button>
        </div>
      </div>
    </div>
  );
};

export default ViewCaseModal;
