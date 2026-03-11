import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const LinkCaseModal = ({ isOpen, onClose, reportId, onLinked }) => {
  const [cases, setCases] = useState([]);
  const [selectedCaseId, setSelectedCaseId] = useState('');
  const [search, setSearch] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setSelectedCaseId('');
    setSearch('');
    setSaving(false);
    setError('');

    const load = async () => {
      try {
        const res = await api.get('/api/v1/cases?limit=50&offset=0');
        if (cancelled) return;
        setCases(res?.items || []);
      } catch (e) {
        if (cancelled) return;
        setCases([]);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const filteredCases = cases.filter((c) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      (c.case_number || '').toLowerCase().includes(q) ||
      (c.title || '').toLowerCase().includes(q) ||
      (c.location_name || '').toLowerCase().includes(q)
    );
  });

  const submit = async () => {
    if (!reportId) {
      setError('Missing report id.');
      return;
    }
    if (!selectedCaseId) {
      setError('Please choose a case to link.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      await api.post(`/api/v1/cases/${selectedCaseId}/reports`, {
        report_ids: [reportId],
      });
      onLinked?.();
      onClose?.();
    } catch (e) {
      setError(e?.message || 'Failed to link to case.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="modal-overlay open"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">Link Report to Existing Case</div>
          <div className="modal-close" onClick={onClose}>
            ✕
          </div>
        </div>

        {error && (
          <div
            className="alert alert-danger"
            style={{ marginBottom: '10px' }}
          >
            <span className="alert-icon">!</span>
            <div>{error}</div>
          </div>
        )}

        <div className="input-group">
          <div className="input-label">Search Cases</div>
          <input
            className="input"
            placeholder="Search by case number, title, or location..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div
          className="tbl-wrap"
          style={{ maxHeight: 260, overflowY: 'auto', marginBottom: 10 }}
        >
          <table>
            <thead>
              <tr>
                <th></th>
                <th>Case</th>
                <th>Location</th>
                <th>Type</th>
                <th>Reports</th>
              </tr>
            </thead>
            <tbody>
              {filteredCases.map((c) => (
                <tr key={c.case_id}>
                  <td>
                    <input
                      type="radio"
                      name="case"
                      checked={selectedCaseId === c.case_id}
                      onChange={() => setSelectedCaseId(c.case_id)}
                    />
                  </td>
                  <td>
                    <div style={{ fontWeight: 600, fontSize: '11px' }}>
                      {c.case_number || String(c.case_id).slice(0, 8)}
                    </div>
                    <div
                      style={{
                        fontSize: '11px',
                        color: 'var(--muted)',
                        maxWidth: 220,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {c.title || 'No title'}
                    </div>
                  </td>
                  <td>{c.location_name || '—'}</td>
                  <td>{c.incident_type_name || '—'}</td>
                  <td>{c.report_count}</td>
                </tr>
              ))}
              {!filteredCases.length && (
                <tr>
                  <td
                    colSpan={5}
                    style={{
                      fontSize: '12px',
                      color: 'var(--muted)',
                      textAlign: 'center',
                    }}
                  >
                    No cases found. Create a new case instead.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div
          style={{
            display: 'flex',
            gap: '8px',
            justifyContent: 'flex-end',
          }}
        >
          <button className="btn btn-outline" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Linking…' : 'Link to Case'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default LinkCaseModal;

