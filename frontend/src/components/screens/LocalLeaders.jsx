import React, { useCallback, useEffect, useMemo, useState } from "react";
import api from "../../api/client";

const ROLE_LABEL = {
  chief_of_village: "Village chief",
  executive_of_cell: "Cell executive",
};

const LocalLeaders = ({ wsRefreshKey, refreshKey = 0, onAddLeader, onEditLeader }) => {
  const PAGE_SIZE = 20;
  const [leaders, setLeaders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [searchText, setSearchText] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);

  const loadLeaders = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/api/v1/local-leaders/");
      setLeaders(res || []);
      setError("");
    } catch (e) {
      setError(e?.message || "Failed to load local leaders.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLeaders();
  }, [loadLeaders, wsRefreshKey, refreshKey]);

  const sendSetupCode = async (leader) => {
    try {
      await api.post(`/api/v1/local-leaders/${leader.local_leader_id}/send-setup-code`);
      window.alert(
        "Setup code sent to the leader's email. They can use it in the app under “Set up password with code”."
      );
    } catch (e) {
      setError(e?.message || "Failed to send setup code.");
    }
  };

  const deleteLeader = async (leader) => {
    const ok = window.confirm(`Delete local leader "${leader.full_name}"?`);
    if (!ok) return;
    try {
      await api.delete(`/api/v1/local-leaders/${leader.local_leader_id}`);
      await loadLeaders();
    } catch (e) {
      setError(e?.message || "Failed to delete local leader.");
    }
  };

  const filteredLeaders = useMemo(() => {
    return leaders.filter((l) => {
      const q = searchText.trim().toLowerCase();
      if (q) {
        const hay = `${l.full_name || ""} ${l.phone_number || ""} ${l.email || ""} ${l.role || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (statusFilter === "active" && !l.is_active) return false;
      if (statusFilter === "inactive" && l.is_active) return false;
      return true;
    });
  }, [leaders, searchText, statusFilter]);

  const paginatedLeaders = useMemo(
    () => filteredLeaders.slice(offset, offset + pageSize),
    [filteredLeaders, offset, pageSize]
  );

  return (
    <>
      <div className="page-header">
        <h2>Local Leaders</h2>
        <p>Register village chiefs and cell executives. Login codes are sent by email.</p>
      </div>

      {error && (
        <div className="alert alert-danger" style={{ marginBottom: "12px" }}>
          <span className="alert-icon">!</span>
          <div>{error}</div>
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <div className="card-title">Registered Local Leaders</div>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => onAddLeader?.()}>
            Add Local Leader
          </button>
        </div>
        <div className="filter-row">
          <input
            className="input"
            placeholder="Search by name, email, phone, role..."
            style={{ flex: 2 }}
            value={searchText}
            onChange={(e) => {
              setSearchText(e.target.value);
              setOffset(0);
            }}
          />
          <select
            className="select"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setOffset(0);
            }}
          >
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
          <input
            type="number"
            min="5"
            max="100"
            placeholder="Rows"
            style={{ minWidth: "80px" }}
            value={pageSize}
            onChange={(e) => {
              const newSize = Math.max(5, Math.min(100, parseInt(e.target.value, 10) || PAGE_SIZE));
              setPageSize(newSize);
              setOffset(0);
            }}
          />
        </div>
        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Name</th>
                <th>Role</th>
                <th>Email</th>
                <th>Phone</th>
                <th>Coverage</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {paginatedLeaders.map((l, idx) => (
                <tr key={l.local_leader_id}>
                  <td>{offset + idx + 1}</td>
                  <td>
                    <strong>{l.full_name}</strong>
                  </td>
                  <td>
                    <span className="badge b-blue">{ROLE_LABEL[l.role] || l.role}</span>
                  </td>
                  <td>{l.email || "—"}</td>
                  <td>{l.phone_number || "—"}</td>
                  <td style={{ fontSize: 11, color: "var(--muted)" }}>
                    {(l.covered_location_names || []).slice(0, 2).join(", ") || "—"}
                    {(l.covered_location_names || []).length > 2 ? "…" : ""}
                  </td>
                  <td>
                    <span className={`badge ${l.is_active ? "b-green" : "b-red"}`}>
                      {l.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
                      <button type="button" className="btn btn-outline btn-sm" onClick={() => onEditLeader?.(l)}>
                        Edit
                      </button>
                      <button type="button" className="btn btn-outline btn-sm" onClick={() => sendSetupCode(l)}>
                        Send setup code
                      </button>
                      <button type="button" className="btn btn-danger btn-sm" onClick={() => deleteLeader(l)}>
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {!paginatedLeaders.length && !loading && (
                <tr>
                  <td colSpan={8} style={{ textAlign: "center", color: "var(--muted)" }}>
                    No local leaders found.
                  </td>
                </tr>
              )}
              {loading && (
                <tr>
                  <td colSpan={8} style={{ textAlign: "center", color: "var(--muted)" }}>
                    Loading...
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginTop: "14px",
            gap: "8px",
            flexWrap: "wrap",
          }}
        >
          <div style={{ fontSize: "12px", color: "var(--muted)" }}>
            Showing {Math.min(offset + 1, filteredLeaders.length)}-
            {Math.min(offset + pageSize, filteredLeaders.length)} of {filteredLeaders.length} local leaders
          </div>
          <div className="pagination">
            <button
              type="button"
              className="page-btn"
              onClick={() => setOffset(Math.max(0, offset - pageSize))}
              disabled={offset === 0}
            >
              ‹
            </button>
            {Array.from({ length: Math.min(5, Math.ceil(filteredLeaders.length / pageSize) || 1) }, (_, i) => {
              const pageNum = i + 1;
              const pageOffset = (pageNum - 1) * pageSize;
              const isCurrent = Math.floor(offset / pageSize) === pageNum - 1;
              return (
                <button
                  key={pageNum}
                  type="button"
                  className={`page-btn ${isCurrent ? "current" : ""}`}
                  onClick={() => setOffset(pageOffset)}
                >
                  {pageNum}
                </button>
              );
            })}
            <button
              type="button"
              className="page-btn"
              onClick={() =>
                setOffset(Math.min(Math.max(filteredLeaders.length - pageSize, 0), offset + pageSize))
              }
              disabled={offset + pageSize >= filteredLeaders.length}
            >
              ›
            </button>
          </div>
        </div>
      </div>
    </>
  );
};

export default LocalLeaders;
