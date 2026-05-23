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

  const activeCount   = units.filter(u =>  u.is_active).length;
  const inactiveCount = units.filter(u => !u.is_active).length;
  const approvalCount = units.filter(u =>  u.requires_commander_approval).length;

  return (
    <>
      {/* ── Header card ── */}
      <div className="card" style={{ marginBottom: 20, padding: '20px 24px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
          <div>
            <h2 style={{ margin: 0, marginBottom: 4, fontSize: 22 }}>Assignment Units</h2>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: 13 }}>
              Units used when routing cases (auto-created from incident types), case updates, and deployment decisions.
            </p>
          </div>
          <button type="button" className="btn btn-primary" style={{ alignSelf: 'center' }} onClick={openAdd}>
            + Add unit
          </button>
        </div>

        {/* Stats */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {[
            { label: 'Total units',        value: units.length,   cls: 'sb-blue'   },
            { label: 'Active',             value: activeCount,    cls: 'sb-green'  },
            { label: 'Inactive',           value: inactiveCount,  cls: 'sb-red'    },
            { label: 'Needs approval',     value: approvalCount,  cls: 'sb-orange' },
          ].map((s) => (
            <div key={s.label} className={`stat-btn ${s.cls}`} style={{ cursor: 'default' }}>
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
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer' }}>
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
                <th>Commander</th>
                <th>Approval</th>
                <th>Status</th>
                <th style={{ width: 200 }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: "center", padding: 24 }}>
                    Loading…
                  </td>
                </tr>
              ) : units.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: "center", padding: 24 }}>
                    No units yet. Click <strong>Add unit</strong> to create one.
                  </td>
                </tr>
              ) : (
                units.map((u) => (
                  <tr key={u.unit_id}>
                    <td>
                      <span className="badge b-blue" style={{ fontSize: 10, fontFamily: 'monospace' }}>
                        {u.unit_code}
                      </span>
                    </td>
                    <td style={{ fontWeight: 500 }}>{u.unit_name}</td>
                    <td style={{ fontSize: 12, color: 'var(--muted)' }}>
                      {u.description || '—'}
                    </td>
                    <td style={{ fontSize: 12 }}>
                      {u.commander_name || (
                        <span style={{ color: "var(--muted)" }}>—</span>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${u.requires_commander_approval ? 'b-orange' : 'b-gray'}`} style={{ fontSize: 10 }}>
                        {u.requires_commander_approval ? 'Required' : 'Not required'}
                      </span>
                    </td>
                    <td>
                      <span className={`badge ${u.is_active ? 'b-green' : 'b-gray'}`}>
                        {u.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        <button type="button" className="btn btn-outline btn-sm" onClick={() => openEdit(u)}>
                          Edit
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm"
                          style={{ background: 'var(--c-danger-dim)', color: 'var(--danger)', border: '1px solid var(--c-danger-ring)', cursor: 'pointer' }}
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
