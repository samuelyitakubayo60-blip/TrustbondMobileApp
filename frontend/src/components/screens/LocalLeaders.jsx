import React, { useCallback, useEffect, useMemo, useState } from "react";
import api from "../../api/client";

const LocalLeaders = ({ wsRefreshKey }) => {
  const PAGE_SIZE = 20;
  const [leaders, setLeaders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [locationsById, setLocationsById] = useState({});
  const [coverageOptions, setCoverageOptions] = useState([]);
  const [searchText, setSearchText] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);

  const [form, setForm] = useState({
    local_leader_id: null,
    full_name: "",
    phone_number: "",
    email: "",
    is_active: true,
    covered_location_ids: [],
  });

  const isEdit = !!form.local_leader_id;

  const loadLocations = useCallback(async () => {
    try {
      const [cov, villages] = await Promise.all([
        api.get("/api/v1/stations/coverage/options"),
        api.get("/api/v1/public/locations/?location_type=village&limit=5000"),
      ]);
      const map = {};
      (villages || []).forEach((v) => {
        map[v.location_id] = v.location_name;
      });
      setLocationsById(map);
      setCoverageOptions(cov?.items || []);
    } catch {
      setCoverageOptions([]);
    }
  }, []);

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
    loadLocations();
    loadLeaders();
  }, [loadLocations, loadLeaders, wsRefreshKey]);

  const clearForm = () =>
    setForm({
      local_leader_id: null,
      full_name: "",
      phone_number: "",
      email: "",
      is_active: true,
      covered_location_ids: [],
    });

  const startEdit = (leader) => {
    setForm({
      local_leader_id: leader.local_leader_id,
      full_name: leader.full_name || "",
      phone_number: leader.phone_number || "",
      email: leader.email || "",
      is_active: !!leader.is_active,
      covered_location_ids: leader.covered_location_ids || [],
    });
    setError("");
  };

  const toggleCell = (cellId) => {
    setForm((prev) => {
      const set = new Set(prev.covered_location_ids || []);
      if (set.has(cellId)) set.delete(cellId);
      else set.add(cellId);
      return { ...prev, covered_location_ids: Array.from(set) };
    });
  };

  const submit = async () => {
    if (!form.full_name.trim()) {
      setError("Full name is required.");
      return;
    }
    if (!form.phone_number.trim()) {
      setError("Phone number is required.");
      return;
    }
    const phoneDigits = form.phone_number.replace(/\D/g, "");
    const normalizedPhone = phoneDigits.startsWith("250")
      ? phoneDigits
      : phoneDigits.startsWith("0")
        ? `250${phoneDigits.slice(1)}`
        : `250${phoneDigits}`;
    if (!normalizedPhone.startsWith("2507") || normalizedPhone.length !== 12) {
      setError("Phone must be a valid Rwandan mobile number (e.g. +2507XXXXXXXX).");
      return;
    }
    if (!form.covered_location_ids.length) {
      setError("Select at least one coverage cell.");
      return;
    }

    const payload = {
      full_name: form.full_name.trim(),
      phone_number: normalizedPhone,
      email: form.email.trim() || null,
      is_active: !!form.is_active,
      covered_location_ids: form.covered_location_ids,
    };

    setSaving(true);
    setError("");
    try {
      if (isEdit) {
        await api.put(`/api/v1/local-leaders/${form.local_leader_id}`, payload);
      } else {
        await api.post("/api/v1/local-leaders/", payload);
      }
      await loadLeaders();
      clearForm();
    } catch (e) {
      setError(e?.message || "Failed to save local leader.");
    } finally {
      setSaving(false);
    }
  };

  const sendSetupCode = async (leader) => {
    try {
      await api.post(`/api/v1/local-leaders/${leader.local_leader_id}/send-setup-code`);
      window.alert("Setup code generated. The leader should use it in mobile app to set a private password.");
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
      if (form.local_leader_id === leader.local_leader_id) clearForm();
    } catch (e) {
      setError(e?.message || "Failed to delete local leader.");
    }
  };

  const coverageSummary = useMemo(
    () => `${form.covered_location_ids.length} selected`,
    [form.covered_location_ids]
  );

  const filteredLeaders = useMemo(() => {
    return leaders.filter((l) => {
      const q = searchText.trim().toLowerCase();
      if (q) {
        const hay = `${l.full_name || ""} ${l.phone_number || ""} ${l.email || ""}`.toLowerCase();
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
        <p>Create local leader accounts and assign coverage cells for verification.</p>
      </div>

      <div className="card" style={{ marginBottom: "12px" }}>
        <div className="card-header">
          <div className="card-title">{isEdit ? "Edit Local Leader" : "Add Local Leader"}</div>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ marginBottom: "10px" }}>
            <span className="alert-icon">!</span>
            <div>{error}</div>
          </div>
        )}

        <div className="form-grid">
          <div className="input-group">
            <div className="input-label">Full Name *</div>
            <input
              className="input"
              value={form.full_name}
              onChange={(e) => setForm((p) => ({ ...p, full_name: e.target.value }))}
            />
          </div>
          <div className="input-group">
            <div className="input-label">Phone Number *</div>
            <input
              className="input"
              value={form.phone_number}
              onChange={(e) => setForm((p) => ({ ...p, phone_number: e.target.value }))}
              placeholder="+2507..."
            />
          </div>
          <div className="input-group">
            <div className="input-label">Email (optional)</div>
            <input
              className="input"
              value={form.email}
              onChange={(e) => setForm((p) => ({ ...p, email: e.target.value }))}
            />
          </div>
          <div className="input-group">
            <div className="input-label">Credential Setup</div>
            <div style={{ fontSize: 12, color: "var(--muted)", paddingTop: 8 }}>
              Password is never entered by admin. After saving, use <strong>Send Setup Code</strong> so the leader sets a private password in mobile app.
            </div>
          </div>
        </div>

        <div className="input-group" style={{ marginTop: 8 }}>
          <div className="input-label">Coverage (cells) — {coverageSummary}</div>
          <div
            style={{
              maxHeight: 220,
              overflowY: "auto",
              border: "1px solid var(--border)",
              borderRadius: 10,
              padding: 10,
            }}
          >
            {coverageOptions.map((sec) => (
              <div key={sec.sector_id} style={{ marginBottom: 10 }}>
                <div style={{ fontWeight: 700, marginBottom: 6 }}>{sec.sector_name}</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                  {(sec.cells || []).map((cell) => (
                    <label key={cell.cell_id} style={{ fontSize: 12, display: "flex", gap: 6 }}>
                      <input
                        type="checkbox"
                        checked={form.covered_location_ids.includes(cell.cell_id)}
                        onChange={() => toggleCell(cell.cell_id)}
                      />
                      <span>{cell.cell_name}</span>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="form-grid" style={{ marginTop: 10 }}>
          <label className="checkbox-wrap">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => setForm((p) => ({ ...p, is_active: e.target.checked }))}
            />
            <span>Active account</span>
          </label>
        </div>

        <div className="card-footer" style={{ justifyContent: "space-between" }}>
          <button className="btn btn-outline" onClick={clearForm} disabled={saving}>
            Clear
          </button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? "Saving..." : isEdit ? "Update Leader" : "Create Leader"}
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <div className="card-title">Registered Local Leaders</div>
        </div>
        <div className="filter-row">
          <input
            className="input"
            placeholder="Search by name, phone, email..."
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
              const newSize = Math.max(5, Math.min(100, parseInt(e.target.value) || PAGE_SIZE));
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
                <th>Phone</th>
                <th>Email</th>
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
                  <td>{l.phone_number}</td>
                  <td>{l.email || "—"}</td>
                  <td style={{ fontSize: 11, color: "var(--muted)" }}>
                    {(l.covered_location_names || []).slice(0, 3).join(", ") || "—"}
                    {(l.covered_location_names || []).length > 3 ? "…" : ""}
                  </td>
                  <td>
                    <span className={`badge ${l.is_active ? "b-green" : "b-red"}`}>
                      {l.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: "4px" }}>
                      <button className="btn btn-outline btn-sm" onClick={() => startEdit(l)}>
                        Edit
                      </button>
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={() => sendSetupCode(l)}
                      >
                        Send Setup Code
                      </button>
                      <button
                        className="btn btn-danger btn-sm"
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
                  <td colSpan={7} style={{ textAlign: "center", color: "var(--muted)" }}>
                    No local leaders found.
                  </td>
                </tr>
              )}
              {loading && (
                <tr>
                  <td colSpan={7} style={{ textAlign: "center", color: "var(--muted)" }}>
                    Loading...
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "14px", gap: "8px", flexWrap: "wrap" }}>
          <div style={{ fontSize: "12px", color: "var(--muted)" }}>
            Showing {Math.min(offset + 1, filteredLeaders.length)}-{Math.min(offset + pageSize, filteredLeaders.length)} of {filteredLeaders.length} local leaders
          </div>
          <div className="pagination">
            <button
              className="page-btn"
              onClick={() => setOffset(Math.max(0, offset - pageSize))}
              disabled={offset === 0}
            >
              ‹
            </button>
            {Array.from({ length: Math.min(5, Math.ceil(filteredLeaders.length / pageSize)) }, (_, i) => {
              const pageNum = i + 1;
              const pageOffset = (pageNum - 1) * pageSize;
              const isCurrent = Math.floor(offset / pageSize) === pageNum - 1;
              return (
                <button
                  key={pageNum}
                  className={`page-btn ${isCurrent ? "current" : ""}`}
                  onClick={() => setOffset(pageOffset)}
                >
                  {pageNum}
                </button>
              );
            })}
            <button
              className="page-btn"
              onClick={() => setOffset(Math.min(Math.max(filteredLeaders.length - pageSize, 0), offset + pageSize))}
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

