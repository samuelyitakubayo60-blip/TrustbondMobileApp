import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Circle,
  Marker,
  Tooltip,
  ZoomControl,
  Polygon,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import api from "../../api/client";
import { policeVerificationOkForHotspots } from "../../utils/reportOperationalLabels";

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

const DEFAULT_TIME_PERIOD = "week";

/** Derive sidebar stats from persisted hotspot rows (same source as map polygons). */
const buildStatsFromHotspots = (hotspots) => {
  const list = Array.isArray(hotspots) ? hotspots : [];
  let reportsIn = 0;
  let crit = 0;
  let warn = 0;
  let normal = 0;
  let emerging = 0;
  let active = 0;
  let intense = 0;
  const trusts = [];
  let latestMs = 0;

  for (const h of list) {
    const count = Number(h.incident_count) || 0;
    reportsIn += count;
    const risk = String(h.risk_level || "").toLowerCase();
    if (risk === "critical" || risk === "high") crit += 1;
    else if (risk === "medium" || risk === "active") warn += 1;
    else normal += 1;

    if (risk === "critical" || count >= 8) intense += 1;
    else if (risk === "high" || count >= 4) active += 1;
    else emerging += 1;

    if (h.avg_trust_score != null && Number.isFinite(Number(h.avg_trust_score))) {
      trusts.push(Number(h.avg_trust_score));
    }
    if (h.detected_at) {
      const t = new Date(h.detected_at).getTime();
      if (Number.isFinite(t) && t > latestMs) latestMs = t;
    }
  }

  return {
    total_clusters: list.length,
    reports_in_clusters: reportsIn,
    risk_counts: { critical: crit, warning: warn, normal: normal },
    stage_counts: { emerging, active, intense },
    avg_cluster_trust:
      trusts.length > 0
        ? Math.round(trusts.reduce((a, b) => a + b, 0) / trusts.length)
        : null,
    latest_cluster_run:
      latestMs > 0 ? new Date(latestMs).toLocaleString() : "Never",
  };
};

const TIME_PERIOD_HOURS = {
  day: 24,
  week: 168,
  month: 720,
  quarter: 2160,
  year: 8760,
};

const getSelectedFilterHours = (timePeriod, customHours) => {
  const custom = Number(customHours);
  if (Number.isFinite(custom) && custom > 0) return custom;
  if (!timePeriod) return null;
  return TIME_PERIOD_HOURS[timePeriod] ?? 168;
};

const isWithinSelectedFilter = (isoDate, filterHours) => {
  if (filterHours == null) return true;
  if (!isoDate) return false;
  const t = new Date(isoDate).getTime();
  if (Number.isNaN(t)) return false;
  return t >= Date.now() - filterHours * 60 * 60 * 1000;
};

const formatFilterPeriodLabel = (timePeriod, customHours) => {
  const hours = getSelectedFilterHours(timePeriod, customHours);
  if (hours == null) return "All time";
  return formatTimeWindow(hours);
};

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

/** Tracks zoom level changes and reports them to parent via callback. */
const ZoomTracker = ({ onZoom }) => {
  const map = useMap();
  useEffect(() => {
    const handle = () => onZoom(map.getZoom());
    map.on("zoomend", handle);
    return () => map.off("zoomend", handle);
  }, [map, onZoom]);
  return null;
};

const SafetyMap = ({ goToScreen, openModal, wsRefreshKey }) => {
  const [loading, setLoading] = useState(true);
  const [confirmedOnMap, setConfirmedOnMap] = useState([]);
  const [typeFilter, setTypeFilter] = useState("all"); // 'all' | incident_type_name
  const [timePeriod, setTimePeriod] = useState(DEFAULT_TIME_PERIOD); // '', 'day', 'week', 'month', 'quarter', 'year'
  const [customHours, setCustomHours] = useState(""); // Custom hours input
  const [historicalHotspots, setHistoricalHotspots] = useState([]);
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
  const [legendOpen, setLegendOpen] = useState(false);
  const [dbscanParams, setDbscanParams] = useState({
    radius_meters: 500,
    min_incidents: 1,
    time_window_hours: 24,
    trust_min: 50,
  });
  const [mapZoom, setMapZoom] = useState(MUSANZE_ZOOM);

  const loadHistoricalHotspots = () => {
    setLoading(true);
    const params = new URLSearchParams();
    params.set("limit", "200");
    if (timePeriod && timePeriod !== "") {
      params.set("time_period", timePeriod);
    } else if (customHours && customHours !== "") {
      params.set("hours_back", customHours);
    }
    api
      .get(`/api/v1/hotspots/?${params.toString()}`)
      .then((res) => {
        const rows = res || [];
        setHistoricalHotspots(rows);
        setHotspotStats(buildStatsFromHotspots(rows));
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  /** Police-confirmed reports for map pins (full history; filter dims older pins). */
  const loadConfirmedReportsForMap = async () => {
    const PAGE = 100; // backend max limit
    let offset = 0;
    let all = [];
    try {
      while (true) {
        const res = await api.get(
          `/api/v1/reports/?limit=${PAGE}&offset=${offset}&verification_status=verified`,
        );
        const items = Array.isArray(res?.items) ? res.items : [];
        all = all.concat(items);
        if (items.length < PAGE) break; // last page
        offset += PAGE;
        if (offset > 2000) break;       // safety cap
      }
      const pins = all
        .filter((r) => policeVerificationOkForHotspots(r).ok)
        .map((r) => ({
          report_id: r.report_id,
          lat: Number(r.latitude),
          lng: Number(r.longitude),
          reported_at: r.reported_at,
          incident_type_name: r.incident_type_name || "Incident",
        }))
        .filter((r) => Number.isFinite(r.lat) && Number.isFinite(r.lng));
      setConfirmedOnMap(pins);
    } catch {
      setConfirmedOnMap([]);
    }
  };

  useEffect(() => {
    loadHistoricalHotspots();
    loadConfirmedReportsForMap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsRefreshKey]);

  const selectedFilterHours = useMemo(
    () => getSelectedFilterHours(timePeriod, customHours),
    [timePeriod, customHours],
  );

  useEffect(() => {
    loadHistoricalHotspots();
  }, [timePeriod, customHours]);

  useEffect(() => {
    api
      .get("/api/v1/hotspots/params")
      .then((res) => {
        if (!res) return;
        const nextParams = { ...dbscanParams, ...res };
        setDbscanParams(nextParams);
        loadHistoricalHotspots();
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
    const byType = typeFilter === "all"
      ? historicalHotspots
      : historicalHotspots.filter(
          (h) =>
            (h.incident_type_name || "").toLowerCase() ===
            typeFilter.toLowerCase(),
        );
    // Apply DBSCAN param sliders as a client-side preview so the map and
    // cluster list reflect the configured thresholds without a server round-trip.
    const minInc = Number(dbscanParams.min_incidents || 1);
    const trustMin = Number(dbscanParams.trust_min || 0);
    return byType.filter(
      (h) =>
        (h.incident_count || 0) >= minInc &&
        (h.avg_trust_score || 0) >= trustMin,
    );
  }, [historicalHotspots, typeFilter, dbscanParams.min_incidents, dbscanParams.trust_min]);

  const filteredConfirmedOnMap = useMemo(() => {
    return typeFilter === "all"
      ? confirmedOnMap
      : confirmedOnMap.filter(
          (r) =>
            (r.incident_type_name || "").toLowerCase() ===
            typeFilter.toLowerCase(),
        );
  }, [confirmedOnMap, typeFilter]);

  const plottedHotspots = useMemo(
    () =>
      filteredHotspots
        .map((h) => ({
          ...h,                           // preserves incident_points + boundary_points from API
          lat: Number(h.center_lat),
          lng: Number(h.center_long),
          // Use the slider radius as a visual preview; falls back to stored value.
          radius_meters: Number(dbscanParams.radius_meters || h.radius_meters || 500),
          stage: getFormationStage(h),
        }))
        .filter((h) => Number.isFinite(h.lat) && Number.isFinite(h.lng)),
    [filteredHotspots, dbscanParams.radius_meters],
  );

  // filteredHistoricalHotspots = same as filteredHotspots (type + param filters already applied)
  const filteredHistoricalHotspots = filteredHotspots;

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

  /** Musanze safety map cluster zone colours (red / yellow / green). */
  const getRiskZoneColor = (risk) => {
    const rl = String(risk || "").toLowerCase();
    if (rl === "high" || rl === "critical") return "#ef4444";
    if (rl === "medium" || rl === "active" || rl === "emerging") return "#eab308";
    if (rl === "low" || rl === "low_activity") return "#22c55e";
    return "#22c55e";
  };

  const getCircleColor = (risk) => getRiskZoneColor(risk);

  /** Haversine distance in metres between two lat/lng points. */
  const haversineMeters = (lat1, lng1, lat2, lng2) => {
    const R = 6371000;
    const toRad = (d) => (d * Math.PI) / 180;
    const dLat = toRad(lat2 - lat1);
    const dLng = toRad(lng2 - lng1);
    const a =
      Math.sin(dLat / 2) ** 2 +
      Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  };

  /**
   * Determine a report pin's risk level by checking which hotspot cluster it
   * falls inside (centre + radius with 1.5× tolerance). Returns the highest
   * risk level found, or "rare" when the report is isolated.
   *
   * Color key:
   *   red    → high / critical hotspot area
   *   yellow → medium hotspot area
   *   green  → low hotspot area
   *   blue   → rare / isolated (not in any cluster)
   */
  const getReportRiskColor = (report, hotspots) => {
    const rankMap = { critical: 4, high: 3, medium: 2, low: 1 };
    let bestRank = 0;
    let bestRisk = null;

    for (const h of hotspots) {
      if (!Number.isFinite(h.lat) || !Number.isFinite(h.lng)) continue;
      const dist = haversineMeters(report.lat, report.lng, h.lat, h.lng);
      const radius = Number(h.radius_meters || 500) * 1.5; // 1.5× tolerance
      if (dist <= radius) {
        const rank = rankMap[h.risk_level] || 0;
        if (rank > bestRank) {
          bestRank = rank;
          bestRisk = h.risk_level;
        }
      }
    }

    if (bestRisk === "critical" || bestRisk === "high") return "#ef4444"; // red
    if (bestRisk === "medium") return "#eab308";                          // yellow
    if (bestRisk === "low")    return "#22c55e";                          // green
    return "#3b82f6";                                                     // blue (rare)
  };

  const getReportRiskBorder = (fillColor) => {
    const borders = {
      "#ef4444": "#991b1b",
      "#eab308": "#854d0e",
      "#22c55e": "#15803d",
      "#3b82f6": "#1e3a8a",
    };
    return borders[fillColor] || "#1e3a8a";
  };

  const getReportRiskLabel = (fillColor) => {
    if (fillColor === "#ef4444") return "High-risk area";
    if (fillColor === "#eab308") return "Medium-risk area";
    if (fillColor === "#22c55e") return "Low-risk area";
    return "Rare / isolated";
  };

  /** Diamond-shaped DivIcon for incident pins — visually distinct from circular hotspot rings. */
  const createDiamondIcon = (fillColor, borderColor, opacity) => {
    const size = 16;
    const half = size / 2;
    return L.divIcon({
      className: "",
      html: `<div style="
        width:${size}px;height:${size}px;
        background:${fillColor};
        border:2.5px solid ${borderColor};
        transform:rotate(45deg);
        opacity:${opacity};
        box-shadow:0 0 0 2px rgba(0,0,0,0.55),0 2px 6px rgba(0,0,0,0.7);
      "></div>`,
      iconSize: [size, size],
      iconAnchor: [half, half],
      tooltipAnchor: [0, -half - 4],
    });
  };

  /** Circular cluster badge showing incident count — larger badge for larger groups. */
  const createClusterIcon = (count, fillColor, borderColor, opacity) => {
    const size = Math.min(48, 28 + Math.floor(Math.log2(Math.max(1, count))) * 5);
    const half = size / 2;
    return L.divIcon({
      className: "",
      html: `<div style="
        width:${size}px;height:${size}px;
        background:${fillColor};
        border:3px solid ${borderColor};
        border-radius:50%;
        display:flex;align-items:center;justify-content:center;
        color:#fff;font-weight:800;font-size:${size < 36 ? 11 : 13}px;
        font-family:sans-serif;
        opacity:${opacity};
        box-shadow:0 0 0 3px rgba(0,0,0,0.45),0 3px 10px rgba(0,0,0,0.65);
        line-height:1;
      ">${count}</div>`,
      iconSize: [size, size],
      iconAnchor: [half, half],
      tooltipAnchor: [0, -half - 4],
    });
  };

  /**
   * Well-known types get hand-picked colours for immediate recognition.
   * Any new type added to the database gets a deterministic colour derived
   * from its name hash (HSL, always vivid and distinct) — no code change needed.
   */
  const INCIDENT_TYPE_COLORS = {
    "Theft":               "#F59E0B",
    "Assault":             "#EF4444",
    "Vandalism":           "#8B5CF6",
    "Domestic Violence":   "#EC4899",
    "Drug Activity":       "#10B981",
    "Fraud/Scam":          "#3B82F6",
    "Harassment":          "#F97316",
    "Suspicious Activity": "#6B7280",
    "Traffic Incident":    "#06B6D4",
  };

  /** Deterministic HSL colour from any string — same name always → same colour. */
  const hashColor = (str) => {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = (Math.imul(31, h) + str.charCodeAt(i)) | 0;
    const hue = ((h >>> 0) % 360);
    // Keep saturation high and lightness mid so colours are vivid on dark maps
    return `hsl(${hue}, 70%, 58%)`;
  };

  const getIncidentTypeColor = (typeName) =>
    typeName ? (INCIDENT_TYPE_COLORS[typeName] ?? hashColor(typeName)) : "#94A3B8";

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

  /**
   * Cluster color palette — matches the diagram spec.
   * Cluster 1: Blue (#1E88E5), Cluster 2: Green (#43A047), Cluster 3: Red (#E53935), …
   */
  const CLUSTER_PALETTE = [
    "#1E88E5", // blue
    "#43A047", // green
    "#E53935", // red
    "#FB8C00", // orange
    "#00ACC1", // cyan
    "#8E24AA", // violet
    "#F4511E", // deep orange
    "#039BE5", // light blue
    "#7CB342", // light green
    "#E91E63", // pink
  ];

  /** Noise / outlier colour — fixed purple per spec. */
  const NOISE_COLOR = "#8E24AA";
  /** Star centroid colour — fixed hot-pink per spec. */
  const STAR_COLOR = "#E91E63";

  const getClusterColor = (idx) => CLUSTER_PALETTE[idx % CLUSTER_PALETTE.length];

  /**
   * Convex hull — Graham scan.
   * Returns [[lat, lng], ...] ordered counter-clockwise for react-leaflet <Polygon>.
   */
  const convexHull = (pts) => {
    if (pts.length <= 2) return pts.map((p) => [p.lat, p.lng]);
    const s = pts.slice().sort((a, b) =>
      a.lng !== b.lng ? a.lng - b.lng : a.lat - b.lat,
    );
    const cross = (O, A, B) =>
      (A.lng - O.lng) * (B.lat - O.lat) - (A.lat - O.lat) * (B.lng - O.lng);
    const lower = [];
    for (const p of s) {
      while (
        lower.length >= 2 &&
        cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0
      )
        lower.pop();
      lower.push(p);
    }
    const upper = [];
    for (let i = s.length - 1; i >= 0; i--) {
      const p = s[i];
      while (
        upper.length >= 2 &&
        cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0
      )
        upper.pop();
      upper.push(p);
    }
    upper.pop();
    lower.pop();
    return [...lower, ...upper].map((p) => [p.lat, p.lng]);
  };

  /** 5-point star DivIcon at cluster centroid — always hot-pink per spec. */
  const createStarIcon = () => {
    const size = 34;
    const half = size / 2;
    const star = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 34 34">
      <polygon
        points="17,2 20.5,12 31,12 22.5,18.5 25.5,29 17,23 8.5,29 11.5,18.5 3,12 13.5,12"
        fill="${STAR_COLOR}" stroke="#fff" stroke-width="2"/>
    </svg>`;
    return L.divIcon({
      className: "",
      html: `<div style="filter:drop-shadow(0 1px 6px rgba(0,0,0,0.8))">${star}</div>`,
      iconSize: [size, size],
      iconAnchor: [half, half],
      tooltipAnchor: [0, -half - 6],
    });
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

  const countIcon = (count, tone = "neutral") => {
    const bg =
      tone === "danger"
        ? "#f87171"
        : tone === "warning"
          ? "#fb923c"
          : tone === "success"
            ? "#34d399"
            : "#60a5fa";
    const size = count >= 10 ? 34 : 30;
    return L.divIcon({
      className: "hotspot-count-icon",
      html: `<div style="
          width:${size}px;height:${size}px;border-radius:${size}px;
          background:${bg};color:white;font-weight:800;
          display:flex;align-items:center;justify-content:center;
          border:2px solid rgba(255,255,255,0.95);
          box-shadow:0 2px 8px rgba(0,0,0,0.28);
          font-size:${count >= 10 ? 12 : 13}px;
        ">${count}</div>`,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
    });
  };

  return (
    <>
      <div className="page-header smx-page-header">
        <h2>Community Safety Map</h2>
        <p>
          Musanze District safety map. Every verified incident is plotted and
          coloured by risk zone — <strong style={{ color: "#ef4444" }}>red</strong> (high-risk
          cluster), <strong style={{ color: "#ca8a04" }}>yellow</strong> (medium-risk
          cluster), <strong style={{ color: "#16a34a" }}>green</strong> (low-risk
          cluster), <strong style={{ color: "#3b82f6" }}>blue</strong> (rare / isolated).
          DBSCAN hotspot circles overlay cluster boundaries. Use the Time Period panel
          to highlight a window; points outside the window appear faded.
        </p>
      </div>

      <div className="alert alert-info">
        <span className="alert-icon">i</span>
        <div>
          Musanze District safety map: every <strong>police-verified</strong> incident is
          plotted and coloured by risk zone — red (high), yellow (medium), green (low),
          blue (rare / isolated). Persisted <strong>DBSCAN hotspot circles</strong> from the
          database overlay cluster boundaries; a single verified report can form its own
          low-risk cluster.
          <span style={{ display: "block", marginTop: "0.65rem" }}>
            Use the <strong>Time Period</strong> panel to highlight a window; incidents
            outside that window appear faded (35% opacity).
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
          Map: {plottedHotspots.length} clusters · {confirmedOnMap.length} verified
          incidents · highlight: {formatFilterPeriodLabel(timePeriod, customHours)}
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
              <ZoomTracker onZoom={setMapZoom} />
              <TileLayer
                attribution="&copy; OpenStreetMap contributors"
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <ZoomControl position="topright" />
              <RelocatorControl maxBounds={musanzeBounds} />

              {polygons.map((p) => (
                <Polygon
                  key={p.id}
                  positions={p.positions}
                  pathOptions={{
                    color: "#94a3b8",
                    weight: 1,
                    opacity: 0.55,
                    fillColor: "#1e293b",
                    fillOpacity: 0.04,
                  }}
                >
                  <Tooltip
                    direction="top"
                    offset={[0, -2]}
                    opacity={0.9}
                    interactive={false}
                  >
                    <div style={{ fontSize: "11px", lineHeight: 1.35 }}>
                      <strong>
                        {p.village || p.cell || p.sector || "Location"}
                      </strong>
                      <br />
                      Sector: {p.sector || "N/A"} · Cell: {p.cell || "N/A"}
                    </div>
                  </Tooltip>
                </Polygon>
              ))}

              {/* ── Backend DBSCAN clusters ─────────────────────────────── */}
              {plottedHotspots.map((h, hIdx) => {
                const zoneColor = getRiskZoneColor(h.risk_level);
                const pts = Array.isArray(h.incident_points) ? h.incident_points : [];
                const clusterInFilter =
                  selectedFilterHours == null ||
                  isWithinSelectedFilter(h.detected_at, selectedFilterHours) ||
                  pts.some((p) =>
                    isWithinSelectedFilter(p.reported_at, selectedFilterHours),
                  );
                const alpha = clusterInFilter ? 1 : 0.35;
                const hull = Array.isArray(h.boundary_points) && h.boundary_points.length >= 3
                  ? h.boundary_points
                  : convexHull(pts.map((p) => ({ lat: p.latitude, lng: p.longitude })));
                const types = [...new Set(pts.map((p) => p.incident_type_name).filter(Boolean))];

                return (
                  <React.Fragment key={`hs-${h.hotspot_id}`}>
                    {h.radius_meters > 0 && (
                      <Circle
                        center={[h.lat, h.lng]}
                        radius={h.radius_meters}
                        pathOptions={{
                          color: zoneColor,
                          weight: 2.5,
                          opacity: alpha * 0.9,
                          fillColor: zoneColor,
                          fillOpacity: alpha * 0.12,
                        }}
                      />
                    )}

                    {hull.length >= 3 && (
                      <Polygon
                        positions={hull}
                        pathOptions={{
                          color: zoneColor,
                          weight: 3,
                          opacity: alpha * 0.95,
                          fillColor: zoneColor,
                          fillOpacity: alpha * 0.2,
                          dashArray: "8 5",
                        }}
                      />
                    )}

                    {pts.length > 1 && (
                      <Marker
                        position={[h.lat, h.lng]}
                        icon={createClusterIcon(
                          pts.length || h.incident_count,
                          zoneColor,
                          getReportRiskBorder(zoneColor),
                          alpha,
                        )}
                        zIndexOffset={900}
                      >
                        <Tooltip direction="top" offset={[0, -18]} opacity={0.97} interactive={false}>
                          <div style={{ fontSize: "11px", lineHeight: 1.6 }}>
                            <strong>Cluster {hIdx + 1}</strong>
                            <br />
                            {pts.length || h.incident_count} incidents · {getReportRiskLabel(zoneColor)}
                            <br />
                            {types.slice(0, 3).join(", ")}
                          </div>
                        </Tooltip>
                      </Marker>
                    )}
                  </React.Fragment>
                );
              })}

              {filteredConfirmedOnMap.map((r) => {
                const inFilter = isWithinSelectedFilter(r.reported_at, selectedFilterHours);
                const alpha = inFilter ? 1 : 0.35;
                const fill = getReportRiskColor(r, plottedHotspots);
                const border = getReportRiskBorder(fill);
                return (
                  <Marker
                    key={`inc-${r.report_id}`}
                    position={[r.lat, r.lng]}
                    icon={createDiamondIcon(fill, border, alpha)}
                    zIndexOffset={800}
                  >
                    <Tooltip direction="top" offset={[0, -12]} opacity={0.97} interactive={false}>
                      <div style={{ fontSize: "11px", lineHeight: 1.5 }}>
                        <strong>{r.incident_type_name || "Incident"}</strong>
                        <br />
                        {getReportRiskLabel(fill)}
                        {!inFilter && (
                          <>
                            <br />
                            <span style={{ color: "var(--muted)" }}>Outside selected period</span>
                          </>
                        )}
                      </div>
                    </Tooltip>
                  </Marker>
                );
              })}

            </MapContainer>

            {/* ── Incident type legend — collapsed pill, expands on hover ── */}
            <div
              onMouseEnter={() => setLegendOpen(true)}
              onMouseLeave={() => setLegendOpen(false)}
              style={{ position: "absolute", bottom: 10, left: 10, zIndex: 500, cursor: "default" }}
            >
              {/* Collapsed pill */}
              <div style={{
                background: "rgba(15,23,42,0.92)",
                border: "1px solid rgba(255,255,255,0.15)",
                borderRadius: 8,
                padding: "5px 11px",
                display: "flex",
                alignItems: "center",
                gap: 6,
                backdropFilter: "blur(4px)",
                userSelect: "none",
              }}>
                <div style={{ display: "flex", gap: 3 }}>
                  {incidentTypes.slice(0, 5).map((t) => {
                    const name = t.type_name || "";
                    return <div key={name} style={{ width: 8, height: 8, borderRadius: "50%", background: getIncidentTypeColor(name) }} />;
                  })}
                </div>
                <span style={{ fontSize: 11, fontWeight: 600, color: "#e2e8f0" }}>Legend</span>
              </div>

              {/* Expanded panel */}
              {legendOpen && (
                <div style={{
                  position: "absolute",
                  bottom: "calc(100% + 6px)",
                  left: 0,
                  background: "rgba(15,23,42,0.95)",
                  border: "1px solid rgba(255,255,255,0.12)",
                  borderRadius: 10,
                  padding: "9px 12px",
                  minWidth: 175,
                  backdropFilter: "blur(4px)",
                  pointerEvents: "none",
                }}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 7 }}>
                    Risk zones (Musanze)
                  </div>
                  {[
                    { color: "#ef4444", label: "High-risk cluster" },
                    { color: "#eab308", label: "Medium-risk cluster" },
                    { color: "#22c55e", label: "Low-risk cluster" },
                    { color: "#3b82f6", label: "Rare / isolated incident" },
                  ].map((row) => (
                    <div key={row.label} style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 4 }}>
                      <div style={{
                        width: 10,
                        height: 10,
                        background: row.color,
                        transform: "rotate(45deg)",
                        border: "1.5px solid rgba(255,255,255,0.35)",
                        flexShrink: 0,
                      }} />
                      <span style={{ fontSize: 11, color: "#e2e8f0" }}>{row.label}</span>
                    </div>
                  ))}
                  <div style={{ borderTop: "1px solid rgba(255,255,255,0.08)", marginTop: 6, paddingTop: 6, fontSize: 10, color: "#94a3b8" }}>
                    DBSCAN circles show cluster radius. Outside the selected time period, incidents appear faded.
                  </div>
                </div>
              )}
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
                {formatFilterPeriodLabel(timePeriod, customHours)}
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
                      loadConfirmedReportsForMap();
                      loadHistoricalHotspots();
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
                      time_window_hours: Number(dbscanParams.time_window_hours || 168),
                      radius_meters: Number(dbscanParams.radius_meters || 500),
                      min_incidents: Number(dbscanParams.min_incidents || 2),
                      trust_min: Number(dbscanParams.trust_min || 0),
                    });
                    loadHistoricalHotspots();
                    loadConfirmedReportsForMap();
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
                <col style={{ width: "7%" }} />
                <col style={{ width: "12%" }} />
                <col style={{ width: "11%" }} />
                <col style={{ width: "7%" }} />
                <col style={{ width: "8%" }} />
                <col style={{ width: "8%" }} />
                <col style={{ width: "9%" }} />
                <col style={{ width: "9%" }} />
                <col style={{ width: "11%" }} />
                <col style={{ width: "9%" }} />
                <col style={{ width: "9%" }} />
              </colgroup>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Area</th>
                  <th>Crime Type</th>
                  <th>Reports</th>
                  <th>Radius (m)</th>
                  <th>Trust %</th>
                  <th>Score</th>
                  <th>Classification</th>
                  <th>Risk Level</th>
                  <th>Detected</th>
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
                  const cls = h.classification || hotspotWithStage.stage || "—";
                  return (
                  <tr key={h.hotspot_id}>
                    <td className="smx-cell-id smx-cell-muted">
                      HS-{String(h.hotspot_id).padStart(3, "0")}
                    </td>
                    <td className="smx-cell-strong">
                      <strong>{h.area_label || h.incident_type_name || "—"}</strong>
                    </td>
                    <td className="smx-cell-compact">
                      {h.dominant_crime_type || h.incident_type_name || "—"}
                    </td>
                    <td className="smx-cell-strong smx-cell-center">
                      {h.incident_count}
                    </td>
                    <td className="smx-cell-center">
                      {Number(dbscanParams.radius_meters || h.radius_meters || 0)}
                    </td>
                    <td className="smx-cell-center">
                      {h.avg_trust_score != null
                        ? `${Math.round(Number(h.avg_trust_score))}%`
                        : "—"}
                    </td>
                    <td className="smx-cell-center">
                      {h.hotspot_score != null
                        ? Math.round(Number(h.hotspot_score))
                        : "—"}
                    </td>
                    <td className="smx-cell-center">
                      <span
                        className={`risk-pill ${
                          cls === "critical"
                            ? "r-critical"
                            : cls === "active"
                              ? "r-warning"
                              : "r-normal"
                        }`}
                      >
                        {String(cls).toUpperCase().slice(0, 5)}
                      </span>
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
                {!filteredHistoricalHotspots.length && !loading && (
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
            {loading ? (
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

// ─── Unit lookup — fallback when backend doesn't supply a unit ───────────────
const UNIT_LOOKUP = [
  { match: /assault|fight|attack|violence|battery/i,                      unit: "RRU" },
  { match: /theft|robbery|burglary|steal|pickpocket/i,                    unit: "CPU" },
  { match: /drug|narcotic|substance|contraband/i,                          unit: "DEU" },
  { match: /traffic|accident|road|vehicle|speeding/i,                      unit: "TPU" },
  { match: /vandal|destruction|damage|property/i,                          unit: "CPU" },
  { match: /suspicious|loiter|trespass|stalking|harassment|threat/i,       unit: "ISU" },
  { match: /fraud|scam|financial/i,                                         unit: "AFU" },
  { match: /domestic|gender|victim/i,                                       unit: "VPU" },
];

function resolveUnit(typeName) {
  const t = typeName || "";
  const match = UNIT_LOOKUP.find((u) => u.match.test(t));
  return { unit: match ? match.unit : "Patrol" };
}

/** Single severity dot — the only decorative symbol on each card. */
function severityDot(alarm) {
  if (alarm >= 75) return "🔴";
  if (alarm >= 50) return "🟠";
  if (alarm >= 30) return "🟡";
  return "🟢";
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
const SecurityRecommendations = ({ hotspots }) => {
  const sorted = useMemo(() => {
    if (!hotspots || hotspots.length === 0) return [];
    return [...hotspots]
      .map((h) => ({ ...h, _alarm: computeAlarm(h) }))
      .sort((a, b) => b._alarm - a._alarm);
  }, [hotspots]);

  if (sorted.length === 0) {
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
          No deployments are required at this time. Continue routine patrols
          and community engagement across all sectors.
        </div>
      </div>
    );
  }

  const totalIncidents = sorted.reduce((s, h) => s + (h.incident_count || 0), 0);
  const peakAlarm = sorted[0]._alarm;
  const peakColor = alarmToColor(peakAlarm);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
      {/* District situation overview bar */}
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

      {/* One recommendation card per hotspot, ordered by alarm severity */}
      {sorted.map((h, idx) => {
        const alarm = h._alarm;
        const color = alarmToColor(alarm);
        const { unit: fallbackUnit } = resolveUnit(h.incident_type_name);
        // Prefer the unit resolved by the backend (pulled from DB), fall back to frontend lookup
        const unit = h.prediction?.recommended_unit || fallbackUnit;
        const dot = severityDot(alarm);
        const narrative = buildNarrative(h);
        const action = buildAction(h, unit);
        const area = h.area_label || "Unknown area";
        const sectors = [...new Set(
          (h.incident_points || []).map((p) => p.sector_name).filter(Boolean)
        )].join(", ") || "—";

        return (
          <div key={h.hotspot_id || idx} style={{
            borderRadius: "10px",
            border: "1px solid var(--border)",
            backgroundColor: "var(--surface)",
            overflow: "hidden",
            display: "flex",
          }}>
            {/* Severity stripe — thin left bar, only colored element on the card */}
            <div style={{
              width: "4px", flexShrink: 0,
              backgroundColor: color,
            }} />

            <div style={{ flex: 1, minWidth: 0 }}>
              {/* Header */}
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
                {/* Level badge — small pill, only coloured element in header */}
                <span style={{
                  fontSize: "9px", fontWeight: 800, letterSpacing: "0.06em",
                  padding: "2px 7px", borderRadius: "99px",
                  backgroundColor: color, color: "#fff", flexShrink: 0,
                }}>
                  {alarmLabel(alarm)}
                </span>
              </div>

              {/* Body */}
              <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: "7px" }}>
                {/* Top meta row: alarm index + prediction status + classification */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "4px" }}>
                  <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                    {h.classification && (
                      <span style={{
                        fontSize: "9px", fontWeight: 700, padding: "1px 6px",
                        borderRadius: "99px", border: `1px solid ${color}88`,
                        color, textTransform: "uppercase", letterSpacing: "0.05em",
                      }}>
                        {h.classification}
                      </span>
                    )}
                    {h.prediction?.status && (
                      <span style={{
                        fontSize: "9px", fontWeight: 600, padding: "1px 6px",
                        borderRadius: "99px", backgroundColor: "var(--border)",
                        color: "var(--text)", letterSpacing: "0.04em",
                      }}>
                        {String(h.prediction.status).replace(/_/g, " ")}
                      </span>
                    )}
                    {h.cluster_kind && (
                      <span style={{ fontSize: "9px", color: "var(--muted)" }}>
                        {h.cluster_kind === "mixed_hotspot" ? "mixed" : "single-type"}
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: "9px", color: "var(--muted)" }}>
                    alarm <strong style={{ color }}>{Math.round(alarm)}/100</strong>
                    {h.classification_confidence != null && (
                      <span> · conf {Math.round(Number(h.classification_confidence) * 100)}%</span>
                    )}
                    {h.hotspot_score != null && (
                      <span> · score {Math.round(Number(h.hotspot_score))}</span>
                    )}
                  </div>
                </div>

                {/* Situation — narrative from LLM */}
                <div style={{
                  fontSize: "11px", color: "var(--text)", lineHeight: 1.5,
                  padding: "7px 10px", borderRadius: "6px",
                  backgroundColor: "var(--background)",
                  border: "1px solid var(--border)",
                }}>
                  <div style={{
                    fontSize: "9px", fontWeight: 700, color: "var(--muted)",
                    letterSpacing: "0.07em", marginBottom: "3px",
                  }}>
                    SITUATION
                  </div>
                  {narrative}
                </div>

                {/* Incident mix — show per-crime breakdown when more than one type */}
                {h.incident_mix && Object.keys(h.incident_mix).length > 1 && (
                  <div style={{
                    display: "flex", gap: "5px", flexWrap: "wrap",
                    padding: "5px 8px", borderRadius: "6px",
                    backgroundColor: "var(--background)",
                    border: "1px solid var(--border)",
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

                {/* Recommended action — from LLM */}
                <div style={{
                  fontSize: "11px", color: "var(--text)", lineHeight: 1.5,
                  padding: "7px 10px", borderRadius: "6px",
                  backgroundColor: "var(--background)",
                  border: "1px solid var(--border)",
                  borderLeft: `3px solid ${color}`,
                }}>
                  <div style={{
                    fontSize: "9px", fontWeight: 700, color,
                    letterSpacing: "0.07em", marginBottom: "3px",
                  }}>
                    RECOMMENDED ACTION
                  </div>
                  {action}
                </div>

                {/* Operation window — always show when available */}
                {(h.prediction?.operation_hours || h.prediction?.concentrate_window) && (
                  <div style={{
                    display: "flex", gap: "10px", flexWrap: "wrap",
                    padding: "5px 10px", borderRadius: "6px",
                    backgroundColor: `${color}0d`,
                    border: `1px solid ${color}33`,
                    fontSize: "10px", color: "var(--text)",
                  }}>
                    {h.prediction?.operation_hours && (
                      <span>
                        <span style={{ color: "var(--muted)" }}>Duration: </span>
                        <strong>{h.prediction.operation_hours} h</strong>
                      </span>
                    )}
                    {h.prediction?.concentrate_window && (
                      <span>
                        <span style={{ color: "var(--muted)" }}>Concentrate: </span>
                        <strong>{h.prediction.concentrate_window}</strong>
                      </span>
                    )}
                    {h.prediction?.peak_time && (
                      <span>
                        <span style={{ color: "var(--muted)" }}>Peak: </span>
                        <strong>{h.prediction.peak_time}</strong>
                      </span>
                    )}
                  </div>
                )}

                {/* Metadata strip */}
                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", fontSize: "10px", color: "var(--muted)" }}>
                  <span>Trust: <strong style={{ color: "var(--text)" }}>{Math.round(h.avg_trust_score || 0)}%</strong></span>
                  {h.prediction?.predicted_increase_pct > 0 && (
                    <span>Growth: <strong style={{ color }}>{h.prediction.predicted_increase_pct}%</strong></span>
                  )}
                  <span>Radius: <strong style={{ color: "var(--text)" }}>{Math.round(Number(h.radius_meters || 0))} m</strong></span>
                  <span>State: <strong style={{ color: "var(--text)" }}>{h.lifecycle_state || "—"}</strong></span>
                </div>
              </div>
            </div>
          </div>
        );
      })}

      <div style={{ fontSize: "10px", color: "var(--muted)", textAlign: "center", paddingTop: "2px" }}>
        Recommendations derived from live verified hotspot data · Commanding officer approval required before execution
      </div>
    </div>
  );
};

export default SafetyMap;
