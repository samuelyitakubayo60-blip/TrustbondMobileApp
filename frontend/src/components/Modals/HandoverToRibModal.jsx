import React, { useEffect, useState } from 'react';
import api from '../../api/client';
import { caseDisplayName, caseDisplayRef } from '../../utils/caseDisplay';

/**
 * One-click RIB handover: closes case and removes it from active Security Situation lists.
 */
const HandoverToRibModal = ({ isOpen, onClose, caseItem, onSuccess }) => {
  const [summary, setSummary] = useState('');
  const [prepAck, setPrepAck] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    setSummary('');
    setPrepAck(false);
    setError('');
    setSaving(false);
  }, [isOpen, caseItem?.case_id]);

  if (!isOpen || !caseItem) return null;

  const alreadyClosed =
    caseItem.status === 'closed' &&
    (caseItem.rib_handed_over_at || caseItem.outcome === 'handed_to_rib');

  const submit = async () => {
    const text = summary.trim();
    if (!text) {
      setError('Enter a handover summary for RIB.');
      return;
    }
    if (!prepAck) {
      setError('Confirm that handover prerequisites are met.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const updated = await api.post(`/api/v1/cases/${caseItem.case_id}/handover-to-rib`, {
        rib_handover_summary: text,
        rib_handover_prerequisites_acknowledged: true,
      });
      onSuccess?.(updated);
      onClose?.();
    } catch (e) {
      setError(e?.message || 'RIB handover failed.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="modal-overlay open"
      style={{ zIndex: 60 }}
      onClick={(e) => e.target === e.currentTarget && !saving && onClose()}
    >
      <div className="modal" style={{ maxWidth: 520 }}>
        <div className="modal-header">
          <div className="modal-title">Hand over to RIB</div>
          <div className="modal-close" onClick={() => !saving && onClose()}>✕</div>
        </div>

        <p style={{ margin: '0 0 14px', fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.5 }}>
          Case <strong>{caseDisplayName(caseItem)}</strong>
          {caseDisplayRef(caseItem) ? ` (${caseDisplayRef(caseItem)})` : ''} will be marked{' '}
          <strong>closed</strong> and removed from active Security Situation lists. RIB receives
          the handover record; police ops treat this case as complete.
        </p>

        {alreadyClosed && (
          <div className="alert alert-danger" style={{ marginBottom: 12 }}>
            <span className="alert-icon">!</span>
            <div>This case was already handed to RIB.</div>
          </div>
        )}

        {error && (
          <div className="alert alert-danger" style={{ marginBottom: 12 }}>
            <span className="alert-icon">!</span>
            <div>{error}</div>
          </div>
        )}

        <div className="input-group">
          <div className="input-label">Handover summary (required)</div>
          <textarea
            rows={4}
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="What was handed over, evidence package, suspects, next steps for RIB…"
            disabled={saving || alreadyClosed}
          />
        </div>

        <label
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 8,
            marginTop: 12,
            fontSize: 13,
            cursor: alreadyClosed ? 'default' : 'pointer',
          }}
        >
          <input
            type="checkbox"
            checked={prepAck}
            onChange={(e) => setPrepAck(e.target.checked)}
            disabled={saving || alreadyClosed}
            style={{ marginTop: 2 }}
          />
          <span style={{ color: 'var(--text-dim)' }}>
            Handover prerequisites met (dossier complete, chain of custody documented, IO
            checklist signed off).
          </span>
        </label>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 18 }}>
          <button type="button" className="btn btn-outline" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={submit}
            disabled={saving || alreadyClosed}
          >
            {saving ? 'Handing over…' : 'Confirm handover to RIB'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default HandoverToRibModal;
