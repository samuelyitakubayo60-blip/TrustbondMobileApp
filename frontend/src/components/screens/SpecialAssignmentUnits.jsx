import React, { useCallback, useEffect, useState } from "react";
import api from "../../api/client";

const SpecialAssignmentUnits = ({ wsRefreshKey }) => {
  const [units, setUnits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [form, setForm] = useState({
    unit_code: "",
    unit_name: "",
    description: "",
    requires_commander_approval: true,
  });
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    const q = showInactive ? "?active_only=false" : "";
    api
      .get(`/api/v1/special-assignment-units/${q}`)
      .then((res) => {
        const list = Array.isArray(res?.data) ? res.data : Array.isArray(res) ? res : [];
        setUnits(list);
        setLoading(false);
      })
      .catch((e) => {
        setError(e?.message || "Failed to load units");
        setUnits([]);
        setLoading(false);
      });
  }, [showInactive]);

  useEffect(() => {
    load();
  }, [load, wsRefreshKey]);

  const handleCreate = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.post("/api/v1/special-assignment-units/", {
        unit_code: form.unit_code.trim(),
        unit_name: form.unit_name.trim(),
        description: form.description.trim() || null,
        requires_commander_approval: form.requires_commander_approval,
      });
      setForm({
        unit_code: "",
        unit_name: "",
        description: "",
        requires_commander_approval: true,
      });
      load();
    } catch (err) {
      setError(err?.message || "Failed to create unit");
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (unit) => {
    try {
      const updated = await api.patch(
        `/api/v1/special-assignment-units/${unit.unit_id}`,
        { is_active: !unit.is_active },
      );
      setUnits((prev) =>
        prev.map((u) => (u.unit_id === updated.unit_id ? updated : u)),
      );
    } catch (err) {
      window.alert(err?.message || "Failed to update unit");
    }
  };

  return (
    <>
      <div className="page-header">
        <h2>Special assignment units</h2>
        <p>
          Units used when routing cases (auto-created from incident types), case
          updates, and deployment decisions. Incident types store a default unit
          code applied to new auto-cases.
        </p>
      </div>

      {error && (
        <div className="alert alert-danger" style={{ marginBottom: 12 }}>
          <span className="alert-icon">!</span>
          <div>{error}</div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-header">
          <div className="card-title">Add unit</div>
        </div>
        <form
          onSubmit={handleCreate}
          style={{ padding: "14px 16px", display: "grid", gap: 12 }}
        >
          <div className="form-grid">
            <div className="input-group">
              <div className="input-label">Unit code</div>
              <input
                className="input"
                required
                maxLength={50}
                placeholder="e.g. RIB"
                value={form.unit_code}
                onChange={(e) =>
                  setForm((f) => ({ ...f, unit_code: e.target.value }))
                }
              />
              <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 4 }}>
                Stored on cases and incident types (uppercase, no spaces).
              </div>
            </div>
            <div className="input-group">
              <div className="input-label">Display name</div>
              <input
                className="input"
                required
                maxLength={100}
                placeholder="e.g. RIB — Investigation Bureau"
                value={form.unit_name}
                onChange={(e) =>
                  setForm((f) => ({ ...f, unit_name: e.target.value }))
                }
              />
            </div>
          </div>
          <div className="input-group">
            <div className="input-label">Description</div>
            <textarea
              className="input"
              rows={2}
              placeholder="When this unit should be used…"
              value={form.description}
              onChange={(e) =>
                setForm((f) => ({ ...f, description: e.target.value }))
              }
            />
          </div>
          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            <input
              type="checkbox"
              checked={form.requires_commander_approval}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  requires_commander_approval: e.target.checked,
                }))
              }
            />
            Requires commander approval before deployment
          </label>
          <div>
            <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>
              {saving ? "Saving…" : "Add unit"}
            </button>
          </div>
        </form>
      </div>

      <div className="card">
        <div className="card-header">
          <div className="card-title">Registered units</div>
          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            <input
              type="checkbox"
              checked={showInactive}
              onChange={(e) => setShowInactive(e.target.checked)}
            />
            Show inactive
          </label>
        </div>
        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>Code</th>
                <th>Name</th>
                <th>Description</th>
                <th>Commander approval</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: "center", padding: 24 }}>
                    Loading…
                  </td>
                </tr>
              ) : units.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: "center", padding: 24 }}>
                    No units yet. Add one above or run backend startup to seed defaults.
                  </td>
                </tr>
              ) : (
                units.map((u) => (
                  <tr key={u.unit_id}>
                    <td>
                      <code>{u.unit_code}</code>
                    </td>
                    <td>{u.unit_name}</td>
                    <td style={{ fontSize: 12, color: "var(--muted)" }}>
                      {u.description || "—"}
                    </td>
                    <td>{u.requires_commander_approval ? "Yes" : "No"}</td>
                    <td>
                      <span
                        className={`badge ${u.is_active ? "b-green" : "b-gray"}`}
                      >
                        {u.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        onClick={() => toggleActive(u)}
                      >
                        {u.is_active ? "Deactivate" : "Activate"}
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
};

export default SpecialAssignmentUnits;
