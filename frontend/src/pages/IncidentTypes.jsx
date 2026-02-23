import { useState, useEffect } from 'react';
import Layout from '../components/Layout.jsx';
import { useAuth } from '../contexts/AuthContext.jsx';
import { apiService } from '../services/apiService.js';

export default function IncidentTypes() {
  const { isAdmin } = useAuth();
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({
    type_name: '',
    description: '',
    severity_weight: '1.00',
    is_active: true,
  });

  const loadTypes = () => {
    setLoading(true);
    apiService
      .getIncidentTypes(true)
      .then((list) => setTypes(Array.isArray(list) ? list : []))
      .catch((err) => setError(err.message || 'Failed to load incident types'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (isAdmin) loadTypes();
  }, [isAdmin]);

  const resetForm = () => {
    setForm({
      type_name: '',
      description: '',
      severity_weight: '1.00',
      is_active: true,
    });
    setEditing(null);
    setShowForm(false);
    setError(null);
  };

  const startEdit = (t) => {
    setEditing(t);
    setForm({
      type_name: t.type_name || '',
      description: t.description || '',
      severity_weight: String(t.severity_weight ?? '1.00'),
      is_active: t.is_active ?? true,
    });
    setShowForm(true);
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!form.type_name?.trim()) {
      setError('Name is required.');
      return;
    }
    setError(null);
    try {
      await apiService.createIncidentType({
        type_name: form.type_name.trim(),
        description: form.description?.trim() || null,
        severity_weight: parseFloat(form.severity_weight) || 1,
        is_active: form.is_active,
      });
      resetForm();
      loadTypes();
    } catch (err) {
      setError(err.message || 'Failed to create incident type');
    }
  };

  const handleUpdate = async (e) => {
    e.preventDefault();
    if (!editing) return;
    if (!form.type_name?.trim()) {
      setError('Name is required.');
      return;
    }
    setError(null);
    try {
      await apiService.updateIncidentType(editing.incident_type_id, {
        type_name: form.type_name.trim(),
        description: form.description?.trim() || null,
        severity_weight: parseFloat(form.severity_weight) || 1,
        is_active: form.is_active,
      });
      resetForm();
      loadTypes();
    } catch (err) {
      setError(err.message || 'Failed to update incident type');
    }
  };

  const handleToggleActive = async (t) => {
    setError(null);
    try {
      await apiService.updateIncidentType(t.incident_type_id, { is_active: !t.is_active });
      loadTypes();
      if (editing?.incident_type_id === t.incident_type_id) resetForm();
    } catch (err) {
      setError(err.message || 'Failed to update');
    }
  };

  if (!isAdmin) {
    return (
      <Layout>
        <div className="page-incident-types">
          <p className="error-message">Only administrators can manage incident types.</p>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="page-incident-types">
        <div className="page-users users-header" style={{ marginBottom: '1rem' }}>
          <h2>Incident types</h2>
          <button
            type="button"
            className="btn-primary"
            onClick={() => {
              resetForm();
              setShowForm(true);
            }}
          >
            Add incident type
          </button>
        </div>
        {error && <p className="error-message">{error}</p>}
        {showForm && (
          <form
            className="user-form"
            onSubmit={editing ? handleUpdate : handleCreate}
            style={{ maxWidth: '480px', marginBottom: '1.5rem' }}
          >
            <h3>{editing ? 'Edit incident type' : 'New incident type'}</h3>
            <div className="form-row">
              <label>Name *</label>
              <input
                value={form.type_name}
                onChange={(e) => setForm((f) => ({ ...f, type_name: e.target.value }))}
                required
                maxLength={100}
              />
            </div>
            <div className="form-row">
              <label>Description</label>
              <textarea
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                rows={2}
              />
            </div>
            <div className="form-row">
              <label>Severity weight (0–10)</label>
              <input
                type="number"
                min="0"
                max="10"
                step="0.01"
                value={form.severity_weight}
                onChange={(e) => setForm((f) => ({ ...f, severity_weight: e.target.value }))}
              />
            </div>
            <div className="form-row checkbox-row">
              <label>
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
                />
                Active (visible to citizens when submitting reports)
              </label>
            </div>
            <div className="form-actions">
              <button type="submit">{editing ? 'Update' : 'Create'}</button>
              <button type="button" onClick={resetForm}>
                Cancel
              </button>
            </div>
          </form>
        )}
        {loading && <p className="loading">Loading incident types…</p>}
        {!loading && types.length === 0 && !showForm && (
          <p className="empty">No incident types. Add one to let citizens choose when reporting.</p>
        )}
        {!loading && types.length > 0 && (
          <div className="table-wrap">
            <table className="users-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Description</th>
                  <th>Severity</th>
                  <th>Active</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {types.map((t) => (
                  <tr key={t.incident_type_id}>
                    <td>{t.type_name}</td>
                    <td style={{ maxWidth: 280 }}>{t.description || '—'}</td>
                    <td>{t.severity_weight}</td>
                    <td>
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => handleToggleActive(t)}
                      >
                        {t.is_active ? 'Deactivate' : 'Activate'}
                      </button>
                    </td>
                    <td>
                      <button type="button" className="link-button" onClick={() => startEdit(t)}>
                        Edit
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Layout>
  );
}
