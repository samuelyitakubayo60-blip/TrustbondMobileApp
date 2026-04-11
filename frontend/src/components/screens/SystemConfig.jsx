import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const SystemConfig = ({ wsRefreshKey }) => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [savingKey, setSavingKey] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [effectiveFormula, setEffectiveFormula] = useState(null);

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
    api
      .get('/api/v1/system-config')
      .then((res) => {
        if (cancelled) return;
        const rows = res?.items || [];
        setItems(rows);
        const nextDrafts = {};
        rows.forEach((row) => {
          nextDrafts[row.config_key] = JSON.stringify(row.config_value ?? {}, null, 2);
        });
        setDrafts(nextDrafts);
        loadEffectiveFormula();
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e?.message || 'Failed to load system configuration.');
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [wsRefreshKey]);

  const handleChangeDraft = (key) => (e) => {
    const value = e.target.value;
    setDrafts((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async (row) => {
    const key = row.config_key;
    const raw = drafts[key] ?? '';
    let parsed;
    try {
      parsed = raw.trim() ? JSON.parse(raw) : {};
    } catch {
      setError(`Config "${key}": value must be valid JSON.`);
      return;
    }
    setError('');
    setSavingKey(key);
    try {
      const updated = await api.put(`/api/v1/system-config/${encodeURIComponent(key)}`, {
        config_key: key,
        config_value: parsed,
        description: row.description,
      });
      setItems((prev) =>
        prev.map((r) => (r.config_key === key ? updated : r)),
      );
      setDrafts((prev) => ({
        ...prev,
        [key]: JSON.stringify(updated.config_value ?? {}, null, 2),
      }));
      if (key === 'trust_score.formula') {
        await loadEffectiveFormula();
      }
    } catch (e) {
      setError(e?.message || `Failed to save configuration for "${key}".`);
    } finally {
      setSavingKey(null);
    }
  };

  return (
    <>
      <div className="page-header">
        <h2>System Configuration</h2>
        <p>Admin settings for risk scoring, alert thresholds, and system performance.</p>
      </div>

      <div className="card">
        {error && (
          <div style={{ color: 'var(--danger)', fontSize: '12px', marginBottom: '8px' }}>
            {error}
          </div>
        )}
        {loading && (
          <div style={{ fontSize: '12px', color: 'var(--muted)' }}>Loading configuration…</div>
        )}
        {!loading && !items.length && !error && (
          <div style={{ fontSize: '12px', color: 'var(--muted)' }}>No configuration rows found.</div>
        )}

        {!loading && !!items.length && (
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>Key</th>
                  <th>Description</th>
                  <th>Value (JSON)</th>
                  <th style={{ width: 120 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.config_key}>
                    <td style={{ fontWeight: 600, fontSize: '11px' }}>{row.config_key}</td>
                    <td style={{ fontSize: '11px', color: 'var(--muted)' }}>
                      {row.description || '—'}
                    </td>
                    <td>
                      <textarea
                        rows={4}
                        style={{
                          width: '100%',
                          fontSize: '11px',
                          fontFamily: 'monospace',
                          background: 'var(--surface2)',
                          borderRadius: '4px',
                        }}
                        value={drafts[row.config_key] ?? ''}
                        onChange={handleChangeDraft(row.config_key)}
                      />
                    </td>
                    <td>
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={() => handleSave(row)}
                        disabled={savingKey === row.config_key}
                      >
                        {savingKey === row.config_key ? 'Saving…' : 'Save'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="card-header">
          <div className="card-title">Effective Trust Formula (Runtime)</div>
        </div>
        {!effectiveFormula ? (
          <div style={{ fontSize: '12px', color: 'var(--muted)', padding: '10px 0' }}>
            Formula not available.
          </div>
        ) : (
          <div className="form-grid">
            <div className="input-group">
              <div className="input-label">Raw DB Value</div>
              <pre
                style={{
                  margin: 0,
                  fontSize: 11,
                  background: 'var(--surface2)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  padding: 10,
                  overflowX: 'auto',
                }}
              >
                {JSON.stringify(effectiveFormula.raw || {}, null, 2)}
              </pre>
            </div>
            <div className="input-group">
              <div className="input-label">Validated + Normalized (Used by Backend)</div>
              <pre
                style={{
                  margin: 0,
                  fontSize: 11,
                  background: 'var(--surface2)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  padding: 10,
                  overflowX: 'auto',
                }}
              >
                {JSON.stringify(effectiveFormula.normalized || {}, null, 2)}
              </pre>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6 }}>
                Sum of normalized weights: {effectiveFormula.sum_normalized}
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
};

export default SystemConfig;

