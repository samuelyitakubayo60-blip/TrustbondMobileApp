import React, { useCallback, useEffect, useState } from "react";
import api from "../../api/client";
import { useAuth } from "../../context/AuthContext";

/**
 * Read-only district incident summary — counts only, no drill-down.
 * Operational case work lives under Security Situation.
 */
const OverallSecuritySituation = ({ goToScreen, wsRefreshKey }) => {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .get("/api/v1/security-situation/district-overview")
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((e) => {
        setError(e?.message || "Failed to load district overview");
        setData(null);
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load, wsRefreshKey]);

  return (
    <>
      <div className="card" style={{ marginBottom: 20, padding: "20px 24px 16px" }}>
        <h2 style={{ margin: 0, marginBottom: 4, fontSize: 22 }}>Overall Security Situation</h2>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>
          Verified incidents in <strong>{data?.scope_label || "your area"}</strong> — summary
          numbers only. To open cases, assign officers, or review details by station, use{" "}
          <strong>Security Situation</strong> in the menu.
        </p>
      </div>

      <div className="alert alert-info" style={{ marginBottom: 16 }}>
        <span className="alert-icon">i</span>
        <div>
          This page does not link to individual incidents. For case management, go to{" "}
          <button
            type="button"
            className="btn btn-link"
            style={{ padding: 0, fontSize: "inherit", verticalAlign: "baseline" }}
            onClick={() => goToScreen?.("security-situation", 3)}
          >
            Security Situation
          </button>
          .
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
          Loading district summary…
        </div>
      ) : (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
              gap: 12,
              marginBottom: 20,
            }}
          >
            <div className="stat-btn sb-blue" style={{ cursor: "default" }}>
              <div className="stat-btn-label">Total incidents</div>
              <div className="stat-btn-value">{data?.total_incidents ?? 0}</div>
            </div>
            <div className="stat-btn sb-green" style={{ cursor: "default" }}>
              <div className="stat-btn-label">Incident types</div>
              <div className="stat-btn-value">{data?.by_incident_type?.length ?? 0}</div>
            </div>
            <div className="stat-btn sb-orange" style={{ cursor: "default" }}>
              <div className="stat-btn-label">Sectors with activity</div>
              <div className="stat-btn-value">{data?.by_sector?.length ?? 0}</div>
            </div>
          </div>

          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-header">
              <div className="card-title">Incidents by type</div>
            </div>
            <div className="card-body" style={{ padding: "12px 16px 16px" }}>
              {!data?.by_incident_type?.length ? (
                <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>No verified incidents recorded.</p>
              ) : (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
                    gap: 10,
                  }}
                >
                  {data.by_incident_type.map((row) => (
                    <div
                      key={row.incident_type_id ?? row.type_name}
                      style={{
                        padding: "14px 16px",
                        borderRadius: 10,
                        border: "1px solid var(--border)",
                        background: "var(--surface)",
                      }}
                    >
                      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>
                        {row.type_name}
                      </div>
                      <div
                        style={{
                          fontFamily: '"Syne", sans-serif',
                          fontWeight: 800,
                          fontSize: 28,
                          lineHeight: 1.1,
                        }}
                      >
                        {row.count}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <div className="card-title">Where incidents occurred (by sector)</div>
            </div>
            <div className="tbl-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Sector</th>
                    <th style={{ textAlign: "right" }}>Incidents</th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.by_sector || []).map((row) => (
                    <tr key={row.sector_name}>
                      <td>{row.sector_name}</td>
                      <td style={{ textAlign: "right", fontWeight: 700 }}>{row.count}</td>
                    </tr>
                  ))}
                  {!data?.by_sector?.length && (
                    <tr>
                      <td colSpan={2} style={{ color: "var(--muted)", fontSize: 12 }}>
                        No sector breakdown available.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </>
  );
};

export default OverallSecuritySituation;
