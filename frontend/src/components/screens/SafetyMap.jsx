import React, { useEffect, useMemo, useState } from "react";
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Circle,
  Polyline,
  Tooltip,
  ZoomControl,
  Polygon,
  useMap,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import api from "../../api/client";

const RWANDA_CENTER = [-1.5, 29.6]; // near Musanze

const riskWeight = { critical: -1, high: 0, medium: 1, low: 2 };
const incidentTone = {
  theft: "danger",
  assault: "danger",
  vandalism: "warning",
  suspicious: "violet",
  traffic: "info",
  drug: "success",
  "drug activity": "success",
};

const MapFocusController = ({ target, trigger }) => {
  const map = useMap();

  useEffect(() => {
    if (!target) return;
    map.flyTo([target.lat, target.lng], 14, { duration: 0.9 });
  }, [map, target, trigger]);

  return null;
};

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

const SafetyMap = ({ goToScreen, openModal, wsRefreshKey }) => {
  const [hotspots, setHotspots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState("all"); // 'all' | incident_type_name
  const [polygons, setPolygons] = useState([]);
  const [incidentTypes, setIncidentTypes] = useState([]);
  const [selectedHotspotId, setSelectedHotspotId] = useState(null);
  const [focusNonce, setFocusNonce] = useState(0);
  const [recomputing, setRecomputing] = useState(false);
  const [dbscanParams, setDbscanParams] = useState({
    radius_meters: 500,
    min_incidents: 2,
    time_window_hours: 24,
    trust_min: 50,
  });

  const loadHotspots = () => {
    setLoading(true);
    api
      .get("/api/v1/hotspots")
      .then((res) => {
        setHotspots(res || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  useEffect(() => {
    loadHotspots();
  }, [wsRefreshKey]);

  useEffect(() => {
    api
      .get("/api/v1/hotspots/params")
      .then((res) => {
        if (!res) return;
        setDbscanParams((prev) => ({ ...prev, ...res }));
      })
      .catch(() => {});
  }, []);

  // Load incident types from backend so filters match DB
  useEffect(() => {
    let mounted = true;
    api
      .get("/api/v1/incident-types")
      .then((res) => {
        if (!mounted || !Array.isArray(res)) return;
        setIncidentTypes(res);
      })
      .catch(() => {
        /* non-fatal; buttons fall back to just "All Types" */
      });
    return () => {
      mounted = false;
    };
  }, [wsRefreshKey]);

  // Load village polygons from public GeoJSON for district boundaries
  useEffect(() => {
    let mounted = true;
    api
      .get("/api/v1/public/locations/geojson?location_type=village&limit=4000")
      .then((geo) => {
        if (!mounted || !geo?.features) return;
        const feats = geo.features || [];

        const polys = feats.map((f) => {
          const props = f.properties || {};
          const sector = props.sector || "Unknown";
          const cell = props.cell || null;
          const village = props.village || null;
          const geom = f.geometry || {};
          const type = geom.type;
          const coords = geom.coordinates || [];

          const toLatLngRings = (rings) =>
            rings.map((ring) =>
              ring.map(([lng, lat]) => [Number(lat), Number(lng)]),
            );

          let positions = [];
          if (type === "Polygon") {
            positions = toLatLngRings(coords);
          } else if (type === "MultiPolygon") {
            positions = coords.map((poly) => toLatLngRings(poly));
          }

          return {
            id: props.location_id || `${sector}-${Math.random()}`,
            sector,
            cell,
            village,
            positions,
          };
        });

        // Filter out any empty geometry
        setPolygons(polys.filter((p) => p.positions && p.positions.length));
      })
      .catch(() => {
        /* non-fatal: hotspots map still works */
      });

    return () => {
      mounted = false;
    };
  }, []);

  const filteredHotspots = useMemo(() => {
    return typeFilter === "all"
      ? hotspots
      : hotspots.filter(
          (h) =>
            (h.incident_type_name || "").toLowerCase() ===
            typeFilter.toLowerCase(),
        );
  }, [hotspots, typeFilter]);

  const plottedHotspots = useMemo(
    () =>
      filteredHotspots
        .map((h) => ({
          ...h,
          lat: Number(h.center_lat),
          lng: Number(h.center_long),
          incident_points: Array.isArray(h.incident_points)
            ? h.incident_points
                .map((p) => ({
                  ...p,
                  lat: Number(p.latitude),
                  lng: Number(p.longitude),
                }))
                .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lng))
            : [],
          stage: getFormationStage(h),
        }))
        .filter((h) => Number.isFinite(h.lat) && Number.isFinite(h.lng)),
    [filteredHotspots],
  );

  const selectedHotspot = useMemo(
    () =>
      plottedHotspots.find((h) => h.hotspot_id === selectedHotspotId) ||
      plottedHotspots[0] ||
      null,
    [plottedHotspots, selectedHotspotId],
  );

  useEffect(() => {
    if (!selectedHotspotId && plottedHotspots.length) {
      setSelectedHotspotId(plottedHotspots[0].hotspot_id);
      return;
    }
    if (
      selectedHotspotId &&
      plottedHotspots.length &&
      !plottedHotspots.some((h) => h.hotspot_id === selectedHotspotId)
    ) {
      setSelectedHotspotId(plottedHotspots[0].hotspot_id);
    }
  }, [plottedHotspots, selectedHotspotId]);

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

  const avgClusterTrust = useMemo(() => {
    const withTrust = plottedHotspots
      .map((h) =>
        Number(
          h.avg_credibility_score ??
            h.avg_trust_score ??
            h.average_trust_score ??
            h.trust_score,
        ),
      )
      .filter((v) => Number.isFinite(v) && v > 0);
    if (!withTrust.length) return null;
    return Math.round(withTrust.reduce((s, v) => s + v, 0) / withTrust.length);
  }, [plottedHotspots]);

  const latestClusterRun = useMemo(() => {
    const latest = plottedHotspots
      .map((h) => (h.detected_at ? new Date(h.detected_at).getTime() : 0))
      .filter((v) => v > 0)
      .sort((a, b) => b - a)[0];
    if (!latest) return "-";
    return new Date(latest).toLocaleString();
  }, [plottedHotspots]);

  const totalClusters = plottedHotspots.length;
  const reportsInClusters = plottedHotspots.reduce(
    (sum, h) => sum + (h.incident_count || 0),
    0,
  );
  const crit = plottedHotspots.filter(
    (h) => h.risk_level === "high" || h.risk_level === "critical",
  ).length;
  const warn = plottedHotspots.filter((h) => h.risk_level === "medium").length;
  const normal = plottedHotspots.filter((h) => h.risk_level === "low").length;
  const topForSide = plottedHotspots.slice(0, 5);

  const prioritizedHotspots = useMemo(
    () =>
      [...plottedHotspots].sort(
        (a, b) =>
          (riskWeight[a.risk_level] ?? 9) - (riskWeight[b.risk_level] ?? 9) ||
          (b.incident_count || 0) - (a.incident_count || 0),
      ),
    [plottedHotspots],
  );

  const advisories = useMemo(
    () =>
      prioritizedHotspots
        .filter(
          (h) =>
            h.risk_level === "critical" ||
            h.risk_level === "high" ||
            h.risk_level === "medium",
        )
        .slice(0, 3),
    [prioritizedHotspots],
  );

  const stageCounts = useMemo(() => {
    return plottedHotspots.reduce(
      (acc, h) => {
        if (h.stage === "intense") acc.intense += 1;
        else if (h.stage === "active") acc.active += 1;
        else acc.emerging += 1;
        return acc;
      },
      { emerging: 0, active: 0, intense: 0 },
    );
  }, [plottedHotspots]);

  const toneForType = (name) => {
    if (!name) return "neutral";
    return incidentTone[String(name).toLowerCase()] || "neutral";
  };

  const getCircleColor = (risk) => {
    // Leaflet needs real color values, not CSS variables.
    // These hex codes should match your --danger / --warning / --success theme colors.
    if (risk === "high" || risk === "critical") return "#f87171"; // Critical (red)
    if (risk === "medium") return "#fb923c"; // Warning (orange)
    return "#34d399"; // Normal (green)
  };

  const getSectorColor = (sector) => {
    const palette = [
      "#00e5b4",
      "#0099ff",
      "#ff6b35",
      "#6c63ff",
      "#00ced1",
      "#ff3b5c",
      "#ffd700",
      "#48b8d0",
      "#f472b6",
      "#34d399",
      "#a78bfa",
      "#fbbf24",
      "#38bdf8",
      "#f87171",
      "#818cf8",
    ];
    if (!sector) return palette[0];
    const hash = Array.from(sector).reduce(
      (acc, ch) => acc + ch.charCodeAt(0),
      0,
    );
    return palette[hash % palette.length];
  };

  const focusHotspot = (hotspotId) => {
    setSelectedHotspotId(hotspotId);
    setFocusNonce((n) => n + 1);
  };

  const formatClusterTimestamp = (value) => {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "-";
    return date.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <>
      <div className="page-header smx-page-header">
        <h2>Community Safety Map</h2>
        <p>
          Live anonymized crime cluster visualization - Musanze District. This
          is also the public-facing view available to citizens.
        </p>
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

      <div className="smx-filter-row">
        <span className="smx-label">Filter:</span>
        <button
          className={`btn btn-sm smx-filter-chip ${typeFilter === "all" ? "btn-primary" : "btn-outline"}`}
          onClick={() => setTypeFilter("all")}
        >
          All Types
        </button>
        {incidentTypes.map((t) => {
          const name = t.type_name || t.incident_type_name || "";
          if (!name) return null;
          const active = typeFilter === name;
          return (
            <button
              key={t.incident_type_id || name}
              className={`btn btn-sm smx-filter-chip tone-${toneForType(name)} ${
                active ? "btn-primary" : "btn-outline"
              }`}
              onClick={() => setTypeFilter(name)}
            >
              {name}
            </button>
          );
        })}
      </div>

      <div className="map-container">
        <div className="map-box">
          <div
            style={{
              width: "100%",
              height: "100%",
              position: "relative",
              overflow: "hidden",
              borderRadius: "14px",
            }}
          >
            <MapContainer
              center={RWANDA_CENTER}
              zoom={11}
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
              <MapFocusController
                target={selectedHotspot}
                trigger={focusNonce}
              />

              {polygons.map((p) => {
                const color = getSectorColor(p.sector);
                return (
                  <Polygon
                    // positions can be Polygon or MultiPolygon-style arrays
                    key={p.id}
                    positions={p.positions}
                    pathOptions={{
                      color,
                      weight: 1,
                      fillColor: color,
                      fillOpacity: 0.15,
                    }}
                  >
                    <Tooltip
                      sticky
                      direction="top"
                      offset={[0, -2]}
                      opacity={0.95}
                    >
                      <div style={{ fontSize: "11px", lineHeight: 1.35 }}>
                        <strong>
                          {p.village || p.cell || p.sector || "Location"}
                        </strong>
                        <br />
                        Sector: {p.sector || "N/A"}
                        <br />
                        Cell: {p.cell || "N/A"}
                        <br />
                        Village: {p.village || "N/A"}
                      </div>
                    </Tooltip>
                  </Polygon>
                );
              })}

              {formationPath.length > 1 && (
                <Polyline
                  positions={formationPath}
                  pathOptions={{
                    color: "#4a90d9",
                    weight: 2,
                    opacity: 0.8,
                    dashArray: "4 8",
                  }}
                />
              )}

              {plottedHotspots.map((h) => {
                const pos = [h.lat, h.lng];
                const count = h.incident_count || 0;
                const radius = 14 + Math.min(count, 24); // visual radius
                const color = getCircleColor(h.risk_level);
                const isSelected = selectedHotspotId === h.hotspot_id;
                const radiusMeters = Math.max(
                  140,
                  Number(h.radius_meters || 0),
                );
                return (
                  <React.Fragment key={h.hotspot_id}>
                    <Circle
                      center={pos}
                      radius={radiusMeters}
                      pathOptions={{
                        color,
                        fillColor: color,
                        fillOpacity: isSelected ? 0.16 : 0.09,
                        weight: isSelected ? 2.5 : 1.5,
                        opacity: 0.65,
                      }}
                      eventHandlers={{
                        click: () => focusHotspot(h.hotspot_id),
                        dblclick: () =>
                          goToScreen("hotspot-details", 0, {
                            hotspotId: h.hotspot_id,
                          }),
                      }}
                    />
                    {isSelected && (
                      <Circle
                        center={pos}
                        radius={Math.round(radiusMeters * 1.35)}
                        pathOptions={{
                          color,
                          fillOpacity: 0,
                          weight: 1,
                          opacity: 0.5,
                          dashArray: "5 7",
                        }}
                      />
                    )}
                    <CircleMarker
                      center={pos}
                      radius={radius / 3}
                      pathOptions={{
                        color,
                        fillColor: color,
                        fillOpacity: 0.86,
                        weight: isSelected ? 3 : 2,
                      }}
                      eventHandlers={{
                        click: () => focusHotspot(h.hotspot_id),
                      }}
                    >
                      <Tooltip
                        permanent
                        direction="center"
                        className="cluster-count-label"
                      >
                        <span>{count}</span>
                      </Tooltip>
                      <Tooltip direction="top" offset={[0, -4]} opacity={0.92}>
                        <div style={{ fontSize: "11px", lineHeight: 1.35 }}>
                          <strong>
                            {h.incident_type_name || "Cluster"} #{h.hotspot_id}
                          </strong>
                          <br />
                          Reports: {count}
                          <br />
                          Risk: {h.risk_level || "low"}
                          <br />
                          Formation: {stageLabel(h.stage)}
                          <br />
                          <em
                            style={{ fontSize: "10px", color: "var(--muted)" }}
                          >
                            Double-click for details
                          </em>
                        </div>
                      </Tooltip>
                    </CircleMarker>
                  </React.Fragment>
                );
              })}
            </MapContainer>
          </div>
        </div>

        <div className="map-side">
          <div className="card smx-side-card">
            <div className="card-header">
              <div className="card-title">Detected Hotspots</div>
            </div>
            {topForSide.map((h, idx) => (
              <button
                type="button"
                className="hs-item smx-hotspot-item"
                key={h.hotspot_id}
                style={{
                  width: "100%",
                  textAlign: "left",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                }}
                onClick={() => focusHotspot(h.hotspot_id)}
              >
                <div className="hs-rank">
                  {String(idx + 1).padStart(2, "0")}
                </div>
                <div className="hs-info">
                  <div className="hs-name">
                    {h.incident_type_name || "Cluster"} #{h.hotspot_id}
                  </div>
                  <div className="hs-meta">
                    {h.incident_count} reports · {stageLabel(h.stage)}
                  </div>
                </div>
                <span
                  className={`risk-pill ${
                    h.risk_level === "high" || h.risk_level === "critical"
                      ? "r-critical"
                      : h.risk_level === "medium"
                        ? "r-warning"
                        : "r-normal"
                  }`}
                >
                  {(h.risk_level || "ok").toUpperCase().slice(0, 4)}
                </span>
              </button>
            ))}
            {!topForSide.length && !loading && (
              <div
                style={{
                  fontSize: "12px",
                  color: "var(--muted)",
                  padding: "10px 14px",
                }}
              >
                No active clusters.
              </div>
            )}
            {loading && (
              <div
                style={{
                  fontSize: "12px",
                  color: "var(--muted)",
                  padding: "10px 14px",
                }}
              >
                Loading...
              </div>
            )}
          </div>

          <div className="card smx-side-card">
            <div className="card-header">
              <div className="card-title">DBSCAN Results</div>
            </div>
            <div className="status-row">
              <span>Total clusters</span>
              <strong>{totalClusters}</strong>
            </div>
            <div className="status-row">
              <span>View mode</span>
              <strong>DBSCAN clusters only</strong>
            </div>
            <div className="status-row">
              <span>Reports in clusters</span>
              <strong>{reportsInClusters}</strong>
            </div>
            <div className="status-row">
              <span>Avg cluster trust</span>
              <strong style={{ color: "var(--success)" }}>
                {avgClusterTrust !== null ? `${avgClusterTrust} / 100` : "-"}
              </strong>
            </div>
            <div className="status-row">
              <span>Emerging / Active / Intense</span>
              <strong>
                {stageCounts.emerging} / {stageCounts.active} /{" "}
                {stageCounts.intense}
              </strong>
            </div>
            <div className="status-row">
              <span>Last DBSCAN run</span>
              <strong>{latestClusterRun}</strong>
            </div>
            <button
              className="btn btn-outline btn-full"
              style={{ marginTop: "10px" }}
            >
              Export Map PDF
            </button>
          </div>

          {/* Simple Status Summary */}
          <div
            style={{
              padding: "12px 14px",
              marginBottom: "14px",
              backgroundColor: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: "8px",
            }}
          >
            <div
              style={{
                fontSize: "12px",
                fontWeight: "600",
                marginBottom: "8px",
                color: "var(--text)",
              }}
            >
              Risk Summary
            </div>
            <div style={{ display: "flex", gap: "12px", fontSize: "11px" }}>
              <div
                style={{ display: "flex", alignItems: "center", gap: "4px" }}
              >
                <div
                  style={{
                    width: "8px",
                    height: "8px",
                    borderRadius: "50%",
                    backgroundColor: "#dc3545",
                  }}
                ></div>
                <span>
                  Critical: <strong>{crit}</strong>
                </span>
              </div>
              <div
                style={{ display: "flex", alignItems: "center", gap: "4px" }}
              >
                <div
                  style={{
                    width: "8px",
                    height: "8px",
                    borderRadius: "50%",
                    backgroundColor: "#fd7e14",
                  }}
                ></div>
                <span>
                  Warning: <strong>{warn}</strong>
                </span>
              </div>
              <div
                style={{ display: "flex", alignItems: "center", gap: "4px" }}
              >
                <div
                  style={{
                    width: "8px",
                    height: "8px",
                    borderRadius: "50%",
                    backgroundColor: "#28a745",
                  }}
                ></div>
                <span>
                  Normal: <strong>{normal}</strong>
                </span>
              </div>
            </div>
          </div>

          {/* Cluster Formation Status */}
          <div
            style={{
              padding: "12px 14px",
              marginBottom: "14px",
              backgroundColor: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: "8px",
            }}
          >
            <div
              style={{
                fontSize: "12px",
                fontWeight: "600",
                marginBottom: "8px",
                color: "var(--text)",
              }}
            >
              Formation Stages
            </div>
            <div style={{ display: "flex", gap: "12px", fontSize: "11px" }}>
              <div
                style={{ display: "flex", alignItems: "center", gap: "4px" }}
              >
                <div
                  style={{
                    width: "8px",
                    height: "8px",
                    borderRadius: "50%",
                    backgroundColor: "#34d399",
                  }}
                ></div>
                <span>
                  Emerging: <strong>{stageCounts.emerging}</strong>
                </span>
              </div>
              <div
                style={{ display: "flex", alignItems: "center", gap: "4px" }}
              >
                <div
                  style={{
                    width: "8px",
                    height: "8px",
                    borderRadius: "50%",
                    backgroundColor: "#fb923c",
                  }}
                ></div>
                <span>
                  Active: <strong>{stageCounts.active}</strong>
                </span>
              </div>
              <div
                style={{ display: "flex", alignItems: "center", gap: "4px" }}
              >
                <div
                  style={{
                    width: "8px",
                    height: "8px",
                    borderRadius: "50%",
                    backgroundColor: "#dc3545",
                  }}
                ></div>
                <span>
                  Intense: <strong>{stageCounts.intense}</strong>
                </span>
              </div>
            </div>
          </div>

          <div className="card smx-side-card">
            <div className="card-header">
              <div className="card-title">Security Advisories</div>
            </div>
            {advisories.map((h) => (
              <div
                className="hs-item smx-hotspot-item"
                key={`adv-${h.hotspot_id}`}
              >
                <div className="hs-info">
                  <div className="hs-name">
                    {h.risk_level === "high" || h.risk_level === "critical"
                      ? "Deploy Patrol"
                      : "Monitor"}{" "}
                    - Cluster #{h.hotspot_id}
                  </div>
                  <div className="hs-meta">
                    {h.incident_count} reports, radius{" "}
                    {Math.round(Number(h.radius_meters || 0))}m
                  </div>
                </div>
                <span
                  className={`risk-pill ${
                    h.risk_level === "high" || h.risk_level === "critical"
                      ? "r-critical"
                      : "r-warning"
                  }`}
                >
                  {h.risk_level === "high" || h.risk_level === "critical"
                    ? "Urgent"
                    : "Watch"}
                </span>
              </div>
            ))}
            {!advisories.length && !loading && (
              <div
                style={{
                  fontSize: "12px",
                  color: "var(--muted)",
                  padding: "10px 14px",
                }}
              >
                No active advisories.
              </div>
            )}

            {/* DBSCAN Controls */}
            <div
              style={{
                borderTop: "1px solid var(--border)",
                paddingTop: "12px",
                marginTop: "12px",
              }}
            >
              <div style={{ marginBottom: "12px" }}>
                <div
                  style={{
                    fontSize: "12px",
                    fontWeight: "600",
                    marginBottom: "8px",
                    color: "var(--text)",
                  }}
                >
                  DBSCAN Parameters
                </div>

                <div style={{ marginBottom: "8px" }}>
                  <div
                    style={{
                      fontSize: "11px",
                      color: "var(--muted)",
                      marginBottom: "4px",
                    }}
                  >
                    Epsilon Radius:{" "}
                    <strong>
                      {Math.round(dbscanParams.radius_meters || 0)}m
                    </strong>
                  </div>
                  <input
                    type="range"
                    min="100"
                    max="1000"
                    step="50"
                    value={Number(dbscanParams.radius_meters || 500)}
                    onChange={(e) =>
                      setDbscanParams((p) => ({
                        ...p,
                        radius_meters: Number(e.target.value),
                      }))
                    }
                    style={{ width: "100%" }}
                  />
                </div>

                <div style={{ marginBottom: "8px" }}>
                  <div
                    style={{
                      fontSize: "11px",
                      color: "var(--muted)",
                      marginBottom: "4px",
                    }}
                  >
                    Min Points: <strong>{dbscanParams.min_incidents}</strong>
                  </div>
                  <input
                    type="range"
                    min="2"
                    max="10"
                    step="1"
                    value={Number(dbscanParams.min_incidents || 2)}
                    onChange={(e) =>
                      setDbscanParams((p) => ({
                        ...p,
                        min_incidents: Number(e.target.value),
                      }))
                    }
                    style={{ width: "100%" }}
                  />
                </div>

                <div style={{ marginBottom: "12px" }}>
                  <div
                    style={{
                      fontSize: "11px",
                      color: "var(--muted)",
                      marginBottom: "4px",
                    }}
                  >
                    Trust ≥: <strong>{dbscanParams.trust_min}</strong>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    step="5"
                    value={Number(dbscanParams.trust_min || 0)}
                    onChange={(e) =>
                      setDbscanParams((p) => ({
                        ...p,
                        trust_min: Number(e.target.value),
                      }))
                    }
                    style={{ width: "100%" }}
                  />
                </div>
              </div>

              <button
                className="btn btn-primary"
                disabled={recomputing}
                onClick={async () => {
                  setRecomputing(true);
                  try {
                    await api.post("/api/v1/hotspots/recompute", {
                      radius_meters: Number(dbscanParams.radius_meters || 500),
                      min_incidents: Number(dbscanParams.min_incidents || 2),
                      time_window_hours: Number(
                        dbscanParams.time_window_hours || 24,
                      ),
                      trust_min: Number(dbscanParams.trust_min || 0),
                    });
                    loadHotspots();
                  } catch {
                    // non-fatal
                  } finally {
                    setRecomputing(false);
                  }
                }}
                style={{ width: "100%", fontSize: "12px", padding: "8px" }}
              >
                {recomputing ? "Recomputing..." : "Run DBSCAN"}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="g31 smx-cluster-layout">
        <div className="card">
          <div className="card-header">
            <div className="card-title">Detected Hotspot Clusters</div>
            <select
              className="select"
              style={{ width: "auto", fontSize: "11px", padding: "4px 8px" }}
              value={typeFilter === "all" ? "all" : ""}
              onChange={(e) =>
                setTypeFilter(e.target.value === "all" ? "all" : e.target.value)
              }
            >
              <option value="all">All Types</option>
              {incidentTypes.map((t) => {
                const name = t.type_name || t.incident_type_name || "";
                if (!name) return null;
                return (
                  <option key={t.incident_type_id || name} value={name}>
                    {name}
                  </option>
                );
              })}
            </select>
          </div>
          <div className="tbl-wrap smx-cluster-table-wrap">
            <table className="smx-cluster-table">
              <colgroup>
                <col style={{ width: "8%" }} />
                <col style={{ width: "13%" }} />
                <col style={{ width: "8%" }} />
                <col style={{ width: "8%" }} />
                <col style={{ width: "8%" }} />
                <col style={{ width: "10%" }} />
                <col style={{ width: "10%" }} />
                <col style={{ width: "10%" }} />
                <col style={{ width: "13%" }} />
                <col style={{ width: "12%" }} />
              </colgroup>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Location</th>
                  <th>Reports</th>
                  <th>Type</th>
                  <th>Radius (m)</th>
                  <th>Risk Level</th>
                  <th>Formation</th>
                  <th>Window</th>
                  <th>Last Updated</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {plottedHotspots.map((h) => (
                  <tr key={h.hotspot_id}>
                    <td className="smx-cell-id smx-cell-muted">
                      HS-{String(h.hotspot_id).padStart(3, "0")}
                    </td>
                    <td className="smx-cell-strong">
                      <strong>{h.incident_type_name || "Cluster"}</strong>
                    </td>
                    <td className="smx-cell-strong smx-cell-center">
                      {h.incident_count}
                    </td>
                    <td className="smx-cell-compact">
                      {h.incident_type_name || "—"}
                    </td>
                    <td className="smx-cell-center">
                      {Number(h.radius_meters || 0)}
                    </td>
                    <td className="smx-cell-center">
                      <span
                        className={`risk-pill ${
                          h.risk_level === "high" || h.risk_level === "critical"
                            ? "r-critical"
                            : h.risk_level === "medium"
                              ? "r-warning"
                              : "r-normal"
                        }`}
                      >
                        {(h.risk_level || "ok").toUpperCase().slice(0, 4)}
                      </span>
                    </td>
                    <td className="smx-cell-center">
                      <span
                        className={`risk-pill ${
                          h.stage === "intense"
                            ? "r-critical"
                            : h.stage === "active"
                              ? "r-warning"
                              : "r-normal"
                        }`}
                      >
                        {stageLabel(h.stage)}
                      </span>
                    </td>
                    <td className="smx-cell-center smx-cell-muted">
                      {dbscanParams.time_window_hours
                        ? `${dbscanParams.time_window_hours}h`
                        : "-"}
                    </td>
                    <td className="smx-cell-muted smx-cell-compact">
                      {formatClusterTimestamp(h.detected_at)}
                    </td>
                    <td>
                      <div className="smx-actions-cell">
                        <button
                          className="btn btn-outline btn-sm"
                          onClick={() => focusHotspot(h.hotspot_id)}
                        >
                          Map
                        </button>
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() =>
                            goToScreen("hotspot-details", 0, {
                              hotspotId: h.hotspot_id,
                            })
                          }
                        >
                          Detail
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!plottedHotspots.length && !loading && (
                  <tr>
                    <td
                      colSpan={10}
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
                      colSpan={10}
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
      </div>
    </>
  );
};

export default SafetyMap;
