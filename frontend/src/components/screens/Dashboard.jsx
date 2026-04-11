import React, { useEffect, useState } from "react";
import api from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { formatRelativeTime } from "../../utils/dateTime";
import AdvancedGeographicCharts from "../charts/AdvancedGeographicCharts";

const Dashboard = ({ goToScreen, onOpenReport, wsRefreshKey }) => {
  const { user } = useAuth();
  const role = user?.role || "officer";
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sectorData, setSectorData] = useState(null);
  const [selectedTimeWindow, setSelectedTimeWindow] = useState(24);

  // Simplify technical system status names
  const simplifySystemStatusName = (name) => {
    const mappings = {
      "ML Engine": "Smart Analysis",
      "Hotspot Detection (DBSCAN)": "Hotspot Monitoring",
      "Database Connection": "Data Storage",
      "WebSocket Service": "Live Updates",
      "Email Service": "Email Alerts",
      "File Storage": "File System",
      "API Gateway": "System Services",
    };
    return mappings[name] || name;
  };

  // Map rule_status to user-friendly labels
  const getStatusLabel = (status) => {
    const statusMap = {
      pending: "Pending",
      passed: "Verified",
      flagged: "Flagged",
      rejected: "Flagged",
    };
    return statusMap[status] || status;
  };

  // Get role-based chart title
  const getChartTitle = (role) => {
    switch(role) {
      case "admin": 
        return "Musanze District Performance Overview";
      case "supervisor": 
        return "Station Performance Overview";
      case "officer": 
        return "My Performance Overview";
      default: 
        return "Performance Overview";
    }
  };

  // Get role-based chart type
  const getChartType = (role) => {
    switch(role) {
      case "admin": 
      case "supervisor":
        return "sectorPerformance";
      case "officer": 
        return "personalPerformance";
      default: 
        return "sectorPerformance";
    }
  };

  // Load sector performance data with time window
  const loadSectorData = (timeWindow) => {
    let endpoint;
    
    // Role-based endpoint selection
    switch(role) {
      case "admin":
        endpoint = `/api/v1/geographic-intelligence/sector-performance?time_window_hours=${timeWindow}`;
        break;
      case "supervisor":
        endpoint = `/api/v1/geographic-intelligence/station-performance?time_window_hours=${timeWindow}`;
        break;
      case "officer":
        endpoint = `/api/v1/geographic-intelligence/officer-performance?time_window_hours=${timeWindow}`;
        break;
      default:
        endpoint = `/api/v1/geographic-intelligence/sector-performance?time_window_hours=${timeWindow}`;
    }

    api
      .get(endpoint)
      .then((d) => {
        console.log(`${role} performance data loaded:`, d);
        console.log(`${role} performance_data:`, d.performance_data);
        console.log(`${role} performance_data[0]:`, d.performance_data?.[0]);
        console.log(`${role} total_reports:`, d.total_reports);
        setSectorData(d);
      })
      .catch((err) => {
        console.log(`${role} performance data not available, using fallback`);
        // Role-based fallback data
        let fallbackData;
        switch(role) {
          case "admin":
            fallbackData = {
              performance_data: [
                { sector_name: 'Sector A', report_count: 15, device_count: 5, avg_trust_score: 75 },
                { sector_name: 'Sector B', report_count: 23, device_count: 8, avg_trust_score: 82 },
                { sector_name: 'Sector C', report_count: 8, device_count: 3, avg_trust_score: 68 }
              ]
            };
            break;
          case "supervisor":
            fallbackData = {
              performance_data: [
                { sector_name: 'Sector 1', report_count: 12, device_count: 4, avg_trust_score: 78 },
                { sector_name: 'Sector 2', report_count: 18, device_count: 6, avg_trust_score: 85 }
              ]
            };
            break;
          case "officer":
            fallbackData = {
              performance_data: [
                { date: 'Mon', reports_processed: 8, avg_response_time: 15 },
                { date: 'Tue', reports_processed: 12, avg_response_time: 12 },
                { date: 'Wed', reports_processed: 10, avg_response_time: 18 },
                { date: 'Thu', reports_processed: 15, avg_response_time: 10 },
                { date: 'Fri', reports_processed: 9, avg_response_time: 20 }
              ]
            };
            break;
          default:
            fallbackData = { performance_data: [] };
        }
        setSectorData(fallbackData);
      });
  };

  useEffect(() => {
    let mounted = true;
    
    // Load dashboard stats
    api
      .get("/api/v1/stats/dashboard")
      .then((d) => {
        if (mounted) {
          setStats(d);
          setLoading(false);
        }
      })
      .catch(() => {
        if (mounted) setLoading(false);
      });

    // Load initial sector performance data
    if (mounted) {
      loadSectorData(selectedTimeWindow);
    }

    return () => {
      mounted = false;
    };
  }, [user, wsRefreshKey]);

  // Reload sector data when time window changes
  useEffect(() => {
    loadSectorData(selectedTimeWindow);
  }, [selectedTimeWindow]);

  const total = stats?.total_reports ?? 0;
  const recent7 = stats?.reports_last_7_days ?? 0;
  const pending = stats?.pending ?? stats?.by_status?.pending ?? 0;
  const verified = stats?.verified ?? stats?.by_status?.passed ?? 0;
  const flagged = stats?.flagged ?? 0;
  const openCases = stats?.open_cases ?? 0;
  const recentReports = stats?.recent_reports ?? [];
  const topHotspots = stats?.top_hotspots ?? [];
  const myScope = stats?.scope === "assigned_to_me";
  const weeklyVolume = stats?.weekly_volume || [];
  const avgTrustScore = stats?.avg_trust_score ?? null;

  const statusBadgeClass = (status) => {
    if (status === "passed" || status === "verified") return "passed";
    if (status === "pending" || status === "under_review") return "pending";
    return "flagged";
  };

  const statusLabel = (status) => {
    if (status === "passed" || status === "verified") return "Verified";
    if (status === "pending" || status === "under_review") return "Pending";
    if (status === "flagged" || status === "rejected") return "Flagged";
    return status || "Unknown";
  };

  const chartWeeks = [0, 1, 2, 3].map((idx) => {
    const src = weeklyVolume[idx];
    if (!src) return { label: `W${idx + 1}`, count: null };
    const rawCount = Number(src.count);
    const count = Number.isFinite(rawCount) && rawCount > 0 ? rawCount : null;
    return {
      label: src.label || `W${idx + 1}`,
      count,
    };
  });

  const maxWeekCount = Math.max(
    1,
    ...chartWeeks.map((w) => (typeof w.count === "number" ? w.count : 0)),
  );

  const credibilityTotal = pending + verified + flagged;
  const credibilityTotalSafe = Math.max(credibilityTotal, 1);
  const flaggedPct = Math.round((flagged / credibilityTotalSafe) * 100);
  const pendingPct = Math.round((pending / credibilityTotalSafe) * 100);
  const verifiedPct = Math.round((verified / credibilityTotalSafe) * 100);

  const openActivityTarget = (activity) => {
    const entityType = (activity?.entity_type || "").toLowerCase();
    const entityId = activity?.entity_id;
    if (!entityId) return;
    if (entityType === "report") return onOpenReport?.(entityId);
    if (entityType === "case") return goToScreen?.("case-management", 3);
    return undefined;
  };

  const quickActions = [
    {
      key: "pending",
      label: `Review pending (${pending})`,
      primary: true,
      onClick: () =>
        goToScreen("reports", 1, { initialStatusFilter: "pending" }),
      icon: (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      ),
    },
    {
      key: "map",
      label: "Safety map",
      onClick: () => goToScreen("safety-map", 5),
      icon: (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <polygon points="3 11 22 2 13 21 11 13 3 11" />
        </svg>
      ),
    },
    {
      key: "flagged",
      label: "Flagged",
      onClick: () =>
        goToScreen("reports", 1, { initialStatusFilter: "flagged" }),
      icon: (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
      ),
    },
    {
      key: "verified",
      label: "Verified",
      onClick: () =>
        goToScreen("reports", 1, { initialStatusFilter: "verified" }),
      icon: (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
      ),
    },
    {
      key: "cases",
      label: "Cases",
      onClick: () => goToScreen("case-management", 3),
      icon: (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect x="2" y="7" width="20" height="14" rx="2" />
          <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
        </svg>
      ),
    },
    {
      key: "officer",
      label: "Add officer",
      hidden: !(role === "admin" || role === "supervisor"),
      onClick: () => goToScreen("users", 7),
      icon: (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <line x1="19" y1="8" x2="19" y2="14" />
          <line x1="22" y1="11" x2="16" y2="11" />
        </svg>
      ),
    },
    {
      key: "devices",
      label: "Devices",
      onClick: () => goToScreen("device-trust", 6),
      icon: (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect x="5" y="2" width="14" height="20" rx="2" />
          <path d="M12 18h.01" />
        </svg>
      ),
    },
  ].filter((action) => !action.hidden);

  if (loading) return <div className="loading-state">Loading dashboard...</div>;

  return (
    <div className="dashboard-police">
      <div className="page-header">
        <div className="page-title">
          Welcome back,{" "}
          {user ? `${user.first_name} ${user.last_name}` : "Officer"}
        </div>
        <div className="page-sub">
          {role === "officer"
            ? "Here is your assigned work and reports needing your attention."
            : "Here's what's happening in Musanze District right now."}
        </div>
      </div>

      <div className="alert-banner">
        <span className="alert-icon">!</span>
        <span>
          {role === "officer"
            ? `${pending} of your assigned reports need a decision.`
            : `${pending} reports are pending review and require verification.`}
        </span>
        <button
          type="button"
          className="alert-link"
          onClick={() =>
            goToScreen("reports", 1, {
              initialStatusFilter: role === "officer" ? "pending" : "pending",
            })
          }
        >
          {role === "officer" ? "Open My Reports" : "Review now"}
        </button>
      </div>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">
            {role === "officer" ? "Assigned reports" : "Total reports"}
          </div>
          <div className="stat-value neutral">{total}</div>
          <div className="stat-meta">{myScope ? "Your scope" : "All time"}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Last 7 days</div>
          <div className="stat-value neutral">{recent7}</div>
          <div className="stat-meta">Recent activity</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Pending review</div>
          <div className="stat-value amber">{pending}</div>
          <div className="stat-meta">Needs action</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Verified</div>
          <div className="stat-value green">{verified}</div>
          <div className="stat-meta">Verification successful</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Flagged</div>
          <div className="stat-value red">{flagged}</div>
          <div className="stat-meta">Anomalies detected</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">
            {role === "officer" ? "My open cases" : "Open cases"}
          </div>
          <div className="stat-value neutral">{openCases}</div>
          <div className="stat-meta">Case files</div>
        </div>
      </div>

      {/* Performance Chart */}
      <div className="card" style={{ marginBottom: '20px' }}>
        <div className="card-header">
          <div className="card-title">{getChartTitle(role)}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <select 
              value={selectedTimeWindow}
              onChange={(e) => setSelectedTimeWindow(Number(e.target.value))}
              style={{
                padding: '6px 12px',
                border: '1px solid #dee2e6',
                borderRadius: '4px',
                backgroundColor: '#fff',
                fontSize: '14px',
                cursor: 'pointer'
              }}
            >
              <option value={0.5}>Last 30 minutes</option>
              <option value={1}>Last 1 hour</option>
              <option value={6}>Last 6 hours</option>
              <option value={12}>Last 12 hours</option>
              <option value={24}>Last 24 hours</option>
              <option value={48}>Last 2 days</option>
              <option value={72}>Last 3 days</option>
              <option value={168}>Last 1 week</option>
              <option value={336}>Last 2 weeks</option>
              <option value={720}>Last 1 month</option>
            </select>
          </div>
        </div>
        <div style={{ padding: '20px' }}>
          <AdvancedGeographicCharts 
            data={sectorData}
            type={getChartType(role)}
            timeWindow={selectedTimeWindow}
          />
        </div>
      </div>

      <div className="main-row">
        <div className="card">
          <div className="card-header">
            <div className="card-title">Weekly volume</div>
            <span className="card-action">Last 4 weeks</span>
          </div>
          <div className="chart-wrap">
            <svg
              className="chart-svg"
              viewBox="0 0 560 140"
              preserveAspectRatio="none"
            >
              <line
                x1="0"
                y1="20"
                x2="560"
                y2="20"
                stroke="rgba(255,255,255,0.04)"
                strokeWidth="1"
              />
              <line
                x1="0"
                y1="55"
                x2="560"
                y2="55"
                stroke="rgba(255,255,255,0.04)"
                strokeWidth="1"
              />
              <line
                x1="0"
                y1="90"
                x2="560"
                y2="90"
                stroke="rgba(255,255,255,0.04)"
                strokeWidth="1"
              />

              <text className="chart-label" x="0" y="23" textAnchor="start">
                25
              </text>
              <text className="chart-label" x="0" y="58" textAnchor="start">
                15
              </text>
              <text className="chart-label" x="0" y="93" textAnchor="start">
                5
              </text>

              {chartWeeks.map((w, idx) => {
                const barWidth = 76;
                const x = 60 + idx * 120;
                const hasData = typeof w.count === "number";
                const count = hasData ? w.count : 0;
                const barHeight = hasData
                  ? Math.max(8, Math.round((count / maxWeekCount) * 91))
                  : 0;
                const y = hasData ? 115 - barHeight : 115;

                return (
                  <g key={w.label}>
                    <rect
                      className="bar-bg"
                      x={x}
                      y="20"
                      width={barWidth}
                      height="95"
                      rx="4"
                    />
                    {hasData && (
                      <rect
                        className="bar-fill"
                        x={x}
                        y={y}
                        width={barWidth}
                        height={barHeight}
                        rx="4"
                        fill="var(--db-blue)"
                        opacity={idx === 2 ? "0.85" : "0.65"}
                      />
                    )}
                    <text
                      className="chart-week"
                      x={x + barWidth / 2}
                      y="128"
                      textAnchor="middle"
                    >
                      {w.label}
                    </text>
                    <text
                      className="chart-value"
                      x={x + barWidth / 2}
                      y={hasData ? Math.max(15, y - 4) : 108}
                      textAnchor="middle"
                      style={{
                        fill: hasData ? "var(--db-blue)" : "var(--text3)",
                      }}
                    >
                      {hasData ? count : "No data"}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <div className="card-title">Credibility split</div>
            <span className="card-action">All time</span>
          </div>
          <div className="donut-wrap">
            <svg className="donut-svg" viewBox="0 0 140 140">
              <circle
                cx="70"
                cy="70"
                r="52"
                fill="none"
                stroke="rgba(255,255,255,0.06)"
                strokeWidth="14"
              />
              <circle
                cx="70"
                cy="70"
                r="52"
                fill="none"
                stroke="#E05252"
                strokeWidth="14"
                strokeDasharray={`${Math.max(1, flaggedPct * 3.26)} 999`}
                strokeDashoffset="0"
                strokeLinecap="round"
                transform="rotate(-90 70 70)"
              />
              <circle
                cx="70"
                cy="70"
                r="52"
                fill="none"
                stroke="#F0A429"
                strokeWidth="14"
                strokeDasharray={`${Math.max(1, pendingPct * 3.26)} 999`}
                strokeDashoffset={`-${Math.max(1, flaggedPct * 3.26)}`}
                strokeLinecap="round"
                transform="rotate(-90 70 70)"
              />
              <circle
                cx="70"
                cy="70"
                r="52"
                fill="none"
                stroke="#3DBE85"
                strokeWidth="14"
                strokeDasharray={`${Math.max(1, verifiedPct * 3.26)} 999`}
                strokeDashoffset={`-${Math.max(1, (flaggedPct + pendingPct) * 3.26)}`}
                strokeLinecap="round"
                transform="rotate(-90 70 70)"
              />
              <text
                x="70"
                y="65"
                textAnchor="middle"
                className="donut-center-main"
              >
                {credibilityTotal ? `${verifiedPct}%` : "0%"}
              </text>
              <text
                x="70"
                y="80"
                textAnchor="middle"
                className="donut-center-sub"
              >
                verified
              </text>
            </svg>

            <div className="donut-legend">
              <div className="legend-row">
                <div className="legend-left">
                  <span
                    className="legend-dot"
                    style={{ background: "#3DBE85" }}
                  ></span>
                  Verified
                </div>
                <span className="legend-val">{verified}</span>
              </div>
              <div className="legend-row">
                <div className="legend-left">
                  <span
                    className="legend-dot"
                    style={{ background: "#F0A429" }}
                  ></span>
                  Pending
                </div>
                <span className="legend-val">{pending}</span>
              </div>
              <div className="legend-row">
                <div className="legend-left">
                  <span
                    className="legend-dot"
                    style={{ background: "#E05252" }}
                  ></span>
                  Flagged
                </div>
                <span className="legend-val">{flagged}</span>
              </div>
            </div>

            <div className="trust-row">
              <div className="trust-label">Avg trust score</div>
              <div className="trust-bar-bg">
                <div
                  className="trust-bar-fill"
                  style={{
                    width: `${
                      avgTrustScore !== null
                        ? Math.max(0, Math.min(100, Math.round(avgTrustScore)))
                        : 0
                    }%`,
                  }}
                ></div>
              </div>
              <div className="trust-score">
                {avgTrustScore !== null
                  ? `${Math.round(avgTrustScore)} / 100`
                  : "0 / 100"}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="main-row">
        <div className="card">
          <div className="card-header" style={{ paddingBottom: 0 }}>
            <div className="card-title">Recent reports</div>
            <button
              type="button"
              className="card-action card-action-btn"
              onClick={() => goToScreen("reports", 1)}
            >
              View all
            </button>
          </div>
          <div className="table-wrap">
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
                  const score = Math.max(
                    0,
                    Math.min(100, Number(r.trust_score || 0)),
                  );
                  const status = (
                    r.status ||
                    r.verification_status ||
                    r.rule_status ||
                    ""
                  ).toLowerCase();
                  return (
                    <tr key={r.report_id}>
                      <td className="id">
                        {r.report_number ||
                          `RPT-${String(r.report_id).slice(-4)}`}
                      </td>
                      <td className="type">
                        {r.incident_type_name || "Unknown type"}
                      </td>
                      <td>{r.village_name || "Unknown location"}</td>
                      <td>
                        <div className="trust-mini">
                          <div className="mini-bar">
                            <div
                              className="mini-fill"
                              style={{ width: `${score}%` }}
                            ></div>
                          </div>
                          <span className="mini-score">
                            {Math.round(score)}
                          </span>
                        </div>
                      </td>
                      <td>
                        <span className={`badge ${statusBadgeClass(status)}`}>
                          {statusLabel(status)}
                        </span>
                      </td>
                      <td>{formatRelativeTime(r.reported_at)}</td>
                      <td>
                        <button
                          type="button"
                          className="view-btn"
                          onClick={() => onOpenReport?.(r.report_id)}
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {!recentReports.length && (
                  <tr>
                    <td colSpan={7} className="dashboard-empty-cell">
                      No reports yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <div className="card-title">Top hotspots</div>
            <button
              type="button"
              className="card-action card-action-btn"
              onClick={() => goToScreen("safety-map", 4)}
            >
              Full view
            </button>
          </div>
          <div className="hotspot-body">
            {(topHotspots || []).map((h) => (
              <div className="hotspot-item" key={h.hotspot_id}>
                <div>
                  <div className="hs-name">{h.area_name || "Unknown area"}</div>
                  <div className="hs-sub">
                    Musanze · {h.incident_type_name || "Mixed"}
                  </div>
                </div>
                <span
                  className={`hs-count ${Number(h.incident_count || 0) < 10 ? "amber" : ""}`}
                >
                  {h.incident_count || 0} reports
                </span>
              </div>
            ))}
            {!topHotspots.length && (
              <div className="dashboard-empty">No hotspot data yet.</div>
            )}
          </div>
        </div>
      </div>

      <div className="bottom-row">
        <div className="card">
          <div className="card-header">
            <div className="card-title">Recent activity</div>
          </div>
          <div className="activity-list">
            {(stats?.recent_activity || []).map((a, i) => {
              const entityType = (a.entity_type || "").toLowerCase();
              const isClickable =
                !!a.entity_id &&
                (entityType === "report" || entityType === "case");
              const text =
                a.text ||
                `${a.action_type || "Activity"}${a.entity_type ? ` on ${a.entity_type}` : ""}`;
              return (
                <div
                  key={`${a.entity_id || "act"}-${i}`}
                  className="activity-item"
                  onClick={() => isClickable && openActivityTarget(a)}
                  style={{ cursor: isClickable ? "pointer" : "default" }}
                >
                  <span className="act-dot"></span>
                  <div className="act-text">{text}</div>
                  <span className="act-time">
                    {formatRelativeTime(a.created_at)}
                  </span>
                </div>
              );
            })}
            {!(stats?.recent_activity || []).length && (
              <div className="dashboard-empty">No recent activity.</div>
            )}
          </div>
        </div>

        <div className="right-col">
          <div className="card">
            <div className="card-header">
              <div className="card-title">Quick actions</div>
            </div>
            <div className="qa-grid">
              {quickActions.map((action) => (
                <button
                  key={action.key}
                  className={`qa-btn ${action.primary ? "primary" : ""}`}
                  onClick={action.onClick}
                >
                  {action.icon}
                  {action.label}
                </button>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <div className="card-title">System status</div>
            </div>
            <div className="status-list">
              {(stats?.system_status || []).map((s, i) => {
                const level = (s.level || "").toLowerCase();
                return (
                  <div className="status-row" key={`${s.name}-${i}`}>
                    <span className="status-name">
                      {simplifySystemStatusName(s.name)}
                    </span>
                    <span className="status-val">
                      <span
                        className={`s-dot ${level === "ok" ? "s-online" : level === "warn" ? "s-nodata" : "s-offline"}`}
                      ></span>
                      <span
                        className={`s-label ${level === "ok" ? "online" : level === "warn" ? "nodata" : "offline"}`}
                      >
                        {s.status || "Unknown"}
                      </span>
                    </span>
                  </div>
                );
              })}
              {!(stats?.system_status || []).length && (
                <div className="dashboard-empty">No status data available.</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
