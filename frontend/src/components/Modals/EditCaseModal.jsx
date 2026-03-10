import React, { useEffect, useState } from 'react';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';

const EditCaseModal = ({ isOpen, onClose, caseItem, onSaved }) => {
  const { user: me } = useAuth();
  const role = me?.role || 'officer';
  const isAdminOrSupervisor = role === 'admin' || role === 'supervisor';

  const [status, setStatus] = useState(caseItem?.status || 'open');
  const [priority, setPriority] = useState(caseItem?.priority || 'medium');
  const [description, setDescription] = useState(caseItem?.description || '');
  const [outcome, setOutcome] = useState(caseItem?.outcome || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isOpen || !caseItem) return;
    setStatus(caseItem.status || 'open');
    setPriority(caseItem.priority || 'medium');
    setDescription(caseItem.description || '');
    setOutcome(caseItem.outcome || '');
    setError('');
    setSaving(false);
  }, [isOpen, caseItem]);

  if (!isOpen || !caseItem) return null;

  const submit = async () => {
    setSaving(true);
    setError('');
    const payload = {
      status,
      description,
      outcome,
      ...(isAdminOrSupervisor ? { priority } : {}),
    };
    try {
      await api.patch(`/api/v1/cases/${caseItem.case_id}`, payload);
      onSaved?.();
      onClose?.();
    } catch (e) {
      setError(e?.message || 'Failed to update case.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">
            Update Case — {caseItem.case_number || String(caseItem.case_id).slice(0, 8)}
          </div>
          <div className="modal-close" onClick={onClose}>✕</div>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ marginBottom: '10px' }}>
            <span className="alert-icon">!</span>
            <div>{error}</div>
          </div>
        )}

        <div className="form-grid" style={{ marginBottom: '12px' }}>
          <div className="input-group">
            <div className="input-label">Status</div>
            <select
              className="select"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="open">open</option>
              <option value="investigating">investigating</option>
              <option value="closed">closed</option>
            </select>
          </div>
          <div className="input-group">
            <div className="input-label">Priority</div>
            <select
              className="select"
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              disabled={!isAdminOrSupervisor}
            >
              <option value="high">high</option>
              <option value="medium">medium</option>
              <option value="low">low</option>
            </select>
          </div>
        </div>

        <div className="input-group">
          <div className="input-label">Description / Progress Notes</div>
          <textarea
            rows="3"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Update investigation details..."
          ></textarea>
        </div>

        <div className="input-group">
          <div className="input-label">Outcome</div>
          <textarea
            rows="2"
            value={outcome}
            onChange={(e) => setOutcome(e.target.value)}
            placeholder="Outcome (for closed cases)..."
          ></textarea>
        </div>

        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', marginTop: '10px' }}>
          <button className="btn btn-outline" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default EditCaseModal;

