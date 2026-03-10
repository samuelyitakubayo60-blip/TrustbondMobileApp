import React, { useEffect, useMemo, useState } from 'react';
import api from '../../api/client';

const AddIncidentModal = ({ isOpen, onClose, mode = 'add', incidentType = null, onSaved }) => {
  if (!isOpen) return null;

  const isEdit = mode === 'edit';
  const incidentId = incidentType?.incident_type_id;

  const initial = useMemo(() => {
    return {
      type_name: incidentType?.type_name ?? '',
      description: incidentType?.description ?? '',
      severity_weight: incidentType?.severity_weight ?? '1.0',
      is_active: incidentType?.is_active ?? true,
    };
  }, [incidentType]);

  const [typeName, setTypeName] = useState(initial.type_name);
  const [description, setDescription] = useState(initial.description);
  const [severity, setSeverity] = useState(String(initial.severity_weight ?? '1.0'));
  const [isActive, setIsActive] = useState(Boolean(initial.is_active));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setTypeName(initial.type_name);
    setDescription(initial.description);
    setSeverity(String(initial.severity_weight ?? '1.0'));
    setIsActive(Boolean(initial.is_active));
    setError('');
    setSaving(false);
  }, [initial, isOpen]);

  const submit = async () => {
    setError('');
    const name = typeName.trim();
    if (!name) {
      setError('Name is required.');
      return;
    }
    const sev = Number(severity);
    if (!Number.isFinite(sev) || sev <= 0) {
      setError('Severity multiplier must be a valid number (e.g. 1.2).');
      return;
    }

    const payload = {
      type_name: name,
      description: description.trim() || null,
      severity_weight: sev,
      is_active: Boolean(isActive),
    };

    setSaving(true);
    try {
      if (isEdit) {
        if (!incidentId) throw new Error('Missing incident type id.');
        await api.put(`/api/v1/incident-types/${incidentId}`, payload);
      } else {
        await api.post('/api/v1/incident-types', payload);
      }
      onSaved?.();
      onClose?.();
    } catch (e) {
      setError(e?.message || 'Failed to save incident type.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">{isEdit ? 'Edit Incident Type' : 'Add Incident Type'}</div>
          <div className="modal-close" onClick={onClose}>✕</div>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ marginBottom: '10px' }}>
            <span className="alert-icon">!</span>
            <div>{error}</div>
          </div>
        )}
        
        <div className="input-group">
          <div className="input-label">Name *</div>
          <input
            className="input"
            placeholder="e.g. Armed Robbery"
            value={typeName}
            onChange={(e) => setTypeName(e.target.value)}
          />
        </div>
        
        <div className="input-group">
          <div className="input-label">Description *</div>
          <textarea
            rows="3"
            placeholder="Brief description..."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          ></textarea>
        </div>
        
        <div className="input-group">
          <div className="input-label">Severity Multiplier (1.0–2.0) *</div>
          <input
            className="input"
            type="number"
            min="0.1"
            max="10"
            step="0.1"
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
          />
          <div style={{ fontSize: '10px', color: 'var(--muted)', marginTop: '3px' }}>
            1.0 = Low &nbsp;·&nbsp; 1.3–1.4 = High &nbsp;·&nbsp; 1.6–2.0 = Severe
          </div>
        </div>

        <div className="input-group" style={{ marginTop: '4px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--muted)' }}>
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
            Active
          </label>
        </div>
        
        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', marginTop: '6px' }}>
          <button className="btn btn-outline" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Saving…' : (isEdit ? 'Update Type' : 'Add Type')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default AddIncidentModal;