import React, { useEffect, useMemo, useState } from 'react';
import api, { cacheBust } from '../api/client';
import HotspotDeployControls from './HotspotDeployControls';

const HOTSPOT_UNIT_LABELS = {
  AFU: "Anti-Fraud Unit (AFU)",
  CPU: "Community Policing Unit (CPU)",
  COUNTER_TERROR: "Counter Terror Unit",
  DEU: "Drug Enforcement Unit (DEU)",
  FIRE_RESCUE: "Fire & Rescue",
  GENERAL_PATROL: "General Patrol",
  ISU: "Intelligence & Surveillance Unit (ISU)",
  K9: "K9 / Canine Unit",
  QUICK_RESPONSE: "Quick Response Team",
  RRU: "Rapid Response Unit (RRU)",
  TRAFFIC: "Traffic Police",
  TPU: "Traffic Police Unit (TPU)",
  VPU: "Victim Protection Unit (VPU)",
};

function hotspotUnitLabel(h) {
  const pred = h.prediction || {};
  if (pred.recommended_unit_name) return pred.recommended_unit_name;
  const units = pred.recommended_units;
  if (Array.isArray(units) && units.length > 0) {
    const primary = units.find((u) => u.role === "primary") || units[0];
    if (primary?.unit_name) return primary.unit_name;
    if (primary?.unit_code && HOTSPOT_UNIT_LABELS[primary.unit_code]) {
      return HOTSPOT_UNIT_LABELS[primary.unit_code];
    }
  }
  const code = pred.recommended_unit;
  if (code && HOTSPOT_UNIT_LABELS[code]) return HOTSPOT_UNIT_LABELS[code];
  return code || "Patrol unit";
}

/** Single severity dot — coloured CSS circle, no emoji. */
function severityDot(alarm) {
  const color =
    alarm >= 75 ? '#ef4444' :
    alarm >= 50 ? '#f97316' :
    alarm >= 30 ? '#eab308' :
    '#22c55e';
  return (
    <span
      style={{
        display: 'inline-block',
        width: 10,
        height: 10,
        borderRadius: '50%',
        background: color,
        flexShrink: 0,
      }}
    />
  );
}

/**
 * Compute an alarm score 0–100 from real hotspot metrics.
 *   - risk_level base
 *   - hotspot_score (backend ML score)
 *   - predicted_increase_pct (growth trend)
 *   - lifecycle_state (active vs emerging)
 *   - incident_count density
 */
function computeAlarm(h) {
  const base = { critical: 80, high: 60, medium: 35, low: 15 }[h.risk_level] || 20;
  const score = Math.min(Number(h.hotspot_score || 0) * 0.25, 15);          // max +15
  const growth = Math.min(Number(h.prediction?.predicted_increase_pct || 0) * 0.15, 10); // max +10
  const state = h.lifecycle_state === "intense" ? 12 : h.lifecycle_state === "active" ? 6 : 0;
  const density = Math.min((h.incident_count || 0) * 0.7, 8);               // max +8
  return Math.min(100, base + score + growth + state + density);
}

/** Map alarm 0–100 to a vivid colour that shifts green→yellow→orange→red. */
function alarmToColor(alarm) {
  if (alarm >= 82) return "#dc2626";   // crimson
  if (alarm >= 65) return "#ef4444";   // red
  if (alarm >= 50) return "#f97316";   // orange
  if (alarm >= 35) return "#eab308";   // amber
  if (alarm >= 20) return "#84cc16";   // lime
  return "#22c55e";                     // green
}

function alarmLabel(alarm) {
  if (alarm >= 82) return "CRITICAL ALARM";
  if (alarm >= 65) return "HIGH ALARM";
  if (alarm >= 50) return "ELEVATED";
  if (alarm >= 35) return "MODERATE";
  if (alarm >= 20) return "LOW";
  return "CALM";
}

/** Hard-cap text to at most `max` words, appending "…" if trimmed. */
function capWords(text, max) {
  if (!text) return "";
  const words = text.trim().split(/\s+/);
  if (words.length <= max) return text.trim();
  return words.slice(0, max).join(" ") + "…";
}

/** Situation brief — narrative capped at 80 words (target 50–80). */
function buildNarrative(h) {
  const pred = h.prediction || {};
  if (pred.narrative) return capWords(pred.narrative, 80);
  const area = h.area_label || "this area";
  const type = h.dominant_crime_type || h.incident_type_name || "incidents";
  const count = h.incident_count || 0;
  return `${count} verified ${type.toLowerCase()} report${count !== 1 ? "s" : ""} recorded in ${area}.`;
}

/** Deployment action — recommendation capped at 40 words (target 20–40). */
function buildAction(h, unit) {
  const pred = h.prediction || {};
  if (pred.recommendation) return capWords(pred.recommendation, 40);
  // Fallback when no LLM recommendation is available
  const area = h.area_label || "the cluster area";
  return `Deploy ${unit} to ${area}.`;
}

// Security Recommendations Component
const HotspotSecurityRecommendations = ({
  hotspots,
  assignmentUnits = [],
  canDeploy = false,
  onReload,
  timePeriod,
  customHours,
  timeWindowHours,
  detailPage = false,
}) => {
  const [actionError, setActionError] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiById, setAiById] = useState({});
  const [aiProgress, setAiProgress] = useState({ done: 0, total: 0 });

  const sorted = useMemo(() => {
    if (!hotspots || hotspots.length === 0) return [];
    return [...hotspots]
      .map((h) => ({ ...h, _alarm: computeAlarm(h) }))
      .sort((a, b) => b._alarm - a._alarm);
  }, [hotspots]);

  const allHotspotIds = useMemo(
    () => sorted.map((h) => h.hotspot_id).filter((id) => id != null),
    [sorted],
  );

  const allHotspotIdsKey = allHotspotIds.join(",");

  const hotspotById = useMemo(() => {
    const map = {};
    for (const h of sorted) {
      if (h.hotspot_id != null) map[h.hotspot_id] = h;
    }
    return map;
  }, [sorted]);

  const mergeHotspotWithAi = (h) => {
    const enriched = aiById[h.hotspot_id];
    if (!enriched?.prediction) return h;
    return {
      ...h,
      prediction: { ...(h.prediction || {}), ...enriched.prediction },
    };
  };

  const hasStoredBriefing = (pred) =>
    Boolean((pred?.narrative || "").trim() && (pred?.recommendation || "").trim());

  useEffect(() => {
    let cancelled = false;
    const AI_BATCH_SIZE = 25;

    const buildAiParams = (ids) => {
      const params = new URLSearchParams();
      params.set("for_map", "false");
      params.set("limit", String(Math.max(ids.length, 1)));
      params.set("hotspot_ids", ids.join(","));
      if (timePeriod && timePeriod !== "") {
        params.set("time_period", timePeriod);
      } else if (customHours && customHours !== "" && Number(customHours) > 0) {
        params.set("hours_back", customHours);
      }
      if (timeWindowHours) {
        params.set("time_window_hours", String(timeWindowHours));
      }
      return params;
    };

    const run = async () => {
      if (!allHotspotIds.length) {
        setAiById({});
        setAiProgress({ done: 0, total: 0 });
        return;
      }

      const merged = {};
      const needsFetch = [];
      for (const id of allHotspotIds) {
        const h = hotspotById[id];
        if (!h) continue;
        const pred = h.prediction || {};
        if (hasStoredBriefing(pred)) {
          merged[id] = h;
        } else {
          needsFetch.push(id);
        }
      }

      if (!cancelled) {
        setAiById(merged);
        setAiProgress({ done: Object.keys(merged).length, total: allHotspotIds.length });
      }

      if (!needsFetch.length) {
        setAiLoading(false);
        return;
      }

      setAiLoading(true);
      cacheBust("/api/v1/hotspots");

      for (let i = 0; i < needsFetch.length; i += AI_BATCH_SIZE) {
        if (cancelled) break;
        const chunk = needsFetch.slice(i, i + AI_BATCH_SIZE);
        try {
          const res = await api.get(
            `/api/v1/hotspots/?${buildAiParams(chunk).toString()}`,
          );
          const items = Array.isArray(res) ? res : [];
          for (const h of items) {
            if (h?.hotspot_id != null) merged[h.hotspot_id] = h;
          }
        } catch (err) {
          if (!cancelled) {
            setActionError(err?.message || "Failed to load AI recommendations for some hotspots");
          }
        }
        if (!cancelled) {
          setAiById({ ...merged });
          setAiProgress({
            done: Object.values(merged).filter((x) => hasStoredBriefing(x.prediction)).length,
            total: allHotspotIds.length,
          });
        }
      }

      if (!cancelled) setAiLoading(false);
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [allHotspotIdsKey, allHotspotIds, hotspotById, timePeriod, customHours, timeWindowHours]);

  if (sorted.length === 0) {
    if (detailPage) return null;
    return (
      <div style={{
        padding: "20px 16px", textAlign: "center",
        backgroundColor: "var(--surface)", borderRadius: "8px",
        border: "1px solid var(--border)",
      }}>
        <div style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)", marginBottom: "4px" }}>
          No active hotspots detected
        </div>
        <div style={{ fontSize: "11px", color: "var(--muted)", lineHeight: 1.5 }}>
          No active hotspot clusters match the current map filters.
          Widen the time period or check that verified incidents exist in Musanze.
        </div>
      </div>
    );
  }

  const totalIncidents = sorted.reduce((s, h) => s + (h.incident_count || 0), 0);
  const peakAlarm = sorted[0]._alarm;
  const peakColor = alarmToColor(peakAlarm);
  const singleAlarm = detailPage && sorted.length === 1 ? sorted[0]._alarm : null;
  const singleAlarmColor = singleAlarm != null ? alarmToColor(singleAlarm) : peakColor;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
      {actionError && (
        <div className="alert alert-danger" style={{ marginBottom: 4 }}>
          <span className="alert-icon">!</span>
          <div>{actionError}</div>
        </div>
      )}
      {aiLoading && (
        <div className="alert alert-info" style={{ marginBottom: 4 }}>
          <span className="alert-icon">i</span>
          <div>
            Generating AI briefings for all hotspots… {aiProgress.done}/{aiProgress.total} ready
            (saved in database after first run).
          </div>
        </div>
      )}
      {/* District situation overview — list view only */}
      {!detailPage && (
      <div style={{
        padding: "10px 12px",
        borderRadius: "8px",
        border: `1px solid ${peakColor}55`,
        backgroundColor: `${peakColor}12`,
        display: "flex", flexDirection: "column", gap: "4px",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: "12px", fontWeight: 700, color: "var(--text)" }}>
            District Security Situation
          </span>
          <span style={{
            fontSize: "9px", fontWeight: 800, letterSpacing: "0.07em",
            padding: "2px 8px", borderRadius: "99px",
            backgroundColor: peakColor, color: "#fff",
          }}>
            {alarmLabel(peakAlarm)}
          </span>
        </div>
        {/* Alarm bar */}
        <div style={{ height: "5px", borderRadius: "3px", backgroundColor: "var(--border)", overflow: "hidden" }}>
          <div style={{
            height: "100%", width: `${peakAlarm}%`,
            backgroundColor: peakColor,
            transition: "width 0.6s ease",
            borderRadius: "3px",
          }} />
        </div>
        <div style={{ fontSize: "10px", color: "var(--muted)", display: "flex", gap: "10px" }}>
          <span><strong style={{ color: "var(--text)" }}>{sorted.length}</strong> active hotspot{sorted.length !== 1 ? "s" : ""}</span>
          <span>·</span>
          <span><strong style={{ color: "var(--text)" }}>{totalIncidents}</strong> verified incidents</span>
          <span>·</span>
          <span>Alarm index: <strong style={{ color: peakColor }}>{Math.round(peakAlarm)}/100</strong></span>
        </div>
      </div>
      )}

      {/* Compact alarm strip on hotspot details */}
      {detailPage && singleAlarm != null && (
        <div style={{
          padding: "8px 12px", borderRadius: 8,
          border: `1px solid ${singleAlarmColor}55`,
          backgroundColor: `${singleAlarmColor}12`,
          display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8,
        }}>
          <span style={{ fontSize: 11, color: "var(--muted)" }}>
            Alarm index: <strong style={{ color: singleAlarmColor }}>{Math.round(singleAlarm)}/100</strong>
          </span>
          <span style={{
            fontSize: 9, fontWeight: 800, letterSpacing: "0.07em",
            padding: "2px 8px", borderRadius: 99,
            backgroundColor: singleAlarmColor, color: "#fff",
          }}>
            {alarmLabel(singleAlarm)}
          </span>
        </div>
      )}

      {/* One recommendation card per hotspot, ordered by alarm severity */}
      {sorted.map((h, idx) => {
        const alarm = h._alarm;
        const color = alarmToColor(alarm);
        const hFull = mergeHotspotWithAi(h);
        const unit = hotspotUnitLabel(hFull);
        const unitChips = Array.isArray(hFull.prediction?.recommended_units)
          ? hFull.prediction.recommended_units
          : [];
        const dot = severityDot(alarm);
        const narrative = buildNarrative(hFull);
        const action = buildAction(hFull, unit);
        const area = h.area_label || "Unknown area";
        const sectors = [...new Set(
          (h.incident_points || []).map((p) => p.sector_name).filter(Boolean)
        )].join(", ") || "—";

        return (
          <div key={h.hotspot_id || idx} style={detailPage ? {
            display: "flex", flexDirection: "column", gap: "8px",
          } : {
            borderRadius: "10px",
            border: "1px solid var(--border)",
            backgroundColor: "var(--surface)",
            overflow: "hidden",
            display: "flex",
          }}>
            {!detailPage && (
            <div style={{
              width: "4px", flexShrink: 0,
              backgroundColor: color,
            }} />
            )}

            <div style={{ flex: 1, minWidth: 0 }}>
              {!detailPage && (
              <div style={{
                display: "flex", alignItems: "center", gap: "8px",
                padding: "9px 12px",
                borderBottom: "1px solid var(--border)",
              }}>
                <span style={{ fontSize: "13px", lineHeight: 1, flexShrink: 0 }}>{dot}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: "12px", fontWeight: 700, color: "var(--text)", lineHeight: 1.2 }}>
                    {h.incident_type_name || "Incident"} · {area}
                  </div>
                  <div style={{ fontSize: "10px", color: "var(--muted)", marginTop: "1px" }}>
                    {sectors} · {h.incident_count} incident{h.incident_count !== 1 ? "s" : ""}
                    {h.radius_meters ? ` · ${Math.round(Number(h.radius_meters))} m` : ""}
                  </div>
                </div>
                <span style={{
                  fontSize: "9px", fontWeight: 800, letterSpacing: "0.06em",
                  padding: "2px 7px", borderRadius: "99px",
                  backgroundColor: color, color: "#fff", flexShrink: 0,
                }}>
                  {alarmLabel(alarm)}
                </span>
              </div>
              )}

              <div style={{ padding: detailPage ? 0 : "10px 12px", display: "flex", flexDirection: "column", gap: "8px" }}>

                {/* Classification + cluster type — compact single line, only if data exists */}
                {(h.classification || h.cluster_kind || hFull.prediction?.status) && (
                  <div style={{ display: "flex", gap: "6px", alignItems: "center", flexWrap: "wrap" }}>
                    {h.classification && (
                      <span style={{
                        fontSize: "9px", fontWeight: 700, padding: "1px 7px",
                        borderRadius: "99px", border: `1px solid ${color}66`,
                        color, textTransform: "uppercase", letterSpacing: "0.05em",
                      }}>
                        {h.classification}
                      </span>
                    )}
                    {h.cluster_kind && (
                      <span style={{ fontSize: "9px", color: "var(--muted)" }}>
                        {h.cluster_kind === "mixed_hotspot" ? "mixed cluster" : "single-type cluster"}
                      </span>
                    )}
                    {hFull.prediction?.status && (
                      <span style={{ fontSize: "9px", color: "var(--muted)", marginLeft: "auto" }}>
                        {String(hFull.prediction.status).replace(/_/g, " ")}
                      </span>
                    )}
                  </div>
                )}

                {/* Situation — narrative from LLM (hidden while loading if no cached text) */}
                {(hFull.prediction?.narrative || !aiLoading) && (
                  <div style={{
                    fontSize: "11px", color: "var(--text)", lineHeight: 1.6,
                    padding: "8px 10px", borderRadius: "6px",
                    backgroundColor: "var(--background)",
                    border: "1px solid var(--border)",
                  }}>
                    <div style={{
                      fontSize: "9px", fontWeight: 700, color: "var(--muted)",
                      letterSpacing: "0.07em", marginBottom: "4px",
                    }}>
                      SITUATION
                    </div>
                    {narrative}
                  </div>
                )}
                {aiLoading && !hFull.prediction?.narrative && (
                  <div style={{
                    fontSize: "11px", lineHeight: 1.6, padding: "8px 10px", borderRadius: "6px",
                    backgroundColor: "var(--background)", border: "1px solid var(--border)",
                  }}>
                    <div style={{ fontSize: "9px", fontWeight: 700, color: "var(--muted)", letterSpacing: "0.07em", marginBottom: "4px" }}>
                      SITUATION
                    </div>
                    <span style={{ color: "var(--muted)", fontStyle: "italic" }}>Generating AI briefing…</span>
                  </div>
                )}

                {/* Incident mix — only for mixed clusters with more than one type */}
                {h.incident_mix && Object.keys(h.incident_mix).length > 1 && (
                  <div style={{
                    display: "flex", gap: "5px", flexWrap: "wrap", alignItems: "center",
                    padding: "5px 8px", borderRadius: "6px",
                    backgroundColor: "var(--background)", border: "1px solid var(--border)",
                  }}>
                    <span style={{ fontSize: "9px", fontWeight: 700, color: "var(--muted)", letterSpacing: "0.07em", marginRight: "2px" }}>
                      MIX:
                    </span>
                    {Object.entries(h.incident_mix)
                      .sort((a, b) => b[1] - a[1])
                      .map(([type, cnt]) => (
                        <span key={type} style={{
                          fontSize: "9px", padding: "1px 5px", borderRadius: "4px",
                          backgroundColor: "var(--border)", color: "var(--text)",
                        }}>
                          {type} ({cnt})
                        </span>
                      ))}
                  </div>
                )}

                {/* Recommended action — colored left border distinguishes it from SITUATION */}
                {(hFull.prediction?.recommendation || !aiLoading) && (
                  <div style={{
                    fontSize: "11px", color: "var(--text)", lineHeight: 1.6,
                    padding: "8px 10px", borderRadius: "6px",
                    backgroundColor: "var(--background)",
                    border: "1px solid var(--border)",
                    borderLeft: `3px solid ${color}`,
                  }}>
                    <div style={{
                      fontSize: "9px", fontWeight: 700, color,
                      letterSpacing: "0.07em", marginBottom: "4px",
                    }}>
                      RECOMMENDED ACTION
                    </div>
                    {action}
                  </div>
                )}
                {aiLoading && !hFull.prediction?.recommendation && (
                  <div style={{
                    fontSize: "11px", lineHeight: 1.6, padding: "8px 10px", borderRadius: "6px",
                    backgroundColor: "var(--background)",
                    border: "1px solid var(--border)", borderLeft: `3px solid ${color}`,
                  }}>
                    <div style={{ fontSize: "9px", fontWeight: 700, color, letterSpacing: "0.07em", marginBottom: "4px" }}>
                      RECOMMENDED ACTION
                    </div>
                    <span style={{ color: "var(--muted)", fontStyle: "italic" }}>Generating AI recommendation…</span>
                  </div>
                )}

                {/* AI-recommended unit chips — only when LLM has returned units */}
                {unitChips.length > 0 && (
                  <div style={{
                    display: "flex", gap: "5px", flexWrap: "wrap", alignItems: "center",
                    padding: "5px 8px", borderRadius: "6px",
                    backgroundColor: "var(--background)", border: "1px solid var(--border)",
                  }}>
                    <span style={{ fontSize: "9px", fontWeight: 700, color: "var(--muted)", letterSpacing: "0.07em" }}>
                      UNITS:
                    </span>
                    {unitChips.map((u) => (
                      <span key={u.unit_code || u.unit_name} style={{
                        fontSize: "9px", fontWeight: 600, padding: "2px 7px", borderRadius: "99px",
                        backgroundColor: u.role === "primary" ? `${color}22` : "var(--border)",
                        border: `1px solid ${u.role === "primary" ? color : "var(--border)"}`,
                        color: "var(--text)",
                      }}>
                        {u.unit_name || HOTSPOT_UNIT_LABELS[u.unit_code] || u.unit_code}
                        {u.role === "support" ? " (support)" : ""}
                      </span>
                    ))}
                  </div>
                )}

                {/* Operation window */}
                {(hFull.prediction?.operation_hours || hFull.prediction?.concentrate_window) && (
                  <div style={{
                    display: "flex", gap: "12px", flexWrap: "wrap",
                    padding: "5px 10px", borderRadius: "6px",
                    backgroundColor: `${color}0d`, border: `1px solid ${color}33`,
                    fontSize: "10px", color: "var(--text)",
                  }}>
                    {hFull.prediction?.operation_hours && (
                      <span><span style={{ color: "var(--muted)" }}>Duration: </span><strong>{hFull.prediction.operation_hours} h</strong></span>
                    )}
                    {hFull.prediction?.concentrate_window && (
                      <span><span style={{ color: "var(--muted)" }}>Window: </span><strong>{hFull.prediction.concentrate_window}</strong></span>
                    )}
                    {hFull.prediction?.peak_time && (
                      <span><span style={{ color: "var(--muted)" }}>Peak: </span><strong>{hFull.prediction.peak_time}</strong></span>
                    )}
                  </div>
                )}

                {/* Deploy controls — IO/DPC only (reassign allowed when already deployed) */}
                <HotspotDeployControls
                  hotspot={h}
                  assignmentUnits={assignmentUnits}
                  canDeploy={canDeploy}
                  compact
                  onDeployed={onReload}
                />

                {/* Footer: trust score + trend */}
                <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", fontSize: "10px", color: "var(--muted)", paddingTop: "2px" }}>
                  <span>Trust: <strong style={{ color: "var(--text)" }}>{Math.round(h.avg_trust_score || 0)}%</strong></span>
                  {h.prediction?.predicted_increase_pct > 0 && (
                    <span>Trend: <strong style={{ color }}>+{h.prediction.predicted_increase_pct}%</strong></span>
                  )}
                  {h.lifecycle_state && (
                    <span>State: <strong style={{ color: "var(--text)" }}>{h.lifecycle_state}</strong></span>
                  )}
                </div>
              </div>
            </div>
          </div>
        );
      })}

      <div style={{ fontSize: "10px", color: "var(--muted)", textAlign: "center", paddingTop: "2px" }}>
        {canDeploy
          ? "IO/DPC: take control, then deploy a unit — the unit commander is emailed automatically."
          : "Recommendations from live verified hotspot data."}
      </div>
    </div>
  );
};

export default HotspotSecurityRecommendations;
