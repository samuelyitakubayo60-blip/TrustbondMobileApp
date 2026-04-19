import React, { useEffect, useState } from "react";
import api from "../../api/client";

const AddUserModal = ({ isOpen, onClose, onSaved }) => {
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    email: "",
    phone_number: "",
    role: "officer",
    station_id: "",
    is_active: true,
  });
  const [stations, setStations] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    const load = async () => {
      try {
        const res = await api.get("/api/v1/stations?only_active=true");
        if (!cancelled) setStations(res?.items || []);
      } catch {
        if (!cancelled) setStations([]);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  const handleChange = (field) => (e) => {
    const value = field === "is_active" ? e.target.checked : e.target.value;
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const submit = async () => {
    setError("");
    const email = form.email.trim();
    if (!form.first_name.trim() || !form.last_name.trim() || !email) {
      setError("First name, last name, and email are required.");
      return;
    }
    const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
    if (!emailOk) {
      setError("Please enter a valid email address.");
      return;
    }

    const payload = {
      first_name: form.first_name.trim(),
      middle_name: null,
      last_name: form.last_name.trim(),
      email,
      phone_number: form.phone_number.trim() || null,
      role: form.role,
      station_id: form.station_id ? Number(form.station_id) : null,
      assigned_location_id: null,
      is_active: !!form.is_active,
    };

    setSaving(true);
    try {
      await api.post("/api/v1/police-users/", payload);
      onSaved?.();
      onClose?.();
    } catch (e) {
      setError(
        e?.message || "Failed to create user. Check SMTP config and try again.",
      );
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="modal-overlay open"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">Add New Officer</div>
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
          <div className="form-section-title">Personal Information</div>
          <div className="form-grid">
            <div className="input-group">
              <div className="input-label">First Name *</div>
              <input
                className="input"
                placeholder="e.g. Alice"
                value={form.first_name}
                onChange={handleChange("first_name")}
              />
            </div>
            <div className="input-group">
              <div className="input-label">Last Name *</div>
              <input
                className="input"
                placeholder="e.g. Uwimana"
                value={form.last_name}
                onChange={handleChange("last_name")}
              />
            </div>
          </div>
          <div className="input-group">
            <div className="input-label">Email Address *</div>
            <input
              className="input"
              type="email"
              placeholder="officer@example.com"
              value={form.email}
              onChange={handleChange("email")}
            />
          </div>
          <div className="input-group">
            <div className="input-label">Phone</div>
            <input
              className="input"
              placeholder="+250 781 234 567"
              value={form.phone_number}
              onChange={handleChange("phone_number")}
            />
          </div>
        </div>

        <div className="form-section">
          <div className="form-section-title">Role & Assignment</div>
          <div className="form-grid">
            <div className="input-group">
              <div className="input-label">Role *</div>
              <select
                className="select"
                value={form.role}
                onChange={handleChange("role")}
              >
                <option value="officer">Officer</option>
                <option value="supervisor">Supervisor</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div className="input-group">
              <div className="input-label">Assigned Station</div>
              <select
                className="select"
                value={form.station_id}
                onChange={handleChange("station_id")}
              >
                <option value="">None</option>
                {stations.map((s) => (
                  <option key={s.station_id} value={s.station_id}>
                    {s.station_name}{s.sector2_name ? ` (${s.location_name} + ${s.sector2_name})` : s.location_name ? ` (${s.location_name})` : ''}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="input-group" style={{ marginTop: "4px" }}>
            <label
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                fontSize: "12px",
                color: "var(--muted)",
              }}
            >
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={handleChange("is_active")}
              />
              Active
            </label>
          </div>
        </div>

        <div
          style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}
        >
          <button className="btn btn-outline" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={submit}
            disabled={saving}
          >
            {saving ? "Creating…" : "Create Account"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default AddUserModal;
