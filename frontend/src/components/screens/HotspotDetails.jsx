import React, { useEffect, useState } from 'react';
import api from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { canDeployHotspotUnits } from "../../utils/roleMapping";
import HotspotDeployControls from "../HotspotDeployControls";

// Strip Cloudinary transformation params to get raw upload URL
const stripCloudinaryTransforms = (url) => {
  if (!url || !url.includes('res.cloudinary.com')) return url;
  return url.replace(
    /(\/image\/upload\/)([^/]+\/)*?(v\d+\/|uploads\/)/,
    (_, prefix, _transforms, versionOrUploads) => `${prefix}${versionOrUploads}`
  );
};

const INCIDENT_COLORS = [
  "#3b82f6", "#ef4444", "#f59e0b", "#10b981", "#8b5cf6",
  "#ec4899", "#06b6d4", "#f97316", "#6366f1", "#14b8a6",
  "#e11d48", "#84cc16", "#a855f7", "#0ea5e9", "#d946ef",
];
const getTypeColor = (name, index = 0) => {
  if (!name) return "#6b7280";
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return INCIDENT_COLORS[Math.abs(hash) % INCIDENT_COLORS.length];
};

const HotspotDetails = ({ hotspotId, goToScreen, wsRefreshKey }) => {
  const { user: me } = useAuth();
  const canDeploy = canDeployHotspotUnits(me?.role);
  const [hotspot, setHotspot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [currentEvidenceIndex, setCurrentEvidenceIndex] = useState(0);
  const [relatedReports, setRelatedReports] = useState([]);
  const [reportsLoading, setReportsLoading] = useState(true);
  const [imgErrors, setImgErrors] = useState({});
  const [expandedAdvisory, setExpandedAdvisory] = useState(false);
  const [assignmentUnits, setAssignmentUnits] = useState([]);

  useEffect(() => {
    api
      .get('/api/v1/special-assignment-units/')
      .then((res) => setAssignmentUnits(Array.isArray(res) ? res : []))
      .catch(() => setAssignmentUnits([]));
  }, []);

  const reloadHotspot = async () => {
    if (!hotspotId) return;
    try {
      const res = await api.get(`/api/v1/hotspots/?hotspot_ids=${hotspotId}&for_map=true`);
      const list = Array.isArray(res) ? res : [];
      const found = list.find((h) => h.hotspot_id == hotspotId);
      if (found) setHotspot(found);
    } catch {
      /* keep existing data */
    }
  };

  useEffect(() => {
    const loadHotspotDetails = async () => {
      try {
        setLoading(true);
        setError(null);

        // Phase 1: Fast load with for_map=true (skips LLM generation)
        const fastResponse = await api.get(`/api/v1/hotspots/?hotspot_ids=${hotspotId}&for_map=true`);
        const fastHotspots = Array.isArray(fastResponse) ? fastResponse : [];
        const foundHotspot = fastHotspots.find(h => h.hotspot_id == hotspotId);

        if (foundHotspot) {
          // Show data immediately
          setHotspot(foundHotspot);
          setImgErrors({});
          setCurrentEvidenceIndex(0);

          if (foundHotspot.incident_points?.length > 0) {
            setRelatedReports(foundHotspot.incident_points);
          } else {
            try {
              const lat = foundHotspot?.center_lat || foundHotspot?.lat;
              const lng = foundHotspot?.center_long || foundHotspot?.lng;
              const radius = foundHotspot?.radius_meters || 500;
              const reportsResponse = await api.get(`/api/v1/reports/?limit=50&lat=${lat}&lng=${lng}&radius=${radius}`);
              const reports = Array.isArray(reportsResponse) ? reportsResponse : reportsResponse?.items || [];
              setRelatedReports(reports);
            } catch (_e) {
              setRelatedReports([]);
            }
          }

          setLoading(false);
          setReportsLoading(false);

          // Phase 2: Background enrichment — fetch LLM briefing + evidence
          const hasBriefing = foundHotspot.prediction?.narrative || foundHotspot.prediction?.recommendation;
          const hasEvidence = foundHotspot.evidence_files?.length > 0;
          if (!hasBriefing || !hasEvidence) {
            try {
              const fullResponse = await api.get(`/api/v1/hotspots/?hotspot_ids=${hotspotId}`);
              const fullHotspots = Array.isArray(fullResponse) ? fullResponse : [];
              const enriched = fullHotspots.find(h => h.hotspot_id == hotspotId);
              if (enriched) {
                setHotspot(enriched);
                if (enriched.incident_points?.length > 0) {
                  setRelatedReports(enriched.incident_points);
                }
              }
            } catch (_e) { /* fast data is already displayed */ }

            // Try public endpoint for evidence/citizen advisory
            if (!hasEvidence) {
              try {
                const publicResponse = await api.get(`/api/v1/public/hotspots/${hotspotId}`);
                if (publicResponse?.evidence_files?.length > 0) {
                  setHotspot(prev => ({ ...prev, evidence_files: publicResponse.evidence_files }));
                }
              } catch (_e) { /* continue with existing data */ }
            }
          }
          return; // skip the finally block's setLoading
        } else {
          setError(`Hotspot #${hotspotId} not found`);
          setRelatedReports([]);
        }
      } catch (_e) {
        setError('Failed to load hotspot details');
        setRelatedReports([]);
      } finally {
        setLoading(false);
        setReportsLoading(false);
      }
    };

    if (hotspotId) {
      loadHotspotDetails();
    } else {
      setLoading(false);
      setReportsLoading(false);
    }
  }, [hotspotId, wsRefreshKey]);

  const getRiskMeta = (level) => {
    switch (level) {
      case 'critical': return { color: '#dc2626', bg: 'rgba(220,38,38,0.1)', label: 'CRITICAL', icon: '!!' };
      case 'high': return { color: '#ef4444', bg: 'rgba(239,68,68,0.1)', label: 'HIGH', icon: '!' };
      case 'medium': return { color: '#f59e0b', bg: 'rgba(245,158,11,0.1)', label: 'MEDIUM', icon: '~' };
      case 'low': return { color: '#10b981', bg: 'rgba(16,185,129,0.1)', label: 'LOW', icon: '-' };
      default: return { color: '#6b7280', bg: 'rgba(107,114,128,0.1)', label: 'UNKNOWN', icon: '?' };
    }
  };

  const getFormationStage = (h) => {
    const count = Number(h?.incident_count || 0);
    if (count >= 8) return { label: "Intense", color: "#dc2626" };
    if (count >= 4) return { label: "Active", color: "#f59e0b" };
    return { label: "Emerging", color: "#10b981" };
  };

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "40vh" }}>
        <div style={{ textAlign: "center", color: "var(--muted)" }}>
          <div style={{ width: 32, height: 32, border: "3px solid var(--border)", borderTopColor: "var(--accent)", borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto 12px" }} />
          Loading hotspot details...
        </div>
      </div>
    );
  }

  if (error || !hotspot) {
    return (
      <div className="card" style={{ padding: 40, textAlign: "center" }}>
        <div style={{ fontSize: 14, color: "var(--danger)", marginBottom: 12 }}>{error || 'Hotspot not found'}</div>
        {goToScreen && (
          <button className="btn btn-outline btn-sm" onClick={() => goToScreen("safety-map")}>
            Back to Map
          </button>
        )}
      </div>
    );
  }

  const risk = getRiskMeta(hotspot.risk_level);
  const stage = getFormationStage(hotspot);
  const incidentMix = hotspot.incident_mix || {};
  const mixEntries = Object.entries(incidentMix).sort((a, b) => b[1] - a[1]);
  const totalMixCount = mixEntries.reduce((sum, [, c]) => sum + c, 0) || hotspot.incident_count || 0;
  const narrative = hotspot.prediction?.narrative || hotspot.llm_narrative;
  const recommendation = hotspot.prediction?.recommendation || hotspot.llm_recommendation;
  const policeAdvisory = narrative || recommendation;
  const evidenceFiles = hotspot.evidence_files || [];

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto" }}>
      {/* ── Breadcrumb ── */}
      {goToScreen && (
        <div style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--muted)" }}>
          <span style={{ cursor: "pointer", color: "var(--accent)" }} onClick={() => goToScreen("safety-map")}>
            Safety Map
          </span>
          <span>/</span>
          <span>Hotspot #{hotspotId}</span>
        </div>
      )}

      {/* ── Header card ── */}
      <div className="card" style={{ marginBottom: 14, overflow: "hidden" }}>
        <div style={{
          padding: "18px 20px",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          flexWrap: "wrap", gap: 12,
          borderBottom: `3px solid ${risk.color}`,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{
              width: 44, height: 44, borderRadius: 10,
              background: risk.bg, border: `2px solid ${risk.color}`,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 18, fontWeight: 800, color: risk.color,
            }}>
              {risk.icon}
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "var(--text)" }}>
                {hotspot.area_label || `Hotspot #${hotspotId}`}
              </h2>
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
                {hotspot.incident_type_name || "Mixed"} cluster
                {hotspot.detected_at && ` · Detected ${new Date(hotspot.detected_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`}
              </div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            {/* Risk badge */}
            <span style={{
              padding: "5px 14px", borderRadius: 20, fontSize: 11, fontWeight: 700,
              background: risk.bg, color: risk.color, border: `1px solid ${risk.color}`,
              textTransform: "uppercase", letterSpacing: "0.05em",
            }}>
              {risk.label} Risk
            </span>
            {/* Stage badge */}
            <span style={{
              padding: "5px 14px", borderRadius: 20, fontSize: 11, fontWeight: 600,
              background: `${stage.color}15`, color: stage.color, border: `1px solid ${stage.color}40`,
            }}>
              {stage.label}
            </span>
            {hotspot.lifecycle_state && hotspot.lifecycle_state !== stage.label.toLowerCase() && (
              <span style={{
                padding: "5px 14px", borderRadius: 20, fontSize: 11, fontWeight: 600,
                background: "var(--c-accent-dim)", color: "var(--accent)",
                textTransform: "capitalize",
              }}>
                {hotspot.lifecycle_state}
              </span>
            )}
            {hotspot.trend_direction && hotspot.trend_direction !== "stable" && (
              <span style={{
                padding: "5px 10px", borderRadius: 20, fontSize: 11, fontWeight: 700,
                color: hotspot.trend_direction === "rising" ? "var(--danger)" : "var(--success)",
              }}>
                {hotspot.trend_direction === "rising" ? "Trend Rising" : "Trend Falling"}
              </span>
            )}
          </div>
        </div>

        {/* ── Quick stats row ── */}
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
          gap: 0, borderBottom: "1px solid var(--border)",
        }}>
          {[
            { label: "Incidents", value: hotspot.incident_count || 0, color: "var(--accent)" },
            { label: "Radius", value: `${Math.round(hotspot.radius_meters || 0)}m`, color: "var(--success)" },
            { label: "Trust Score", value: hotspot.avg_trust_score ? `${Math.round(Number(hotspot.avg_trust_score))}%` : "—", color: "#8b5cf6" },
            { label: "Hotspot Score", value: hotspot.hotspot_score ? Math.round(Number(hotspot.hotspot_score)) : "—", color: "#f59e0b" },
            { label: "Time Window", value: hotspot.time_window_hours ? `${hotspot.time_window_hours}h` : "—", color: "var(--muted)" },
          ].map((s, i) => (
            <div key={i} style={{
              padding: "14px 16px", textAlign: "center",
              borderRight: "1px solid var(--border)",
            }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: s.color, lineHeight: 1.2 }}>{s.value}</div>
              <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>{s.label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Two-column layout ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>

        {/* ── Left: Incident Breakdown ── */}
        <div className="card" style={{ overflow: "hidden" }}>
          <div className="card-header" style={{ padding: "12px 16px" }}>
            <div className="card-title" style={{ fontSize: 13 }}>Incident Breakdown</div>
          </div>
          <div style={{ padding: 16 }}>
            {mixEntries.length > 0 ? (
              <>
                {/* Bar chart */}
                <div style={{ marginBottom: 16 }}>
                  {mixEntries.map(([name, count], i) => {
                    const pct = totalMixCount > 0 ? (count / totalMixCount) * 100 : 0;
                    const color = getTypeColor(name, i);
                    return (
                      <div key={name} style={{ marginBottom: 10 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 500, color: "var(--text)" }}>
                            <div style={{ width: 8, height: 8, borderRadius: "50%", background: color }} />
                            {name}
                          </div>
                          <span style={{ fontSize: 11, color: "var(--muted)" }}>{count} ({Math.round(pct)}%)</span>
                        </div>
                        <div style={{ height: 6, borderRadius: 3, background: "var(--border)", overflow: "hidden" }}>
                          <div style={{ width: `${pct}%`, height: "100%", borderRadius: 3, background: color, transition: "width 0.5s ease" }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            ) : (
              <div style={{ textAlign: "center", padding: 20, color: "var(--muted)", fontSize: 12 }}>
                {hotspot.incident_type_name ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: "center" }}>
                    <div style={{ width: 10, height: 10, borderRadius: "50%", background: getTypeColor(hotspot.incident_type_name) }} />
                    <span style={{ fontWeight: 600, color: "var(--text)" }}>{hotspot.incident_type_name}</span>
                    <span>({hotspot.incident_count || 0} incidents)</span>
                  </div>
                ) : "No incident type data available"}
              </div>
            )}

            {/* Additional metrics */}
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              {hotspot.severity_score != null && (
                <div style={{ padding: "8px 10px", borderRadius: 8, background: "var(--surface2, rgba(0,0,0,0.03))" }}>
                  <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 2, textTransform: "uppercase" }}>Severity</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text)" }}>{Number(hotspot.severity_score).toFixed(1)}<span style={{ fontSize: 11, color: "var(--muted)" }}>/10</span></div>
                </div>
              )}
              {hotspot.temporal_intensity != null && (
                <div style={{ padding: "8px 10px", borderRadius: 8, background: "var(--surface2, rgba(0,0,0,0.03))" }}>
                  <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 2, textTransform: "uppercase" }}>Incident Rate</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text)" }}>{Number(hotspot.temporal_intensity).toFixed(1)}<span style={{ fontSize: 11, color: "var(--muted)" }}>/hr</span></div>
                </div>
              )}
              {hotspot.crime_group && (
                <div style={{ padding: "8px 10px", borderRadius: 8, background: "var(--surface2, rgba(0,0,0,0.03))" }}>
                  <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 2, textTransform: "uppercase" }}>Crime Group</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", textTransform: "capitalize" }}>{hotspot.crime_group}</div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Right: Location & Navigation ── */}
        <div className="card" style={{ overflow: "hidden" }}>
          <div className="card-header" style={{ padding: "12px 16px" }}>
            <div className="card-title" style={{ fontSize: 13 }}>Location & Details</div>
          </div>
          <div style={{ padding: 16 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {[
                { label: "Coordinates", value: `${Number(hotspot.center_lat || 0).toFixed(5)}, ${Number(hotspot.center_long || 0).toFixed(5)}` },
                { label: "Coverage Radius", value: `${Math.round(hotspot.radius_meters || 0)} meters` },
                { label: "Incident Types", value: mixEntries.length > 1 ? mixEntries.map(([name, count]) => `${name} (${count})`).join(", ") : (hotspot.incident_type_name || "Mixed") },
                { label: "Detected", value: hotspot.detected_at ? new Date(hotspot.detected_at).toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "Unknown" },
                { label: "Time Window", value: hotspot.time_window_hours ? `${hotspot.time_window_hours} hours` : "Unknown" },
              ].map((item, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
                  <span style={{ fontSize: 12, color: "var(--muted)" }}>{item.label}</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text)" }}>{item.value}</span>
                </div>
              ))}
            </div>

            {/* Navigation buttons */}
            <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
              <button
                onClick={() => {
                  const lat = Number(hotspot.center_lat || 0);
                  const lng = Number(hotspot.center_long || 0);
                  window.open(`https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}&travelmode=driving`, '_blank');
                }}
                style={{
                  flex: 1, padding: "10px 14px", fontSize: 12, fontWeight: 600,
                  background: "var(--accent)", color: "#fff", border: "none",
                  borderRadius: 8, cursor: "pointer", display: "flex",
                  alignItems: "center", justifyContent: "center", gap: 6,
                }}
              >
                Navigate
              </button>
              {goToScreen && (
                <button
                  onClick={() => goToScreen("safety-map", 0, { focusHotspotId: hotspot.hotspot_id })}
                  style={{
                    flex: 1, padding: "10px 14px", fontSize: 12, fontWeight: 600,
                    background: "var(--surface2, rgba(0,0,0,0.05))", color: "var(--text)",
                    border: "1px solid var(--border)", borderRadius: 8, cursor: "pointer",
                    display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
                  }}
                >
                  View on Map
                </button>
              )}
            </div>

            {/* Risk assessment compact */}
            <div style={{
              marginTop: 16, padding: 14, borderRadius: 10,
              background: risk.bg, border: `1px solid ${risk.color}30`,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                <div style={{
                  width: 32, height: 32, borderRadius: 8, background: risk.color,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  color: "#fff", fontSize: 14, fontWeight: 800,
                }}>
                  {risk.icon}
                </div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: risk.color }}>{risk.label} RISK</div>
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>
                    {hotspot.risk_level === 'high' || hotspot.risk_level === 'critical' ? 'Priority response needed' :
                     hotspot.risk_level === 'medium' ? 'Active monitoring required' : 'Further observation needed'}
                  </div>
                </div>
              </div>
              {hotspot.hotspot_score != null && (
                <div style={{ display: "flex", gap: 16, marginTop: 8, fontSize: 11, color: "var(--muted)" }}>
                  <span>Score: <strong style={{ color: "var(--text)" }}>{Math.round(Number(hotspot.hotspot_score))}/100</strong></span>
                  {hotspot.avg_trust_score != null && (
                    <span>Trust: <strong style={{ color: "var(--text)" }}>{Math.round(Number(hotspot.avg_trust_score))}%</strong></span>
                  )}
                </div>
              )}
            </div>

          </div>
        </div>
      </div>

      {/* ── Unit deployment ── */}
      <div className="card" style={{ marginTop: 14, overflow: 'hidden' }}>
        <div className="card-header" style={{ padding: '12px 16px' }}>
          <div className="card-title" style={{ fontSize: 13 }}>Unit deployment</div>
        </div>
        <div style={{ padding: 16 }}>
          <HotspotDeployControls
            hotspot={hotspot}
            assignmentUnits={assignmentUnits}
            canDeploy={canDeploy}
            onDeployed={reloadHotspot}
          />
        </div>
      </div>

      {/* ── Operational Briefing (full-width, between columns and table) ── */}
      {policeAdvisory && (
        <div className="card" style={{ marginTop: 14, overflow: "hidden" }}>
          <div className="card-header" style={{ padding: "12px 16px" }}>
            <div className="card-title" style={{ fontSize: 13 }}>Operational Briefing</div>
          </div>
          <div style={{ padding: 16 }}>
            {narrative && (
              <div style={{
                fontSize: 12, lineHeight: 1.7, color: "var(--text)", marginBottom: recommendation ? 12 : 0,
                maxHeight: expandedAdvisory ? "none" : 100, overflow: "hidden", position: "relative",
              }}>
                {narrative}
                {!expandedAdvisory && narrative.length > 250 && (
                  <div style={{
                    position: "absolute", bottom: 0, left: 0, right: 0, height: 30,
                    background: "linear-gradient(transparent, var(--surface))",
                  }} />
                )}
              </div>
            )}
            {recommendation && (
              <div style={{
                fontSize: 12, lineHeight: 1.6, color: "var(--text)",
                padding: "12px 14px", borderRadius: 8, borderLeft: `3px solid ${risk.color}`,
                background: "var(--surface2, rgba(0,0,0,0.03))",
                maxHeight: expandedAdvisory ? "none" : 80, overflow: "hidden", position: "relative",
              }}>
                <div style={{ fontSize: 10, fontWeight: 600, color: risk.color, marginBottom: 4, textTransform: "uppercase" }}>Recommendation</div>
                {recommendation}
                {!expandedAdvisory && recommendation.length > 200 && (
                  <div style={{
                    position: "absolute", bottom: 0, left: 0, right: 0, height: 30,
                    background: "linear-gradient(transparent, var(--surface))",
                  }} />
                )}
              </div>
            )}
            {(narrative?.length > 250 || recommendation?.length > 200) && (
              <button
                onClick={() => setExpandedAdvisory(!expandedAdvisory)}
                style={{
                  marginTop: 8, background: "none", border: "none",
                  color: "var(--accent)", fontSize: 11, fontWeight: 600,
                  cursor: "pointer", padding: 0,
                }}
              >
                {expandedAdvisory ? "Show less" : "Read full briefing"}
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── Related Reports ── */}
      <div className="card" style={{ marginTop: 14, overflow: "hidden" }}>
        <div className="card-header" style={{ padding: "12px 16px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div className="card-title" style={{ fontSize: 13 }}>
            Related Reports
            <span style={{ fontSize: 11, fontWeight: 400, color: "var(--muted)", marginLeft: 6 }}>({relatedReports.length})</span>
          </div>
        </div>
        <div style={{ padding: 0 }}>
          {reportsLoading ? (
            <div style={{ textAlign: "center", padding: 24, color: "var(--muted)", fontSize: 12 }}>Loading reports...</div>
          ) : relatedReports.length === 0 ? (
            <div style={{ textAlign: "center", padding: 24, color: "var(--muted)", fontSize: 12 }}>No related reports found</div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "2px solid var(--border)" }}>
                    {["Type", "Location", "Date", "Trust", ""].map((h, i) => (
                      <th key={i} style={{
                        textAlign: "left", padding: "10px 14px", fontSize: 10,
                        color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em",
                        fontWeight: 600, whiteSpace: "nowrap",
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {relatedReports.map((report, index) => {
                    const trust = Number(report.trust_score || 0);
                    const trustColor = trust >= 80 ? "var(--success)" : trust >= 60 ? "var(--warning, #f59e0b)" : "var(--danger)";
                    const loc = [report.village_name, report.cell_name, report.sector_name].filter(Boolean).join(", ");
                    return (
                      <tr
                        key={report.report_id || index}
                        style={{
                          borderBottom: "1px solid var(--border)",
                          cursor: goToScreen ? "pointer" : "default",
                          transition: "background 0.15s",
                        }}
                        onClick={() => goToScreen && goToScreen("report-details", 0, { reportId: report.report_id })}
                        onMouseEnter={(e) => e.currentTarget.style.background = "var(--surface2, rgba(0,0,0,0.03))"}
                        onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                      >
                        <td style={{ padding: "10px 14px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <div style={{ width: 8, height: 8, borderRadius: "50%", background: getTypeColor(report.incident_type_name), flexShrink: 0 }} />
                            <div>
                              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)" }}>{report.incident_type_name || "Unknown"}</div>
                              <div style={{ fontSize: 10, color: "var(--muted)", fontFamily: "monospace" }}>#{String(report.report_id || "").slice(-8)}</div>
                            </div>
                          </div>
                        </td>
                        <td style={{ padding: "10px 14px", fontSize: 12, color: "var(--text)", maxWidth: 250 }}>
                          {loc || (report.latitude ? `${Number(report.latitude).toFixed(4)}, ${Number(report.longitude).toFixed(4)}` : "—")}
                        </td>
                        <td style={{ padding: "10px 14px", fontSize: 12, color: "var(--muted)", whiteSpace: "nowrap" }}>
                          {report.reported_at ? new Date(report.reported_at).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}
                        </td>
                        <td style={{ padding: "10px 14px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <div style={{
                              width: 32, height: 4, borderRadius: 2, background: "var(--border)", overflow: "hidden",
                            }}>
                              <div style={{ width: `${trust}%`, height: "100%", background: trustColor, borderRadius: 2 }} />
                            </div>
                            <span style={{ fontSize: 11, fontWeight: 600, color: trustColor }}>{trust}%</span>
                          </div>
                        </td>
                        <td style={{ padding: "10px 14px", fontSize: 11, color: "var(--accent)" }}>
                          {goToScreen && "View"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ── Evidence ── */}
      {evidenceFiles.length > 0 && (
        <div className="card" style={{ marginTop: 14, overflow: "hidden" }}>
          <div className="card-header" style={{ padding: "12px 16px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div className="card-title" style={{ fontSize: 13 }}>
              Evidence
              <span style={{ fontSize: 11, fontWeight: 400, color: "var(--muted)", marginLeft: 6 }}>({evidenceFiles.length})</span>
            </div>
            {evidenceFiles.length > 1 && (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <button
                  onClick={() => setCurrentEvidenceIndex(i => i > 0 ? i - 1 : evidenceFiles.length - 1)}
                  style={{
                    width: 28, height: 28, borderRadius: 6, border: "1px solid var(--border)",
                    background: "var(--surface)", color: "var(--text)", cursor: "pointer",
                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14,
                  }}
                >&#8249;</button>
                <span style={{ fontSize: 11, color: "var(--muted)" }}>{currentEvidenceIndex + 1} / {evidenceFiles.length}</span>
                <button
                  onClick={() => setCurrentEvidenceIndex(i => i < evidenceFiles.length - 1 ? i + 1 : 0)}
                  style={{
                    width: 28, height: 28, borderRadius: 6, border: "1px solid var(--border)",
                    background: "var(--surface)", color: "var(--text)", cursor: "pointer",
                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14,
                  }}
                >&#8250;</button>
              </div>
            )}
          </div>
          <div style={{ padding: 16 }}>
            {(() => {
              const ev = evidenceFiles[currentEvidenceIndex];
              if (!ev) return null;
              const isPhoto = ev.file_type === 'photo';
              return (
                <div>
                  {/* Media tags */}
                  <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
                    <span style={{
                      padding: "3px 10px", borderRadius: 12, fontSize: 10, fontWeight: 600,
                      background: isPhoto ? "rgba(59,130,246,0.1)" : "rgba(245,158,11,0.1)",
                      color: isPhoto ? "#3b82f6" : "#f59e0b",
                    }}>{isPhoto ? "PHOTO" : "VIDEO"}</span>
                    {ev.quality_label && (
                      <span style={{
                        padding: "3px 10px", borderRadius: 12, fontSize: 10, fontWeight: 600,
                        background: ev.quality_label === 'good' ? "rgba(16,185,129,0.1)" : "rgba(245,158,11,0.1)",
                        color: ev.quality_label === 'good' ? "#10b981" : "#f59e0b",
                        textTransform: "uppercase",
                      }}>{ev.quality_label}</span>
                    )}
                    {ev.is_live_capture && (
                      <span style={{
                        padding: "3px 10px", borderRadius: 12, fontSize: 10, fontWeight: 600,
                        background: "rgba(239,68,68,0.1)", color: "#ef4444",
                      }}>LIVE CAPTURE</span>
                    )}
                    {ev.uploaded_at && (
                      <span style={{ fontSize: 10, color: "var(--muted)", padding: "3px 0" }}>
                        {new Date(ev.uploaded_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                      </span>
                    )}
                  </div>

                  {/* Media display */}
                  <div style={{
                    background: "#000", borderRadius: 10, overflow: "hidden",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    minHeight: 200, maxHeight: 400,
                  }}>
                    {isPhoto ? (() => {
                      const idx = currentEvidenceIndex;
                      const origUrl = ev.file_url || ev.cloudinary_url;
                      const rawUrl = stripCloudinaryTransforms(origUrl);
                      const errState = imgErrors[idx];

                      if (errState === 'failed') {
                        return (
                          <div style={{ padding: 24, textAlign: "center" }}>
                            <div style={{ color: "#999", fontSize: 12, marginBottom: 8 }}>Preview unavailable</div>
                            <a href={origUrl} target="_blank" rel="noopener noreferrer"
                              style={{ color: "#3b82f6", fontSize: 12 }}>Open in new tab</a>
                          </div>
                        );
                      }

                      const src = errState === 'retry' && rawUrl !== origUrl ? rawUrl : origUrl;
                      return (
                        <img
                          key={`${idx}-${errState || 'orig'}`}
                          src={src}
                          alt="Evidence"
                          crossOrigin="anonymous"
                          style={{ maxWidth: "100%", maxHeight: 400, objectFit: "contain" }}
                          onError={() => {
                            setImgErrors(prev => {
                              const cur = prev[idx];
                              if (!cur) {
                                if (rawUrl !== origUrl) return { ...prev, [idx]: 'retry' };
                                return { ...prev, [idx]: 'failed' };
                              }
                              return { ...prev, [idx]: 'failed' };
                            });
                          }}
                        />
                      );
                    })() : (
                      <video controls style={{ width: "100%", maxHeight: 400, objectFit: "contain" }}>
                        <source src={ev.file_url || ev.cloudinary_url} type="video/mp4" />
                      </video>
                    )}
                  </div>
                </div>
              );
            })()}
          </div>
        </div>
      )}

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @media (max-width: 768px) {
          div[style*="grid-template-columns: 1fr 1fr"] {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
};

export default HotspotDetails;
