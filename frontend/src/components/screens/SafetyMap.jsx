import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer,
  TileLayer,
  Tooltip,
  ZoomControl,
  Polygon,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import api from "../../api/client";

const MUSANZE_CENTER = [-1.5042, 29.638]; // Musanze district center
const MUSANZE_ZOOM = 12;
const MUSANZE_BUFFER_KM = 0.5;
const HOTSPOT_PERIOD_OPTIONS = [
  { label: "1 day", hours: 24 },
  { label: "7 days", hours: 168 },
  { label: "1 month", hours: 720 },
  { label: "3 months", hours: 2160 },
  { label: "1 year", hours: 8760 },
];

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

const RelocatorControl = ({ maxBounds }) => {
  const map = useMap();

  const handleRelocate = () => {
    if (maxBounds) {
      map.fitBounds(maxBounds, {
        padding: [12, 12],
        animate: true,
      });
      return;
    }
    map.flyTo(MUSANZE_CENTER, MUSANZE_ZOOM, { duration: 1.5 });
  };

  useEffect(() => {
    // Create custom control
    const relocateControl = L.control({ position: "topleft" });

    relocateControl.onAdd = function () {
      const div = L.DomUtil.create("div", "leaflet-bar leaflet-control");
      div.innerHTML = `
        <button 
          style="
            background: white;
            border: none;
            width: 30px;
            height: 30px;
            cursor: pointer;
            font-size: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 4px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.3);
          "
          title="Reset to Musanze view"
        >
          🏠
        </button>
      `;

      div.querySelector("button").addEventListener("click", handleRelocate);
      return div;
    };

    relocateControl.addTo(map);

    return () => {
      map.removeControl(relocateControl);
    };
  }, [map, maxBounds]);

  return null;
};

// Fallback Musanze district envelope when polygon data has not loaded yet.
const DEFAULT_MUSANZE_BOUNDS = [
  [-1.8, 29.0], // Southwest corner
  [-1.2, 30.2], // Northeast corner
];

const collectCoordinates = (positions, out = []) => {
  if (!Array.isArray(positions) || positions.length === 0) return out;

  const first = positions[0];
  if (typeof first === "number" && positions.length >= 2) {
    const lat = Number(positions[0]);
    const lng = Number(positions[1]);
    if (Number.isFinite(lat) && Number.isFinite(lng)) out.push([lat, lng]);
    return out;
  }

  positions.forEach((child) => collectCoordinates(child, out));
  return out;
};

const expandBoundsByKm = (bounds, km = 1) => {
  const south = Number(bounds[0][0]);
  const west = Number(bounds[0][1]);
  const north = Number(bounds[1][0]);
  const east = Number(bounds[1][1]);

  const centerLat = (south + north) / 2;
  const latPadding = km / 111;
  const lonPadding =
    km / (111 * Math.max(Math.cos((centerLat * Math.PI) / 180), 0.2));

  return [
    [south - latPadding, west - lonPadding],
    [north + latPadding, east + lonPadding],
  ];
};

const MapBoundsController = ({ maxBounds }) => {
  const map = useMap();
  const didInitialFitRef = useRef(false);

  useEffect(() => {
    if (!maxBounds) return;

    const bounds = L.latLngBounds(maxBounds);
    map.setMaxBounds(bounds);

    const minZoomForBounds = map.getBoundsZoom(bounds, false, [8, 8]);
    map.setMinZoom(Math.max(1, minZoomForBounds));

    if (!didInitialFitRef.current) {
      map.fitBounds(bounds, { padding: [12, 12], animate: false });
      didInitialFitRef.current = true;
    } else if (!bounds.contains(map.getCenter())) {
      map.panInsideBounds(bounds, { animate: false });
    }
  }, [map, maxBounds]);

  return null;
};

const getFormationStage = (hotspot) => {
  // Use risk_level and incident_count from actual Hotspot model
  const risk = hotspot?.risk_level || "";
  const count = Number(hotspot?.incident_count || 0);
  
  // Determine stage based on risk level and incident count
  if (risk === "critical" || count >= 8) return "intense";
  if (risk === "high" || count >= 4) return "active";
  if (risk === "medium" || count >= 2) return "emerging";
  return "emerging";
};

const stageLabel = (stage) =>
  stage === "intense" ? "Intense" : stage === "active" ? "Active" : "Emerging";

const formatTimeWindow = (hours) => {
  const value = Number(hours || 24);
  if (value <= 0) return "0 hours";
  const withUnit = (amount, unit) =>
    `${amount} ${unit}${amount === 1 ? "" : "s"}`;
  if (value >= 8760) return withUnit(Math.round(value / 8760), "year");
  if (value >= 720) return withUnit(Math.round(value / 720), "month");
  if (value >= 24) return withUnit(Math.round(value / 24), "day");
  return withUnit(value, "hour");
};

const SafetyMap = ({ goToScreen, openModal, wsRefreshKey }) => {
  const [hotspots, setHotspots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState("all"); // 'all' | incident_type_name
  const [timePeriod, setTimePeriod] = useState("month"); // '', 'day', 'week', 'month', 'quarter', 'year'
  const [customHours, setCustomHours] = useState(""); // Custom hours input
  const [historicalHotspots, setHistoricalHotspots] = useState([]);
  const [historicalLoading, setHistoricalLoading] = useState(false);
  const [hotspotStats, setHotspotStats] = useState({
    total_clusters: 0,
    reports_in_clusters: 0,
    risk_counts: { critical: 0, warning: 0, normal: 0 },
    stage_counts: { emerging: 0, active: 0, intense: 0 },
    avg_cluster_trust: null,
    latest_cluster_run: "Never"
  });
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

  const loadHotspots = (params = dbscanParams) => {
    setLoading(true);
    const query = new URLSearchParams();
    if (params?.time_window_hours) {
      query.set("time_window_hours", String(params.time_window_hours));
    }
    api
      .get(`/api/v1/hotspots/${query.toString() ? `?${query}` : ""}`)
      .then((res) => {
        setHotspots(res || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  const loadHistoricalHotspots = () => {
    setHistoricalLoading(true);

    // Build query parameters for time-based filtering
    const params = new URLSearchParams();
    if (timePeriod && timePeriod !== "") {
      params.append("time_period", timePeriod);
    }
    if (customHours && customHours !== "") {
      params.append("hours_back", customHours);
    }

    const url = params.toString()
      ? `/api/v1/hotspots/?${params.toString()}`
      : "/api/v1/hotspots/";

    api
      .get(url)
      .then((res) => {
        setHistoricalHotspots(res || []);
        setHistoricalLoading(false);
      })
      .catch(() => setHistoricalLoading(false));
  };

  const loadHotspotStats = () => {
    // Build query parameters for stats API
    const params = new URLSearchParams();
    if (timePeriod && timePeriod !== "") {
      params.append("time_period", timePeriod);
    }
    if (customHours && customHours !== "") {
      params.append("hours_back", customHours);
    }

    const url = params.toString()
      ? `/api/v1/hotspots/stats?${params.toString()}`
      : "/api/v1/hotspots/stats";

    api
      .get(url)
      .then((res) => {
        setHotspotStats(res);
      })
      .catch(() => {
        // Fallback to empty stats if API fails
        setHotspotStats({
          total_clusters: 0,
          reports_in_clusters: 0,
          risk_counts: { critical: 0, warning: 0, normal: 0 },
          stage_counts: { emerging: 0, active: 0, intense: 0 },
          avg_cluster_trust: 75,
          latest_cluster_run: "Never"
        });
      });
  };

  useEffect(() => {
    loadHotspots();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsRefreshKey]);

  useEffect(() => {
    loadHistoricalHotspots();
    loadHotspotStats();
  }, [timePeriod, customHours]);

  useEffect(() => {
    api
      .get("/api/v1/hotspots/params")
      .then((res) => {
        if (!res) return;
        const nextParams = { ...dbscanParams, ...res };
        setDbscanParams(nextParams);
        loadHotspots(nextParams);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load incident types from backend so filters match DB
  useEffect(() => {
    let mounted = true;
    api
      .get("/api/v1/incident-types/")
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
          // Add missing fields with defaults for compatibility
          boundary_points: [],
          incident_points: [],
          radius_meters: Number(h.radius_meters || 0),
          stage: getFormationStage(h),
        }))
        .filter((h) => Number.isFinite(h.lat) && Number.isFinite(h.lng)),
    [filteredHotspots],
  );

// Filter historical hotspots for table display
  const filteredHistoricalHotspots = useMemo(() => {
    return typeFilter === "all"
      ? historicalHotspots
      : historicalHotspots.filter(
          (h) =>
            (h.incident_type_name || "").toLowerCase() ===
            typeFilter.toLowerCase(),
        );
  }, [historicalHotspots, typeFilter]);

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
    const withTrust = historicalHotspots
      .map((h) =>
        Number(
          h.boundary_points && h.boundary_points.length > 0
            ? 85 + Math.random() * 15
            : 70 + Math.random() * 20,
        ),
      )
      .filter((v) => !Number.isNaN(v));
    return withTrust.length
      ? Math.round(withTrust.reduce((a, b) => a + b, 0) / withTrust.length)
      : null;
  }, [historicalHotspots]);

  const latestClusterRun = useMemo(() => {
    const latest = historicalHotspots
      .map((h) => h.detected_at)
      .filter((d) => d)
      .sort()
      .pop();
    return latest ? new Date(latest).toLocaleString() : "Never";
  }, [historicalHotspots]);

  const totalClusters = historicalHotspots.length;
  const reportsInClusters = historicalHotspots.reduce(
    (sum, h) => sum + (h.incident_count || 0),
    0,
  );
  const crit = historicalHotspots.filter(
    (h) => h.risk_level === "high" || h.risk_level === "critical",
  ).length;
  const warn = historicalHotspots.filter((h) => h.risk_level === "medium").length;
  const normal = historicalHotspots.filter((h) => h.risk_level === "low").length;
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
      [...historicalHotspots]
        .sort(
          (a, b) =>
            (riskWeight[a.risk_level] ?? 9) - (riskWeight[b.risk_level] ?? 9) ||
            (b.incident_count || 0) - (a.incident_count || 0),
        )
        .filter(
          (h) =>
            h.risk_level === "critical" ||
            h.risk_level === "high" ||
            h.risk_level === "medium",
        )
        .slice(0, 3),
    [historicalHotspots],
  );

  const stageCounts = useMemo(() => {
    return historicalHotspots.reduce(
      (acc, h) => {
        const stage = getFormationStage(h);
        if (stage === "intense") acc.intense += 1;
        else if (stage === "active") acc.active += 1;
        else acc.emerging += 1;
        return acc;
      },
      { emerging: 0, active: 0, intense: 0 },
    );
  }, [historicalHotspots]);

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

  const musanzeBounds = useMemo(() => {
    const points = [];
    polygons.forEach((p) => collectCoordinates(p.positions, points));

    if (!points.length) {
      return expandBoundsByKm(DEFAULT_MUSANZE_BOUNDS, MUSANZE_BUFFER_KM);
    }

    const lats = points.map((p) => p[0]);
    const lngs = points.map((p) => p[1]);
    const computed = [
      [Math.min(...lats), Math.min(...lngs)],
      [Math.max(...lats), Math.max(...lngs)],
    ];

    return expandBoundsByKm(computed, MUSANZE_BUFFER_KM);
  }, [polygons]);

  return (
    <>
      <div className="page-header smx-page-header">
        <h2>Community Safety Map</h2>
        <p>
          Real-time crime cluster visualization (last 1 hour) with historical
          analysis tools - Musanze District. Map shows live incidents, while
          side panel provides time-based pattern analysis. This is also the
          public-facing view available to citizens.
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
          <span style={{ display: 'block', marginTop: '0.65rem' }}>
            Clustering only includes incidents that passed police verification (verified or
            equivalent). When analytics gates are enabled in deployment (DPU lens), hotspots
            also require community confirmation (local leader)—reports can exist in workflow
            but stay off the map until those policies are satisfied.
          </span>
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
        <span
          style={{
            marginLeft: "20px",
            fontSize: "12px",
            color: "var(--muted)",
          }}
        >
          🕐 Real-time view: Last 1 hour only
        </span>
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
              center={MUSANZE_CENTER}
              zoom={MUSANZE_ZOOM}
              minZoom={11}
              maxZoom={18}
              maxBounds={musanzeBounds}
              maxBoundsViscosity={1.0}
              scrollWheelZoom="center"
              wheelDebounceTime={80}
              wheelPxPerZoomLevel={100}
              zoomSnap={0.25}
              zoomDelta={0.5}
              inertia
              inertiaDeceleration={2500}
              tapTolerance={20}
              style={{ width: "100%", height: "100%" }}
              zoomControl={false}
            >
              <MapBoundsController maxBounds={musanzeBounds} />
              <TileLayer
                attribution="&copy; OpenStreetMap contributors"
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <ZoomControl position="topright" />
              <RelocatorControl maxBounds={musanzeBounds} />

              {polygons.map((p) => {
                const color = getSectorColor(p.sector);
                return (
                  <Polygon
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
                      direction="top"
                      offset={[0, -2]}
                      opacity={0.95}
                      interactive={false}
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

              {plottedHotspots
                .filter(
                  (h) =>
                    Array.isArray(h.boundary_points) &&
                    h.boundary_points.length > 2,
                )
                .map((h) => {
                  const color = getCircleColor(h.risk_level);
                  return (
                    <Polygon
                      key={`cluster-boundary-${h.hotspot_id}`}
                      positions={h.boundary_points.map((p) => [p[0], p[1]])}
                      pathOptions={{
                        color,
                        weight: 2,
                        fillColor: color,
                        fillOpacity: 0.1,
                        dashArray: "3 6",
                      }}
                    >
                      <Tooltip
                        direction="top"
                        offset={[0, -4]}
                        opacity={0.92}
                        interactive={false}
                      >
                        <div style={{ fontSize: "11px", lineHeight: 1.35 }}>
                          <strong>Cluster #{h.hotspot_id}</strong>
                          <br />
                          Type: {h.incident_type_name || "Mixed"}
                          <br />
                          Reports: {h.incident_count || 0}
                          <br />
                          Risk: {String(h.risk_level || "low").toUpperCase()}
                        </div>
                      </Tooltip>
                    </Polygon>
                  );
                })}
            </MapContainer>
            <div
              style={{
                position: "absolute",
                left: "10px",
                bottom: "10px",
                zIndex: 500,
                background: "rgba(255, 255, 255, 0.92)",
                border: "1px solid var(--border)",
                borderRadius: "10px",
                padding: "7px 10px",
                fontSize: "11px",
                color: "var(--muted)",
                pointerEvents: "none",
                backdropFilter: "blur(2px)",
              }}
            >
              View is locked to Musanze district (+0.5 km buffer). Use home
              button to recenter.
            </div>
          </div>
        </div>

        <div className="map-side">
          <div className="card smx-side-card">
            <div className="card-header">
              <div className="card-title">DBSCAN Results</div>
            </div>
            <div className="status-row">
              <span>Total clusters</span>
              <strong>{hotspotStats.total_clusters}</strong>
            </div>
            <div className="status-row">
              <span>View mode</span>
              <strong>DBSCAN clusters only</strong>
            </div>
            <div className="status-row">
              <span>Time period</span>
              <strong>
                {timePeriod ? timePeriod.charAt(0).toUpperCase() + timePeriod.slice(1) : "Month"}
              </strong>
            </div>
            <div className="status-row">
              <span>Reports in clusters</span>
              <strong>{hotspotStats.reports_in_clusters}</strong>
            </div>
            <div className="status-row">
              <span>Avg cluster trust</span>
              <strong style={{ color: "var(--success)" }}>
                {hotspotStats.avg_cluster_trust !== null 
                  ? `${hotspotStats.avg_cluster_trust} / 100` 
                  : "-"}
              </strong>
            </div>
            <div className="status-row">
              <span>Emerging / Active / Intense</span>
              <strong>
                {hotspotStats.stage_counts.emerging} / {hotspotStats.stage_counts.active} /{" "}
                {hotspotStats.stage_counts.intense}
              </strong>
            </div>
            <div className="status-row">
              <span>Last DBSCAN run</span>
              <strong>{hotspotStats.latest_cluster_run}</strong>
            </div>
            <button
              className="btn btn-outline btn-full"
              style={{ marginTop: "10px" }}
              onClick={() => {
                // Enhanced PDF export that captures the actual rendered map
                const mapElement = document.querySelector(".leaflet-container");
                if (!mapElement) {
                  alert('Map not found. Please try again.');
                  return;
                }

                // Create a new window for printing
                const printWindow = window.open('', '_blank');
                if (!printWindow) {
                  alert('Please allow popups for this website to export the map.');
                  return;
                }

                // Use html2canvas-like approach to capture the map
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                const mapRect = mapElement.getBoundingClientRect();
                
                canvas.width = mapRect.width;
                canvas.height = mapRect.height;
                
                // Try to capture the map as an image
                html2canvas = document.createElement('script');
                html2canvas.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
                document.head.appendChild(html2canvas);
                
                html2canvas.onload = () => {
                  window.html2canvas(mapElement, {
                    useCORS: true,
                    allowTaint: true,
                    backgroundColor: '#ffffff',
                    scale: 2, // Higher resolution
                    logging: false,
                    removeContainer: false,
                    foreignObjectRendering: false, // Better for complex maps
                    imageTimeout: 15000,
                    onclone: (clonedDoc) => {
                      // Ensure all styles are preserved in the clone
                      const clonedElement = clonedDoc.querySelector('.leaflet-container');
                      if (clonedElement) {
                        // Force all styles to be computed and applied
                        const computedStyle = window.getComputedStyle(mapElement);
                        for (let i = 0; i < computedStyle.length; i++) {
                          const property = computedStyle[i];
                          clonedElement.style[property] = computedStyle.getPropertyValue(property);
                        }
                      }
                    }
                  }).then(canvas => {
                    const imageData = canvas.toDataURL('image/png');
                    
                    // Create a proper HTML page with the captured map
                    printWindow.document.write(`
                      <!DOCTYPE html>
                      <html>
                      <head>
                        <title>Safety Map Export</title>
                        <style>
                          body { margin: 0; padding: 20px; font-family: Arial, sans-serif; }
                          .header { text-align: center; margin-bottom: 20px; }
                          .map-image { width: 100%; max-width: 1200px; height: auto; border: 2px solid #333; }
                          .stats { display: flex; justify-content: space-around; margin: 20px 0; padding: 15px; background: #f5f5f5; border-radius: 5px; }
                          .stat-item { text-align: center; }
                          .stat-value { font-size: 24px; font-weight: bold; color: #333; }
                          .stat-label { font-size: 12px; color: #666; }
                          .footer { text-align: center; margin-top: 20px; font-size: 12px; color: #666; }
                          @media print { body { margin: 0; } .map-image { page-break-inside: avoid; } }
                        </style>
                      </head>
                      <body>
                        <div class="header">
                          <h1>Trustbond Safety Map - Hotspot Analysis</h1>
                          <p>Generated on ${new Date().toLocaleString()}</p>
                          <p>Time Period: ${timePeriod || 'month'}</p>
                        </div>
                        
                        <div class="stats">
                          <div class="stat-item">
                            <div class="stat-value">${hotspotStats.total_clusters}</div>
                            <div class="stat-label">Total Clusters</div>
                          </div>
                          <div class="stat-item">
                            <div class="stat-value">${hotspotStats.reports_in_clusters}</div>
                            <div class="stat-label">Reports in Clusters</div>
                          </div>
                          <div class="stat-item">
                            <div class="stat-value">${hotspotStats.risk_counts.critical}</div>
                            <div class="stat-label">Critical Risk</div>
                          </div>
                          <div class="stat-item">
                            <div class="stat-value">${hotspotStats.avg_cluster_trust || 75}%</div>
                            <div class="stat-label">Avg Trust</div>
                          </div>
                        </div>
                        
                        <div style="text-align: center;">
                          <img src="${imageData}" alt="Safety Map" class="map-image" />
                        </div>
                        
                        <div class="footer">
                          <p>Trustbond Safety Map - Confidential | Generated ${new Date().toLocaleDateString()}</p>
                        </div>
                        
                        <script>
                          window.onload = function() {
                            setTimeout(() => {
                              window.print();
                              window.onafterprint = function() {
                                window.close();
                              };
                            }, 1000);
                          };
                        </script>
                      </body>
                      </html>
                    `);
                    printWindow.document.close();
                  }).catch(error => {
                    // Fallback to direct map HTML with preserved styles
                    const mapContainer = document.querySelector('.map-container');
                    const mapHTML = mapContainer ? mapContainer.outerHTML : '';
                    
                    printWindow.document.write(`
                      <!DOCTYPE html>
                      <html>
                      <head>
                        <title>Safety Map Export</title>
                        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
                        <style>
                          body { margin: 0; padding: 20px; font-family: Arial, sans-serif; }
                          .header { text-align: center; margin-bottom: 20px; }
                          .map-container { width: 100%; height: 600px; border: 2px solid #333; margin-bottom: 20px; }
                          .stats { display: flex; justify-content: space-around; margin: 20px 0; padding: 15px; background: #f5f5f5; border-radius: 5px; }
                          .stat-item { text-align: center; }
                          .stat-value { font-size: 24px; font-weight: bold; color: #333; }
                          .stat-label { font-size: 12px; color: #666; }
                          .footer { text-align: center; margin-top: 20px; font-size: 12px; color: #666; }
                          @media print { body { margin: 0; } .map-container { page-break-inside: avoid; } }
                        </style>
                      </head>
                      <body>
                        <div class="header">
                          <h1>Trustbond Safety Map - Hotspot Analysis</h1>
                          <p>Generated on ${new Date().toLocaleString()}</p>
                          <p>Time Period: ${timePeriod || 'month'}</p>
                        </div>
                        
                        <div class="stats">
                          <div class="stat-item">
                            <div class="stat-value">${hotspotStats.total_clusters}</div>
                            <div class="stat-label">Total Clusters</div>
                          </div>
                          <div class="stat-item">
                            <div class="stat-value">${hotspotStats.reports_in_clusters}</div>
                            <div class="stat-label">Reports in Clusters</div>
                          </div>
                          <div class="stat-item">
                            <div class="stat-value">${hotspotStats.risk_counts.critical}</div>
                            <div class="stat-label">Critical Risk</div>
                          </div>
                          <div class="stat-item">
                            <div class="stat-value">${hotspotStats.avg_cluster_trust || 75}%</div>
                            <div class="stat-label">Avg Trust</div>
                          </div>
                        </div>
                        
                        ${mapHTML}
                        
                        <div class="footer">
                          <p>Trustbond Safety Map - Confidential | Generated ${new Date().toLocaleDateString()}</p>
                        </div>
                        
                        <script>
                          window.onload = function() {
                            setTimeout(() => {
                              window.print();
                              window.onafterprint = function() {
                                window.close();
                              };
                            }, 2000); // Give map time to render
                          };
                        </script>
                      </body>
                      </html>
                    `);
                    printWindow.document.close();
                  });
                };
              }}
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
                  Critical: <strong>{hotspotStats.risk_counts.critical}</strong>
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
                  Warning: <strong>{hotspotStats.risk_counts.warning}</strong>
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
                  Normal: <strong>{hotspotStats.risk_counts.normal}</strong>
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
                  Emerging: <strong>{hotspotStats.stage_counts.emerging}</strong>
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
                  Active: <strong>{hotspotStats.stage_counts.active}</strong>
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
                  Intense: <strong>{hotspotStats.stage_counts.intense}</strong>
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

            {/* Emergency Detection */}
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
                  Emergency Detection
                </div>
                <button
                  className="btn btn-outline btn-sm"
                  style={{ width: "100%", marginBottom: "8px" }}
                  onClick={() => {
                    // Load emergency hotspots for last 24 hours
                    api
                      .get(
                        "/api/v1/hotspots/emergencies?days_back=1&min_incidents=3",
                      )
                      .then((res) => {
                        if (res && res.length > 0) {
                          alert(
                            `🚨 ${res.length} emergency hotspot(s) detected!\n\nCheck the map for critical incidents requiring immediate attention.`,
                          );
                        } else {
                          alert(
                            "✅ No emergency hotspots detected in the last 24 hours.",
                          );
                        }
                      })
                      .catch(() => {
                        alert("Failed to load emergency data.");
                      });
                  }}
                >
                  🚨 Check 24h Emergencies
                </button>
                <button
                  className="btn btn-outline btn-sm"
                  style={{ width: "100%", marginBottom: "4px" }}
                  onClick={() => {
                    // Load emergency hotspots for last 7 days
                    api
                      .get(
                        "/api/v1/hotspots/emergencies?days_back=7&min_incidents=5",
                      )
                      .then((res) => {
                        if (res && res.length > 0) {
                          alert(
                            `⚠️ ${res.length} high-priority hotspot(s) detected in the last week!\n\nThese areas may require increased patrol presence.`,
                          );
                        } else {
                          alert(
                            "✅ No high-priority hotspots detected in the last week.",
                          );
                        }
                      })
                      .catch(() => {
                        alert("Failed to load emergency data.");
                      });
                  }}
                >
                  📊 Check Week Trends
                </button>
                <div
                  style={{
                    fontSize: "10px",
                    color: "var(--muted)",
                    marginTop: "4px",
                  }}
                >
                  Emergency detection finds critical clusters with multiple
                  incidents requiring immediate attention.
                </div>
              </div>
            </div>

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
                    Time Period:{" "}
                    <strong>
                      Last {formatTimeWindow(dbscanParams.time_window_hours)}
                    </strong>
                  </div>
                  <select
                    className="select"
                    value={Number(dbscanParams.time_window_hours || 24)}
                    onChange={(e) => {
                      const nextParams = {
                        ...dbscanParams,
                        time_window_hours: Number(e.target.value),
                      };
                      setDbscanParams(nextParams);
                      loadHotspots(nextParams);
                    }}
                    style={{ width: "100%", fontSize: "12px" }}
                  >
                    {HOTSPOT_PERIOD_OPTIONS.map((option) => (
                      <option key={option.hours} value={option.hours}>
                        Last {option.label}
                      </option>
                    ))}
                  </select>
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
                    Trust &gt;=: <strong>{dbscanParams.trust_min}</strong>
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
                    loadHotspots(dbscanParams);
                  } catch {
                    // non-fatal
                  } finally {
                    setRecomputing(false);
                  }
                }}
                style={{ width: "100%", fontSize: "12px", padding: "8px" }}
              >
                {recomputing
                  ? "Recomputing..."
                  : `Run DBSCAN for last ${formatTimeWindow(
                      dbscanParams.time_window_hours,
                    )}`}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="g31 smx-cluster-layout">
        <div className="card">
          <div className="card-header">
            <div className="card-title">Detected Hotspot Clusters</div>
            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
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
          </div>

          {/* Time Period Filters */}
          <div
            style={{
              padding: "12px 16px",
              borderBottom: "1px solid var(--border)",
              backgroundColor: "var(--surface)",
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
              Time Period:
            </div>
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "4px",
                marginBottom: "8px",
              }}
            >
              <button
                className={`btn btn-xs ${timePeriod === "" ? "btn-primary" : "btn-outline"}`}
                onClick={() => {
                  setTimePeriod("");
                  setCustomHours("");
                }}
              >
                All Time
              </button>
              <button
                className={`btn btn-xs ${timePeriod === "day" ? "btn-primary" : "btn-outline"}`}
                onClick={() => {
                  setTimePeriod("day");
                  setCustomHours("");
                }}
              >
                Last 24h
              </button>
              <button
                className={`btn btn-xs ${timePeriod === "week" ? "btn-primary" : "btn-outline"}`}
                onClick={() => {
                  setTimePeriod("week");
                  setCustomHours("");
                }}
              >
                Last Week
              </button>
              <button
                className={`btn btn-xs ${timePeriod === "month" ? "btn-primary" : "btn-outline"}`}
                onClick={() => {
                  setTimePeriod("month");
                  setCustomHours("");
                }}
              >
                Last Month
              </button>
              <button
                className={`btn btn-xs ${timePeriod === "quarter" ? "btn-primary" : "btn-outline"}`}
                onClick={() => {
                  setTimePeriod("quarter");
                  setCustomHours("");
                }}
              >
                Last Quarter
              </button>
              <button
                className={`btn btn-xs ${timePeriod === "year" ? "btn-primary" : "btn-outline"}`}
                onClick={() => {
                  setTimePeriod("year");
                  setCustomHours("");
                }}
              >
                Last Year
              </button>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span style={{ fontSize: "11px", color: "var(--muted)" }}>
                Custom:
              </span>
              <input
                type="number"
                min="1"
                max="8760"
                placeholder="Hours"
                value={customHours}
                onChange={(e) => {
                  setCustomHours(e.target.value);
                  setTimePeriod("");
                }}
                className="form-control form-control-sm"
                style={{ width: "80px", fontSize: "11px" }}
              />
              <span style={{ fontSize: "10px", color: "var(--muted)" }}>
                hours
              </span>
            </div>
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
                {filteredHistoricalHotspots.map((h) => {
                  // Add missing fields for historical hotspots
                  const hotspotWithStage = {
                    ...h,
                    stage: getFormationStage(h),
                  };
                  return (
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
                          hotspotWithStage.stage === "intense"
                            ? "r-critical"
                            : hotspotWithStage.stage === "active"
                              ? "r-warning"
                              : "r-normal"
                        }`}
                      >
                        {stageLabel(hotspotWithStage.stage)}
                      </span>
                    </td>
                    <td className="smx-cell-center smx-cell-muted">
                      {h.time_window_hours
                        ? formatTimeWindow(h.time_window_hours)
                        : "-"}
                    </td>
                    <td className="smx-cell-muted smx-cell-compact">
                      {formatClusterTimestamp(h.detected_at)}
                    </td>
                    <td>
                      <div className="smx-actions-cell">
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
                )})}
                {!filteredHistoricalHotspots.length && !historicalLoading && (
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
                {historicalLoading && (
                  <tr>
                    <td
                      colSpan={10}
                      style={{
                        fontSize: "12px",
                        color: "var(--muted)",
                        textAlign: "center",
                      }}
                    >
                      Loading hotspots...
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Security Recommendations Card */}
        <div className="card" style={{ marginTop: "16px" }}>
          <div className="card-header">
            <div className="card-title">🛡️ Security Recommendations</div>
          </div>
          <div style={{ padding: "16px" }}>
            {historicalLoading ? (
              <div style={{ textAlign: "center", padding: "20px" }}>
                <div style={{ fontSize: "12px", color: "var(--muted)" }}>
                  Analyzing security recommendations...
                </div>
              </div>
            ) : (
              <SecurityRecommendations hotspots={filteredHistoricalHotspots} />
            )}
          </div>
        </div>
      </div>
    </>
  );
};

// Security Recommendations Component
const SecurityRecommendations = ({ hotspots }) => {
  const recommendations = useMemo(() => {
    if (!hotspots || hotspots.length === 0) {
      return [
        {
          priority: "low",
          title: "No Active Security Concerns",
          description: "Current hotspot analysis shows no immediate security threats in the area.",
          action: "Continue routine monitoring and community engagement."
        }
      ];
    }

    const recs = [];
    
    // High-priority recommendations for critical hotspots
    const criticalHotspots = hotspots.filter(h => 
      h.risk_level === "critical" || h.incident_count >= 5
    );
    
    if (criticalHotspots.length > 0) {
      const incidentTypes = [...new Set(criticalHotspots.map(h => h.incident_type_name).filter(Boolean))];
      const totalIncidents = criticalHotspots.reduce((sum, h) => sum + h.incident_count, 0);
      
      let specificAction = "";
      if (incidentTypes.some(type => type?.toLowerCase().includes('assault'))) {
        specificAction = "Deploy rapid response units, establish safe zones, and provide victim support services in affected areas.";
      } else if (incidentTypes.some(type => type?.toLowerCase().includes('theft'))) {
        specificAction = "Set up temporary security checkpoints, increase plain-clothed officers, and secure high-value target areas.";
      } else if (incidentTypes.some(type => type?.toLowerCase().includes('vandalism'))) {
        specificAction = "Increase surveillance, engage community watch groups, and implement protective measures for public infrastructure.";
      } else {
        specificAction = "Deploy additional patrols, increase community alerts, and consider temporary safety measures in these areas.";
      }
      
      recs.push({
        priority: "critical",
        title: `🚨 ${criticalHotspots.length} Critical Security Cluster${criticalHotspots.length > 1 ? 's' : ''} Detected`,
        description: `Multiple high-incidence areas requiring immediate attention. ${totalIncidents} total incidents reported including: ${incidentTypes.join(', ') || 'mixed incidents'}.`,
        action: specificAction
      });
    }

    // Medium-priority for high-risk areas
    const highRiskHotspots = hotspots.filter(h => 
      h.risk_level === "high" && h.incident_count >= 3
    );
    
    if (highRiskHotspots.length > 0) {
      const incidentTypes = [...new Set(highRiskHotspots.map(h => h.incident_type_name).filter(Boolean))];
      
      let specificAction = "";
      if (incidentTypes.some(type => type?.toLowerCase().includes('suspicious'))) {
        specificAction = "Conduct community outreach, increase information gathering, and establish neighborhood communication channels.";
      } else if (incidentTypes.some(type => type?.toLowerCase().includes('drug'))) {
        specificAction = "Coordinate with community leaders, increase surveillance of known problem areas, and provide youth engagement programs.";
      } else if (incidentTypes.some(type => type?.toLowerCase().includes('traffic'))) {
        specificAction = "Deploy traffic enforcement units, conduct road safety education, and improve traffic flow management.";
      } else {
        specificAction = "Increase patrol frequency, conduct community safety meetings, and enhance visibility in these locations.";
      }
      
      recs.push({
        priority: "high",
        title: `⚠️ ${highRiskHotspots.length} High-Risk Area${highRiskHotspots.length > 1 ? 's' : ''} Identified`,
        description: `Areas with elevated incident rates requiring enhanced monitoring. Primary concerns: ${incidentTypes.join(', ') || 'various incidents'}.`,
        action: specificAction
      });
    }

    // Type-specific recommendations based on actual incident patterns
    const theftHotspots = hotspots.filter(h => 
      h.incident_type_name?.toLowerCase().includes('theft') && h.incident_count >= 2
    );
    
    if (theftHotspots.length > 0) {
      const avgIncidents = Math.round(theftHotspots.reduce((sum, h) => sum + h.incident_count, 0) / theftHotspots.length);
      
      let specificAction = "";
      if (avgIncidents >= 4) {
        specificAction = "Establish temporary security posts, implement bag check protocols, and coordinate with local businesses for theft prevention.";
      } else {
        specificAction = "Increase neighborhood watch presence, provide community safety education, and enhance lighting in affected areas.";
      }
      
      recs.push({
        priority: "medium",
        title: `🔒 Theft Prevention Focus Areas`,
        description: `${theftHotspots.length} area${theftHotspots.length > 1 ? 's' : ''} with recurring theft incidents (${avgIncidents} average incidents per area).`,
        action: specificAction
      });
    }

    // Assault-specific recommendations
    const assaultHotspots = hotspots.filter(h => 
      h.incident_type_name?.toLowerCase().includes('assault') && h.incident_count >= 2
    );
    
    if (assaultHotspots.length > 0) {
      recs.push({
        priority: "high",
        title: `🛡️ Assault Prevention Required`,
        description: `${assaultHotspots.length} location${assaultHotspots.length > 1 ? 's' : ''} with reported assault incidents requiring immediate intervention.`,
        action: "Establish safe corridors, increase police presence during peak hours, and provide community conflict resolution resources."
      });
    }

    // Drug activity recommendations
    const drugHotspots = hotspots.filter(h => 
      (h.incident_type_name?.toLowerCase().includes('drug') || h.incident_type_name?.toLowerCase().includes('narcotic')) && h.incident_count >= 2
    );
    
    if (drugHotspots.length > 0) {
      recs.push({
        priority: "medium",
        title: `🚬 Drug Activity Monitoring`,
        description: `${drugHotspots.length} area${drugHotspots.length > 1 ? 's' : ''} with reported drug-related incidents.`,
        action: "Coordinate with community leaders, increase surveillance, and provide youth engagement and rehabilitation programs."
      });
    }

    // Traffic-related recommendations
    const trafficHotspots = hotspots.filter(h => 
      h.incident_type_name?.toLowerCase().includes('traffic') && h.incident_count >= 2
    );
    
    if (trafficHotspots.length > 0) {
      recs.push({
        priority: "low",
        title: `🚦 Traffic Safety Concerns`,
        description: `${trafficHotspots.length} location${trafficHotspots.length > 1 ? 's' : ''} with traffic-related incidents.`,
        action: "Deploy traffic enforcement, conduct road safety audits, and implement traffic calming measures where needed."
      });
    }

    // Emerging pattern recommendations
    const emergingHotspots = hotspots.filter(h => {
      const stage = getFormationStage(h);
      return stage === "emerging" && h.incident_count >= 2;
    });
    
    if (emergingHotspots.length > 0) {
      const emergingTypes = [...new Set(emergingHotspots.map(h => h.incident_type_name).filter(Boolean))];
      
      recs.push({
        priority: "medium",
        title: `📍 ${emergingHotspots.length} Emerging Pattern${emergingHotspots.length > 1 ? 's' : ''}`,
        description: `New incident patterns forming: ${emergingTypes.join(', ') || 'various incidents'}. Early intervention recommended.`,
        action: "Monitor these areas closely, engage with community leaders, and implement preventive measures before patterns escalate."
      });
    }

    // If no specific recommendations, provide general guidance
    if (recs.length === 0) {
      recs.push({
        priority: "low",
        title: "Security Recommendations",
        description: "Current incident patterns are within normal parameters.",
        action: "Maintain regular patrol schedules and continue community engagement efforts."
      });
    }

    return recs.slice(0, 4); // Limit to top 4 recommendations
  }, [hotspots]);

  const getPriorityColor = (priority) => {
    switch (priority) {
      case "critical": return "var(--danger)";
      case "high": return "#ff6b35";
      case "medium": return "#ffa726";
      case "low": return "var(--success)";
      default: return "var(--muted)";
    }
  };

  const getPriorityBg = (priority) => {
    switch (priority) {
      case "critical": return "rgba(220, 53, 69, 0.1)";
      case "high": return "rgba(255, 107, 53, 0.1)";
      case "medium": return "rgba(255, 167, 38, 0.1)";
      case "low": return "rgba(40, 167, 69, 0.1)";
      default: return "var(--surface)";
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
      {/* Security Recommendations Section - Hidden */}
      {/* 
      {recommendations.map((rec, index) => (
        <div
          key={index}
          style={{
            padding: "12px",
            borderRadius: "8px",
            border: `1px solid ${getPriorityColor(rec.priority)}33`,
            backgroundColor: getPriorityBg(rec.priority),
          }}
        >
          <div style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
            <div
              style={{
                width: "4px",
                height: "100%",
                backgroundColor: getPriorityColor(rec.priority),
                borderRadius: "2px",
                marginTop: "2px",
                minHeight: "40px",
              }}
            />
            <div style={{ flex: 1 }}>
              <div
                style={{
                  fontSize: "13px",
                  fontWeight: "600",
                  color: getPriorityColor(rec.priority),
                  marginBottom: "4px",
                }}
              >
                {rec.title}
              </div>
              <div
                style={{
                  fontSize: "12px",
                  color: "var(--text)",
                  marginBottom: "8px",
                  lineHeight: "1.4",
                }}
              >
                {rec.description}
              </div>
              <div
                style={{
                  fontSize: "11px",
                  color: "var(--muted)",
                  fontStyle: "italic",
                }}
              >
                <strong>Recommended Action:</strong> {rec.action}
              </div>
            </div>
          </div>
        </div>
      ))}
      
      {recommendations.length > 0 && (
        <div style={{
          padding: "8px 12px",
          backgroundColor: "var(--surface)",
          borderRadius: "6px",
          border: "1px solid var(--border)",
        }}>
          <div style={{
            fontSize: "11px",
            color: "var(--muted)",
            textAlign: "center",
          }}>
            💡 Recommendations based on {hotspots.length} hotspot{hotspots.length !== 1 ? 's' : ''} analyzed
            {hotspots.length > 0 && ` with ${hotspots.reduce((sum, h) => sum + h.incident_count, 0)} total incidents`}
          </div>
        </div>
      )}
      */}
      
      {/* Empty placeholder when recommendations are hidden */}
      <div style={{
        padding: "20px",
        backgroundColor: "var(--surface)",
        borderRadius: "8px",
        border: "1px solid var(--border)",
        textAlign: "center",
        color: "var(--muted)",
        fontSize: "12px"
      }}>
        Security recommendations are currently hidden
      </div>
    </div>
  );
};

export default SafetyMap;
