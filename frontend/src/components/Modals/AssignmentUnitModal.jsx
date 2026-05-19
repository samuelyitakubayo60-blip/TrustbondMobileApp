import React, { useEffect, useState } from "react";
import api from "../../api/client";

const emptyForm = {
  unit_code: "",
  unit_name: "",
  description: "",
  requires_commander_approval: true,
  is_active: true,
};

const AssignmentUnitModal = ({ isOpen, onClose, mode = "add", unit = null, onSaved }) => {
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const isEdit = mode === "edit" && unit?.unit_id != null;

  useEffect(() => {
    if (!isOpen) return;
    if (isEdit && unit) {
      setForm({
        unit_code: unit.unit_code || "",
        unit_name: unit.unit_name || "",
        description: unit.description || "",
        requires_commander_approval: !!unit.requires_commander_approval,
        is_active: unit.is_active !== false,
      });
    } else {
      setForm({ ...emptyForm });
    }
    setError("");
  }, [isOpen, isEdit, unit]);

  const handleChange = (field) => (e) => {
    const value =
      e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [field]: value }));
  };

  const submit = async () => {
    const code = form.unit_code.trim();
    const name = form.unit_name.trim();
    if (!name) {
      setError("Display name is required.");
      return;
    }
    if (!isEdit && code.length < 2) {
      setError("Unit code is required (at least 2 characters).");
      return;
    }

    setSaving(true);
    setError("");
    try {
      if (isEdit) {
        await api.patch(`/api/v1/special-assignment-units/${unit.unit_id}`, {
          unit_name: name,
          description: form.description.trim() || null,
          requires_commander_approval: form.requires_commander_approval,
          is_active: form.is_active,
        });
      } else {
        await api.post("/api/v1/special-assignment-units/", {
          unit_code: code,
          unit_name: name,
          description: form.description.trim() || null,
          requires_commander_approval: form.requires_commander_approval,
        });
      }
      onSaved?.();
      onClose?.();
    } catch (e) {
      setError(e?.message || "Failed to save unit.");
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 520 }}>
        <div className="modal-header">
          <div className="modal-title">
            {isEdit ? "Edit assignment unit" : "Add assignment unit"}
          </div>
          <div className="modal-close" onClick={onClose} role="button" tabIndex={0}>
            ✕
          </div>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ margin: "0 16px 10px" }}>
            <span className="alert-icon">!</span>
            <div>{error}</div>
          </div>
        )}

        <div className="form-section">
          <div className="form-grid">
            <div className="input-group">
              <div className="input-label">Unit code *</div>
              <input
                className="input"
                required
                maxLength={50}
                placeholder="e.g. RIB"
                value={form.unit_code}
                onChange={handleChange("unit_code")}
                disabled={isEdit}
                readOnly={isEdit}
              />
              <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 4 }}>
                {isEdit
                  ? "Code cannot be changed after creation (stored on cases and incident types)."
                  : "Uppercase, no spaces — stored on cases and incident types."}
              </div>
            </div>
            <div className="input-group">
              <div className="input-label">Display name *</div>
              <input
                className="input"
                required
                maxLength={100}
                placeholder="e.g. RIB — Investigation Bureau"
                value={form.unit_name}
                onChange={handleChange("unit_name")}
              />
            </div>
            <div className="input-group" style={{ gridColumn: "1 / -1" }}>
              <div className="input-label">Description</div>
              <textarea
                className="input"
                rows={2}
                placeholder="When this unit should be used…"
                value={form.description}
                onChange={handleChange("description")}
              />
            </div>
            <label
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontSize: 13,
                cursor: "pointer",
                gridColumn: "1 / -1",
              }}
            >
              <input
                type="checkbox"
                checked={form.requires_commander_approval}
                onChange={handleChange("requires_commander_approval")}
              />
              Requires commander approval before deployment
            </label>
            {isEdit && (
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 13,
                  cursor: "pointer",
                  gridColumn: "1 / -1",
                }}
              >
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={handleChange("is_active")}
                />
                Active (inactive units are hidden from dropdowns)
              </label>
            )}
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, padding: "0 16px 16px" }}>
          <button type="button" className="btn btn-outline" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? "Saving…" : isEdit ? "Save changes" : "Add unit"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default AssignmentUnitModal;
