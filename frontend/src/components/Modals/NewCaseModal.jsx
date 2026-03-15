import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const NewCaseModal = ({ isOpen, onClose, onCreated, initialReportId }) => {
  const [title, setTitle] = useState('');
  const [incidentTypes, setIncidentTypes] = useState([]);
  const [incidentTypeId, setIncidentTypeId] = useState('');
  const [priority, setPriority] = useState('high');
  const [assignedToId, setAssignedToId] = useState('');
  const [officers, setOfficers] = useState([]);
  const [availableReports, setAvailableReports] = useState([]);
  const [selectedReportIds, setSelectedReportIds] = useState(new Set());
  const [sectorId, setSectorId] = useState('');
  const [sectors, setSectors] = useState([]);
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setTitle('');
    setIncidentTypeId('');
    setPriority('high');
    setAssignedToId('');
    setAvailableReports([]);
    setSelectedReportIds(
      initialReportId ? new Set([String(initialReportId)]) : new Set(),
    );
    setNotes('');
    setSectorId('');
    setError('');
    setSaving(false);

    const load = async () => {
      try {
        const [types, offs, locs] = await Promise.all([
          api.get('/api/v1/incident-types'),
          api.get('/api/v1/police-users/options'),
          api.get('/api/v1/locations'),
        ]);
        if (cancelled) return;
        setIncidentTypes(types || []);
        setOfficers(offs || []);
        const sectorList = (locs || []).filter((l) => l.location_type === 'sector');
        setSectors(sectorList);
      } catch {
        if (cancelled) return;
        setIncidentTypes([]);
        setOfficers([]);
        setSectors([]);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const submit = async () => {
    if (!title.trim()) {
      setError('Case title is required.');
      return;
    }
    setSaving(true);
    setError('');
    const ids = Array.from(selectedReportIds);

    const payload = {
      title: title.trim(),
      description: notes.trim() || null,
      incident_type_id: incidentTypeId ? Number(incidentTypeId) : null,
      priority: priority || 'medium',
      report_ids: ids,
      assigned_to_id: assignedToId ? Number(assignedToId) : null,
      location_id: sectorId ? Number(sectorId) : null,
    };

    try {
      await api.post('/api/v1/cases', payload);
      onCreated?.();
      onClose?.();
    } catch (e) {
      setError(e?.message || 'Failed to create case.');
    } finally {
      setSaving(false);
    }
  };

  const toggleReportSelected = (id) => {
    setSelectedReportIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  // When sector is chosen, load available reports for that sector (not yet linked to any case).
  const loadReportsForSector = async (newSectorId) => {
    setAvailableReports([]);
    setSelectedReportIds(
      initialReportId ? new Set([String(initialReportId)]) : new Set(),
    );
    if (!newSectorId) return;
    try {
      const res = await api.get(
        `/api/v1/cases/available-reports?sector_location_id=${newSectorId}`,
      );
      setAvailableReports(res || []);
      // If modal was opened from a specific report, keep it pre-selected if present.
      if (initialReportId) {
        const found = (res || []).some(
          (r) => String(r.report_id) === String(initialReportId),
        );
        if (found) {
          setSelectedReportIds(new Set([String(initialReportId)]));
        }
      }
    } catch {
      setAvailableReports([]);
    }
  };

  return (
    <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">Create New Case</div>
          <div className="modal-close" onClick={onClose}>✕</div>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ marginBottom: '10px' }}>
            <span className="alert-icon">!</span>
            <div>{error}</div>
          </div>
        )}
        
        <div className="input-group">
          <div className="input-label">Case Title *</div>
          <input
            className="input"
            placeholder="e.g. Muhoza Market Assault Series"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        
        <div className="form-grid">
          <div className="input-group">
            <div className="input-label">Incident Type</div>
            <select
              className="select"
              value={incidentTypeId}
              onChange={(e) => setIncidentTypeId(e.target.value)}
            >
              <option value="">— Select type —</option>
              {incidentTypes.map((t) => (
                <option key={t.incident_type_id} value={t.incident_type_id}>
                  {t.type_name}
                </option>
              ))}
            </select>
          </div>
          <div className="input-group">
            <div className="input-label">Priority *</div>
            <select
              className="select"
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
            >
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>
          <div className="input-group">
            <div className="input-label">Sector (Case Location)</div>
            <select
              className="select"
              value={sectorId}
              onChange={(e) => {
                const val = e.target.value;
                setSectorId(val);
                loadReportsForSector(val);
              }}
            >
              <option value="">— Detect from linked reports or choose sector —</option>
              {sectors.map((s) => (
                <option key={s.location_id} value={s.location_id}>
                  {s.location_name}
                </option>
              ))}
            </select>
          </div>
        </div>
        
        <div className="input-group">
          <div className="input-label">Assign Officer</div>
          <select
            className="select"
            value={assignedToId}
            onChange={(e) => setAssignedToId(e.target.value)}
          >
            <option value="">Unassigned (assignment handled separately)</option>
            {officers.map((o) => (
              <option key={o.police_user_id} value={o.police_user_id}>
                {o.first_name} {o.last_name}
              </option>
            ))}
          </select>
        </div>
        
        <div className="input-group">
          <div className="input-label">Link Reports in Sector</div>
          {!sectorId && (
            <div style={{ fontSize: '11px', color: 'var(--muted)' }}>
              Select a <strong>Sector</strong> first to see unassigned reports in that area.
            </div>
          )}
          {sectorId && (
            <div
              style={{
                maxHeight: '180px',
                overflowY: 'auto',
                border: '1px solid var(--border-subtle)',
                borderRadius: '8px',
                padding: '6px 8px',
                marginTop: '4px',
              }}
            >
              {availableReports.length === 0 && (
                <div style={{ fontSize: '11px', color: 'var(--muted)' }}>
                  No unassigned reports found for this sector.
                </div>
              )}
              {availableReports.map((r) => (
                <label
                  key={r.report_id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontSize: '11px',
                    marginBottom: '4px',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={selectedReportIds.has(String(r.report_id))}
                    onChange={() => toggleReportSelected(String(r.report_id))}
                  />
                  <span style={{ fontFamily: 'monospace' }}>
                    {r.report_number || String(r.report_id).slice(0, 8)}
                  </span>
                  <span style={{ color: 'var(--muted)' }}>
                    · {r.incident_type_name || 'Incident'} ·{' '}
                    {r.village_name || 'Unknown'}
                  </span>
                </label>
              ))}
            </div>
          )}
        </div>
        
        <div className="input-group">
          <div className="input-label">Notes</div>
          <textarea
            rows="3"
            placeholder="Initial case notes..."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          ></textarea>
        </div>
        
        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
          <button className="btn btn-outline" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Creating…' : 'Create Case'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default NewCaseModal;