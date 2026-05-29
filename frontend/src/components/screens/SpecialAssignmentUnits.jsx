import React, { useCallback, useEffect, useRef, useState } from "react";
import api from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import AssignmentUnitModal from "../Modals/AssignmentUnitModal";

// ── Module-level cache ─────────────────────────────────────────────────────
// Keyed by showInactive (true/false) since the API URL differs.
// Survives navigation away and back; cleared when a real refresh is triggered.
let _sauCache = {}; // { [showInactive]: unitList }
let _sauCacheRefreshKey = undefined; // the wsRefreshKey value that produced this cache

// ── Component ──────────────────────────────────────────────────────────────

const SpecialAssignmentUnits = ({ wsRefreshKey }) => {
  const { user } = useAuth();
  const canManage = user?.role === "admin";
  const canView = canManage;

  // Initialise state from cache immediately so returning to this screen is instant.
  const [units, setUnits] = useState(_sauCache[false] ?? []);
  // Only show the full spinner on the very first load (no cache for current key).
  const [loading, setLoading] = useState(_sauCache[false] === undefined);
  const [bgRefreshing, setBgRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState("add");
  const [selectedUnit, setSelectedUnit] = useState(null);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const fetchUnits = useCallback(async ({ silent = false } = {}) => {
    if (silent) {
      setBgRefreshing(true);
    } else {
      setLoading(true);
    }
    setError("");
    const path = showInactive
      ? "/api/v1/special-assignment-units/?active_only=false"
      : "/api/v1/special-assignment-units/";
    try {
      const res = await api.get(path);
      if (!mountedRef.current) return;
      const list = Array.isArray(res?.data) ? res.data : Array.isArray(res) ? res : [];
      _sauCache[showInactive] = list;
      _sauCacheRefreshKey = wsRefreshKey;
      setUnits(list);
    } catch (e) {
      if (!mountedRef.current) return;
      // On background refresh keep showing stale data; only surface error on hard load.
      if (!silent) {
        setError(e?.message || "Failed to load units");
        setUnits([]);
      }
    } finally {
      if (!mountedRef.current) return;
      setLoading(false);
      setBgRefreshing(false);
    }
  }, [showInactive, wsRefreshKey]);

  useEffect(() => {
    if (_sauCache[showInactive] === undefined) {
      // No cache for this key — show spinner.
      fetchUnits({ silent: false });
    } else {
      // Cache exists (including WS-triggered refresh) — stay silent, update key.
      _sauCacheRefreshKey = wsRefreshKey;
      fetchUnits({ silent: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsRefreshKey, showInactive]);

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
      delete _sauCache[showInactive];
      fetchUnits({ silent: false });
    } catch (err) {
      window.alert(err?.message || "Failed to delete unit.");
    }
  };

  const activeCount   = units.filter(u =>  u.is_active).length;
  const inactiveCount = units.filter(u => !u.is_active).length;
  return (
    <>
      {/* ── Header card ── */}
      <div className="card" style={{ marginBottom: 20, padding: '20px 24px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
              <h2 style={{ margin: 0, fontSize: 22 }}>Assignment Units</h2>
              {bgRefreshing && (
                <span style={{ fontSize: 11, color: 'var(--muted)', fontStyle: 'italic' }}>
                  refreshing…
                </span>
              )}
            </div>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: 13 }}>
              Units used when routing cases (auto-created from incident types), case updates, and deployment decisions.
            </p>
          </div>
          {canManage && (
            <button type="button" className="btn btn-primary" style={{ alignSelf: 'center' }} onClick={openAdd}>
              + Add unit
            </button>
          )}
        </div>

        {/* Stats */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          {[
            { label: 'Total units',        value: units.length,   cls: 'sb-blue'   },
            { label: 'Active',             value: activeCount,    cls: 'sb-green'  },
            { label: 'Inactive',           value: inactiveCount,  cls: 'sb-red'    },
          ].map((s) => (
            <div key={s.label} className={`stat-btn ${s.cls}`} style={{ cursor: 'default' }}>
              <div className="stat-btn-label">{s.label}</div>
              <div className="stat-btn-value">{s.value}</div>
            </div>
          ))}
        </div>
      </div>

      {!canView && (
        <div className="alert alert-warn" style={{ marginBottom: 12 }}>
          <span className="alert-icon">!</span>
          <div>You do not have access to assignment units.</div>
        </div>
      )}

      {canView && !canManage && (
        <div className="alert alert-warn" style={{ marginBottom: 12 }}>
          <span className="alert-icon">!</span>
          <div>View only — only DPC (admin) can create or edit assignment units.</div>
        </div>
      )}

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
        onSaved={() => { delete _sauCache[showInactive]; fetchUnits({ silent: false }); }}
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
                      <span className={`badge ${u.is_active ? 'b-green' : 'b-gray'}`}>
                        {u.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td>
                      {canManage ? (
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
                      ) : (
                        <span style={{ fontSize: 12, color: 'var(--muted)' }}>—</span>
                      )}
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
