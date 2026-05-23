import React, { useEffect, useState } from 'react';
import api from '../../api/client';

// Group config keys by prefix for visual sections
const GROUP_META = {
  dbscan:      { label: 'DBSCAN Clustering',     sub: 'Spatial clustering parameters for incident hotspot detection' },
  ml:          { label: 'ML / Model Settings',   sub: 'Machine-learning thresholds for auto-verification and confidence scoring' },
  spam:        { label: 'Spam Detection',         sub: 'Heuristic rules that flag low-quality or duplicate reports' },
  trust_score: { label: 'Trust Score Formula',   sub: 'Weighted formula used to compute per-device trust scores at runtime' },
};

const getGroup = (key) => {
  const prefix = key.split('.')[0];
  return GROUP_META[prefix] || { label: 'Other', sub: '' };
};

const groupItems = (items) => {
  const groups = {};
  items.forEach((row) => {
    const prefix = row.config_key.split('.')[0];
    if (!groups[prefix]) groups[prefix] = [];
    groups[prefix].push(row);
  });
  return groups;
};

const SystemConfig = ({ wsRefreshKey }) => {
  const [items, setItems]                   = useState([]);
  const [loading, setLoading]               = useState(true);
  const [error, setError]                   = useState('');
  const [savingKey, setSavingKey]           = useState(null);
  const [drafts, setDrafts]                 = useState({});
  const [savedKeys, setSavedKeys]           = useState({}); // original saved values for dirty check
  const [effectiveFormula, setEffectiveFormula] = useState(null);
  const [saveSuccess, setSaveSuccess]       = useState('');

  const loadEffectiveFormula = async () => {
    try {
      const res = await api.get('/api/v1/system-config/effective/trust-score-formula');
      setEffectiveFormula(res || null);
    } catch {
      setEffectiveFormula(null);
    }
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get('/api/v1/system-config/')
      .then((res) => {
        if (cancelled) return;
        const rows = res?.items || [];
        setItems(rows);
        const nextDrafts = {};
        const nextSaved  = {};
        rows.forEach((row) => {
          const val = JSON.stringify(row.config_value ?? {}, null, 2);
          nextDrafts[row.config_key] = val;
          nextSaved[row.config_key]  = val;
        });
        setDrafts(nextDrafts);
        setSavedKeys(nextSaved);
        loadEffectiveFormula();
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e?.message || 'Failed to load system configuration.');
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [wsRefreshKey]);

  const handleChangeDraft = (key) => (e) => {
    setDrafts((prev) => ({ ...prev, [key]: e.target.value }));
  };

  const handleSave = async (row) => {
    const key = row.config_key;
    const raw = drafts[key] ?? '';
    let parsed;
    try {
      parsed = raw.trim() ? JSON.parse(raw) : {};
    } catch {
      setError(`"${key}": value must be valid JSON.`);
      return;
    }
    setError('');
    setSaveSuccess('');
    setSavingKey(key);
    try {
      const updated = await api.put(`/api/v1/system-config/${encodeURIComponent(key)}`, {
        config_key:   key,
        config_value: parsed,
        description:  row.description,
      });
      setItems((prev) => prev.map((r) => (r.config_key === key ? updated : r)));
      const newVal = JSON.stringify(updated.config_value ?? {}, null, 2);
      setDrafts((prev)    => ({ ...prev, [key]: newVal }));
      setSavedKeys((prev) => ({ ...prev, [key]: newVal }));
      setSaveSuccess(`"${key}" saved.`);
      if (key === 'trust_score.formula') await loadEffectiveFormula();
    } catch (e) {
      setError(e?.message || `Failed to save "${key}".`);
    } finally {
      setSavingKey(null);
    }
  };

  const handleReset = (key) => {
    setDrafts((prev) => ({ ...prev, [key]: savedKeys[key] ?? '' }));
  };

  const isDirty = (key) => drafts[key] !== savedKeys[key];

  const groups = groupItems(items);

  return (
    <>
      <div className="page-header">
        <h2>System Configuration</h2>
        <p>Admin settings for risk scoring, alert thresholds, and system performance.</p>
      </div>

      {error && (
        <div className="alert alert-danger" style={{ marginBottom: 12 }}>
          <span className="alert-icon">!</span>
          <div>{error}</div>
        </div>
      )}
      {saveSuccess && !error && (
        <div className="alert alert-success" style={{ marginBottom: 12 }}>
          <span className="alert-icon">✓</span>
          <div>{saveSuccess}</div>
        </div>
      )}

      {loading && (
        <div className="card" style={{ padding: 40, textAlign: 'center', color: 'var(--muted)' }}>
          Loading configuration…
        </div>
      )}

      {!loading && !items.length && !error && (
        <div className="card" style={{ padding: 40, textAlign: 'center', color: 'var(--muted)' }}>
          No configuration entries found.
        </div>
      )}

      {!loading && Object.entries(groups).map(([prefix, rows]) => {
        const meta = GROUP_META[prefix] || { label: prefix, sub: '' };
        return (
          <div key={prefix} className="card" style={{ marginBottom: 16 }}>
            <div className="card-header" style={{ borderLeft: '4px solid var(--accent)', paddingLeft: 12 }}>
              <div>
                <div className="card-title" style={{ fontSize: 14 }}>{meta.label}</div>
                {meta.sub && (
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{meta.sub}</div>
                )}
              </div>
              <span className="badge b-blue" style={{ fontSize: 10 }}>
                {rows.length} key{rows.length !== 1 ? 's' : ''}
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
              {rows.map((row, i) => {
                const key   = row.config_key;
                const dirty = isDirty(key);
                const saving = savingKey === key;

                return (
                  <div
                    key={key}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '220px 1fr auto',
                      gap: 16,
                      alignItems: 'flex-start',
                      padding: '14px 20px',
                      borderTop: i > 0 ? '1px solid var(--border)' : 'none',
                      background: dirty ? 'color-mix(in srgb, var(--warning) 5%, transparent)' : 'transparent',
                      transition: 'background 0.2s',
                    }}
                  >
                    {/* Key + description */}
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                        <code style={{
                          fontSize: 11,
                          fontWeight: 700,
                          background: 'var(--surface2)',
                          border: '1px solid var(--border)',
                          borderRadius: 4,
                          padding: '2px 6px',
                          color: 'var(--text)',
                        }}>
                          {key}
                        </code>
                        {dirty && (
                          <span className="badge b-orange" style={{ fontSize: 9 }}>unsaved</span>
                        )}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.4 }}>
                        {row.description || '—'}
                      </div>
                    </div>

                    {/* JSON editor */}
                    <textarea
                      rows={Math.max(3, (drafts[key] ?? '').split('\n').length)}
                      style={{
                        width: '100%',
                        fontSize: 11,
                        fontFamily: 'monospace',
                        background: 'var(--surface2)',
                        border: `1px solid ${dirty ? 'var(--warning)' : 'var(--border)'}`,
                        borderRadius: 6,
                        padding: '8px 10px',
                        resize: 'vertical',
                        color: 'var(--text)',
                        transition: 'border-color 0.2s',
                      }}
                      value={drafts[key] ?? ''}
                      onChange={handleChangeDraft(key)}
                    />

                    {/* Actions */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, paddingTop: 2 }}>
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={() => handleSave(row)}
                        disabled={saving || !dirty}
                        style={{ whiteSpace: 'nowrap' }}
                      >
                        {saving ? 'Saving…' : 'Save'}
                      </button>
                      {dirty && (
                        <button
                          className="btn btn-outline btn-sm"
                          onClick={() => handleReset(key)}
                          disabled={saving}
                          style={{ whiteSpace: 'nowrap' }}
                        >
                          Reset
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}

      {/* Effective Trust Formula panel */}
      {effectiveFormula && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-header" style={{ borderLeft: '4px solid var(--accent)', paddingLeft: 12 }}>
            <div>
              <div className="card-title" style={{ fontSize: 14 }}>Effective Trust Formula (Runtime)</div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                Live read-only view of the formula being applied by the backend
              </div>
            </div>
            {effectiveFormula.sum_normalized != null && (
              <span
                className={`badge ${Math.abs(effectiveFormula.sum_normalized - 1) < 0.001 ? 'b-green' : 'b-orange'}`}
                style={{ fontSize: 10 }}
              >
                Σ = {Number(effectiveFormula.sum_normalized).toFixed(4)}
              </span>
            )}
          </div>

          <div className="form-grid" style={{ padding: '14px 20px', gap: 16 }}>
            <div className="input-group">
              <div className="input-label">Raw DB Value</div>
              <pre style={{
                margin: 0, fontSize: 11, fontFamily: 'monospace',
                background: 'var(--surface2)', border: '1px solid var(--border)',
                borderRadius: 6, padding: 10, overflowX: 'auto',
                color: 'var(--text)',
              }}>
                {JSON.stringify(effectiveFormula.raw || {}, null, 2)}
              </pre>
            </div>
            <div className="input-group">
              <div className="input-label">Validated + Normalized (Used by Backend)</div>
              <pre style={{
                margin: 0, fontSize: 11, fontFamily: 'monospace',
                background: 'var(--surface2)', border: '1px solid var(--border)',
                borderRadius: 6, padding: 10, overflowX: 'auto',
                color: 'var(--text)',
              }}>
                {JSON.stringify(effectiveFormula.normalized || {}, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default SystemConfig;
