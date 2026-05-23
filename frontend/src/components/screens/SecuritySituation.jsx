import React, { useCallback, useEffect, useState } from "react";
import api from "../../api/client";
import { useAuth } from "../../context/AuthContext";

/**
 * Security Situation — case management by station (open a station for cases by type).
 */
const SecuritySituation = ({ goToScreen, wsRefreshKey }) => {
  const { user } = useAuth();
  const role = user?.role || "officer";
  const [stations, setStations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .get("/api/v1/stations/?only_active=true&include_metrics=true")
      .then((res) => {
        setStations(res?.items || []);
        setLoading(false);
      })
      .catch((e) => {
        setError(e?.message || "Failed to load stations");
        setStations([]);
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load, wsRefreshKey]);

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
            <h2 style={{ margin: 0, marginBottom: 4, fontSize: 22 }}>Security Situation</h2>
            <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>
              Case management by station — select a station to view and open active cases grouped
              by incident type. For district totals only, see{" "}
              <strong>Overall Security Situation</strong>.{" "}
              {role === "officer"
                ? "You see your station only."
                : "District-wide station view."}
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
