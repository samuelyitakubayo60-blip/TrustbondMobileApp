import React, { useEffect, useMemo, useState } from 'react';
import api from '../../api/client';

const AddIncidentModal = ({ isOpen, onClose, mode = 'add', incidentType = null, onSaved }) => {
  const isEdit = mode === 'edit';
  const incidentId = incidentType?.incident_type_id;

  const initial = useMemo(() => {
    return {
      type_name: incidentType?.type_name ?? '',
      description: incidentType?.description ?? '',
      semantic_definition: incidentType?.semantic_definition ?? '',
      severity_weight: incidentType?.severity_weight ?? '1.0',
      is_active: incidentType?.is_active ?? true,
    };
  }, [incidentType]);

  const [typeName, setTypeName] = useState(initial.type_name);
  const [description, setDescription] = useState(initial.description);
  const [semanticDef, setSemanticDef] = useState(initial.semantic_definition);
  const [severity, setSeverity] = useState(String(initial.severity_weight ?? '1.0'));
  const [isActive, setIsActive] = useState(Boolean(initial.is_active));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setTypeName(initial.type_name);
    setDescription(initial.description);
    setSemanticDef(initial.semantic_definition);
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
      semantic_definition: semanticDef.trim() || null,
      severity_weight: sev,
      is_active: Boolean(isActive),
    };

    setSaving(true);
    try {
      if (isEdit) {
        if (!incidentId) throw new Error('Missing incident type id.');
        await api.put(`/api/v1/incident-types/${incidentId}`, payload);
      } else {
        await api.post('/api/v1/incident-types/', payload);
      }
      onSaved?.();
      onClose?.();
    } catch (e) {
      setError(e?.message || 'Failed to save incident type.');
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 640, width: '95%', padding: '28px 32px' }}>
        <div className="modal-header" style={{ marginBottom: 16 }}>
          <div className="modal-title" style={{ fontSize: 18, fontWeight: 700 }}>
            {isEdit ? 'Edit Incident Type' : 'Add Incident Type'}
          </div>
          <div className="modal-close" onClick={onClose}>✕</div>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ marginBottom: 14 }}>
            <span className="alert-icon">!</span>
            <div>{error}</div>
          </div>
        )}

        {/* Two-column row: Name + Severity */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 160px', gap: 16, marginBottom: 4 }}>
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
            <div className="input-label">Severity (1.0–2.0) *</div>
            <input
              className="input"
              type="number"
              min="0.1"
              max="10"
              step="0.1"
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
            />
            <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 3 }}>
              1.0 = Low · 1.3 = High · 1.6+ = Severe
            </div>
          </div>
        </div>

        <div className="input-group">
          <div className="input-label">Description *</div>
          <textarea
            rows="2"
            placeholder="Brief description of this incident type..."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            style={{ fontSize: 13, lineHeight: 1.5 }}
          ></textarea>
        </div>

        {/* Semantic definition — prominent section */}
        <div className="input-group" style={{ marginTop: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
            <div className="input-label" style={{ margin: 0, fontSize: 13, fontWeight: 600 }}>
              Semantic Definition (AI Verification)
            </div>
            <span style={{ fontSize: 11, color: semanticDef.length > 100 ? 'var(--success, #16a34a)' : 'var(--muted)', fontWeight: 500 }}>
              {semanticDef.length} chars
            </span>
          </div>
          <textarea
            rows="8"
            placeholder="Detailed definition used by the AI pipeline to match citizen reports to this incident type. Describe what this crime looks like, common scenarios, typical evidence, and keywords..."
            value={semanticDef}
            onChange={(e) => setSemanticDef(e.target.value)}
            style={{
              fontSize: 13,
              lineHeight: 1.6,
              padding: '12px 14px',
              borderRadius: 8,
              border: '1.5px solid var(--border, #e2e8f0)',
              background: 'var(--bg-secondary, #f8fafc)',
              transition: 'border-color 0.2s, box-shadow 0.2s',
              resize: 'vertical',
              minHeight: 120,
            }}
            onFocus={(e) => {
              e.target.style.borderColor = 'var(--primary, #2563eb)';
              e.target.style.boxShadow = '0 0 0 3px rgba(37,99,235,0.1)';
            }}
            onBlur={(e) => {
              e.target.style.borderColor = 'var(--border, #e2e8f0)';
              e.target.style.boxShadow = 'none';
            }}
          ></textarea>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4, lineHeight: 1.4 }}>
            A rich, detailed definition helps the AI accurately match citizen reports to this incident type during the verification pipeline.
          </div>
        </div>

        {/* Active toggle */}
        <div className="input-group" style={{ marginTop: 10 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--muted)', cursor: 'pointer' }}>
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
            Active — visible to citizens for reporting
          </label>
        </div>

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 18, paddingTop: 14, borderTop: '1px solid var(--border, #e2e8f0)' }}>
          <button className="btn btn-outline" onClick={onClose} style={{ padding: '8px 20px' }}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving} style={{ padding: '8px 24px', fontWeight: 600 }}>
            {saving ? 'Saving…' : (isEdit ? 'Update Type' : 'Add Type')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default AddIncidentModal;