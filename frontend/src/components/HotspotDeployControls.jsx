import React, { useState } from 'react';
import api from '../api/client';
import { showToast } from '../utils/toast';

/**
 * Take control + deploy a special assignment unit to one hotspot.
 * Visible to IO/DPC (canDeploy); others see a short permission note.
 */
const HotspotDeployControls = ({
  hotspot,
  assignmentUnits = [],
  canDeploy = false,
  onDeployed,
  compact = false,
}) => {
  const [deploying, setDeploying] = useState(false);
  const [takingControl, setTakingControl] = useState(false);
  const [unitCode, setUnitCode] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState('');

  if (!hotspot?.hotspot_id) return null;

  const activeUnits = (assignmentUnits || []).filter((u) => u.is_active !== false);
  const hotspotId = hotspot.hotspot_id;

  const handleTakeControl = async () => {
    setTakingControl(true);
    setError('');
    try {
      await api.post(`/api/v1/hotspots/${hotspotId}/take-control`);
      showToast(`You now control hotspot #${hotspotId}.`, 'success');
      onDeployed?.();
    } catch (e) {
      setError(e?.message || 'Failed to take control');
    } finally {
      setTakingControl(false);
    }
  };

  const handleDeploy = async () => {
    if (!unitCode) {
      setError('Select a unit to deploy.');
      return;
    }
    setDeploying(true);
    setError('');
    try {
      const res = await api.post(`/api/v1/hotspots/${hotspotId}/deploy`, {
        unit_code: unitCode,
        note: note.trim() || null,
      });
      showToast(res?.message || 'Unit deployed.', 'success');
      setUnitCode('');
      setNote('');
      onDeployed?.(res);
    } catch (e) {
      setError(e?.message || 'Deployment failed');
    } finally {
      setDeploying(false);
    }
  };

  const statusBlock = (hotspot.assigned_unit_code || hotspot.controlled_by_name || hotspot.deployed_at) && (
    <div
      style={{
        fontSize: compact ? 10 : 11,
        color: 'var(--text)',
        padding: compact ? '5px 10px' : '8px 12px',
        borderRadius: 6,
        backgroundColor: 'var(--background)',
        border: '1px solid var(--border)',
        display: 'flex',
        gap: 10,
        flexWrap: 'wrap',
        marginBottom: canDeploy ? 10 : 0,
      }}
    >
      {hotspot.controlled_by_name && (
        <span>Control: <strong>{hotspot.controlled_by_name}</strong></span>
      )}
      {hotspot.assigned_unit_name && (
        <span>Deployed: <strong>{hotspot.assigned_unit_name}</strong></span>
      )}
      {!hotspot.assigned_unit_name && hotspot.assigned_unit_code && (
        <span>Deployed: <strong>{hotspot.assigned_unit_code}</strong></span>
      )}
      {hotspot.deployed_at && (
        <span style={{ color: 'var(--muted)' }}>
          {new Date(hotspot.deployed_at).toLocaleString()}
        </span>
      )}
    </div>
  );

  if (!canDeploy) {
    return (
      <div>
        {statusBlock}
        <p style={{ margin: statusBlock ? '10px 0 0' : 0, fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }}>
          Unit deployment is available to <strong>IO</strong> and <strong>DPC</strong> accounts.
          {hotspot.assigned_unit_code ? ' A unit is already assigned to this hotspot.' : ''}
        </p>
      </div>
    );
  }

  return (
    <div>
      {error && (
        <div className="alert alert-danger" style={{ marginBottom: 10 }}>
          <span className="alert-icon">!</span>
          <div>{error}</div>
        </div>
      )}

      {statusBlock}

      {activeUnits.length === 0 ? (
        <p style={{ margin: '0 0 10px', fontSize: 12, color: 'var(--warning, #d97706)' }}>
          No special assignment units are configured. Add units under{' '}
          <strong>Special Assignment Units</strong> (admin) before deploying.
        </p>
      ) : null}

      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          padding: compact ? '8px 10px' : '12px 14px',
          borderRadius: 6,
          border: '1px dashed var(--border)',
          backgroundColor: 'var(--background)',
        }}
      >
        <div style={{ fontSize: compact ? 10 : 11, fontWeight: 700, color: 'var(--muted)', letterSpacing: '0.06em' }}>
          DEPLOY UNIT
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn btn-outline btn-sm"
            disabled={takingControl}
            onClick={handleTakeControl}
          >
            {takingControl ? '…' : 'Take control'}
          </button>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <select
            className="select"
            style={{ flex: 1, minWidth: 140, fontSize: 11 }}
            value={unitCode}
            onChange={(e) => setUnitCode(e.target.value)}
            disabled={deploying || activeUnits.length === 0}
          >
            <option value="">Select unit to deploy…</option>
            {activeUnits.map((u) => (
              <option key={u.unit_code} value={u.unit_code}>
                {u.unit_name} ({u.unit_code})
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={deploying || activeUnits.length === 0}
            onClick={handleDeploy}
          >
            {deploying ? 'Deploying…' : hotspot.assigned_unit_code ? 'Reassign unit' : 'Deploy unit'}
          </button>
        </div>
        <input
          className="input"
          style={{ fontSize: 11 }}
          placeholder="Optional deployment note for commander"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          disabled={deploying}
        />
        <p style={{ margin: 0, fontSize: 10, color: 'var(--muted)', lineHeight: 1.45 }}>
          Commander and station users are notified in-app; commander email is sent when configured.
        </p>
      </div>
    </div>
  );
};

export default HotspotDeployControls;
