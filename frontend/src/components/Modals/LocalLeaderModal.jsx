import React, { useEffect, useState, useMemo } from "react";
import api from "../../api/client";

const ROLE_VILLAGE = "chief_of_village";
const ROLE_CELL = "executive_of_cell";

const LocalLeaderModal = ({ isOpen, onClose, mode = "add", leader = null, onSaved }) => {
  const [form, setForm] = useState({
    full_name: "",
    role: ROLE_CELL,
    email: "",
    phone_number: "",
    lead_location_id: "",
    is_active: true,
  });
  const [cells, setCells] = useState([]);
  const [villages, setVillages] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const isEdit = mode === "edit" && leader?.local_leader_id;

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    const load = async () => {
      try {
        const [cellRes, vilRes] = await Promise.all([
          api.get("/api/v1/public/locations/?location_type=cell&limit=2000"),
          api.get("/api/v1/public/locations/?location_type=village&limit=2000"),
        ]);
        if (!cancelled) {
          setCells(cellRes || []);
          setVillages(vilRes || []);
        }
      } catch {
        if (!cancelled) {
          setCells([]);
          setVillages([]);
        }
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    if (isEdit && leader) {
      const locId =
        leader.covered_location_ids && leader.covered_location_ids.length
          ? String(leader.covered_location_ids[0])
          : "";
      setForm({
        full_name: leader.full_name || "",
        role: leader.role || ROLE_CELL,
        email: leader.email || "",
        phone_number: leader.phone_number || "",
        lead_location_id: locId,
        is_active: !!leader.is_active,
      });
    } else {
      setForm({
        full_name: "",
        role: ROLE_CELL,
        email: "",
        phone_number: "",
        lead_location_id: "",
        is_active: true,
      });
    }
    setError("");
  }, [isOpen, isEdit, leader]);

  const cellById = useMemo(() => {
    const m = {};
    (cells || []).forEach((c) => {
      m[c.location_id] = c;
    });
    return m;
  }, [cells]);

  const locationOptions = useMemo(() => {
    if (form.role === ROLE_VILLAGE) {
      return (villages || []).map((v) => {
        const cell = cellById[v.parent_location_id];
        const label = cell
          ? `${v.location_name} — ${cell.location_name}`
          : v.location_name;
        return { value: String(v.location_id), label };
      });
    }
    return (cells || []).map((c) => ({
      value: String(c.location_id),
      label: c.location_name,
    }));
  }, [form.role, villages, cells, cellById]);

  const handleChange = (field) => (e) => {
    const value = field === "is_active" ? e.target.checked : e.target.value;
    setForm((prev) => {
      const next = { ...prev, [field]: value };
      if (field === "role") {
        next.lead_location_id = "";
      }
      return next;
    });
  };

  const submit = async () => {
    setError("");
    const email = form.email.trim();
    const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
    if (!form.full_name.trim()) {
      setError("Full name is required.");
      return;
    }
    if (!emailOk) {
      setError("A valid email is required (used for login codes).");
      return;
    }
    if (!form.lead_location_id) {
      setError(form.role === ROLE_VILLAGE ? "Select the village they lead." : "Select the cell they lead.");
      return;
    }

    const payload = {
      full_name: form.full_name.trim(),
      role: form.role,
      email,
      phone_number: form.phone_number.trim() || null,
      is_active: !!form.is_active,
      covered_location_ids: [Number(form.lead_location_id)],
    };

    setSaving(true);
    try {
      if (isEdit) {
        await api.put(`/api/v1/local-leaders/${leader.local_leader_id}`, payload);
      } else {
        await api.post("/api/v1/local-leaders/", payload);
      }
      onSaved?.();
      onClose?.();
    } catch (e) {
      setError(e?.message || "Failed to save local leader.");
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 520 }}>
        <div className="modal-header">
          <div className="modal-title">{isEdit ? "Edit Local Leader" : "Add Local Leader"}</div>
          <div className="modal-close" onClick={onClose}>
            ✕
          </div>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ marginBottom: "10px" }}>
            <span className="alert-icon">!</span>
            <div>{error}</div>
          </div>
        )}

        <div className="form-section">
          <div className="form-grid">
            <div className="input-group">
              <div className="input-label">Full Name *</div>
              <input
                className="input"
                value={form.full_name}
                onChange={handleChange("full_name")}
              />
            </div>
            <div className="input-group">
              <div className="input-label">Role *</div>
              <select className="select" value={form.role} onChange={handleChange("role")}>
                <option value={ROLE_CELL}>Executive of cell (chief of cell)</option>
                <option value={ROLE_VILLAGE}>Chief of village</option>
              </select>
            </div>
            <div className="input-group">
              <div className="input-label">Email *</div>
              <input
                className="input"
                type="email"
                autoComplete="email"
                value={form.email}
                onChange={handleChange("email")}
                placeholder="used for OTP and login"
              />
            </div>
            <div className="input-group">
              <div className="input-label">Phone (optional)</div>
              <input
                className="input"
                value={form.phone_number}
                onChange={handleChange("phone_number")}
                placeholder="+2507..."
              />
            </div>
            <div className="input-group" style={{ gridColumn: "1 / -1" }}>
              <div className="input-label">
                {form.role === ROLE_VILLAGE ? "Village they lead *" : "Cell they lead *"}
              </div>
              <select
                className="select"
                value={form.lead_location_id}
                onChange={handleChange("lead_location_id")}
              >
                <option value="">— Select —</option>
                {locationOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <label className="checkbox-wrap" style={{ gridColumn: "1 / -1" }}>
              <input type="checkbox" checked={form.is_active} onChange={handleChange("is_active")} />
              <span>Active account</span>
            </label>
            <div className="input-group" style={{ gridColumn: "1 / -1", fontSize: 12, color: "var(--muted)" }}>
              Passwords are not entered here. After creating a leader, use <strong>Send setup code</strong> on the
              list so they receive an email to set a private password, or they sign in with email OTP in the mobile
              app.
            </div>
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, padding: "0 16px 16px" }}>
          <button type="button" className="btn btn-outline" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? "Saving…" : isEdit ? "Save changes" : "Create leader"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default LocalLeaderModal;
