import React, { useEffect, useState } from 'react';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { parseApiDate } from '../../utils/dateTime';
import SpecialAssignmentUnitSelect from '../SpecialAssignmentUnitSelect';
import { canEditCaseLeadFields } from '../../utils/roleMapping';
import { caseDisplayName, caseDisplayRef } from '../../utils/caseDisplay';

function toDatetimeLocalValue(iso) {
  const d = parseApiDate(iso);
  if (!d) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const EditCaseModal = ({ isOpen, onClose, caseItem, onSaved }) => {
  const { user: me } = useAuth();
  const role = me?.role || 'officer';
  const canEditLead = canEditCaseLeadFields(role);

  const [status, setStatus] = useState(caseItem?.status || 'open');
  const [priority, setPriority] = useState(caseItem?.priority || 'medium');
  const [description, setDescription] = useState(caseItem?.description || '');
  const [outcome, setOutcome] = useState(caseItem?.outcome || '');
  const [assignedToId, setAssignedToId] = useState(caseItem?.assigned_to_id || '');
  const [officers, setOfficers] = useState([]);
  const [specialAssignmentUnit, setSpecialAssignmentUnit] = useState('');
  const [ribHandedOverLocal, setRibHandedOverLocal] = useState('');
  const [ribHandoverSummary, setRibHandoverSummary] = useState('');
  const [ribHandoverPrepAck, setRibHandoverPrepAck] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isOpen || !caseItem) return;
    setStatus(caseItem.status || 'open');
    setPriority(caseItem.priority || 'medium');
    setDescription(caseItem.description || '');
    setOutcome(caseItem.outcome || '');
    setAssignedToId(caseItem.assigned_to_id || '');
    setSpecialAssignmentUnit(caseItem.special_assignment_unit || '');
    setRibHandedOverLocal(toDatetimeLocalValue(caseItem.rib_handed_over_at));
    setRibHandoverSummary(caseItem.rib_handover_summary || '');
    setRibHandoverPrepAck(!!caseItem.rib_handover_prerequisites_acknowledged);
    setError('');
    setSaving(false);
  }, [isOpen, caseItem]);

  // Load officer options scoped strictly to the case's own station.
  useEffect(() => {
    if (!isOpen || !canEditLead || !caseItem) return;
    let cancelled = false;

    const stationId = caseItem.station_id || caseItem.assigned_to_station_id;
    const path = stationId
      ? `/api/v1/police-users/options?station_id=${stationId}`
      : '/api/v1/police-users/options';

    api.get(path)
      .then((res) => {
        if (cancelled) return;
        setOfficers(res || []);
      })
      .catch(() => {
        if (cancelled) return;
        setOfficers([]);
      });

    return () => { cancelled = true; };
  }, [isOpen, canEditLead, caseItem?.station_id, caseItem?.assigned_to_station_id]);

  if (!isOpen || !caseItem) return null;

  const submit = async () => {
    setSaving(true);
    setError('');
    const payload = {
      status,
      description,
      outcome,
      ...(canEditLead
        ? {
            priority,
            assigned_to_id: assignedToId || null,
            special_assignment_unit: specialAssignmentUnit.trim() || null,
            rib_handover_summary: ribHandoverSummary.trim() || null,
            rib_handed_over_at: ribHandedOverLocal
              ? new Date(ribHandedOverLocal).toISOString()
              : null,
            rib_handover_prerequisites_acknowledged: ribHandoverPrepAck,
          }
        : {}),
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
            Update Case — {caseDisplayName(caseItem)}
            {caseDisplayRef(caseItem) ? ` (${caseDisplayRef(caseItem)})` : ''}
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
              disabled={!canEditLead}
            >
              <option value="high">high</option>
              <option value="medium">medium</option>
              <option value="low">low</option>
            </select>
          </div>
          {canEditLead && (
            <div className="input-group">
              <div className="input-label">Assign Officer</div>
              <select
                className="select"
                value={assignedToId}
                onChange={(e) => setAssignedToId(e.target.value)}
              >
                <option value="">Unassigned</option>
                {officers.map((o) => (
                  <option key={o.police_user_id} value={o.police_user_id}>
                    {o.first_name} {o.last_name}
                  </option>
                ))}
              </select>
            </div>
          )}
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

        {canEditLead && (
          <>
            <div className="input-group">
              <div className="input-label">RIB</div>
              <SpecialAssignmentUnitSelect
                value={specialAssignmentUnit}
                onChange={setSpecialAssignmentUnit}
                placeholder="None"
                allowEmpty
                ribOnly
              />
            </div>
            <div className="form-grid" style={{ marginBottom: '12px' }}>
              <div className="input-group">
                <div className="input-label">RIB handover time</div>
                <input
                  className="input"
                  type="datetime-local"
                  value={ribHandedOverLocal}
                  onChange={(e) => setRibHandedOverLocal(e.target.value)}
                />
              </div>
            </div>
            <div className="input-group">
              <div className="input-label">RIB handover summary</div>
              <textarea
                rows="2"
                value={ribHandoverSummary}
                onChange={(e) => setRibHandoverSummary(e.target.value)}
                placeholder="Notes on handover to RIB…"
              />
            </div>
            <label
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 8,
                marginTop: 8,
                fontSize: 13,
                cursor: 'pointer',
              }}
            >
              <input
                type="checkbox"
                checked={ribHandoverPrepAck}
                onChange={(e) => setRibHandoverPrepAck(e.target.checked)}
                style={{ marginTop: 2 }}
              />
              <span style={{ color: 'var(--text-dim)' }}>
                Handover prerequisites met (manual checklist — for record keeping only;
                does not change report verification or community confirmation)
              </span>
            </label>
          </>
        )}

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

