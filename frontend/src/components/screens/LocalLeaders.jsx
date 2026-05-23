import React, { useCallback, useEffect, useMemo, useState } from "react";
import api from "../../api/client";

const ROLE_LABEL = {
  chief_of_village: "Village chief",
  executive_of_cell: "Cell executive",
};

const LocalLeaders = ({ wsRefreshKey, refreshKey = 0, onAddLeader, onEditLeader }) => {
  const PAGE_SIZE = 20;
  const [leaders, setLeaders] = useState([]);
  const [coverageGaps, setCoverageGaps] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [searchText, setSearchText] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [sendingNotifyId, setSendingNotifyId] = useState(null);

  const loadLeaders = useCallback(async () => {
    setLoading(true);
    try {
      const [res, gapsRes, statsRes] = await Promise.all([
        api.get("/api/v1/local-leaders/"),
        api.get("/api/v1/local-leaders/coverage-gaps?limit=1000"),
        api.get("/api/v1/local-leaders/stats"),
      ]);
      setLeaders(res || []);
      setCoverageGaps(gapsRes?.items || []);
      setStats(statsRes || null);
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

  const resendAccountNotification = async (leader) => {
    if (!leader?.email) {
      setError("This leader has no email address.");
      return;
    }
    setSendingNotifyId(leader.local_leader_id);
    setError("");
    try {
      const res = await api.post(
        `/api/v1/local-leaders/${leader.local_leader_id}/send-account-notification`,
      );
      window.alert(res?.message || `Account notification sent to ${leader.email}.`);
    } catch (e) {
      setError(e?.message || "Failed to send account notification.");
    } finally {
      setSendingNotifyId(null);
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

  const villageGaps = coverageGaps.filter(g => g.location_type === "village");
  const cellGaps    = coverageGaps.filter(g => g.location_type === "cell");

  return (
    <>
      {/* ── Header card ── */}
      <div className="card" style={{ marginBottom: 20, padding: '20px 24px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
          <div>
            <h2 style={{ margin: 0, marginBottom: 4, fontSize: 22 }}>Local Leaders</h2>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: 13 }}>
              Register village chiefs and cell executives. They receive an email that their account is ready; they request a setup code in the TrustBond mobile app to choose a password.
            </p>
          </div>
          <button type="button" className="btn btn-primary" style={{ alignSelf: 'center' }} onClick={() => onAddLeader?.()}>
            + Add Local Leader
          </button>
        </div>

        {/* Stats — accurate counts from the database */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: coverageGaps.length > 0 ? 16 : 0 }}>
          {[
            { label: 'Village Chiefs',        value: stats?.village_chiefs      ?? '—', cls: 'sb-blue'   },
            { label: 'Cell Executives',       value: stats?.cell_executives     ?? '—', cls: 'sb-green'  },
            { label: 'Villages w/o Leader',   value: stats?.villages_without_leader ?? '—', cls: 'sb-orange' },
            { label: 'Cells w/o Executive',   value: stats?.cells_without_executive ?? '—', cls: 'sb-red'    },
          ].map((s) => (
            <div key={s.label} className={`stat-btn ${s.cls}`} style={{ cursor: 'default' }}>
              <div className="stat-btn-label">{s.label}</div>
              <div className="stat-btn-value">{s.value}</div>
            </div>
          ))}
        </div>

        {/* Coverage gaps warning — split by village / cell */}
        {coverageGaps.length > 0 && (
          <div style={{ background: 'var(--c-warning-dim)', border: '1px solid var(--c-warning-ring)', borderRadius: 8, padding: '10px 14px', fontSize: 12 }}>
            <div style={{ fontWeight: 700, color: 'var(--warning)', marginBottom: 4 }}>
              {villageGaps.length} village(s) and {cellGaps.length} cell(s) have no active leader
            </div>
            <div style={{ color: 'var(--muted)', marginBottom: 8 }}>
              Citizen reports in these areas will not reach a leader until you register one.
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              {villageGaps.length > 0 && (
                <div>
                  <div style={{ fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>
                    Villages without a chief or cell executive ({villageGaps.length})
                  </div>
                  <ul style={{ margin: 0, paddingLeft: 16, color: 'var(--muted)' }}>
                    {villageGaps.slice(0, 8).map((g) => (
                      <li key={g.location_id}>
                        <span style={{ color: 'var(--text)' }}>{g.location_name}</span>
                        {g.parent_name ? ` (${g.parent_name})` : ""}
                      </li>
                    ))}
                    {villageGaps.length > 8 && <li>…and {villageGaps.length - 8} more</li>}
                  </ul>
                </div>
              )}
              {cellGaps.length > 0 && (
                <div>
                  <div style={{ fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>
                    Cells without an executive ({cellGaps.length})
                  </div>
                  <ul style={{ margin: 0, paddingLeft: 16, color: 'var(--muted)' }}>
                    {cellGaps.slice(0, 8).map((g) => (
                      <li key={g.location_id}>
                        <span style={{ color: 'var(--text)' }}>{g.location_name}</span>
                        {g.parent_name ? ` (${g.parent_name})` : ""}
                      </li>
                    ))}
                    {cellGaps.length > 8 && <li>…and {cellGaps.length - 8} more</li>}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="alert alert-danger" style={{ marginBottom: 12 }}>
          <span className="alert-icon">!</span>
          <div>{error}</div>
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <div className="card-title">Registered Local Leaders</div>
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
            className="input"
            type="number"
            min="5"
            max="100"
            placeholder="Rows"
            style={{ minWidth: "70px" }}
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
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        disabled={!l.email || sendingNotifyId === l.local_leader_id}
                        onClick={() => resendAccountNotification(l)}
                        title={l.email ? "Resend account-ready email (no OTP)" : "No email on file"}
                      >
                        {sendingNotifyId === l.local_leader_id ? "Sending…" : "Resend welcome email"}
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm"
                        style={{ background: 'var(--c-danger-dim)', color: 'var(--danger)', border: '1px solid var(--c-danger-ring)', cursor: 'pointer' }}
                        onClick={() => deleteLeader(l)}
                      >
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
