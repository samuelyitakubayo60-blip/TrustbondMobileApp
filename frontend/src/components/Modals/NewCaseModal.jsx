import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const NewCaseModal = ({ isOpen, onClose, onCreated, initialReportId }) => {
  const [title, setTitle] = useState('');
  const [incidentTypes, setIncidentTypes] = useState([]);
  const [incidentTypeId, setIncidentTypeId] = useState('');
  const [priority, setPriority] = useState('high');
  const [assignedToId, setAssignedToId] = useState('');
  const [officers, setOfficers] = useState([]);
  const [reportIds, setReportIds] = useState('');
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
    // Pre-fill the reports field when opened from a specific report
    setReportIds(initialReportId ? String(initialReportId) : '');
    setNotes('');
    setError('');
    setSaving(false);

    const load = async () => {
      try {
        const [types, offs] = await Promise.all([
          api.get('/api/v1/incident-types'),
          api.get('/api/v1/police-users/options'),
        ]);
        if (cancelled) return;
        setIncidentTypes(types || []);
        setOfficers(offs || []);
      } catch {
        if (cancelled) return;
        setIncidentTypes([]);
        setOfficers([]);
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
    // Expect comma-separated UUIDs for now
    const ids = (reportIds || '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    const payload = {
      title: title.trim(),
      description: notes.trim() || null,
      incident_type_id: incidentTypeId ? Number(incidentTypeId) : null,
      priority: priority || 'medium',
      report_ids: ids,
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
        </div>
        
        <div className="input-group">
          <div className="input-label">Assign Officer</div>
          <select
            className="select"
            value={assignedToId}
            onChange={(e) => setAssignedToId(e.target.value)}
            disabled
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
          <div className="input-label">Link Reports (comma-separated UUIDs)</div>
          <input
            className="input"
            placeholder="e.g. 5c9a... , 7bd2..."
            value={reportIds}
            onChange={(e) => setReportIds(e.target.value)}
          />
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