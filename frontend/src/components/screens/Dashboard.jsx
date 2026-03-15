import React, { useEffect, useState } from 'react';
import api from '../../api/client';
import { useAuth } from '../../context/AuthContext';

const Dashboard = ({ goToScreen }) => {
  const { user } = useAuth();
  const role = user?.role || 'officer';
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    api.get('/api/v1/stats/dashboard')
      .then((d) => { if (mounted) { setStats(d); setLoading(false); } })
      .catch(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  const total = stats?.total_reports ?? 0;
  const recent7 = stats?.reports_last_7_days ?? 0;
  const pending = stats?.pending ?? (stats?.by_status?.pending ?? 0);
  const verified = stats?.verified ?? (stats?.by_status?.passed ?? 0);
  const flagged = stats?.flagged ?? 0;
  const openCases = stats?.open_cases ?? 0;
  const recentReports = stats?.recent_reports ?? [];
  const topHotspots = stats?.top_hotspots ?? [];
  const myScope = stats?.scope === 'assigned_to_me';
  const credibilityTotal = pending + verified + flagged;
  const weeklyVolume = stats?.weekly_volume || [];
  const avgTrustScore = stats?.avg_trust_score ?? null;

  return (
    <>
      <div className="page-header">
        <h2>
          Welcome back,{' '}
          {user ? `${user.first_name} ${user.last_name}` : 'Officer'}
        </h2>
        <p>
          {role === 'officer'
            ? 'Here is your assigned work — cases and reports that need your attention.'
            : "Here's what's happening in Musanze District right now."}
        </p>
      </div>

      {role === 'officer' ? (
        <div className="alert alert-info">
          <span className="alert-icon">i</span>
          <div>
            <strong>{pending} of your assigned reports</strong> still need a
            decision.{' '}
            <span
              className="card-action"
              onClick={() => goToScreen('reports', 1)}
            >
              Open My Reports
            </span>
          </div>
        </div>
      ) : (
        <div className="alert alert-warn">
          <span className="alert-icon">!</span>
          <div>
            <strong>{pending} reports pending review</strong> — view and verify.
            <span
              className="card-action"
              onClick={() => goToScreen('reports', 1)}
            >
              Review now
            </span>
          </div>
        </div>
      )}

      <div className="stats-row">
        <div className="stat-card c-blue">
          <div className="stat-label">
            {role === 'officer' ? 'My Assigned Reports' : 'Total Reports'}
          </div>
          <div className="stat-value sv-blue">{total}</div>
          <div className="stat-change">
            <span className="up">{myScope ? 'assigned' : 'live'}</span>
          </div>
        </div>
        <div className="stat-card c-cyan">
          <div className="stat-label">Last 7 Days</div>
          <div className="stat-value sv-cyan">{recent7}</div>
          <div className="stat-change">
            <span className="up">recent</span>
          </div>
        </div>
        <div className="stat-card c-orange">
          <div className="stat-label">Pending</div>
          <div className="stat-value sv-orange">{pending}</div>
          <div className="stat-change">
            <span className="dn">
              {role === 'officer' ? 'your queue' : 'needs review'}
            </span>
          </div>
        </div>
        <div className="stat-card c-green">
          <div className="stat-label">Verified</div>
          <div className="stat-value sv-green">{verified}</div>
          <div className="stat-change">
            <span className="up">rule "passed"</span>
          </div>
        </div>
        <div className="stat-card c-red">
          <div className="stat-label">Flagged</div>
          <div className="stat-value sv-red">{flagged}</div>
          <div className="stat-change">
            <span className="dn">
              {role === 'officer' ? 'check anomalies' : 'check anomalies'}
            </span>
          </div>
        </div>
        <div className="stat-card c-purple">
          <div className="stat-label">
            {role === 'officer' ? 'My Open Cases' : 'Open Cases'}
          </div>
          <div className="stat-value sv-purple">{openCases}</div>
          <div className="stat-change">
            <span className="dn">case files</span>
          </div>
        </div>
      </div>

      {/* Weekly Volume + Credibility Split row */}
      <div className="g31">
        <div className="card">
          <div className="card-header">
            <div className="card-title">Weekly Volume</div>
            <div className="card-action">Last 4 weeks</div>
          </div>
          <div
            style={{
              padding: '10px 14px',
              display: 'flex',
              gap: '8px',
              alignItems: 'flex-end',
              fontSize: '11px',
            }}
          >
            {(weeklyVolume || []).map((w) => {
              const max = Math.max(
                1,
                ...weeklyVolume.map((x) => x.count || 0),
              );
              const height = Math.max(
                8,
                Math.round(((w.count || 0) / max) * 40),
              );
              return (
                <div
                  key={w.label}
                  style={{
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: 4,
                  }}
                >
                  <div
                    style={{
                      width: '100%',
                      height,
                      borderRadius: '4px 4px 0 0',
                      background: 'var(--accent)',
                      opacity: 0.85,
                    }}
                  ></div>
                  <div style={{ fontSize: '10px', color: 'var(--muted)' }}>
                    {w.label}
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--muted)' }}>
                    {w.count}
                  </div>
                </div>
              );
            })}
            {!weeklyVolume.length && (
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                No reports yet.
              </div>
            )}
          </div>
        </div>

        {/* Credibility Split: donut chart + legend + Avg Trust Score */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">Credibility Split</div>
            <div className="card-action">All time</div>
          </div>
          <div style={{ padding: '10px 14px', fontSize: '12px' }}>
            {(() => {
              const vPct = credibilityTotal
                ? Math.round((verified / credibilityTotal) * 100)
                : 0;
              const pPct = credibilityTotal
                ? Math.round((pending / credibilityTotal) * 100)
                : 0;
              const fPct = credibilityTotal
                ? Math.round((flagged / credibilityTotal) * 100)
                : 0;
              const r = 45;
              const c = 2 * Math.PI * r;
              const vLen = (vPct / 100) * c;
              const pLen = (pPct / 100) * c;
              const fLen = (fPct / 100) * c;
              const centerLabel =
                vPct >= pPct && vPct >= fPct
                  ? 'verified'
                  : pPct >= fPct
                  ? 'pending'
                  : 'flagged';
              const centerPct =
                centerLabel === 'verified'
                  ? vPct
                  : centerLabel === 'pending'
                  ? pPct
                  : fPct;
              return (
                <>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '12px',
                      marginBottom: '12px',
                      flexWrap: 'wrap',
                    }}
                  >
                    <div style={{ position: 'relative', flexShrink: 0 }}>
                      <svg
                        width="120"
                        height="120"
                        viewBox="0 0 120 120"
                        style={{ transform: 'rotate(-90deg)' }}
                      >
                        <circle
                          cx="60"
                          cy="60"
                          r={r}
                          fill="none"
                          stroke="var(--success)"
                          strokeWidth="14"
                          strokeDasharray={
                            credibilityTotal
                              ? `${vLen} ${c - vLen}`
                              : '0 999'
                          }
                          strokeDashoffset="0"
                        />
                        <circle
                          cx="60"
                          cy="60"
                          r={r}
                          fill="none"
                          stroke="var(--warning)"
                          strokeWidth="14"
                          strokeDasharray={
                            credibilityTotal
                              ? `${pLen} ${c - pLen}`
                              : '0 999'
                          }
                          strokeDashoffset={-vLen}
                        />
                        <circle
                          cx="60"
                          cy="60"
                          r={r}
                          fill="none"
                          stroke="var(--danger)"
                          strokeWidth="14"
                          strokeDasharray={
                            credibilityTotal
                              ? `${fLen} ${c - fLen}`
                              : '0 999'
                          }
                          strokeDashoffset={-(vLen + pLen)}
                        />
                      </svg>
                      <div
                        style={{
                          position: 'absolute',
                          left: '50%',
                          top: '50%',
                          transform: 'translate(-50%, -50%)',
                          textAlign: 'center',
                          fontWeight: 700,
                          fontSize: '18px',
                          color:
                            centerLabel === 'verified'
                              ? 'var(--success)'
                              : centerLabel === 'pending'
                              ? 'var(--warning)'
                              : 'var(--danger)',
                        }}
                      >
                        <div>{credibilityTotal ? `${centerPct}%` : '—'}</div>
                        <div
                          style={{
                            fontSize: '10px',
                            color: 'var(--muted)',
                            textTransform: 'capitalize',
                            fontWeight: 500,
                          }}
                        >
                          {centerLabel}
                        </div>
                      </div>
                    </div>
                    <div style={{ flex: 1, minWidth: 100 }}>
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 6,
                          marginBottom: 4,
                        }}
                      >
                        <span
                          style={{
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            background: 'var(--success)',
                          }}
                        />
                        <span>Verified – {verified}</span>
                      </div>
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 6,
                          marginBottom: 4,
                        }}
                      >
                        <span
                          style={{
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            background: 'var(--warning)',
                          }}
                        />
                        <span>Pending – {pending}</span>
                      </div>
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 6,
                        }}
                      >
                        <span
                          style={{
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            background: 'var(--danger)',
                          }}
                        />
                        <span>Flagged – {flagged}</span>
                      </div>
                    </div>
                  </div>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      marginBottom: 4,
                      fontSize: '11px',
                      color: 'var(--muted)',
                    }}
                  >
                    <span>Avg Trust Score</span>
                    <span
                      style={{
                        color: 'var(--text)',
                        fontWeight: 600,
                      }}
                    >
                      {avgTrustScore !== null
                        ? `${Math.round(avgTrustScore)} / 100`
                        : '—'}
                    </span>
                  </div>
                  <div className="prog-bar">
                    <div
                      className="prog-fill"
                      style={{
                        width: `${
                          avgTrustScore !== null
                            ? Math.max(
                                0,
                                Math.min(100, Math.round(avgTrustScore)),
                              )
                            : 0
                        }%`,
                        background: 'var(--accent)',
                      }}
                    ></div>
                  </div>
                </>
              );
            })()}
          </div>
        </div>
      </div>

      <div className="g31">
        <div className="card">
          <div className="card-header">
            <div className="card-title">Recent Reports</div>
            <div className="card-action" onClick={() => goToScreen('reports', 1)}>View all</div>
          </div>
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Type</th>
                  <th>Location</th>
                  <th>Trust</th>
                  <th>Status</th>
                  <th>Time</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {(recentReports || []).map((r) => {
                  const score = r.trust_score ?? 0;
                  const width = Math.max(0, Math.min(100, Number(score)));
                  const status = r.rule_status;
                  return (
                    <tr key={r.report_id}>
                      <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                        {r.report_number || String(r.report_id).slice(0, 8)}
                      </td>
                      <td><strong>{r.incident_type_name || '—'}</strong></td>
                      <td>{r.village_name || '—'}</td>
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
                          <div className="trust-val">{Math.round(score)}</div>
                        </div>
                      </td>
                      <td>
                        <span
                          className={`badge ${
                            status === 'pending'
                              ? 'b-orange'
                              : status === 'passed'
                              ? 'b-green'
                              : 'b-red'
                          }`}
                        >
                          {status}
                        </span>
                      </td>
                      <td style={{ fontSize: '10px', color: 'var(--muted)' }}>
                        {r.reported_at ? new Date(r.reported_at).toLocaleString() : '—'}
                      </td>
                      <td>
                        <button className="btn btn-outline btn-sm" onClick={() => goToScreen('reports', 1)}>View</button>
                      </td>
                    </tr>
                  );
                })}
                {(!recentReports || recentReports.length === 0) && (
                  <tr>
                    <td colSpan={7} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                      {loading ? 'Loading...' : 'No reports yet.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <div className="card-title">Top Hotspots</div>
            <div className="card-action" onClick={() => goToScreen('hotspots', 4)}>Full view</div>
          </div>
          {(topHotspots || []).map((h, idx) => (
            <div className="hs-item" key={h.hotspot_id}>
              <div className="hs-rank">{String(idx + 1).padStart(2, '0')}</div>
              <div className="hs-info">
                <div className="hs-name">{h.area_name || 'Area'}</div>
                <div className="hs-meta">
                  {h.incident_count} reports · {h.incident_type_name || 'Mixed'}
                </div>
              </div>
              <span className={`risk-pill ${
                h.risk_level === 'high' ? 'r-critical'
                  : h.risk_level === 'medium' ? 'r-warning'
                  : 'r-normal'
              }`}>
                {h.risk_level?.toUpperCase() || 'OK'}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Second row: Recent Activity (left) | Quick Actions + System Status (right) */}
      <div className="g31" style={{ marginTop: '16px' }}>
        {/* Recent Activity */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">Recent Activity</div>
          </div>
          <div style={{ padding: '10px 14px' }}>
            {(stats?.recent_activity || []).map((a, i) => {
              const severity = a.severity || 'neutral';
              const dotColor =
                severity === 'success'
                  ? 'var(--success)'
                  : severity === 'danger'
                  ? 'var(--danger)'
                  : severity === 'critical'
                  ? 'var(--accent)'
                  : severity === 'warn'
                  ? 'var(--warning)'
                  : 'var(--muted)';
              const text =
                a.text ||
                `${a.action_type || 'Activity'}${
                  a.entity_type ? ` on ${a.entity_type}` : ''
                }`;
              return (
              <div
                key={i}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 8,
                  marginBottom: 10,
                  fontSize: '12px',
                }}
              >
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    background: dotColor,
                    flexShrink: 0,
                    marginTop: 5,
                  }}
                />
                <div style={{ flex: 1 }}>
                  <div style={{ color: 'var(--text)' }}>{text}</div>
                  <div style={{ fontSize: '10px', color: 'var(--muted)', marginTop: 2 }}>
                    {a.created_at}
                  </div>
                </div>
              </div>
            )})}
          </div>
        </div>

        {/* Quick Actions + System Status */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div className="card">
            <div className="card-header">
              <div className="card-title">Quick Actions</div>
            </div>
            <div
              style={{
                padding: '10px 14px',
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: 8,
              }}
            >
              {[
                { label: 'Pending', border: 'var(--warning)', go: () => goToScreen('reports', 1) },
                { label: 'Flagged', border: 'var(--danger)', go: () => goToScreen('reports', 1) },
                { label: 'Cases', border: 'var(--accent)', go: () => goToScreen('case-management', 3) },
                { label: 'Add Officer', border: 'var(--success)', go: () => goToScreen('users', 7) },
                { label: 'Map', border: 'var(--accent)', go: () => goToScreen('safety-map', 5) },
                { label: 'Devices', border: 'var(--success)', go: () => goToScreen('device-trust', 6) },
              ].map((btn, i) => (
                <button
                  key={i}
                  type="button"
                  className="btn btn-outline"
                  style={{
                    borderColor: btn.border,
                    color: btn.border,
                    borderRadius: 8,
                    padding: '10px 12px',
                    fontSize: '12px',
                  }}
                  onClick={btn.go}
                >
                  {btn.label}
                </button>
              ))}
            </div>
          </div>
          <div className="card">
            <div className="card-header">
              <div className="card-title">System Status</div>
            </div>
            <div style={{ padding: '10px 14px', fontSize: '12px' }}>
              {(stats?.system_status || []).map((s, i) => {
                const level = s.level || 'neutral';
                const dotColor =
                  level === 'ok'
                    ? 'var(--success)'
                    : level === 'warn'
                    ? 'var(--warning)'
                    : level === 'error'
                    ? 'var(--danger)'
                    : 'var(--muted)';
                return (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    marginBottom: 8,
                  }}
                >
                  <span style={{ color: 'var(--text)' }}>{s.name}</span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: '50%',
                        background: dotColor,
                      }}
                    />
                    <span style={{ color: 'var(--muted)', fontSize: '11px' }}>{s.status}</span>
                  </span>
                </div>
              )})}
            </div>
          </div>
        </div>
      </div>
    </>
  );
};

export default Dashboard;