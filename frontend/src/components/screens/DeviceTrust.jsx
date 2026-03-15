import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const DeviceTrust = () => {
  const [devices, setDevices] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [trustLevel, setTrustLevel] = useState('all'); // all | high | medium | low
  const [search, setSearch] = useState('');
  const [sortField, setSortField] = useState('device_trust_score');
  const [sortDir, setSortDir] = useState('desc'); // asc | desc
  const [selectedProfile, setSelectedProfile] = useState(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [sectorFilter, setSectorFilter] = useState('all');
  const [sectors, setSectors] = useState([]);

  // Load devices from backend, filtered by trust level
  useEffect(() => {
    let mounted = true;
    const params = new URLSearchParams({ limit: '50', offset: '0' });
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
  }, [trustLevel]);

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
    try {
      setProfileLoading(true);
      setSelectedProfile(null);
      const mlStats = await api.get(
        `/api/v1/devices/${deviceId}/ml-stats`,
      );
      setSelectedProfile({
        ...mlStats,
        device_hash: dev.device_hash,
        device_trust_score: dev.device_trust_score,
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
    ];
    const rows = devices.map((d) => {
      const score = d.device_trust_score ?? 0;
      const status =
        score < 10 ? 'Banned' : score < 40 ? 'Flagged' : 'Active';
      return [
        d.device_hash,
        Math.round(score),
        d.total_reports ?? 0,
        d.trusted_reports ?? 0,
        d.flagged_reports ?? 0,
        d.spam_flags ?? 0,
        d.last_active_at || '',
        status,
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

  return (
    <>
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

      <div className="g31">
        <div className="card">
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

          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>Device Hash</th>
                  <th
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
                  <th>Confirmed</th>
                  <th>Rejected</th>
                  <th>Spam Flags</th>
                  <th
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
                  <th>Status</th>
                  <th></th>
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
                  .map((d) => {
                    const score = d.device_trust_score ?? 0;
                    const width = Math.max(
                      0,
                      Math.min(100, Number(score)),
                    );
                    const shortHash =
                      d.device_hash_short ||
                      d.device_hash?.slice(0, 8) ||
                      'device';
                    const statusBadge =
                      score < 10
                        ? 'b-red'
                        : score < 40
                        ? 'b-orange'
                        : 'b-green';
                    const statusLabel =
                      score < 10
                        ? 'Banned'
                        : score < 40
                        ? 'Flagged'
                        : 'Active';

                    return (
                      <tr key={d.device_id}>
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
                        <td>{d.total_reports}</td>
                        <td style={{ color: 'var(--success)' }}>
                          {d.trusted_reports}
                        </td>
                        <td style={{ color: 'var(--danger)' }}>
                          {d.flagged_reports}
                        </td>
                        <td>{d.spam_flags ?? '—'}</td>
                        <td
                          style={{
                            fontSize: '10px',
                            color: 'var(--muted)',
                          }}
                        >
                          {d.last_active_at
                            ? new Date(d.last_active_at).toLocaleDateString()
                            : '—'}
                        </td>
                        <td>
                          <span className={`badge ${statusBadge}`}>
                            {statusLabel}
                          </span>
                        </td>
                        <td>
                          <button
                            className="btn btn-outline btn-sm"
                            type="button"
                            onClick={() => openProfile(d.device_id)}
                          >
                            Profile
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                {!devices.length && !loading && (
                  <tr>
                    <td
                      colSpan={9}
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
                      colSpan={9}
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

        <div className="card">
          <div className="card-header">
            <div className="card-title">Selected Device Profile</div>
          </div>
          {!selectedProfile && !profileLoading && (
            <div
              style={{
                fontSize: '12px',
                color: 'var(--muted)',
                padding: '10px 14px',
              }}
            >
              Click a <strong>Profile</strong> button in the registry to see
              ML trust details for that device.
            </div>
          )}
          {profileLoading && (
            <div
              style={{
                fontSize: '12px',
                color: 'var(--muted)',
                padding: '10px 14px',
              }}
            >
              Loading profile...
            </div>
          )}
          {selectedProfile && !profileLoading && (
            <div style={{ padding: '10px 14px', fontSize: '12px' }}>
              {/* Identity + headline trust score */}
              <div
                style={{
                  marginBottom: '6px',
                  fontFamily: '"Syne", sans-serif',
                  fontWeight: 700,
                }}
              >
                Hash:{' '}
                <span style={{ fontFamily: 'monospace' }}>
                  {selectedProfile.device_hash}
                </span>
              </div>
              <div style={{ marginBottom: '6px' }}>
                Trust score:{' '}
                <strong>
                  {Math.round(selectedProfile.device_trust_score ?? 0)}
                </strong>{' '}
                / 100
              </div>
              <div style={{ marginBottom: '6px' }}>
                Reports:{' '}
                <strong>{selectedProfile.total_reports}</strong> total ·{' '}
                <span style={{ color: 'var(--success)' }}>
                  {selectedProfile.verified_reports} verified
                </span>{' '}
                ·{' '}
                <span style={{ color: 'var(--danger)' }}>
                  {selectedProfile.flagged_reports} flagged
                </span>
              </div>
              {selectedProfile.last_ml_update && (
                <div
                  style={{ marginBottom: '10px', color: 'var(--muted)' }}
                >
                  Last ML update:{' '}
                  {new Date(
                    selectedProfile.last_ml_update,
                  ).toLocaleString()}
                </div>
              )}

              {/* Trust Score Formula (static explanation based on DB + ML) */}
              <div
                style={{
                  marginTop: '8px',
                  paddingTop: '8px',
                  borderTop: '1px solid var(--border2)',
                }}
              >
                <div
                  style={{
                    fontSize: '11px',
                    fontWeight: 700,
                    marginBottom: '4px',
                  }}
                >
                  Trust Score Formula
                </div>
                <div style={{ fontSize: '11px', color: 'var(--muted)' }}>
                  Combines{' '}
                  <strong>confirmed vs flagged reports</strong>,{' '}
                  <strong>spam flags</strong>, and{' '}
                  <strong>recent activity</strong>, with ML credibility as a
                  cap on very low quality devices.
                </div>

                <div
                  style={{
                    marginTop: '6px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                  }}
                >
                  {/* Confirmation rate */}
                  <div>
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        fontSize: '10px',
                        marginBottom: 2,
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
                              (selectedProfile.verified_reports || 0) /
                                Math.max(
                                  1,
                                  selectedProfile.total_reports || 1,
                                ) *
                                100,
                            ),
                          )}%`,
                          background: 'var(--success)',
                        }}
                      ></div>
                    </div>
                  </div>

                  {/* History weight (more reports => more stable score) */}
                  <div>
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        fontSize: '10px',
                        marginBottom: 2,
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
                            Math.min(
                              100,
                              (selectedProfile.total_reports || 0) * 5,
                            ),
                          )}%`,
                          background: 'var(--accent)',
                        }}
                      ></div>
                    </div>
                  </div>

                  {/* Spam penalty based on suspicious/fake flags */}
                  <div>
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        fontSize: '10px',
                        marginBottom: 2,
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
                            Math.min(
                              100,
                              (selectedProfile.suspicious_reports || 0) *
                                20,
                            ),
                          )}%`,
                          background: 'var(--danger)',
                        }}
                      ></div>
                    </div>
                  </div>
                </div>

                <div
                  style={{
                    marginTop: '6px',
                    fontSize: '10px',
                    color: 'var(--muted)',
                  }}
                >
                  Example formula:{' '}
                  <code style={{ fontSize: '10px' }}>
                    score = 0.4·confirm_rate + 0.3·history − 0.2·spam
                  </code>
                </div>
              </div>

              {/* ML trust distribution for this device */}
              <div
                style={{
                  marginTop: '8px',
                  paddingTop: '8px',
                  borderTop: '1px solid var(--border2)',
                }}
              >
                <div
                  style={{
                    fontSize: '11px',
                    fontWeight: 700,
                    marginBottom: '4px',
                  }}
                >
                  ML Distribution (this device)
                </div>
                <div style={{ fontSize: '11px', marginBottom: 4 }}>
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
                    <div
                      style={{
                        fontSize: '10px',
                        color: 'var(--muted)',
                      }}
                    >
                      Models used:{' '}
                      {selectedProfile.model_versions.join(', ')}
                    </div>
                  )}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
};

export default DeviceTrust;