import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const AssignModal = ({ isOpen, onClose, reportId, onAssigned }) => {
  const [officers, setOfficers] = useState([]);
  const [officerId, setOfficerId] = useState('');
  const [priority, setPriority] = useState('high');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setError('');
    setSaving(false);
    setOfficerId('');
    setPriority('high');
    setNotes('');
    const path = reportId
      ? `/api/v1/police-users/options?report_id=${reportId}`
      : '/api/v1/police-users/options';
    api
      .get(path)
      .then((res) => {
        if (cancelled) return;
        setOfficers(res || []);
      })
      .catch(() => {
        if (cancelled) return;
        setOfficers([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, reportId]);

  if (!isOpen) return null;

  const submit = async () => {
    if (!officerId) {
      setError('Please select an officer to assign.');
      return;
    }
    if (!reportId) {
      setError('Missing report id.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      await api.post(`/api/v1/reports/${reportId}/assign`, {
        police_user_id: Number(officerId),
        priority,
        note: notes || null,
      });
      onAssigned?.();
      onClose?.();
    } catch (e) {
      setError(e?.message || 'Failed to assign officer.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">Assign Officer</div>
          <div className="modal-close" onClick={onClose}>✕</div>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ marginBottom: '10px' }}>
            <span className="alert-icon">!</span>
            <div>{error}</div>
          </div>
        )}
        
        <div className="input-group">
          <div className="input-label">Select Officer *</div>
          <div style={{ fontSize: '11px', color: 'var(--muted)', marginBottom: '6px' }}>
            Showing officers for this report&apos;s location.
          </div>
          <select
            className="select"
            value={officerId}
            onChange={(e) => setOfficerId(e.target.value)}
          >
            <option value="">— Select officer —</option>
            {officers.map((o) => (
              <option key={o.police_user_id} value={o.police_user_id}>
                {o.first_name} {o.last_name} ({o.email})
              </option>
            ))}
          </select>
          {officers.length === 0 && (
            <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '6px' }}>
              No eligible officers found for this report location.
            </div>
          )}
        </div>
        
        <div className="input-group">
          <div className="input-label">Priority</div>
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
          <div className="input-label">Notes (optional)</div>
          <textarea
            rows="3"
            placeholder="Instructions or context for the assigned officer..."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          ></textarea>
        </div>
        
        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
          <button className="btn btn-outline" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Assigning…' : 'Assign'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default AssignModal;