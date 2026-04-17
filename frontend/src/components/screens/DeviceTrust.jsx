import React, { useEffect, useState } from 'react';
import api from '../../api/client';

// Helper functions for location analysis
const calculateDistance = (lat1, lon1, lat2, lon2) => {
  const R = 6371; // Earth's radius in km
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLon/2) * Math.sin(dLon/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return R * c;
};

const analyzeLocationConsistency = (metadata) => {
  if (!metadata || !metadata.location_history || metadata.location_history.length < 2) {
    return {
      consistency_score: null, // No location data available
      movement_radius_km: 0,
      location_count: metadata?.last_latitude ? 1 : 0,
      suspicious_jumps: 0,
      avg_gps_accuracy: metadata?.last_gps_accuracy_m || null
    };
  }

  const history = metadata.location_history;
  let totalDistance = 0;
  let maxDistance = 0;
  let suspiciousJumps = 0;
  let accuracies = [];

  for (let i = 1; i < history.length; i++) {
    const prev = history[i-1];
    const curr = history[i];
    const distance = calculateDistance(
      prev.latitude, prev.longitude,
      curr.latitude, curr.longitude
    );
    
    totalDistance += distance;
    maxDistance = Math.max(maxDistance, distance);
    
    // Flag jumps > 50km as suspicious
    if (distance > 50) suspiciousJumps++;
    
    if (curr.gps_accuracy) accuracies.push(curr.gps_accuracy);
  }

  const avgDistance = totalDistance / (history.length - 1);
  const consistency_score = Math.max(0, 100 - (avgDistance * 2) - (suspiciousJumps * 20));
  
  return {
    consistency_score: Math.round(consistency_score),
    movement_radius_km: Math.round(maxDistance * 100) / 100,
    location_count: history.length,
    suspicious_jumps: suspiciousJumps,
    avg_gps_accuracy: accuracies.length > 0 
      ? Math.round(accuracies.reduce((a, b) => a + b, 0) / accuracies.length)
      : metadata?.last_gps_accuracy_m || null
  };
};

const formatLocation = (lat, lng) => {
  const nLat = Number(lat);
  const nLng = Number(lng);
  if (!Number.isFinite(nLat) || !Number.isFinite(nLng)) return 'Unknown';
  return `${nLat.toFixed(4)}, ${nLng.toFixed(4)}`;
};

const formatTimestamp = (timestamp) => {
  if (!timestamp) return 'Unknown';
  try {
    return new Date(timestamp).toLocaleString();
  } catch {
    return 'Invalid';
  }
};

const formatShortDate = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString();
};

const normalizePercentValue = (value) => {
  if (value == null) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  // Some APIs provide 0..1 ratios, others 0..100 percentages.
  return n <= 1 ? n * 100 : n;
};

const resolveLastLocation = (device) => {
  const coords = device?.last_location || null;
  const hierarchy =
    device?.last_location_hierarchy ||
    [device?.sector_name, device?.cell_name, device?.village_name]
      .filter(Boolean)
      .join(' > ') ||
    null;
  if (coords) return { coords, hierarchy };
  const lat =
    device?.metadata_json?.last_latitude ??
    device?.metadata_json?.latitude ??
    device?.metadata?.last_latitude ??
    device?.metadata?.latitude ??
    device?.last_latitude ??
    device?.latitude;
  const lng =
    device?.metadata_json?.last_longitude ??
    device?.metadata_json?.longitude ??
    device?.metadata?.last_longitude ??
    device?.metadata?.longitude ??
    device?.last_longitude ??
    device?.longitude;
  const fallbackCoords = formatLocation(lat, lng);
  return {
    coords: fallbackCoords !== 'Unknown' ? fallbackCoords : null,
    hierarchy,
  };
};

const DeviceTrust = ({ wsRefreshKey }) => {
  const [devices, setDevices] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [trustLevel, setTrustLevel] = useState('all'); // all | high | medium | low
  const [search, setSearch] = useState('');
  const [sortField, setSortField] = useState('device_trust_score');
  const [sortDir, setSortDir] = useState('desc'); // asc | desc
  const [selectedProfile, setSelectedProfile] = useState(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileDialogOpen, setProfileDialogOpen] = useState(false);
  const [sectorFilter, setSectorFilter] = useState('all');
  const [sectors, setSectors] = useState([]);
  const [banDialog, setBanDialog] = useState({
    open: false,
    deviceId: null,
    preset: 'policy_violation',
    details: '',
  });

  // Load devices from backend, filtered by trust level
  useEffect(() => {
    let mounted = true;
    const params = new URLSearchParams({ limit: '50', offset: '0' });
    params.set('include_banned', 'true');
    if (trustLevel !== 'all') {
      params.set('trust_level', trustLevel);
    }
    api
      .get(`/api/v1/devices?${params.toString()}`)
      .then((res) => {
        if (!mounted) return;
        setDevices(res.items || []);
        setStats(res.stats || null);
        setLoading(false);
      })
      .catch(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [trustLevel, wsRefreshKey]);

  // Load sectors for dropdown (locations with type=sector)
  useEffect(() => {
    api
      .get('/api/v1/locations')
      .then((res) => {
        const sectorList = (res || []).filter(
          (loc) => loc.location_type === 'sector',
        );
        setSectors(sectorList);
      })
      .catch(() => setSectors([]));
  }, []);

  const active = stats?.active_30d ?? 0;
  const high = stats?.high_trust ?? 0;
  const medium = stats?.medium_trust ?? 0;
  const low = stats?.low_trust ?? 0;
  const banned = stats?.banned ?? 0;

  const openProfile = async (deviceId) => {
    const dev = devices.find((d) => d.device_id === deviceId);
    if (!dev) return;
    setProfileDialogOpen(true);
    try {
      setProfileLoading(true);
      setSelectedProfile(null);
      const mlStats = await api.get(
        `/api/v1/devices/${deviceId}/ml-stats`,
      );
      const trustedReports =
        dev.trusted_reports ?? dev.confirmed_reports ?? dev.verified_reports ?? 0;
      const flaggedReports = dev.flagged_reports ?? dev.rejected_reports ?? 0;
      const distribution = mlStats?.prediction_distribution || {};
      const likelyReal = Number(distribution.likely_real || 0);
      const suspicious = Number(distribution.suspicious || 0);
      const uncertain = Number(distribution.uncertain || 0);
      const fake = Number(distribution.fake || 0);
      setSelectedProfile({
        ...mlStats,
        device_hash: dev.device_hash,
        device_trust_score: dev.device_trust_score,
        total_reports: dev.total_reports ?? mlStats?.total_reports ?? 0,
        trusted_reports: trustedReports,
        verified_reports: trustedReports, // backward compatibility with existing UI fragments
        flagged_reports: flaggedReports,
        spam_flags: dev.spam_flags ?? mlStats?.behavior?.spam_signal ?? 0,
        ml_avg_trust: dev.ml_avg_trust ?? mlStats?.ml?.avg_trust_score ?? null,
        ml_fake_rate: dev.ml_fake_rate ?? mlStats?.ml?.fake_rate ?? null,
        ml_last_confidence:
          dev.ml_last_confidence ?? mlStats?.ml?.last_confidence ?? null,
        ml_last_prediction_at:
          dev.ml_last_prediction_at ?? mlStats?.last_prediction_at ?? null,
        last_active_at: dev.last_active_at ?? null,
        last_location: dev.last_location ?? null,
        last_location_hierarchy: dev.last_location_hierarchy ?? null,
        prediction_distribution: distribution,
        credible_reports: likelyReal,
        suspicious_reports: suspicious + uncertain,
        fake_reports: fake,
        model_versions: mlStats?.ml?.model_versions || [],
      });
    } catch {
      setSelectedProfile(null);
    } finally {
      setProfileLoading(false);
    }
  };

  const exportCsv = () => {
    if (!devices.length) return;
    const headers = [
      'device_hash',
      'trust_score',
      'total_reports',
      'confirmed',
      'rejected',
      'spam_flags',
      'last_active_at',
      'status',
      'is_banned',
    ];
    const rows = devices.map((d) => {
      const score = d.device_trust_score ?? 0;
      const status = d.is_banned
        ? 'Banned'
        : score < 10
          ? 'Banned'
          : score < 40
            ? 'Flagged'
            : 'Active';
      return [
        d.device_hash,
        Math.round(score),
        d.total_reports ?? 0,
        d.trusted_reports ?? 0,
        d.flagged_reports ?? 0,
        d.spam_flags ?? 0,
        d.last_active_at || '',
        status,
        d.is_banned ? 'true' : 'false',
      ];
    });
    const csv = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'device_trust.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  const updateDeviceRow = (deviceId, patch) => {
    setDevices((prev) =>
      prev.map((d) => (d.device_id === deviceId ? { ...d, ...patch } : d)),
    );
  };

  const banDevice = async (deviceId) => {
    const reason = [
      banDialog.preset,
      (banDialog.details || '').trim(),
    ]
      .filter(Boolean)
      .join(': ')
      .slice(0, 255);
    updateDeviceRow(deviceId, { _banBusy: true });
    try {
      const res = await api.patch(`/api/v1/devices/${deviceId}/ban`, {
        reason: reason || undefined,
      });
      updateDeviceRow(deviceId, {
        is_banned: true,
        is_blacklisted: res?.is_blacklisted ?? true,
        blacklist_reason: res?.blacklist_reason ?? (reason || null),
        _banBusy: false,
      });
    } catch {
      updateDeviceRow(deviceId, { _banBusy: false });
    }
  };

  const unbanDevice = async (deviceId) => {
    updateDeviceRow(deviceId, { _banBusy: true });
    try {
      const res = await api.patch(`/api/v1/devices/${deviceId}/unban`);
      updateDeviceRow(deviceId, {
        is_banned: false,
        is_blacklisted: res?.is_blacklisted ?? false,
        blacklist_reason: res?.blacklist_reason ?? null,
        _banBusy: false,
      });
    } catch {
      updateDeviceRow(deviceId, { _banBusy: false });
    }
  };

  return (
    <>
      {banDialog.open && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,.55)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 14,
            zIndex: 50,
          }}
          onClick={() => setBanDialog((s) => ({ ...s, open: false }))}
        >
          <div
            className="card"
            style={{ width: 'min(560px, 96vw)' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="card-header" style={{ marginBottom: 10 }}>
              <div className="card-title">Ban device</div>
              <div
                className="card-action"
                onClick={() => setBanDialog((s) => ({ ...s, open: false }))}
              >
                Close
              </div>
            </div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
              Choose a reason so the team can understand why this device was banned.
            </div>
            <div style={{ display: 'grid', gap: 10 }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 6 }}>
                  Reason preset
                </div>
                <select
                  className="select"
                  value={banDialog.preset}
                  onChange={(e) =>
                    setBanDialog((s) => ({ ...s, preset: e.target.value }))
                  }
                >
                  <option value="policy_violation">Policy violation</option>
                  <option value="ml_high_fake_rate">ML: high fake rate</option>
                  <option value="ml_low_trust_average">ML: low trust average</option>
                  <option value="high_spam_signal">High spam signal</option>
                  <option value="manual_review">Manual review decision</option>
                </select>
              </div>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 6 }}>
                  Details (optional)
                </div>
                <input
                  className="input"
                  placeholder="Short note… (e.g., repeated fake submissions)"
                  value={banDialog.details}
                  onChange={(e) =>
                    setBanDialog((s) => ({ ...s, details: e.target.value }))
                  }
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                <button
                  className="btn btn-outline btn-sm"
                  type="button"
                  onClick={() => setBanDialog((s) => ({ ...s, open: false }))}
                >
                  Cancel
                </button>
                <button
                  className="btn btn-sm"
                  type="button"
                  onClick={async () => {
                    const id = banDialog.deviceId;
                    setBanDialog((s) => ({ ...s, open: false }));
                    if (id) await banDevice(id);
                  }}
                  style={{ background: 'var(--danger)', borderColor: 'transparent' }}
                >
                  Ban
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      {profileDialogOpen && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,.6)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 14,
            zIndex: 60,
          }}
          onClick={() => setProfileDialogOpen(false)}
        >
          <div
            className="card"
            style={{
              width: 'min(980px, 96vw)',
              maxHeight: '88vh',
              overflowY: 'auto',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="card-header" style={{ marginBottom: 10 }}>
              <div className="card-title">Selected Device Profile</div>
              <div
                className="card-action"
                onClick={() => setProfileDialogOpen(false)}
              >
                Close
              </div>
            </div>

            {!selectedProfile && !profileLoading && (
              <div
                style={{
                  fontSize: '13px',
                  color: 'var(--muted)',
                  padding: '8px 14px 14px',
                }}
              >
                Click a <strong>Profile</strong> button in the registry to see
                ML trust details for that device.
              </div>
            )}

            {profileLoading && (
              <div
                style={{
                  fontSize: '13px',
                  color: 'var(--muted)',
                  padding: '8px 14px 14px',
                }}
              >
                Loading profile...
              </div>
            )}

            {selectedProfile && !profileLoading && (
              <div style={{ padding: '6px 14px 16px', fontSize: '13px' }}>
                <div
                  style={{
                    marginBottom: '8px',
                    fontFamily: '"Syne", sans-serif',
                    fontWeight: 700,
                    fontSize: '15px',
                  }}
                >
                  Hash:{' '}
                  <span
                    style={{
                      fontFamily: 'monospace',
                      whiteSpace: 'normal',
                      overflowWrap: 'anywhere',
                      wordBreak: 'break-word',
                      fontSize: '14px',
                    }}
                  >
                    {selectedProfile.device_hash}
                  </span>
                </div>

                <div style={{ marginBottom: '8px', fontSize: '14px' }}>
                  Trust score:{' '}
                  <strong>
                    {Math.round(selectedProfile.device_trust_score ?? 0)}
                  </strong>{' '}
                  / 100
                </div>

                <div style={{ marginBottom: '10px', fontSize: '14px' }}>
                  Reports:{' '}
                  <strong>{selectedProfile.total_reports}</strong> total ·{' '}
                  <span style={{ color: 'var(--success)' }}>
                    {selectedProfile.trusted_reports} trusted
                  </span>{' '}
                  ·{' '}
                  <span style={{ color: 'var(--danger)' }}>
                    {selectedProfile.flagged_reports} flagged
                  </span>
                </div>

                <div style={{ marginBottom: '10px', fontSize: '12px', color: 'var(--muted)' }}>
                  ML Avg: <strong style={{ color: 'var(--text)' }}>
                    {selectedProfile.ml_avg_trust != null
                      ? Math.round(selectedProfile.ml_avg_trust)
                      : '—'}
                  </strong>
                  {' · '}
                  Fake %: <strong style={{ color: 'var(--text)' }}>
                    {normalizePercentValue(selectedProfile.ml_fake_rate) != null
                      ? `${Math.round(normalizePercentValue(selectedProfile.ml_fake_rate))}%`
                      : '—'}
                  </strong>
                  {' · '}
                  Conf: <strong style={{ color: 'var(--text)' }}>
                    {normalizePercentValue(selectedProfile.ml_last_confidence) != null
                      ? `${Math.round(normalizePercentValue(selectedProfile.ml_last_confidence))}%`
                      : '—'}
                  </strong>
                  {' · '}
                  Last ML: <strong style={{ color: 'var(--text)' }}>
                    {formatShortDate(selectedProfile.ml_last_prediction_at)}
                  </strong>
                </div>

                <div style={{ marginBottom: '10px', fontSize: '12px', color: 'var(--muted)' }}>
                  Last active: <strong style={{ color: 'var(--text)' }}>
                    {formatShortDate(selectedProfile.last_active_at)}
                  </strong>
                  {' · '}
                  Last location: <strong style={{ color: 'var(--text)' }}>
                    {selectedProfile.last_location || '—'}
                  </strong>
                  {selectedProfile.last_location_hierarchy && (
                    <>
                      {' · '}
                      <span style={{ color: 'var(--text)' }}>
                        {selectedProfile.last_location_hierarchy}
                      </span>
                    </>
                  )}
                </div>

                {(selectedProfile.ml || selectedProfile.behavior) && (
                  <div
                    style={{
                      marginTop: '10px',
                      paddingTop: '10px',
                      borderTop: '1px solid var(--border2)',
                    }}
                  >
                    <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: 6 }}>
                      ML reasons (aggregated)
                    </div>
                    {selectedProfile.ml && (
                      <div style={{ fontSize: '13px', color: 'var(--muted)' }}>
                        Avg trust:{' '}
                        <strong style={{ color: 'var(--text)' }}>
                          {selectedProfile.ml.avg_trust_score != null
                            ? Math.round(selectedProfile.ml.avg_trust_score)
                            : '—'}
                        </strong>
                        {' · '}
                        Fake rate:{' '}
                        <strong style={{ color: 'var(--text)' }}>
                          {selectedProfile.ml.fake_rate != null
                            ? `${Math.round(selectedProfile.ml.fake_rate * 100)}%`
                            : '—'}
                        </strong>
                        {Array.isArray(selectedProfile.ml.model_versions) &&
                          selectedProfile.ml.model_versions.length > 0 && (
                            <>
                              {' · '}
                              Models:{' '}
                              <span style={{ color: 'var(--text)' }}>
                                {selectedProfile.ml.model_versions.join(', ')}
                              </span>
                            </>
                          )}
                      </div>
                    )}
                    {selectedProfile.behavior && (
                      <div style={{ fontSize: '13px', color: 'var(--muted)', marginTop: 5 }}>
                        Confirmation rate:{' '}
                        <strong style={{ color: 'var(--text)' }}>
                          {selectedProfile.behavior.confirmation_rate != null
                            ? `${Math.round(selectedProfile.behavior.confirmation_rate * 100)}%`
                            : '—'}
                        </strong>
                        {' · '}
                        Spam signal:{' '}
                        <strong style={{ color: 'var(--text)' }}>
                          {selectedProfile.behavior.spam_signal != null
                            ? selectedProfile.behavior.spam_signal
                            : '—'}
                        </strong>
                      </div>
                    )}
                  </div>
                )}

                {selectedProfile.last_ml_update && (
                  <div style={{ marginTop: '8px', marginBottom: '8px', color: 'var(--muted)' }}>
                    Last ML update:{' '}
                    {new Date(selectedProfile.last_ml_update).toLocaleString()}
                  </div>
                )}

                <div
                  style={{
                    marginTop: '10px',
                    paddingTop: '10px',
                    borderTop: '1px solid var(--border2)',
                  }}
                >
                  <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '6px' }}>
                    Trust Score Formula
                  </div>
                  <div style={{ fontSize: '13px', color: 'var(--muted)' }}>
                    Combines <strong>confirmed vs flagged reports</strong>,{' '}
                    <strong>spam flags</strong>, and{' '}
                    <strong>recent activity</strong>, with ML credibility as a
                    cap on very low quality devices.
                  </div>

                  <div
                    style={{
                      marginTop: '8px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 7,
                    }}
                  >
                    <div>
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          fontSize: '12px',
                          marginBottom: 3,
                        }}
                      >
                        <span>Confirmation Rate (40%)</span>
                      </div>
                      <div className="prog-bar">
                        <div
                          className="prog-fill"
                          style={{
                            width: `${Math.max(
                              0,
                              Math.min(
                                100,
                                (selectedProfile.trusted_reports || 0) /
                                  Math.max(1, selectedProfile.total_reports || 1) *
                                  100,
                              ),
                            )}%`,
                            background: 'var(--success)',
                          }}
                        ></div>
                      </div>
                    </div>

                    <div>
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          fontSize: '12px',
                          marginBottom: 3,
                        }}
                      >
                        <span>History Weight (30%)</span>
                      </div>
                      <div className="prog-bar">
                        <div
                          className="prog-fill"
                          style={{
                            width: `${Math.max(
                              0,
                              Math.min(100, (selectedProfile.total_reports || 0) * 5),
                            )}%`,
                            background: 'var(--accent)',
                          }}
                        ></div>
                      </div>
                    </div>

                    <div>
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          fontSize: '12px',
                          marginBottom: 3,
                        }}
                      >
                        <span>Spam Penalty (20%)</span>
                      </div>
                      <div className="prog-bar">
                        <div
                          className="prog-fill"
                          style={{
                            width: `${Math.max(
                              0,
                              Math.min(100, (selectedProfile.spam_flags || 0) * 10),
                            )}%`,
                            background: 'var(--danger)',
                          }}
                        ></div>
                      </div>
                    </div>
                  </div>

                  <div style={{ marginTop: '7px', fontSize: '11px', color: 'var(--muted)' }}>
                    Example formula:{' '}
                    <code style={{ fontSize: '11px' }}>
                      score = 0.4·confirm_rate + 0.3·history − 0.2·spam
                    </code>
                  </div>
                </div>

                <div
                  style={{
                    marginTop: '10px',
                    paddingTop: '10px',
                    borderTop: '1px solid var(--border2)',
                  }}
                >
                  <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '6px' }}>
                    ML Distribution (this device)
                  </div>
                  <div style={{ fontSize: '13px', marginBottom: 5 }}>
                    <span style={{ color: 'var(--success)' }}>
                      {selectedProfile.credible_reports ?? 0} credible
                    </span>
                    ,{' '}
                    <span style={{ color: 'var(--warning)' }}>
                      {selectedProfile.suspicious_reports ?? 0} suspicious
                    </span>
                    ,{' '}
                    <span style={{ color: 'var(--danger)' }}>
                      {selectedProfile.fake_reports ?? 0} fake
                    </span>
                  </div>
                  {Array.isArray(selectedProfile.model_versions) &&
                    selectedProfile.model_versions.length > 0 && (
                      <div style={{ fontSize: '11px', color: 'var(--muted)' }}>
                        Models used: {selectedProfile.model_versions.join(', ')}
                      </div>
                    )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
      <div className="page-header">
        <h2>Device Trust Management</h2>
        <p>
          Pseudonymous device profiles — track reporting patterns, trust
          scores, and spam behavior without exposing user identity.
        </p>
      </div>

      <div className="alert alert-info">
        <span className="alert-icon">i</span>
        <div>
          Device identifiers are one-way SHA-256 hashes. No personally
          identifiable information is stored.
        </div>
      </div>

      <div className="stats-row">
        <div className="stat-card c-blue">
          <div className="stat-label">Active Devices</div>
          <div className="stat-value sv-blue">{active}</div>
          <div className="stat-change">Last 30 days</div>
        </div>
        <div className="stat-card c-green">
          <div className="stat-label">High Trust</div>
          <div className="stat-value sv-green">{high}</div>
          <div className="stat-change">Score ≥ 70</div>
        </div>
        <div className="stat-card c-orange">
          <div className="stat-label">Medium Trust</div>
          <div className="stat-value sv-orange">{medium}</div>
          <div className="stat-change">Score 40–69</div>
        </div>
        <div className="stat-card c-red">
          <div className="stat-label">Low / Banned</div>
          <div className="stat-value sv-red">{low + banned}</div>
          <div className="stat-change">Low trust or banned</div>
        </div>
      </div>

      <div>
        <div className="card" style={{ minWidth: 0, overflow: 'hidden' }}>
          <div className="card-header">
            <div className="card-title">Device Registry</div>
            <div style={{ display: 'flex', gap: '6px' }}>
              <select
                className="select"
                style={{
                  width: 'auto',
                  fontSize: '11px',
                  padding: '4px 8px',
                }}
                value={trustLevel}
                onChange={(e) => setTrustLevel(e.target.value)}
              >
                <option value="all">All Trust Levels</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
              <button
                className="btn btn-outline btn-sm"
                type="button"
                onClick={exportCsv}
              >
                Export
              </button>
            </div>
          </div>

          <div className="filter-row">
            <input
              className="input"
              placeholder="Search by device hash..."
              style={{ flex: 2 }}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <select
              className="select"
              value={sectorFilter}
              onChange={(e) => setSectorFilter(e.target.value)}
            >
              <option value="all">All Sectors</option>
              {sectors.map((s) => (
                <option key={s.location_id} value={s.location_id}>
                  {s.location_name}
                </option>
              ))}
            </select>
          </div>

          <div className="tbl-wrap" style={{ width: '100%', overflowX: 'auto' }}>
            <table style={{ minWidth: 760, width: '100%' }}>
              <thead>
                <tr>
                  <th rowSpan={2}>#</th>
                  <th rowSpan={2}>Device Hash</th>
                  <th
                    rowSpan={2}
                    style={{ cursor: 'pointer' }}
                    onClick={() => {
                      setSortField('device_trust_score');
                      setSortDir((d) =>
                        sortField === 'device_trust_score' && d === 'desc'
                          ? 'asc'
                          : 'desc',
                      );
                    }}
                  >
                    Trust Score{' '}
                    {sortField === 'device_trust_score'
                      ? sortDir === 'asc'
                        ? '↑'
                        : '↓'
                      : ''}
                  </th>
                  <th
                    rowSpan={2}
                    style={{ cursor: 'pointer' }}
                    onClick={() => {
                      setSortField('total_reports');
                      setSortDir((d) =>
                        sortField === 'total_reports' && d === 'desc'
                          ? 'asc'
                          : 'desc',
                      );
                    }}
                  >
                    Total Reports{' '}
                    {sortField === 'total_reports'
                      ? sortDir === 'asc'
                        ? '↑'
                        : '↓'
                      : ''}
                  </th>
                  <th rowSpan={2}>Confirmed</th>
                  <th rowSpan={2}>Rejected</th>
                  <th rowSpan={2}>Spam Flags</th>
                  <th rowSpan={2} title="Avg ML trust (last window)">ML Avg</th>
                  <th rowSpan={2} title="ML fake-rate (last window)">Fake %</th>
                  <th rowSpan={2} title="ML confidence (last prediction)">Conf</th>
                  <th rowSpan={2} title="Last ML prediction time">Last ML</th>
                  <th
                    rowSpan={2}
                    style={{ cursor: 'pointer' }}
                    onClick={() => {
                      setSortField('last_active_at');
                      setSortDir((d) =>
                        sortField === 'last_active_at' && d === 'desc'
                          ? 'asc'
                          : 'desc',
                      );
                    }}
                  >
                    Last Active{' '}
                    {sortField === 'last_active_at'
                      ? sortDir === 'asc'
                        ? '↑'
                        : '↓'
                      : ''}
                  </th>
                  <th rowSpan={2} title="Last Known Location">Last Location</th>
                  <th rowSpan={2} title="Location Consistency Score">Location Score</th>
                  <th rowSpan={2} title="Movement Radius (km)">Radius (km)</th>
                  <th rowSpan={2}>Status</th>
                  <th rowSpan={2}>Reason</th>
                  <th colSpan={2} style={{ textAlign: 'center' }}>Actions</th>
                </tr>
                <tr>
                  <th style={{ textAlign: 'center' }}>Profile</th>
                  <th style={{ textAlign: 'center' }}>Moderation</th>
                </tr>
              </thead>
              <tbody>
                {[...devices]
                  .filter((d) => {
                    if (sectorFilter !== 'all') {
                      const sid = Number(sectorFilter);
                      if (!d.sector_location_id || d.sector_location_id !== sid) {
                        return false;
                      }
                    }
                    if (!search.trim()) return true;
                    const needle = search.trim().toLowerCase();
                    return (
                      (d.device_hash || '').toLowerCase().includes(needle) ||
                      (d.device_hash_short || '')
                        .toLowerCase()
                        .includes(needle)
                    );
                  })
                  .sort((a, b) => {
                    const dir = sortDir === 'asc' ? 1 : -1;
                    const va = a[sortField];
                    const vb = b[sortField];
                    if (va == null && vb == null) return 0;
                    if (va == null) return 1;
                    if (vb == null) return -1;
                    if (sortField === 'last_active_at') {
                      const da = new Date(va).getTime();
                      const db = new Date(vb).getTime();
                      return (da - db) * dir;
                    }
                    return (Number(va) - Number(vb)) * dir;
                  })
                  .map((d, index) => {
                    const score = d.device_trust_score ?? 0;
                    const width = Math.max(
                      0,
                      Math.min(100, Number(score)),
                    );
                    const shortHash =
                      d.device_hash_short ||
                      d.device_hash?.slice(0, 8) ||
                      'device';
                    const statusBadge = d.is_banned
                      ? 'b-red'
                      : score < 10
                        ? 'b-red'
                        : score < 40
                          ? 'b-orange'
                          : 'b-green';
                    const statusLabel = d.is_banned
                      ? 'Banned'
                      : score < 10
                        ? 'Banned'
                        : score < 40
                          ? 'Flagged'
                          : 'Active';
                    const busy = Boolean(d._banBusy);

                    // Analyze location data
                    const metadata = d.metadata_json || d.metadata || {};
                    const locationAnalysis = analyzeLocationConsistency(metadata);
                    const locationView = resolveLastLocation(d);
                    const locationScoreBadge = locationAnalysis.consistency_score === null
                      ? 'b-gray'
                      : locationAnalysis.consistency_score >= 80 
                      ? 'b-green' 
                      : locationAnalysis.consistency_score >= 60 
                      ? 'b-orange' 
                      : 'b-red';

                    return (
                      <tr key={d.device_id}>
                        <td style={{ fontSize: "12px", color: "var(--muted)", textAlign: "center" }}>
                          {index + 1}
                        </td>
                        <td
                          style={{
                            fontFamily: 'monospace',
                            fontSize: '10px',
                          }}
                        >
                          {shortHash}
                        </td>
                        <td>
                          <div className="trust-wrap">
                            <div className="trust-track">
                              <div
                                className="trust-fill"
                                style={{
                                  width: `${width}%`,
                                  background:
                                    score >= 70
                                      ? 'var(--success)'
                                      : score >= 40
                                      ? 'var(--warning)'
                                      : 'var(--danger)',
                                }}
                              ></div>
                            </div>
                            <div className="trust-val">
                              {Math.round(score)}
                            </div>
                          </div>
                        </td>
                        <td>{d.total_reports ?? 0}</td>
                        <td style={{ color: 'var(--success)' }}>
                          {d.trusted_reports ?? d.confirmed_reports ?? d.verified_reports ?? 0}
                        </td>
                        <td style={{ color: 'var(--danger)' }}>
                          {d.flagged_reports ?? d.rejected_reports ?? 0}
                        </td>
                        <td>{d.spam_flags ?? d.spam_count ?? 0}</td>
                        <td style={{ fontSize: '11px', color: 'var(--muted)' }}>
                          {d.ml_avg_trust != null ? Math.round(d.ml_avg_trust) : 
                           d.ml_stats?.avg_trust_score != null ? Math.round(d.ml_stats.avg_trust_score) : '—'}
                        </td>
                        <td style={{ fontSize: '11px', color: 'var(--muted)' }}>
                          {normalizePercentValue(d.ml_fake_rate) != null
                            ? `${Math.round(normalizePercentValue(d.ml_fake_rate))}%`
                            : normalizePercentValue(d.ml_stats?.fake_rate) != null
                              ? `${Math.round(normalizePercentValue(d.ml_stats?.fake_rate))}%`
                              : '—'}
                        </td>
                        <td style={{ fontSize: '11px', color: 'var(--muted)' }}>
                          {normalizePercentValue(d.ml_last_confidence) != null
                            ? `${Math.round(normalizePercentValue(d.ml_last_confidence))}%`
                            : normalizePercentValue(d.ml_stats?.last_confidence) != null
                              ? `${Math.round(normalizePercentValue(d.ml_stats?.last_confidence))}%`
                              : '—'}
                        </td>
                        <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                          {formatShortDate(d.ml_last_prediction_at || d.ml_stats?.last_prediction_at)}
                        </td>
                        <td
                          style={{
                            fontSize: '10px',
                            color: 'var(--muted)',
                          }}
                        >
                          {formatShortDate(d.last_active_at)}
                        </td>
                        <td style={{ fontSize: '10px', color: 'var(--muted)', maxWidth: 120 }}>
                          <div
                            title={
                              locationView.coords || locationView.hierarchy
                                ? [locationView.coords, locationView.hierarchy]
                                    .filter(Boolean)
                                    .join(' | ')
                                : 'No location data'
                            }
                          >
                            {locationView.coords || '—'}
                          </div>
                          {locationView.hierarchy && (
                            <div style={{ fontSize: '8px', color: 'var(--muted)', marginTop: 2 }}>
                              {locationView.hierarchy}
                            </div>
                          )}
                          {(d.metadata_json?.last_location_timestamp || d.metadata?.last_location_timestamp) && (
                            <div style={{ fontSize: '8px', color: 'var(--muted)', marginTop: 2 }}>
                              {formatTimestamp(d.metadata_json?.last_location_timestamp || d.metadata?.last_location_timestamp).split(',')[0]}
                            </div>
                          )}
                        </td>
                        <td>
                          <span className={`badge ${locationScoreBadge}`} style={{ fontSize: '10px' }}>
                            {locationAnalysis.consistency_score === null ? 'No Data' : locationAnalysis.consistency_score}
                          </span>
                          {locationAnalysis.suspicious_jumps > 0 && (
                            <div style={{ fontSize: '8px', color: 'var(--danger)', marginTop: 2 }}>
                              ⚠️ {locationAnalysis.suspicious_jumps} jumps
                            </div>
                          )}
                        </td>
                        <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                          {locationAnalysis.movement_radius_km} km
                          {locationAnalysis.avg_gps_accuracy && (
                            <div style={{ fontSize: '8px', color: 'var(--muted)', marginTop: 2 }}>
                              GPS: ±{locationAnalysis.avg_gps_accuracy}m
                            </div>
                          )}
                        </td>
                        <td>
                          <span className={`badge ${statusBadge}`}>
                            {statusLabel}
                          </span>
                        </td>
                        <td style={{ maxWidth: 220, color: 'var(--muted)' }}>
                          <span title={d.blacklist_reason || ''}>
                            {d.blacklist_reason || '—'}
                          </span>
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          <button
                            className="btn btn-outline btn-sm"
                            type="button"
                            onClick={() => openProfile(d.device_id)}
                            disabled={busy}
                          >
                            Profile
                          </button>
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          {!d.is_banned ? (
                            <button
                              className="btn btn-outline btn-sm"
                              type="button"
                              onClick={() =>
                                setBanDialog({
                                  open: true,
                                  deviceId: d.device_id,
                                  preset:
                                    d.is_blacklisted && d.blacklist_reason
                                      ? d.blacklist_reason
                                      : 'policy_violation',
                                  details: '',
                                })
                              }
                              disabled={busy}
                              style={{
                                borderColor: 'rgba(239,68,68,.5)',
                                color: 'var(--danger)',
                              }}
                            >
                              {busy ? '...' : 'Ban'}
                            </button>
                          ) : (
                            <button
                              className="btn btn-outline btn-sm"
                              type="button"
                              onClick={() => unbanDevice(d.device_id)}
                              disabled={busy}
                              style={{
                                borderColor: 'rgba(52,211,153,.5)',
                                color: 'var(--success)',
                              }}
                            >
                              {busy ? '...' : 'Unban'}
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                {!devices.length && !loading && (
                  <tr>
                    <td
                      colSpan={16}
                      style={{
                        fontSize: '12px',
                        color: 'var(--muted)',
                        textAlign: 'center',
                      }}
                    >
                      No devices yet.
                    </td>
                  </tr>
                )}
                {loading && (
                  <tr>
                    <td
                      colSpan={16}
                      style={{
                        fontSize: '12px',
                        color: 'var(--muted)',
                        textAlign: 'center',
                      }}
                    >
                      Loading...
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginTop: '14px',
              flexWrap: 'wrap',
              gap: '8px',
            }}
          >
            <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
              Showing {devices.length} of{' '}
              {stats?.active_30d ?? devices.length} devices
            </div>
            <div className="pagination">
              <div className="page-btn">‹</div>
              <div className="page-btn current">1</div>
              <div className="page-btn">2</div>
              <div className="page-btn">3</div>
              <div className="page-btn">›</div>
            </div>
          </div>
        </div>

      </div>
    </>
  );
};

export default DeviceTrust;