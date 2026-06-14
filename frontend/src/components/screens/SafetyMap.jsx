import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Circle,
  Tooltip,
  ZoomControl,
  Polygon,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import api, { cacheBust } from "../../api/client";

const MUSANZE_CENTER = [-1.5042, 29.638]; // Musanze district center
const MUSANZE_ZOOM = 12;
const MUSANZE_BUFFER_KM = 0.5;
const DEFAULT_TIME_PERIOD = ""; // All-time view by default for police dashboard

/** Derive sidebar stats from persisted hotspot rows (same source as map polygons). */
/**
 * Client-side report-date filter — only when the API was loaded without time_period.
 * If the backend already filtered by week/month, do not re-filter (that was splitting
 * multi-report clusters into singles on the map).
 */
const applyReportTimeWindow = (hotspots, filterHours) => {
  const list = Array.isArray(hotspots) ? hotspots : [];
  if (filterHours == null) return list;
  const cutoff = Date.now() - filterHours * 60 * 60 * 1000;
  return list
    .map((h) => {
      const rawPts = Array.isArray(h.incident_points) ? h.incident_points : [];
      const pts = rawPts.filter((p) => {
        if (!p?.reported_at) return true;
        const t = new Date(p.reported_at).getTime();
        return Number.isFinite(t) && t >= cutoff;
      });
      // IMPORTANT: keep the original DB incident_count, never override it with
      // the filtered point count.  The stored count reflects the actual cluster
      // size used by DBSCAN; reducing it here causes valid 2-report clusters to
      // appear as single-point clusters and then be silently hidden by the
      // showSinglesOnMap filter.  We only swap out incident_points so the detail
      // panel shows the time-relevant subset, not the full cluster history.
      return {
        ...h,
        incident_points: pts,
        _active_in_period: pts.length > 0,
        // incident_count is intentionally NOT overwritten here.
      };
    })
    .filter((h) => h._active_in_period);
};

const buildStatsFromHotspots = (hotspots) => {
  const list = Array.isArray(hotspots) ? hotspots : [];
  const uniqueReportIds = new Set();
  let reportsIn = 0;
  let clusters = 0;
  let high = 0;
  let medium = 0;
  let low = 0;
  const trusts = [];
  let latestMs = 0;

  for (const h of list) {
    const pts = Array.isArray(h.incident_points) ? h.incident_points : [];
    const count = pts.length > 0 ? pts.length : Number(h.incident_count) || 0;
    reportsIn += count;
    pts.forEach((p) => {
      if (p?.report_id) uniqueReportIds.add(String(p.report_id));
    });

    const tier = resolveHotspotRiskTier(h);
    if (tier === "critical" || tier === "high") high++;
    else if (tier === "medium") medium++;
    else low++;

    if (count >= 2) clusters++;

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
    active_clusters: clusters,
    total_incidents: reportsIn,
    reports_in_clusters: reportsIn,
    unique_reports: uniqueReportIds.size,
    risk_counts: { critical: high, warning: medium, normal: low },
    stage_counts: { emerging: low, active: medium, intense: high },
    avg_cluster_trust:
      trusts.length > 0
        ? Math.round(trusts.reduce((a, b) => a + b, 0) / trusts.length)
        : null,
    latest_cluster_run:
      latestMs > 0 ? new Date(latestMs).toLocaleString() : "Never",
  };
};

/**
 * Compare this-week vs previous-week hotspot counts to detect rising trends.
 * Returns { totalTrend, highTrend, mediumTrend, lowTrend } each: 'rising' | 'falling' | 'stable'
 */
const computeWeekTrends = (hotspots) => {
  const list = Array.isArray(hotspots) ? hotspots : [];
  const now = Date.now();
  const oneWeek = 7 * 24 * 60 * 60 * 1000;
  const thisWeekCutoff = now - oneWeek;
  const prevWeekCutoff = now - 2 * oneWeek;

  const bucket = { thisWeek: { total: 0, high: 0, medium: 0, low: 0 }, prevWeek: { total: 0, high: 0, medium: 0, low: 0 } };
  for (const h of list) {
    const t = h.detected_at ? new Date(h.detected_at).getTime() : 0;
    if (!Number.isFinite(t)) continue;
    const tier = resolveHotspotRiskTier(h);
    const isHigh = tier === 'critical' || tier === 'high';
    const isMed = tier === 'medium';
    if (t >= thisWeekCutoff) {
      bucket.thisWeek.total++;
      if (isHigh) bucket.thisWeek.high++;
      else if (isMed) bucket.thisWeek.medium++;
      else bucket.thisWeek.low++;
    } else if (t >= prevWeekCutoff) {
      bucket.prevWeek.total++;
      if (isHigh) bucket.prevWeek.high++;
      else if (isMed) bucket.prevWeek.medium++;
      else bucket.prevWeek.low++;
    }
  }
  const trend = (curr, prev) => curr > prev ? 'rising' : curr < prev ? 'falling' : 'stable';
  return {
    totalTrend:  trend(bucket.thisWeek.total, bucket.prevWeek.total),
    highTrend:   trend(bucket.thisWeek.high, bucket.prevWeek.high),
    mediumTrend: trend(bucket.thisWeek.medium, bucket.prevWeek.medium),
    lowTrend:    trend(bucket.thisWeek.low, bucket.prevWeek.low),
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

const formatFilterPeriodLabel = (timePeriod, customHours) => {
  const hours = getSelectedFilterHours(timePeriod, customHours);
  if (hours == null) return "All time";
  return formatTimeWindow(hours);
};

/** Green / yellow / red tiers — prefer live API classification over stale DB risk_level. */
const MAP_RISK_COLORS = {
  critical: "#dc2626",
  high: "#dc2626",
  medium: "#eab308",
  low: "#22c55e",
};

const resolveHotspotRiskTier = (hotspot) => {
  const classification = String(hotspot?.classification || "").toLowerCase().trim();
  if (classification === "critical") return "critical";
  if (classification === "active") return "high";
  if (classification === "emerging") return "medium";
  if (classification === "low_activity") return "low";

  const rl = String(hotspot?.risk_level || "").toLowerCase().trim();
  if (rl === "critical") return "critical";
  if (rl === "high" || rl === "active") return "high";
  if (rl === "medium" || rl === "emerging") return "medium";
  if (rl === "low" || rl === "low_activity") return "low";

  const score = Number(hotspot?.hotspot_score);
  if (Number.isFinite(score)) {
    if (score >= 80) return "critical";
    if (score >= 60) return "high";
    if (score >= 40) return "medium";
  }
  return "low";
};

const getMapRiskColor = (hotspot) =>
  MAP_RISK_COLORS[resolveHotspotRiskTier(hotspot)] || MAP_RISK_COLORS.low;

const getReportRiskBorder = (fillColor) => {
  const borders = {
    "#dc2626": "#7f1d1d",
    "#eab308": "#854d0e",
    "#22c55e": "#15803d",
  };
  return borders[fillColor] || "#1e293b";
};

const getReportRiskLabel = (fillColor) => {
  if (fillColor === "#dc2626") return "High-risk area";
  if (fillColor === "#eab308") return "Medium-risk area";
  if (fillColor === "#22c55e") return "Low-risk area";
  return "Cluster";
};

const incidentTone = {
  theft: "danger",
  assault: "danger",
  vandalism: "warning",
  suspicious: "violet",
  traffic: "info",
  drug: "success",
  "drug activity": "success",
};

/** Fly map to a cluster when user picks a table row or cluster. */
const MapFlyTo = ({ lat, lng, triggerId }) => {
  const map = useMap();
  useEffect(() => {
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
    map.flyTo([lat, lng], Math.max(map.getZoom(), 14), { duration: 0.75 });
  }, [lat, lng, triggerId, map]);
  return null;
};

const RelocatorControl = ({ maxBounds }) => {
  const map = useMap();

  const handleRelocate = useCallback(() => {
    if (maxBounds) {
      map.fitBounds(maxBounds, {
        padding: [12, 12],
        animate: true,
      });
      return;
    }
    map.flyTo(MUSANZE_CENTER, MUSANZE_ZOOM, { duration: 1.5 });
  }, [map, maxBounds]);

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
          &#8634;
        </button>
      `;

      div.querySelector("button").addEventListener("click", handleRelocate);
      return div;
    };

    relocateControl.addTo(map);

    return () => {
      map.removeControl(relocateControl);
    };
  }, [map, handleRelocate]);

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

// ── Module-level cache ─────────────────────────────────────────────────────
const _mapHotCache = {}; // { [timePeriod_customHours]: hotspots[] }

/** Sector → distinct color (deterministic palette for up to ~20 sectors). */
const SECTOR_COLORS = [
  "#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6",
  "#ec4899", "#06b6d4", "#f97316", "#14b8a6", "#a855f7",
  "#84cc16", "#e11d48", "#0ea5e9", "#d946ef", "#22d3ee",
  "#facc15", "#4ade80", "#fb7185", "#38bdf8", "#a78bfa",
];
const _sectorColorMap = {};
let _sectorIdx = 0;
const getSectorColor = (sectorName) => {
  if (!sectorName) return "#64748b";
  if (!_sectorColorMap[sectorName]) {
    _sectorColorMap[sectorName] = SECTOR_COLORS[_sectorIdx % SECTOR_COLORS.length];
    _sectorIdx++;
  }
  return _sectorColorMap[sectorName];
};

const SafetyMap = ({ goToScreen, wsRefreshKey, focusHotspotId, focusCoords }) => {
  const _defaultKey = `${DEFAULT_TIME_PERIOD}_`;
  const [loading, setLoading] = useState(!_mapHotCache[`${DEFAULT_TIME_PERIOD}_`]);
  // Dark mode detection — syncs with body.dark-mode class toggle
  const [isDarkMode, setIsDarkMode] = useState(() =>
    typeof document !== "undefined" && document.body.classList.contains("dark-mode"),
  );
  useEffect(() => {
    const obs = new MutationObserver(() => {
      setIsDarkMode(document.body.classList.contains("dark-mode"));
    });
    obs.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);
  const [backgroundRefreshing, setBackgroundRefreshing] = useState(false);
  const [typeFilter, setTypeFilter] = useState("all"); // 'all' | incident_type_name
  const [timePeriod, setTimePeriod] = useState(DEFAULT_TIME_PERIOD); // '', 'day', 'week', 'month', 'quarter', 'year' — default 30 days
  const [customHours, setCustomHours] = useState(""); // Custom hours input
  const [historicalHotspots, setHistoricalHotspots] = useState(_mapHotCache[`${DEFAULT_TIME_PERIOD}_`] ?? []);
  /** True when last /hotspots fetch included time_period or hours_back (backend already filtered). */
  const [apiTimeFilterActive, setApiTimeFilterActive] = useState(false);
  const [hotspotStats, setHotspotStats] = useState({
    total_clusters: 0,
    reports_in_clusters: 0,
    unique_reports: 0,
    total_incidents: 0,
    risk_counts: { critical: 0, warning: 0, normal: 0 },
    stage_counts: { emerging: 0, active: 0, intense: 0 },
    avg_cluster_trust: null,
    latest_cluster_run: "Never"
  });
  const [weekTrends, setWeekTrends] = useState({ totalTrend: 'stable', highTrend: 'stable', mediumTrend: 'stable', lowTrend: 'stable' });
  const [polygons, setPolygons] = useState([]);
  const [incidentTypes, setIncidentTypes] = useState([]);
  const [selectedHotspotId, setSelectedHotspotId] = useState(null);
  const [focusNonce, setFocusNonce] = useState(0);
  const [mapFocusId, setMapFocusId] = useState(null);
  const [directFocusCoords, setDirectFocusCoords] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [showSinglesOnMap, setShowSinglesOnMap] = useState(true);
  const [showVillageBoundaries, setShowVillageBoundaries] = useState(true);
  const [allIncidents, setAllIncidents] = useState([]);
  const [legendOpen, setLegendOpen] = useState(false);
  /** Read-only defaults from system config (DBSCAN lives under System Configuration). */
  const [clusterDefaults, setClusterDefaults] = useState({
    radius_meters: 500,
    time_window_hours: 168,
  });
  const [mapZoom, setMapZoom] = useState(MUSANZE_ZOOM);
  const [selectedCluster, setSelectedCluster] = useState(null); // hotspot object for detail panel

  // Fetch ALL verified incidents — both clustered and standalone.
  // Police dashboard defaults to all-time; the time filter is applied server-side
  // only when the user explicitly selects a period.
  useEffect(() => {
    const params = new URLSearchParams();
    params.set("limit", "3000");
    const filterHours = getSelectedFilterHours(timePeriod, customHours);
    if (filterHours != null) {
      params.set("hours_back", String(filterHours));
    }
    api
      .get(`/api/v1/hotspots/all-incidents?${params}`)
      .then((res) => setAllIncidents(Array.isArray(res) ? res : []))
      .catch(() => setAllIncidents([]));
  }, [wsRefreshKey, timePeriod, customHours]);

  const focusClusterOnMap = (h) => {
    if (!h) {
      setSelectedCluster(null);
      setSelectedHotspotId(null);
      setMapFocusId(null);
      return;
    }
    // Navigate to hotspot details screen on click
    goToScreen("hotspot-details", 0, { hotspotId: h.hotspot_id });
  };

  const singlesDefaultApplied = useRef(false);

  const loadHistoricalHotspots = ({ silent = false } = {}) => {
    const cacheKey = `${timePeriod}_${customHours}`;
    const cached = _mapHotCache[cacheKey];
    if (silent || cached) {
      setBackgroundRefreshing(true);
    } else {
      setLoading(true);
    }
    setLoadError(null);
    cacheBust("/api/v1/hotspots");
    const params = new URLSearchParams();
    params.set("limit", "500");
    params.set("for_map", "true");
    const hasApiTimeFilter =
      (timePeriod && timePeriod !== "") ||
      (customHours && customHours !== "" && Number(customHours) > 0);
    if (timePeriod && timePeriod !== "") {
      params.set("time_period", timePeriod);
    } else if (customHours && customHours !== "") {
      params.set("hours_back", customHours);
    }
    api
      .get(`/api/v1/hotspots/?${params.toString()}`)
      .then((res) => {
        const raw = res || [];
        const seen = new Set();
        const rows = raw.filter((h) => {
          if (seen.has(h.hotspot_id)) return false;
          seen.add(h.hotspot_id);
          return true;
        });
        _mapHotCache[cacheKey] = rows;
        setApiTimeFilterActive(hasApiTimeFilter);
        setHistoricalHotspots(rows);
        setLoading(false);
        setBackgroundRefreshing(false);
      })
      .catch((err) => {
        setLoadError(err?.message || "Failed to load hotspots");
        setLoading(false);
        setBackgroundRefreshing(false);
      });
  };

  useEffect(() => {
    const cacheKey = `${timePeriod}_${customHours}`;
    if (_mapHotCache[cacheKey]) {
      setHistoricalHotspots(_mapHotCache[cacheKey]);
      loadHistoricalHotspots({ silent: true });
    } else {
      loadHistoricalHotspots({ silent: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsRefreshKey]);

  const selectedFilterHours = useMemo(
    () => getSelectedFilterHours(timePeriod, customHours),
    [timePeriod, customHours],
  );

  useEffect(() => {
    loadHistoricalHotspots();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timePeriod, customHours]);

  useEffect(() => {
    api
      .get("/api/v1/hotspots/params")
      .then((res) => {
        if (!res) return;
        setClusterDefaults((p) => ({ ...p, ...res }));
        loadHistoricalHotspots();
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-focus hotspot when navigated from hotspot-details "View on Map"
  useEffect(() => {
    if (!focusHotspotId || !historicalHotspots.length) return;
    const target = historicalHotspots.find(h => h.hotspot_id == focusHotspotId);
    if (target) {
      setSelectedCluster(target);
      setSelectedHotspotId(target.hotspot_id);
      setMapFocusId(target.hotspot_id);
      setFocusNonce((n) => n + 1);
    }
  }, [focusHotspotId, historicalHotspots]);

  // Auto-focus coordinates when navigated from case "View on Map"
  useEffect(() => {
    if (!focusCoords) return;
    const { lat, lon } = focusCoords;
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    setDirectFocusCoords({ lat, lng: lon });
    setFocusNonce((n) => n + 1);
  }, [focusCoords]);

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

  const timeFilteredHotspots = useMemo(() => {
    if (apiTimeFilterActive) {
      return historicalHotspots;
    }
    return applyReportTimeWindow(historicalHotspots, selectedFilterHours);
  }, [historicalHotspots, selectedFilterHours, apiTimeFilterActive]);

  useEffect(() => {
    setHotspotStats(buildStatsFromHotspots(timeFilteredHotspots));
    setWeekTrends(computeWeekTrends(timeFilteredHotspots));
  }, [timeFilteredHotspots]);

  const filteredHotspots = useMemo(() => {
    if (typeFilter === "all") return timeFilteredHotspots;
    const tf = typeFilter.toLowerCase();
    return timeFilteredHotspots.filter((h) => {
      // Show cluster if it CONTAINS the selected incident type
      // (mixed clusters have multiple types in incident_mix)
      const mix = h.incident_mix || h.composition || {};
      if (typeof mix === "object" && Object.keys(mix).some(
        (k) => k.toLowerCase() === tf
      )) return true;
      if ((h.incident_type_name || "").toLowerCase() === tf) return true;
      if ((h.dominant_crime_type || "").toLowerCase() === tf) return true;
      return false;
    });
  }, [timeFilteredHotspots, typeFilter]);

  // Filter all-incidents dots by type when a specific type is selected
  const filteredIncidents = useMemo(() => {
    if (typeFilter === "all") return allIncidents;
    const tf = typeFilter.toLowerCase();
    return allIncidents.filter(
      (p) => (p.incident_type_name || "").toLowerCase() === tf,
    );
  }, [allIncidents, typeFilter]);

  const plottedHotspots = useMemo(
    () =>
      filteredHotspots
        .map((h) => ({
          ...h,
          lat: Number(h.center_lat),
          lng: Number(h.center_long),
          radius_meters: Number(h.radius_meters || clusterDefaults.radius_meters || 500),
          stage: getFormationStage(h),
        }))
        .filter((h) => Number.isFinite(h.lat) && Number.isFinite(h.lng)),
    [filteredHotspots, clusterDefaults.radius_meters],
  );

  // Count genuine single-report clusters using the raw API value stored in
  // historicalHotspots, not the potentially time-filtered plottedHotspots.
  // Using plottedHotspots here would inflate the count whenever the client-side
  // time filter reduces a valid 2-report cluster's displayed point count,
  // triggering the auto-hide and removing real hotspots from the map.
  const singleClusterCount = useMemo(
    () =>
      historicalHotspots.filter((h) => (Number(h.incident_count) || 0) < 2)
        .length,
    [historicalHotspots],
  );

  useEffect(() => {
    if (singlesDefaultApplied.current || loading) return;
    if (singleClusterCount > 50) {
      setShowSinglesOnMap(false);
      singlesDefaultApplied.current = true;
    }
  }, [singleClusterCount, loading]);

  const mapRenderableHotspots = useMemo(() => {
    if (showSinglesOnMap) return plottedHotspots;
    return plottedHotspots.filter((h) => {
      const n = Number(h.incident_count) || 0;
      return n >= 2 || selectedCluster?.hotspot_id === h.hotspot_id;
    });
  }, [plottedHotspots, showSinglesOnMap, selectedCluster?.hotspot_id]);

  const mapFocusTarget = useMemo(() => {
    if (directFocusCoords) {
      return { lat: directFocusCoords.lat, lng: directFocusCoords.lng, id: "coords" };
    }
    const h =
      selectedCluster ||
      plottedHotspots.find((x) => x.hotspot_id === mapFocusId) ||
      null;
    if (!h) return null;
    return { lat: h.lat, lng: h.lng, id: h.hotspot_id };
  }, [selectedCluster, plottedHotspots, mapFocusId, directFocusCoords]);

  // filteredHistoricalHotspots = plottedHotspots so table count always matches map circles
  const filteredHistoricalHotspots = plottedHotspots;

  // Pagination for hotspot table
  const [clusterPage, setClusterPage] = useState(1);
  const CLUSTERS_PER_PAGE = 10;
  const totalClusterPages = Math.max(1, Math.ceil(filteredHistoricalHotspots.length / CLUSTERS_PER_PAGE));
  const pagedHotspots = filteredHistoricalHotspots.slice(
    (clusterPage - 1) * CLUSTERS_PER_PAGE,
    clusterPage * CLUSTERS_PER_PAGE
  );
  // Reset to page 1 when filters change
  useEffect(() => { setClusterPage(1); }, [filteredHistoricalHotspots.length]);

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

  const toneForType = (name) => {
    if (!name) return "neutral";
    return incidentTone[String(name).toLowerCase()] || "neutral";
  };

  /** Map dots and zones — green / yellow / red from classification + score. */
  const getHotspotDotColor = (hotspot) => getMapRiskColor(hotspot);

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
      {/* ── Page header + unified stats ── */}
      <div className="card" style={{ marginBottom: 16, padding: '18px 20px 16px' }}>

        {/* Title row */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10, marginBottom: 16 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 3 }}>
              <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Community Safety Map</h2>
              {backgroundRefreshing && (
                <span style={{ fontSize: 11, color: 'var(--muted)', fontStyle: 'italic' }}>refreshing…</span>
              )}
            </div>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: 12 }}>
              Musanze District · {formatFilterPeriodLabel(timePeriod, customHours)} · polygons show cluster boundaries, dots show individual incidents
            </p>
          </div>
          <button
            type="button"
            className="btn btn-outline btn-sm"
            style={{ flexShrink: 0 }}
            onClick={() => {
              const mapElement = document.querySelector(".leaflet-container");
              if (!mapElement) { alert("Map not found. Please try again."); return; }
              const printWindow = window.open("", "_blank");
              if (!printWindow) { alert("Please allow popups for this website to export the map."); return; }
              const exportScript = document.createElement("script");
              exportScript.src = "https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js";
              document.head.appendChild(exportScript);
              exportScript.onload = () => {
                if (typeof window.html2canvas !== "function") { alert("Export library failed to load."); return; }
                window.html2canvas(mapElement, { useCORS: true, allowTaint: true, backgroundColor: null, scale: 2, logging: false })
                  .then((captureCanvas) => {
                    const imageData = captureCanvas.toDataURL("image/png");
                    printWindow.document.write(`<!DOCTYPE html><html><head><title>Safety Map Export</title></head><body style="margin:0;padding:20px;font-family:Arial,sans-serif"><h1>TrustBond Safety Map</h1><p>${new Date().toLocaleString()} · ${formatFilterPeriodLabel(timePeriod, customHours)}</p><img src="${imageData}" style="width:100%;max-width:1200px;border:1px solid #ccc" /><script>window.onload=function(){setTimeout(function(){window.print();},800);};<\/script></body></html>`);
                    printWindow.document.close();
                  }).catch(() => alert("Could not capture map image."));
              };
            }}
          >
            Export Map PDF
          </button>
        </div>

        {/* Primary stats — 4 large cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 12 }}>
          {[
            { label: 'Total Clusters',  value: hotspotStats.total_clusters, cls: 'sb-blue',   trend: weekTrends.totalTrend  },
            { label: 'High Risk',       value: hotspotStats.risk_counts.critical, cls: 'sb-red',    trend: weekTrends.highTrend   },
            { label: 'Medium Risk',     value: hotspotStats.risk_counts.warning, cls: 'sb-orange', trend: weekTrends.mediumTrend },
            { label: 'Low Risk',        value: hotspotStats.risk_counts.normal, cls: 'sb-green',  trend: weekTrends.lowTrend    },
          ].map((s) => (
            <div key={s.label} className={`stat-btn ${s.cls}`} style={{ cursor: 'default', position: 'relative' }}>
              <div className="stat-btn-label">{s.label}</div>
              <div className="stat-btn-value" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                {loading ? '—' : (s.value ?? '0')}
                {!loading && s.trend !== 'stable' && (
                  <span
                    title={s.trend === 'rising' ? 'Rising vs last week' : 'Falling vs last week'}
                    style={{
                      fontSize: 12,
                      fontWeight: 700,
                      color: s.trend === 'rising' ? '#ef4444' : '#22c55e',
                    }}
                  >
                    {s.trend === 'rising' ? '\u2191' : '\u2193'}
                  </span>
                )}
              </div>
              {!loading && s.trend !== 'stable' && (
                <div style={{
                  fontSize: 9,
                  fontWeight: 600,
                  textAlign: 'center',
                  marginTop: 2,
                  color: s.trend === 'rising' ? '#ef4444' : '#22c55e',
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                }}>
                  {s.trend === 'rising' ? 'Rising' : 'Falling'} vs last week
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Secondary stats — thin row */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 0, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
          {[
            { label: 'Reports on map',  value: filteredIncidents.length || '—' },
            { label: 'Emerging / Active / Intense', value: `${hotspotStats.stage_counts.emerging} / ${hotspotStats.stage_counts.active} / ${hotspotStats.stage_counts.intense}` },
            { label: 'Avg trust score', value: hotspotStats.avg_cluster_trust != null ? `${hotspotStats.avg_cluster_trust} / 100` : '—' },
            { label: 'Last cluster run', value: hotspotStats.latest_cluster_run ?? '—' },
            { label: 'Cluster params',  value: 'System Configuration', isLink: true },
          ].map((item) => (
            <div key={item.label} style={{ padding: '4px 12px', borderRight: '1px solid var(--border)', lastChild: { borderRight: 'none' } }}>
              <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: 3 }}>{item.label}</div>
              <div style={{ fontSize: 13, fontWeight: 600, color: item.isLink ? 'var(--accent)' : 'var(--text)' }}>
                {loading ? '…' : item.value}
              </div>
            </div>
          ))}
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
          {filteredIncidents.length} incidents · {mapRenderableHotspots.length} clusters ·{" "}
          {typeFilter !== "all" ? `${typeFilter} · ` : ""}{formatFilterPeriodLabel(timePeriod, customHours)}
        </span>
        <label
          style={{
            marginLeft: 12,
            fontSize: 11,
            color: "var(--muted)",
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <input
            type="checkbox"
            checked={showSinglesOnMap}
            onChange={(e) => setShowSinglesOnMap(e.target.checked)}
          />
          Show 1-report hotspots ({singleClusterCount})
        </label>
        <label
          style={{
            marginLeft: 12,
            fontSize: 11,
            color: "var(--muted)",
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <input
            type="checkbox"
            checked={showVillageBoundaries}
            onChange={(e) => setShowVillageBoundaries(e.target.checked)}
          />
          Village boundaries
        </label>
      </div>

      {loadError && (
        <div className="alert alert-danger" style={{ marginBottom: 12 }}>
          <span className="alert-icon">!</span>
          <div>{loadError}</div>
        </div>
      )}

      <div className="map-container map-container--full">
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
              {mapFocusTarget && (
                <MapFlyTo
                  lat={mapFocusTarget.lat}
                  lng={mapFocusTarget.lng}
                  triggerId={`${mapFocusTarget.id}-${focusNonce}`}
                />
              )}
              <TileLayer
                attribution="&copy; OpenStreetMap &amp; CartoDB"
                url={isDarkMode
                  ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                  : "https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png"}
                opacity={0.35}
              />
              <ZoomControl position="topright" />
              <RelocatorControl maxBounds={musanzeBounds} />

              {showVillageBoundaries && polygons.map((p) => {
                const sColor = getSectorColor(p.sector);
                return (
                  <Polygon
                    key={p.id}
                    positions={p.positions}
                    pathOptions={{
                      color: sColor,
                      weight: 1.2,
                      opacity: 0.5,
                      fillColor: sColor,
                      fillOpacity: 0.04,
                    }}
                  >
                    <Tooltip
                      direction="top"
                      offset={[0, -2]}
                      opacity={0.95}
                      interactive={false}
                    >
                      <div style={{
                        fontSize: "12px", lineHeight: 1.5, minWidth: 140,
                        borderLeft: `3px solid ${sColor}`,
                      }}>
                        <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 2 }}>
                          {p.village || "Unknown Village"}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--muted)" }}>
                          Cell: {p.cell || "N/A"}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--muted)" }}>
                          Sector: {p.sector || "N/A"}
                        </div>
                      </div>
                    </Tooltip>
                  </Polygon>
                );
              })}

              {/* ── Cluster boundary polygons — RED alert zones ── */}
              {mapRenderableHotspots
                .filter((h) => {
                  const rl = (h.risk_level || "").toLowerCase();
                  return (
                    rl !== "low" && rl !== "low_activity" &&
                    Array.isArray(h.boundary_points) && h.boundary_points.length >= 3
                  );
                })
                .map((h) => {
                  const isSelected = selectedCluster?.hotspot_id === h.hotspot_id;
                  return (
                    <Polygon
                      key={`poly-${h.hotspot_id}`}
                      positions={h.boundary_points}
                      pathOptions={{
                        color: "#dc2626",
                        weight: isSelected ? 4 : 3,
                        opacity: 1,
                        fillColor: "#dc2626",
                        fillOpacity: isSelected ? 0.35 : 0.22,
                      }}
                      eventHandlers={{ click: () => focusClusterOnMap(h) }}
                    >
                      <Tooltip direction="top" offset={[0, -4]} opacity={0.97} interactive={false}>
                        <div style={{ fontSize: 12, lineHeight: 1.5, minWidth: 140 }}>
                          <div style={{ fontWeight: 700, color: "var(--danger)" }}>
                            Cluster · {(h.risk_level || "").toUpperCase()}
                          </div>
                          <div>{h.incident_count} incidents · {h.area_label || "Unknown area"}</div>
                          <div style={{ fontSize: 11, color: "var(--muted)" }}>
                            {(() => {
                              const mix = h.incident_mix || h.composition || {};
                              const types = Object.keys(mix);
                              if (types.length <= 1) return h.dominant_crime_type || h.incident_type_name || "—";
                              const sorted = Object.entries(mix).sort((a,b) => b[1]-a[1]).slice(0, 3);
                              return sorted.map(([k,v]) => `${k}(${v})`).join(", ") + (types.length > 3 ? ` +${types.length-3}` : "");
                            })()}
                          </div>
                        </div>
                      </Tooltip>
                    </Polygon>
                  );
                })}

              {/* ── All verified incidents — unified dot layer (filtered by type) ── */}
              {filteredIncidents.map((p, i) => {
                const lat = Number(p.latitude);
                const lng = Number(p.longitude);
                if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
                const typeColor = getIncidentTypeColor(p.incident_type_name);
                const inCluster = p.in_cluster;
                const parentCluster = inCluster
                  ? mapRenderableHotspots.find((h) => h.hotspot_id === p.hotspot_id)
                  : null;
                const isSelected = parentCluster && selectedCluster?.hotspot_id === parentCluster.hotspot_id;

                const dotRadius = inCluster
                  ? (isSelected ? (mapZoom >= 14 ? 10 : 8) : (mapZoom >= 14 ? 8 : 6))
                  : (mapZoom >= 14 ? 6 : mapZoom >= 12 ? 5 : 4);
                const loc = [p.village_name, p.cell_name, p.sector_name].filter(Boolean).join(", ");

                return (
                  <CircleMarker
                    key={`inc-${p.report_id || i}`}
                    center={[lat, lng]}
                    radius={dotRadius}
                    eventHandlers={parentCluster ? { click: () => focusClusterOnMap(parentCluster) } : {}}
                    pathOptions={inCluster ? {
                      color: "#1e293b",
                      weight: 2,
                      opacity: 1,
                      fillColor: typeColor,
                      fillOpacity: 0.95,
                    } : {
                      color: "#475569",
                      weight: 1.5,
                      opacity: 0.8,
                      fillColor: typeColor,
                      fillOpacity: 0.75,
                      dashArray: "3 2",
                    }}
                  >
                    <Tooltip direction="top" offset={[0, -6]} opacity={0.97} interactive={false}>
                      <div style={{ fontSize: "12px", lineHeight: 1.6, minWidth: 160 }}>
                        <div style={{ fontWeight: 700, marginBottom: 2, color: typeColor }}>
                          {p.incident_type_name || "Incident"}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--muted)" }}>
                          {inCluster
                            ? `Part of cluster · ${(parentCluster?.risk_level || "").toUpperCase()}`
                            : "Standalone · not yet clustered"}
                        </div>
                        <div style={{ color: "var(--text-dim)", fontSize: 11 }}>
                          #{String(p.report_id || "").slice(-6)}
                        </div>
                        {p.reported_at && (
                          <div style={{ fontSize: 11 }}>
                            {new Date(p.reported_at).toLocaleString(undefined, {
                              month: "short", day: "numeric",
                              hour: "2-digit", minute: "2-digit",
                            })}
                          </div>
                        )}
                        {loc && <div style={{ fontSize: 11, color: "var(--muted)" }}>{loc}</div>}
                      </div>
                    </Tooltip>
                  </CircleMarker>
                );
              })}

            </MapContainer>

            {/* ── Map legend — hover to expand ── */}
            <div
              onMouseEnter={() => setLegendOpen(true)}
              onMouseLeave={() => setLegendOpen(false)}
              style={{ position: "absolute", bottom: 10, right: 10, zIndex: 500, cursor: "default" }}
            >
              {/* Collapsed pill */}
              <div style={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                padding: "5px 11px",
                display: "flex",
                alignItems: "center",
                gap: 6,
                backdropFilter: "blur(4px)",
                boxShadow: "0 1px 6px rgba(0,0,0,0.1)",
                userSelect: "none",
              }}>
                <div style={{ display: "flex", gap: 3 }}>
                  {incidentTypes.slice(0, 5).map((t) => {
                    const name = t.type_name || "";
                    return <div key={name} style={{ width: 8, height: 8, borderRadius: "50%", background: getIncidentTypeColor(name) }} />;
                  })}
                </div>
                <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text)" }}>Legend</span>
              </div>

              {/* Expanded panel */}
              {legendOpen && (
                <div style={{
                  position: "absolute",
                  bottom: "calc(100% + 6px)",
                  right: 0,
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 10,
                  padding: "10px 14px",
                  minWidth: 180,
                  backdropFilter: "blur(6px)",
                  boxShadow: "0 4px 16px rgba(0,0,0,0.15)",
                }}>
                  <div style={{
                    fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.07em",
                    color: "var(--muted)", marginBottom: 7,
                  }}>
                    Incident Types
                  </div>
                  {(() => {
                    const typesOnMap = new Set();
                    filteredIncidents.forEach((p) => { if (p.incident_type_name) typesOnMap.add(p.incident_type_name); });
                    incidentTypes.forEach((t) => { if (t.type_name) typesOnMap.add(t.type_name); });
                    return [...typesOnMap].sort().map((name) => (
                      <div key={name} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5, cursor: "pointer" }}
                        onClick={() => setTypeFilter(name)}
                        title={`Filter to ${name}`}
                      >
                        <div style={{
                          width: 12, height: 12, borderRadius: "50%",
                          background: getIncidentTypeColor(name),
                          border: "1.5px solid var(--border2)",
                          flexShrink: 0,
                        }} />
                        <span style={{ fontSize: 11, color: "var(--text)", fontWeight: 500 }}>
                          {name}
                        </span>
                      </div>
                    ));
                  })()}

                  <div style={{
                    borderTop: "1px solid var(--border)",
                    marginTop: 8, paddingTop: 7, fontSize: 10, lineHeight: 1.5,
                    color: "var(--muted)",
                  }}>
                    Highlighted points on the map are clusters.
                    <br />Dashed dots are standalone incidents.
                  </div>
                </div>
              )}
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
              Time Period (report dates on map):
            </div>
            <p style={{ fontSize: 11, color: "var(--muted)", margin: "0 0 8px" }}>
              Filters clusters by report dates — only clusters with incidents in the selected period are shown.
            </p>
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "4px",
                marginBottom: "8px",
              }}
            >
              {[
                { label: "All Time", value: "" },
                { label: "Last 24h", value: "day" },
                { label: "Last Week", value: "week" },
                { label: "Last Month", value: "month" },
                { label: "Last Quarter", value: "quarter" },
                { label: "Last Year", value: "year" },
              ].map(({ label, value }) => (
                <button
                  key={label}
                  className={`btn btn-xs ${timePeriod === value ? "btn-primary" : "btn-outline"}`}
                  onClick={() => {
                    setTimePeriod(value);
                    setCustomHours("");
                  }}
                >
                  {label}
                </button>
              ))}
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
                  <th>Recent Activity</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pagedHotspots.map((h) => {
                  // Add missing fields for historical hotspots
                  const hotspotWithStage = {
                    ...h,
                    stage: getFormationStage(h),
                  };
                  const cls = h.classification || hotspotWithStage.stage || "—";
                  return (
                  <tr
                    key={h.hotspot_id}
                    className={selectedCluster?.hotspot_id === h.hotspot_id ? "smx-row-selected" : ""}
                    style={{
                      cursor: "pointer",
                      background:
                        selectedCluster?.hotspot_id === h.hotspot_id
                          ? "var(--c-accent-dim)"
                          : undefined,
                    }}
                    onClick={() => focusClusterOnMap(h)}
                    onMouseEnter={() => setSelectedCluster(h)}
                  >
                    <td className="smx-cell-id smx-cell-muted">
                      HS-{String(h.hotspot_id).padStart(3, "0")}
                    </td>
                    <td className="smx-cell-strong">
                      <strong>{h.area_label || h.incident_type_name || "—"}</strong>
                    </td>
                    <td className="smx-cell-compact" title={(() => {
                      const mix = h.incident_mix || h.composition || {};
                      return Object.entries(mix).sort((a,b) => b[1]-a[1]).map(([k,v]) => `${k}: ${v}`).join(", ");
                    })()}>
                      {(() => {
                        const mix = h.incident_mix || h.composition || {};
                        const types = Object.keys(mix);
                        if (types.length <= 1) return h.dominant_crime_type || h.incident_type_name || "—";
                        const sorted = Object.entries(mix).sort((a,b) => b[1]-a[1]);
                        return `${sorted[0][0]} +${types.length - 1} more`;
                      })()}
                    </td>
                    <td className="smx-cell-strong smx-cell-center">
                      {h.incident_count}
                    </td>
                    <td className="smx-cell-center">
                      {Number(h.radius_meters || 0)}
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
                      {(() => {
                        const tier = resolveHotspotRiskTier(h);
                        const pillCls =
                          tier === "critical" || tier === "high"
                            ? "r-critical"
                            : tier === "medium"
                              ? "r-warning"
                              : "r-normal";
                        const label =
                          tier === "critical"
                            ? "CRIT"
                            : tier === "high"
                              ? "HIGH"
                              : tier === "medium"
                                ? "MED"
                                : "LOW";
                        return (
                          <span className={`risk-pill ${pillCls}`}>{label}</span>
                        );
                      })()}
                    </td>
                    <td className="smx-cell-muted smx-cell-compact" title={h.recency_label || ""}>
                      {h.recency_label
                        ? h.recency_label.split("—")[0].trim()
                        : formatClusterTimestamp(h.detected_at)}
                    </td>
                    <td>
                      <div className="smx-actions-cell">
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            goToScreen("hotspot-details", 0, {
                              hotspotId: h.hotspot_id,
                            });
                          }}
                        >
                          Detail
                        </button>
                      </div>
                    </td>
                  </tr>
                )})}
                {!pagedHotspots.length && !loading && (
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
          {/* Pagination controls */}
          {totalClusterPages > 1 && (
            <div style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              padding: "8px 12px", fontSize: "12px", borderTop: "1px solid var(--border)",
            }}>
              <span style={{ color: "var(--muted)" }}>
                Showing {(clusterPage - 1) * CLUSTERS_PER_PAGE + 1}–
                {Math.min(clusterPage * CLUSTERS_PER_PAGE, filteredHistoricalHotspots.length)} of{" "}
                {filteredHistoricalHotspots.length} hotspots
              </span>
              <div style={{ display: "flex", gap: "4px", alignItems: "center" }}>
                <button
                  className="btn btn-sm btn-outline-secondary"
                  disabled={clusterPage <= 1}
                  onClick={() => setClusterPage((p) => Math.max(1, p - 1))}
                  style={{ fontSize: "11px", padding: "2px 8px" }}
                >
                  ← Prev
                </button>
                <span style={{ margin: "0 6px", color: "var(--muted)" }}>
                  Page {clusterPage} / {totalClusterPages}
                </span>
                <button
                  className="btn btn-sm btn-outline-secondary"
                  disabled={clusterPage >= totalClusterPages}
                  onClick={() => setClusterPage((p) => Math.min(totalClusterPages, p + 1))}
                  style={{ fontSize: "11px", padding: "2px 8px" }}
                >
                  Next →
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
};

export default SafetyMap;
