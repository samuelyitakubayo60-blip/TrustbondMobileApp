import React, { useCallback, useEffect, useState } from "react";
import api from "../../api/client";
import ViewCaseModal from "../Modals/ViewCaseModal";

/**
 * Cases for one station — GET /stations/{id}/cases grouped by incident type.
 */
const StationSecurityDetail = ({ goToScreen, stationId, stationName, wsRefreshKey }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [viewCase, setViewCase] = useState(null);
  const [viewOpen, setViewOpen] = useState(false);

  const sid = stationId != null ? Number(stationId) : null;

  const load = useCallback(() => {
    if (!sid) return;
    setLoading(true);
    setError("");
    api
      .get(`/api/v1/stations/${sid}/cases`)
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((e) => {
        setError(e?.message || "Failed to load station cases");
        setData(null);
        setLoading(false);
      });
  }, [sid]);

  useEffect(() => {
    load();
  }, [load, wsRefreshKey]);

  const title = data?.station_name || stationName || `Station ${sid}`;

  return (
    <>
      <div className="card" style={{ marginBottom: 16, padding: "16px 20px" }}>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          style={{ marginBottom: 12 }}
          onClick={() => goToScreen?.("security-situation", 3)}
        >
          ← All stations
        </button>
        <h2 style={{ margin: 0, fontSize: 22 }}>{title}</h2>
        <p style={{ margin: "6px 0 0", color: "var(--muted)", fontSize: 13 }}>
          Active cases auto-assigned to this station from incident locations.
        </p>
        {data && (
          <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
            <span className="badge b-orange">{data.active_case_count} active cases</span>
            <span className="badge b-blue">{data.total_incident_count} incidents</span>
          </div>
        )}
      </div>

      {error && (
        <div className="alert alert-danger" style={{ marginBottom: 12 }}>
          <span className="alert-icon">!</span>
          <div>{error}</div>
        </div>
      )}

      {loading ? (
        <div className="card" style={{ padding: 24, textAlign: "center", color: "var(--muted)" }}>
          Loading cases…
        </div>
      ) : !data?.groups?.length ? (
        <div className="card" style={{ padding: 24, textAlign: "center", color: "var(--muted)" }}>
          No active cases in this station area.
        </div>
      ) : (
        data.groups.map((group) => (
          <div key={group.incident_type_id ?? group.incident_type_name} className="card" style={{ marginBottom: 16 }}>
            <div className="card-header">
              <div className="card-title">
                {group.incident_type_name} — {group.case_count} case{group.case_count === 1 ? "" : "s"},{" "}
                {group.incident_count} incident{group.incident_count === 1 ? "" : "s"}
              </div>
            </div>
            <div className="tbl-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>Status</th>
                    <th>Priority</th>
                    <th>Incidents</th>
                    <th>Assigned</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {(group.cases || []).map((c) => (
                    <tr key={c.case_id}>
                      <td>
                        <strong>{c.title || c.case_number}</strong>
                        <div style={{ fontSize: 11, color: "var(--muted)" }}>{c.case_number}</div>
                      </td>
                      <td>
                        <span className="badge b-blue">{c.status}</span>
                      </td>
                      <td>{c.priority}</td>
                      <td>{c.report_count}</td>
                      <td style={{ fontSize: 12 }}>{c.assigned_to_name || "—"}</td>
                      <td>
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          onClick={() => {
                            setViewCase(c);
                            setViewOpen(true);
                          }}
                        >
                          Open
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))
      )}

      <ViewCaseModal
        isOpen={viewOpen}
        onClose={() => {
          setViewOpen(false);
          setViewCase(null);
        }}
        caseItem={viewCase}
        onUpdated={load}
      />
    </>
  );
};

export default StationSecurityDetail;
