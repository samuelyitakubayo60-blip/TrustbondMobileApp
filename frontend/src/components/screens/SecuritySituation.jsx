import React, { useCallback, useEffect, useState } from "react";
import api from "../../api/client";
import { useAuth } from "../../context/AuthContext";

/**
 * District Security Situation — dynamic station cards from GET /stations?include_metrics=true
 */
const SecuritySituation = ({ goToScreen, wsRefreshKey }) => {
  const { user } = useAuth();
  const role = user?.role || "officer";
  const [stations, setStations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");

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

  const filtered = search.trim()
    ? stations.filter((s) =>
        s.station_name.toLowerCase().includes(search.trim().toLowerCase()) ||
        (s.station_code || "").toLowerCase().includes(search.trim().toLowerCase())
      )
    : stations;

  // Urgency tier for left-border colour: high ≥ 5 cases, medium 1–4, calm 0
  const urgencyClass = (count) => {
    if (count >= 5) return "p-high";
    if (count >= 1) return "p-medium";
    return "p-low";
  };

  const stationTypeLabel = (t) => {
    if (!t) return null;
    return t === "headquarters" ? "HQ" : t.charAt(0).toUpperCase() + t.slice(1);
  };

  return (
    <>
      {/* ── Header card ── */}
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
              Cases are grouped by station based on incident location.{" "}
              {role === "officer"
                ? "You see your station only."
                : role === "supervisor"
                  ? "Viewing all stations — management tasks are admin-only."
                  : "District-wide view."}
            </p>
          </div>
          {role === "admin" && (
            <button
              type="button"
              className="btn btn-outline"
              style={{ alignSelf: "center", whiteSpace: "nowrap" }}
              onClick={() => goToScreen?.("stations", 10)}
            >
              Manage stations
            </button>
          )}
        </div>

        {/* Summary stats */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
          {[
            { label: "Active Stations", sub: "Reporting coverage", value: stations.length, cls: "sb-blue" },
            { label: "Active Cases",    sub: "Open + investigating",  value: totalActive,   cls: "sb-orange" },
            { label: "Linked Incidents", sub: "Across all stations", value: totalIncidents, cls: "sb-green" },
          ].map((s) => (
            <div key={s.label} className={`stat-btn ${s.cls}`} style={{ cursor: "default" }}>
              <div className="stat-btn-label">{s.label}</div>
              <div className="stat-btn-value">{s.value}</div>
              <div className="stat-btn-sub">{s.sub}</div>
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

      {/* ── Search bar ── */}
      {!loading && stations.length > 0 && (
        <div className="card" style={{ marginBottom: 14, padding: "12px 16px" }}>
          <input
            className="input"
            placeholder="Search stations by name or code…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: "100%", maxWidth: 400 }}
          />
        </div>
      )}

      {loading ? (
        <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>
          Loading stations…
        </div>
      ) : stations.length === 0 ? (
        <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>🏢</div>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>No active stations</div>
          <div style={{ fontSize: 12 }}>
            {role === "admin" ? "Create one under Stations to start tracking security situation." : "Contact your administrator."}
          </div>
        </div>
      ) : filtered.length === 0 ? (
        <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--muted)" }}>
          No stations match <strong>"{search}"</strong>.
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 16,
          }}
        >
          {filtered.map((st) => {
            const activeCases = st.active_case_count ?? 0;
            const incidents = st.total_incident_count ?? 0;
            const uCls = urgencyClass(activeCases);

            return (
              <button
                key={st.station_id}
                type="button"
                className={`case-card ${uCls}`}
                style={{ textAlign: "left", cursor: "pointer", padding: "18px 20px", width: "100%" }}
                onClick={() =>
                  goToScreen?.("station-security", 3, {
                    stationId: st.station_id,
                    stationName: st.station_name,
                  })
                }
              >
                {/* Card header */}
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 6, gap: 8 }}>
                  <div style={{ fontWeight: 700, fontSize: 15, lineHeight: 1.3 }}>
                    {st.station_name}
                  </div>
                  {stationTypeLabel(st.station_type) && (
                    <span className="badge b-gray" style={{ fontSize: 10, whiteSpace: "nowrap", flexShrink: 0 }}>
                      {stationTypeLabel(st.station_type)}
                    </span>
                  )}
                </div>

                {/* Code + coverage cells */}
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12, lineHeight: 1.5 }}>
                  {st.station_code && (
                    <span style={{ fontFamily: "var(--font-mono, monospace)", marginRight: 6 }}>
                      {st.station_code}
                    </span>
                  )}
                  {st.covered_cell_names?.length > 0 && (
                    <span>
                      {st.station_code ? "· " : ""}
                      {st.covered_cell_names.slice(0, 3).join(", ")}
                      {st.covered_cell_names.length > 3 && ` +${st.covered_cell_names.length - 3} more`}
                    </span>
                  )}
                </div>

                {/* Metrics */}
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <span
                    className={`badge ${activeCases >= 5 ? "b-red" : activeCases >= 1 ? "b-orange" : "b-green"}`}
                    style={{ fontSize: 11 }}
                  >
                    {activeCases} active case{activeCases === 1 ? "" : "s"}
                  </span>
                  <span className="badge b-blue" style={{ fontSize: 11 }}>
                    {incidents} incident{incidents === 1 ? "" : "s"}
                  </span>
                  {st.covered_cell_names?.length > 0 && (
                    <span className="badge b-gray" style={{ fontSize: 11 }}>
                      {st.covered_cell_names.length} cell{st.covered_cell_names.length === 1 ? "" : "s"}
                    </span>
                  )}
                </div>

                {/* Active-cases progress bar */}
                {activeCases > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--muted)", marginBottom: 4 }}>
                      <span>Case load</span>
                      <span>{activeCases} active</span>
                    </div>
                    <div style={{ height: 4, borderRadius: 2, background: "var(--border)", overflow: "hidden" }}>
                      <div
                        style={{
                          height: "100%",
                          borderRadius: 2,
                          width: `${Math.min(100, activeCases * 10)}%`,
                          background: activeCases >= 5 ? "var(--danger)" : activeCases >= 1 ? "var(--warning)" : "var(--success)",
                          transition: "width 0.4s",
                        }}
                      />
                    </div>
                  </div>
                )}

                {/* Click hint */}
                <div style={{ marginTop: 12, fontSize: 11, color: "var(--accent)", fontWeight: 500 }}>
                  View cases →
                </div>
              </button>
            );
          })}
        </div>
      )}
    </>
  );
};

export default SecuritySituation;
