import React, { useEffect, useMemo, useState } from "react";
import {
  Circle,
  CircleMarker,
  MapContainer,
  Polyline,
  TileLayer,
  Tooltip,
  ZoomControl,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import api from "../../api/client";

const MUSANZE_CENTER = [-1.499, 29.635];

/**
 * TrustBond DBSCAN formation stage.
 *
 * Prefers the backend's `classification` / `lifecycle_state` field (already
 * computed via trust-weighted DBSCAN scoring on the server). Falls back to
 * score-based and then count-based heuristics for backward compatibility.
 */
const getFormationStage = (hotspot) => {
  const cls = hotspot?.classification || hotspot?.lifecycle_state || "";
  if (cls === "critical") return "intense";
  if (cls === "active") return "active";
  if (cls === "emerging") return "emerging";

  const score = Number(hotspot?.hotspot_score ?? 0);
  if (score >= 80) return "intense";
  if (score >= 60) return "active";
  if (score >= 40) return "emerging";

  const count = Number(hotspot?.incident_count || 0);
  if (count >= 8) return "intense";
  if (count >= 4) return "active";
  return "emerging";
};

const stageLabel = (stage) =>
  stage === "intense" ? "Intense" : stage === "active" ? "Active" : "Emerging";

const riskColor = (riskLevel) => {
  if (riskLevel === "high") return "#f87171";
  if (riskLevel === "medium") return "#fb923c";
  return "#34d399";
};

const Hotspots = ({ wsRefreshKey }) => {
  const [hotspots, setHotspots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [riskFilter, setRiskFilter] = useState("all");
  const [params, setParams] = useState({
    time_window_hours: 24,
    min_incidents: 2,
    radius_meters: 500,
    trust_min: 50,
  });
  const [recomputing, setRecomputing] = useState(false);

  const loadHotspots = () => {
    setLoading(true);
    const path =
      riskFilter === "all"
        ? "/api/v1/public/hotspots"
        : `/api/v1/public/hotspots?risk_level=${encodeURIComponent(
            riskFilter === "critical"
              ? "high"
              : riskFilter === "warning"
                ? "medium"
                : "low",
          )}`;
    api
      .get(path)
      .then((res) => {
        setHotspots(res || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  const handleDetailsClick = (hotspotId) => {
    window.location.href = `/hotspots/${hotspotId}`;
  };

  useEffect(() => {
    loadHotspots();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [riskFilter, wsRefreshKey]);

  const crit = hotspots.filter((h) => h.risk_level === "high").length;
  const warn = hotspots.filter((h) => h.risk_level === "medium").length;
  const normal = hotspots.filter((h) => h.risk_level === "low").length;

  const plottedHotspots = useMemo(
    () =>
      hotspots
        .map((h) => ({
          ...h,
          lat: Number(h.center_lat),
          lng: Number(h.center_long),
          stage: getFormationStage(h),
        }))
        .filter((h) => Number.isFinite(h.lat) && Number.isFinite(h.lng)),
    [hotspots],
  );

  const latestByTime = useMemo(
    () =>
      [...plottedHotspots].sort(
        (a, b) =>
          new Date(b.detected_at || 0).getTime() -
          new Date(a.detected_at || 0).getTime(),
      ),
    [plottedHotspots],
  );

  const formationPath = useMemo(
    () =>
      [...plottedHotspots]
        .sort(
          (a, b) =>
            new Date(a.detected_at || 0).getTime() -
            new Date(b.detected_at || 0).getTime(),
        )
        .map((h) => [h.lat, h.lng]),
    [plottedHotspots],
  );

  const stageCounts = useMemo(
    () =>
      plottedHotspots.reduce(
        (acc, h) => {
          acc[h.stage] += 1;
          return acc;
        },
        { emerging: 0, active: 0, intense: 0 },
      ),
    [plottedHotspots],
  );

  // Load default hotspot parameters once
  useEffect(() => {
    api
      .get("/api/v1/hotspots/params")
      .then((res) => {
        if (!res) return;
        setParams((prev) => ({
          ...prev,
          ...res,
        }));
      })
      .catch(() => {});
  }, []);

  // Aggregate type breakdown from current hotspots
  const typeTotals = {};
  let totalReports = 0;
  hotspots.forEach((h) => {
    const key = h.incident_type_name || "Other";
    typeTotals[key] = (typeTotals[key] || 0) + (h.incident_count || 0);
    totalReports += h.incident_count || 0;
  });
  const typeEntries = Object.entries(typeTotals).sort((a, b) => b[1] - a[1]);

  return (
    <>
      <div className="page-header">
        <h2>Crime Hotspots</h2>
        <p>Auto-detected incident clusters from verified reports.</p>
      </div>

      <div className="alert alert-info">
        <span className="alert-icon">i</span>
        <div>
          Hotspots are auto-detected using{" "}
          <strong>trust-weighted DBSCAN</strong>: reports are clustered by
          proximity (epsilon-radius) and minimum density (min samples). Each
          cluster&apos;s risk score (0-100) is weighted by the average Random
          Forest trust score of its constituent reports; low-trust reports
          reduce the hotspot score even if many are present.
        </div>
      </div>

      <div className="stats-row">
        <div className="stat-card c-red">
          <div className="stat-label">Critical</div>
          <div className="stat-value sv-red">{crit}</div>
          <div className="stat-change">High risk</div>
        </div>
        <div className="stat-card c-orange">
          <div className="stat-label">Warning</div>
          <div className="stat-value sv-orange">{warn}</div>
          <div className="stat-change">Monitor</div>
        </div>
        <div className="stat-card c-green">
          <div className="stat-label">Normal</div>
          <div className="stat-value sv-green">{normal}</div>
          <div className="stat-change">Lower risk</div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: "14px" }}>
        <div className="card-header">
          <div className="card-title">Cluster Formation Map</div>
          <span style={{ fontSize: "11px", color: "var(--muted)" }}>
            Sequence of hotspot emergence
          </span>
        </div>

        <div className="cluster-formation-strip">
          <div className="cluster-formation-chip c-emerging">
            <div className="cluster-formation-label">Emerging</div>
            <div className="cluster-formation-value">
              {stageCounts.emerging}
            </div>
          </div>
          <div className="cluster-formation-chip c-active">
            <div className="cluster-formation-label">Active</div>
            <div className="cluster-formation-value">{stageCounts.active}</div>
          </div>
          <div className="cluster-formation-chip c-intense">
            <div className="cluster-formation-label">Intense</div>
            <div className="cluster-formation-value">{stageCounts.intense}</div>
          </div>
        </div>

        <div className="hotspot-map-preview">
          <MapContainer
            center={
              latestByTime[0]
                ? [latestByTime[0].lat, latestByTime[0].lng]
                : MUSANZE_CENTER
            }
            zoom={12}
            minZoom={9}
            maxZoom={18}
            scrollWheelZoom
            style={{ width: "100%", height: "100%" }}
            zoomControl={false}
          >
            <TileLayer
              attribution="&copy; OpenStreetMap contributors"
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <ZoomControl position="topright" />

            {formationPath.length > 1 && (
              <Polyline
                positions={formationPath}
                pathOptions={{
                  color: "#4a90d9",
                  weight: 2,
                  opacity: 0.8,
                  dashArray: "5 7",
                }}
              />
            )}

            {latestByTime.map((h, idx) => {
              const color = riskColor(h.risk_level);
              const radiusMeters = Math.max(140, Number(h.radius_meters || 0));
              return (
                <React.Fragment key={h.hotspot_id}>
                  <Circle
                    center={[h.lat, h.lng]}
                    radius={radiusMeters}
                    pathOptions={{
                      color,
                      fillColor: color,
                      fillOpacity: 0.1,
                      weight: 2,
                      opacity: 0.55,
                    }}
                  >
                    <Tooltip direction="top" opacity={0.95}>
                      <div style={{ fontSize: "11px", lineHeight: 1.45 }}>
                        <strong>
                          {h.incident_type_name || "Hotspot"} #{h.hotspot_id}
                        </strong>
                        <br />
                        DBSCAN Stage: {stageLabel(h.stage)}
                        <br />
                        Trust-weighted Score:{" "}
                        {Number.isFinite(Number(h.hotspot_score))
                          ? `${Number(h.hotspot_score).toFixed(1)} / 100`
                          : "-"}
                        <br />
                        Avg Trust:{" "}
                        {Number.isFinite(Number(h.avg_trust_score))
                          ? `${Math.round(Number(h.avg_trust_score))} / 100`
                          : "-"}
                        <br />
                        Reports: {h.incident_count || 0}
                        <br />
                        Epsilon-Radius: {Math.round(radiusMeters)}m
                        <br />
                        Cluster Type:{" "}
                        {h.cluster_kind === "mixed_hotspot"
                          ? "Mixed"
                          : "Single-type"}
                      </div>
                    </Tooltip>
                  </Circle>

                  <CircleMarker
                    center={[h.lat, h.lng]}
                    radius={7}
                    pathOptions={{
                      color,
                      fillColor: color,
                      fillOpacity: 0.92,
                      weight: 2,
                    }}
                  >
                    <Tooltip
                      permanent
                      direction="center"
                      className="cluster-seq-label"
                    >
                      <span>{idx + 1}</span>
                    </Tooltip>
                  </CircleMarker>
                </React.Fragment>
              );
            })}
          </MapContainer>
        </div>
      </div>

      <div className="g31">
        <div className="card">
          <div className="card-header">
            <div className="card-title">Detected Hotspot Clusters</div>
            <select
              className="select"
              style={{ width: "auto", fontSize: "11px", padding: "4px 8px" }}
              value={riskFilter}
              onChange={(e) => setRiskFilter(e.target.value)}
            >
              <option value="all">All Risk Levels</option>
              <option value="critical">Critical</option>
              <option value="warning">Warning</option>
              <option value="normal">Normal</option>
            </select>
          </div>
          <div
            className="tbl-wrap"
            style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" }}
          >
            <table style={{ minWidth: "800px" }}>
              <thead>
                <tr>
                  <th style={{ minWidth: "50px" }}>#</th>
                  <th style={{ minWidth: "80px" }}>ID</th>
                  <th style={{ minWidth: "120px" }}>Location</th>
                  <th style={{ minWidth: "80px" }}>Reports</th>
                  <th style={{ minWidth: "100px" }}>Type</th>
                  <th style={{ minWidth: "90px" }}>Radius (m)</th>
                  <th style={{ minWidth: "100px" }}>Risk Level</th>
                  <th style={{ minWidth: "110px" }}>Formation</th>
                  <th style={{ minWidth: "80px" }}>Window</th>
                  <th style={{ minWidth: "120px" }}>Last Updated</th>
                  <th style={{ minWidth: "80px" }}></th>
                </tr>
              </thead>
              <tbody>
                {hotspots.map((h, index) => (
                  <tr key={h.hotspot_id}>
                    <td
                      style={{
                        fontSize: "12px",
                        color: "var(--muted)",
                        textAlign: "center",
                        minWidth: "50px",
                      }}
                    >
                      {index + 1}
                    </td>
                    <td
                      style={{
                        fontFamily: "monospace",
                        fontSize: "10px",
                        color: "var(--muted)",
                        minWidth: "80px",
                      }}
                    >
                      HS-{String(h.hotspot_id).padStart(3, "0")}
                    </td>
                    <td style={{ minWidth: "120px" }}>
                      <strong>{h.incident_type_name || "Cluster"}</strong>
                    </td>
                    <td style={{ fontWeight: 700, minWidth: "80px" }}>
                      {h.incident_count}
                    </td>
                    <td style={{ fontSize: "11px", minWidth: "100px" }}>
                      {h.incident_type_name || "—"}
                    </td>
                    <td style={{ minWidth: "90px" }}>
                      {Number(h.radius_meters || 0)}
                    </td>
                    <td style={{ minWidth: "100px" }}>
                      <span
                        className={`risk-pill ${
                          h.risk_level === "high"
                            ? "r-critical"
                            : h.risk_level === "medium"
                              ? "r-warning"
                              : "r-normal"
                        }`}
                      >
                        {h.risk_level?.toUpperCase() || "OK"}
                      </span>
                    </td>
                    <td style={{ minWidth: "110px" }}>
                      <span
                        className={`risk-pill ${
                          getFormationStage(h) === "intense"
                            ? "r-critical"
                            : getFormationStage(h) === "active"
                              ? "r-warning"
                              : "r-normal"
                        }`}
                      >
                        {stageLabel(getFormationStage(h))}
                      </span>
                    </td>
                    <td
                      style={{
                        fontSize: "10px",
                        color: "var(--muted)",
                        minWidth: "80px",
                      }}
                    >
                      {h.time_window_hours ? `${h.time_window_hours}h` : "—"}
                    </td>
                    <td
                      style={{
                        fontSize: "10px",
                        color: "var(--muted)",
                        minWidth: "120px",
                      }}
                    >
                      {h.detected_at
                        ? new Date(h.detected_at).toLocaleString()
                        : "—"}
                    </td>
                    <td style={{ minWidth: "80px" }}>
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={() => handleDetailsClick(h.hotspot_id)}
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                ))}
                {!hotspots.length && !loading && (
                  <tr>
                    <td
                      colSpan={11}
                      style={{
                        fontSize: "12px",
                        color: "var(--muted)",
                        textAlign: "center",
                      }}
                    >
                      No hotspots found.
                    </td>
                  </tr>
                )}
                {loading && (
                  <tr>
                    <td
                      colSpan={11}
                      style={{
                        fontSize: "12px",
                        color: "var(--muted)",
                        textAlign: "center",
                      }}
                    >
                      Loading...
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <div className="card-title">Analysis Settings</div>
          </div>
          <div style={{ padding: "10px 14px", fontSize: "12px" }}>
            <div style={{ marginBottom: "10px" }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: "11px",
                  marginBottom: 4,
                }}
              >
                <span>Epsilon Radius (m)</span>
                <span>{Math.round(params.radius_meters || 0)} m</span>
              </div>
              <input
                type="range"
                min="100"
                max="1000"
                step="50"
                value={params.radius_meters}
                onChange={(e) =>
                  setParams((p) => ({
                    ...p,
                    radius_meters: Number(e.target.value),
                  }))
                }
              />
            </div>
            <div style={{ marginBottom: "10px" }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: "11px",
                  marginBottom: 4,
                }}
              >
                <span>Min. Samples</span>
                <span>{params.min_incidents}</span>
              </div>
              <input
                type="range"
                min="2"
                max="10"
                step="1"
                value={params.min_incidents}
                onChange={(e) =>
                  setParams((p) => ({
                    ...p,
                    min_incidents: Number(e.target.value),
                  }))
                }
              />
            </div>
            <div style={{ marginBottom: "10px" }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: "11px",
                  marginBottom: 4,
                }}
              >
                <span>Time Window</span>
                <span>
                  {params.time_window_hours >= 24
                    ? `${Math.round(params.time_window_hours / 24)} days`
                    : `${params.time_window_hours} hours`}
                </span>
              </div>
              <select
                className="select"
                value={params.time_window_hours}
                onChange={(e) =>
                  setParams((p) => ({
                    ...p,
                    time_window_hours: Number(e.target.value),
                  }))
                }
              >
                <option value={24}>Last 24 hours</option>
                <option value={72}>Last 3 days</option>
                <option value={168}>Last 7 days</option>
              </select>
            </div>
            <div style={{ marginBottom: "10px" }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: "11px",
                  marginBottom: 4,
                }}
              >
                <span>Min. Trust Score</span>
                <span>{params.trust_min}</span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                step="5"
                value={params.trust_min}
                onChange={(e) =>
                  setParams((p) => ({
                    ...p,
                    trust_min: Number(e.target.value),
                  }))
                }
              />
            </div>
            <button
              className="btn btn-primary btn-sm"
              type="button"
              disabled={recomputing}
              onClick={async () => {
                setRecomputing(true);
                try {
                  await api.post("/api/v1/hotspots/recompute", params);
                  loadHotspots();
                } catch {
                  // ignore
                } finally {
                  setRecomputing(false);
                }
              }}
            >
              {recomputing ? "Recomputing…" : "Recompute Clusters"}
            </button>
          </div>

          <div
            style={{
              padding: "10px 14px",
              borderTop: "1px solid var(--border2)",
              fontSize: "12px",
            }}
          >
            <div
              style={{
                fontSize: "11px",
                fontWeight: 700,
                marginBottom: 6,
              }}
            >
              Type Breakdown
            </div>
            {typeEntries.length === 0 && (
              <div style={{ fontSize: "12px", color: "var(--muted)" }}>
                No hotspots yet.
              </div>
            )}
            {typeEntries.map(([name, count]) => {
              const pct = totalReports
                ? Math.round((count / totalReports) * 100)
                : 0;
              return (
                <div key={name} style={{ marginBottom: 6 }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: "11px",
                    }}
                  >
                    <span>{name}</span>
                    <span>
                      {count} ({pct}%)
                    </span>
                  </div>
                  <div className="prog-bar">
                    <div
                      className="prog-fill"
                      style={{
                        width: `${pct}%`,
                        background: "var(--accent)",
                      }}
                    ></div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </>
  );
};

export default Hotspots;
