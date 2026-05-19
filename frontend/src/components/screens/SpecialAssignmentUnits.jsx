import React, { useCallback, useEffect, useState } from "react";
import api from "../../api/client";
import AssignmentUnitModal from "../Modals/AssignmentUnitModal";

const SpecialAssignmentUnits = ({ wsRefreshKey }) => {
  const [units, setUnits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState("add");
  const [selectedUnit, setSelectedUnit] = useState(null);

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

  const openAdd = () => {
    setSelectedUnit(null);
    setModalMode("add");
    setModalOpen(true);
  };

  const openEdit = (unit) => {
    setSelectedUnit(unit);
    setModalMode("edit");
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    setSelectedUnit(null);
  };

  const handleDelete = async (unit) => {
    const label = unit.unit_name || unit.unit_code;
    if (
      !window.confirm(
        `Delete assignment unit "${label}" (${unit.unit_code})? This cannot be undone.`,
      )
    ) {
      return;
    }
    try {
      await api.delete(`/api/v1/special-assignment-units/${unit.unit_id}`);
      load();
    } catch (err) {
      window.alert(err?.message || "Failed to delete unit.");
    }
  };

  return (
    <>
      <div className="page-header" style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <h2>Assignment units</h2>
          <p>
            Units used when routing cases (auto-created from incident types), case
            updates, and deployment decisions. Incident types store a default unit
            code applied to new auto-cases.
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={openAdd}>
          + Add unit
        </button>
      </div>

      {error && (
        <div className="alert alert-danger" style={{ marginBottom: 12 }}>
          <span className="alert-icon">!</span>
          <div>{error}</div>
        </div>
      )}

      <AssignmentUnitModal
        isOpen={modalOpen}
        onClose={closeModal}
        mode={modalMode}
        unit={selectedUnit}
        onSaved={load}
      />

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
                <th style={{ width: 200 }}>Actions</th>
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
                    No units yet. Click <strong>Add unit</strong> to create one.
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
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          onClick={() => openEdit(u)}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          style={{ color: "var(--danger)" }}
                          onClick={() => handleDelete(u)}
                        >
                          Delete
                        </button>
                      </div>
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
