import React, { useCallback, useEffect, useRef, useState } from "react";
import api from "../../api/client";
import { useAuth } from "../../context/AuthContext";

/**
 * District Security Situation — dynamic station cards from GET /stations?include_metrics=true
 */

// ── Module-level cache ─────────────────────────────────────────────────────
// Survives navigation away and back; cleared when a real refresh is triggered.
let _ssCache = null; // { stations }
let _ssCacheRefreshKey = undefined; // the wsRefreshKey value that produced this cache

// ── Component ──────────────────────────────────────────────────────────────

const SecuritySituation = ({ goToScreen, wsRefreshKey }) => {
  const { user } = useAuth();
  const role = user?.role || "officer";

  // Initialise state from cache immediately so returning to this screen is instant.
  const [stations, setStations] = useState(_ssCache?.stations ?? []);
  // Only show the full spinner on the very first load (no cache yet).
  const [loading, setLoading] = useState(_ssCache === null);
  const [bgRefreshing, setBgRefreshing] = useState(false);
  const [error, setError] = useState("");

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const fetchStations = useCallback(async ({ silent = false } = {}) => {
    if (silent) {
      setBgRefreshing(true);
    } else {
      setLoading(true);
    }
    setError("");
    try {
      const res = await api.get("/api/v1/stations/?only_active=true&include_metrics=true");
      if (!mountedRef.current) return;
      const list = res?.items || [];
      _ssCache = { stations: list };
      _ssCacheRefreshKey = wsRefreshKey;
      setStations(list);
    } catch (e) {
      if (!mountedRef.current) return;
      // On background refresh keep showing stale data; only surface error on hard load.
      if (!silent) {
        setError(e?.message || "Failed to load stations");
        setStations([]);
      }
    } finally {
      if (!mountedRef.current) return;
      setLoading(false);
      setBgRefreshing(false);
    }
  }, [wsRefreshKey]);

  useEffect(() => {
    if (_ssCache === null) {
      // Truly first load (no cache) — show spinner.
      fetchStations({ silent: false });
    } else {
      // Cache exists (including WS-triggered refresh) — stay silent, update key.
      _ssCacheRefreshKey = wsRefreshKey;
      fetchStations({ silent: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsRefreshKey]);

  const totalActive = stations.reduce((n, s) => n + (s.active_case_count || 0), 0);
  const totalIncidents = stations.reduce((n, s) => n + (s.total_incident_count || 0), 0);

  return (
    <>
      <div className="card" style={{ marginBottom: 20, padding: "20px 24px 16px" }}>
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: 12,
            marginBottom: 16,
          }}
        >
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
              <h2 style={{ margin: 0, fontSize: 22 }}>Security Situation</h2>
              {bgRefreshing && (
                <span style={{ fontSize: 11, color: "var(--muted)", fontStyle: "italic" }}>
                  refreshing…
                </span>
              )}
            </div>
            <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>
              Cases are grouped by station based on incident location.{" "}
              {role === "officer"
                ? "You see your station only."
                : role === "supervisor"
                  ? "IO view: all stations (management tasks are DPC-only)."
                  : "District-wide view."}
            </p>
          </div>
          {role === "admin" && (
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => goToScreen?.("stations", 10)}
            >
              Manage stations
            </button>
          )}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
          {[
            { label: "Stations", value: stations.length, cls: "sb-blue" },
            { label: "Active cases", value: totalActive, cls: "sb-orange" },
            { label: "Linked incidents", value: totalIncidents, cls: "sb-green" },
          ].map((s) => (
            <div key={s.label} className={`stat-btn ${s.cls}`} style={{ cursor: "default" }}>
              <div className="stat-btn-label">{s.label}</div>
              <div className="stat-btn-value">{s.value}</div>
            </div>
          ))}
        </div>
      </div>

      {error && (
        <div className="alert alert-danger" style={{ marginBottom: 12 }}>
          <span className="alert-icon">!</span>
          <div>{error}</div>
        </div>
      )}

      {loading ? (
        <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--muted)" }}>
          Loading stations…
        </div>
      ) : stations.length === 0 ? (
        <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--muted)" }}>
          No active stations. {role === "admin" ? "Create one under Stations." : ""}
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
            gap: 16,
          }}
        >
          {stations.map((st) => (
            <button
              key={st.station_id}
              type="button"
              className="card"
              style={{
                textAlign: "left",
                cursor: "pointer",
                padding: "18px 20px",
                border: "1px solid var(--border)",
                background: "var(--surface)",
              }}
              onClick={() =>
                goToScreen?.("station-security", 3, { stationId: st.station_id, stationName: st.station_name })
              }
            >
              <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 6 }}>{st.station_name}</div>
              <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 10 }}>
                {st.station_code}
                {st.covered_cell_names?.length
                  ? ` · ${st.covered_cell_names.slice(0, 2).join(", ")}${st.covered_cell_names.length > 2 ? "…" : ""}`
                  : ""}
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <span className="badge b-orange" style={{ fontSize: 10 }}>
                  {st.active_case_count ?? 0} active case{(st.active_case_count ?? 0) === 1 ? "" : "s"}
                </span>
                <span className="badge b-blue" style={{ fontSize: 10 }}>
                  {st.total_incident_count ?? 0} incident{(st.total_incident_count ?? 0) === 1 ? "" : "s"}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
    </>
  );
};

export default SecuritySituation;
