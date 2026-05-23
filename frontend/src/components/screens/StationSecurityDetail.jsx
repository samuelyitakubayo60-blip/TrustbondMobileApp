import React, { useCallback, useEffect, useState } from "react";
import api from "../../api/client";
import ViewCaseModal from "../Modals/ViewCaseModal";
import EditCaseModal from "../Modals/EditCaseModal";
import { caseDisplayName, caseDisplayRef } from "../../utils/caseDisplay";

/**
 * Cases for one station — GET /stations/{id}/cases grouped by incident type.
 */
const StationSecurityDetail = ({ goToScreen, stationId, stationName, wsRefreshKey }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [viewCase, setViewCase] = useState(null);
  const [viewOpen, setViewOpen] = useState(false);
  const [editCase, setEditCase] = useState(null);
  const [editOpen, setEditOpen] = useState(false);

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
  const activeCases = data?.active_case_count ?? 0;
  const totalIncidents = data?.total_incident_count ?? 0;

  // Apply search + status filter across all groups
  const filteredGroups = (data?.groups || [])
    .map((group) => {
      const cases = (group.cases || []).filter((c) => {
        if (statusFilter !== "all" && c.status !== statusFilter) return false;
        if (search.trim()) {
          const q = search.trim().toLowerCase();
          const name = (c.title || c.case_number || "").toLowerCase();
          const loc = (c.location_name || "").toLowerCase();
          if (!name.includes(q) && !loc.includes(q)) return false;
        }
        return true;
      });
      return { ...group, cases };
    })
    .filter((g) => g.cases.length > 0);

  const totalFilteredCases = filteredGroups.reduce((n, g) => n + g.cases.length, 0);

  return (
    <>
      {/* ── Header ── */}
      <div className="card" style={{ marginBottom: 16, padding: "18px 22px" }}>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          style={{ marginBottom: 14 }}
          onClick={() => goToScreen?.("security-situation", 3)}
        >
          ← All stations
        </button>

        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: 12,
            marginBottom: data ? 16 : 0,
          }}
        >
          <div>
            <h2 style={{ margin: 0, fontSize: 22 }}>{title}</h2>
            <p style={{ margin: "6px 0 0", color: "var(--muted)", fontSize: 13 }}>
              Active cases auto-assigned from incident locations within this station's jurisdiction.
            </p>
          </div>
        </div>

        {/* Stat cards — only shown once data is loaded */}
        {data && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
            {[
              {
                label: "Active Cases",
                sub: "Open + investigating",
                value: activeCases,
                cls: activeCases >= 5 ? "sb-red" : activeCases >= 1 ? "sb-orange" : "sb-green",
              },
              {
                label: "Linked Incidents",
                sub: "Reports in active cases",
                value: totalIncidents,
                cls: "sb-blue",
              },
              {
                label: "Incident Types",
                sub: "Categories with cases",
                value: data.groups?.length ?? 0,
                cls: "sb-purple",
              },
            ].map((s) => (
              <div key={s.label} className={`stat-btn ${s.cls}`} style={{ cursor: "default" }}>
                <div className="stat-btn-label">{s.label}</div>
                <div className="stat-btn-value">{s.value}</div>
                <div className="stat-btn-sub">{s.sub}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {error && (
        <div className="alert alert-danger" style={{ marginBottom: 12 }}>
          <span className="alert-icon">!</span>
          <div>{error}</div>
        </div>
      )}

      {/* ── Filters ── */}
      {!loading && data?.groups?.length > 0 && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="filter-row">
            <input
              className="input"
              placeholder="Search by case title or location…"
              style={{ flex: 2 }}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <select
              className="select"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="all">All Statuses</option>
              <option value="open">Open</option>
              <option value="investigating">Investigating</option>
            </select>
          </div>
        </div>
      )}

      {loading ? (
        <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>
          Loading cases…
        </div>
      ) : !data?.groups?.length ? (
        <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>📋</div>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>No active cases</div>
          <div style={{ fontSize: 12 }}>No open or investigating cases are currently assigned to this station.</div>
        </div>
      ) : filteredGroups.length === 0 ? (
        <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--muted)" }}>
          No cases match the current filters.{" "}
          <button
            type="button"
            className="btn btn-outline btn-sm"
            style={{ marginLeft: 8 }}
            onClick={() => { setSearch(""); setStatusFilter("all"); }}
          >
            Clear filters
          </button>
        </div>
      ) : (
        filteredGroups.map((group) => {
          const groupUrgent = group.cases.some((c) => c.priority === "high");

          return (
            <div
              key={group.incident_type_id ?? group.incident_type_name}
              className="card"
              style={{ marginBottom: 16 }}
            >
              {/* Group header */}
              <div
                className="card-header"
                style={{
                  borderLeft: `4px solid ${groupUrgent ? "var(--danger)" : "var(--accent)"}`,
                  paddingLeft: 12,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  flexWrap: "wrap",
                  gap: 8,
                }}
              >
                <div className="card-title" style={{ fontSize: 14 }}>
                  {group.incident_type_name}
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <span className={`badge ${groupUrgent ? "b-red" : "b-blue"}`} style={{ fontSize: 11 }}>
                    {group.cases.length} case{group.cases.length === 1 ? "" : "s"}
                  </span>
                  <span className="badge b-gray" style={{ fontSize: 11 }}>
                    {group.incident_count} incident{group.incident_count === 1 ? "" : "s"}
                  </span>
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
                      <th>Location</th>
                      <th>Assigned</th>
                      <th>Opened</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {group.cases.map((c) => {
                      const pri = c.priority || "medium";
                      const status = c.status || "open";

                      return (
                        <tr key={c.case_id}>
                          <td>
                            <div style={{ fontWeight: 600, fontSize: 13 }}>
                              {caseDisplayName(c)}
                            </div>
                            {caseDisplayRef(c) && (
                              <div style={{ fontSize: 11, color: "var(--muted)" }}>
                                {caseDisplayRef(c)}
                              </div>
                            )}
                          </td>
                          <td>
                            <span className={`s-badge s-${status}`}>
                              {status === "investigating" ? "In Progress" : status.charAt(0).toUpperCase() + status.slice(1)}
                            </span>
                          </td>
                          <td>
                            <span className={`p-badge p-${pri}`}>
                              {pri.charAt(0).toUpperCase() + pri.slice(1)}
                            </span>
                          </td>
                          <td style={{ textAlign: "center" }}>{c.report_count}</td>
                          <td style={{ fontSize: 12, color: "var(--text-dim)" }}>
                            {c.location_name || "—"}
                          </td>
                          <td style={{ fontSize: 12 }}>{c.assigned_to_name || "—"}</td>
                          <td style={{ fontSize: 11, color: "var(--muted)", whiteSpace: "nowrap" }}>
                            {c.opened_at ? new Date(c.opened_at).toLocaleDateString() : "—"}
                          </td>
                          <td>
                            <div style={{ display: "flex", gap: 4 }}>
                              <button
                                type="button"
                                className="btn btn-primary btn-sm"
                                onClick={() => {
                                  setViewCase(c);
                                  setViewOpen(true);
                                }}
                              >
                                View
                              </button>
                              <button
                                type="button"
                                className="btn btn-outline btn-sm"
                                onClick={() => {
                                  setEditCase(c);
                                  setEditOpen(true);
                                }}
                              >
                                Edit
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })
      )}

      {/* Show total when filtered */}
      {!loading && filteredGroups.length > 0 && (search || statusFilter !== "all") && (
        <div style={{ textAlign: "right", fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
          Showing {totalFilteredCases} case{totalFilteredCases === 1 ? "" : "s"}
        </div>
      )}

      <ViewCaseModal
        isOpen={viewOpen}
        onClose={() => {
          setViewOpen(false);
          setViewCase(null);
        }}
        caseItem={viewCase}
        onEdit={(item) => {
          setViewOpen(false);
          setEditCase(item);
          setEditOpen(true);
        }}
      />

      <EditCaseModal
        isOpen={editOpen}
        onClose={() => {
          setEditOpen(false);
          setEditCase(null);
        }}
        caseItem={editCase}
        onSaved={load}
      />
    </>
  );
};

export default StationSecurityDetail;
