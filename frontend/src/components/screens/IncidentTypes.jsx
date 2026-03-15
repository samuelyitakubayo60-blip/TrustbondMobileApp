import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const IncidentTypes = ({ openModal, onEditIncidentType, refreshKey }) => {
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadTypes = () => {
    setLoading(true);
    api.get('/api/v1/incident-types?include_inactive=true')
      .then((res) => {
        setTypes(res || []);
        setLoading(false);
      })
      .catch(() => { setLoading(false); });
  };

  useEffect(() => {
    let mounted = true;
    loadTypes();
    return () => { mounted = false; };
  }, [refreshKey]);

  const handleToggleActive = async (type) => {
    try {
      const updated = await api.put(`/api/v1/incident-types/${type.incident_type_id}`, {
        is_active: !type.is_active,
      });
      setTypes((prev) =>
        prev.map((t) =>
          t.incident_type_id === updated.incident_type_id ? updated : t
        )
      );
    } catch (e) {
      window.alert(e.message || 'Failed to update incident type status');
    }
  };

  const handleDelete = async (type) => {
    if (!window.confirm(`Delete incident type "${type.type_name}"? This cannot be undone.`)) {
      return;
    }
    try {
      await api.delete(`/api/v1/incident-types/${type.incident_type_id}`);
      setTypes((prev) =>
        prev.filter((t) => t.incident_type_id !== type.incident_type_id)
      );
    } catch (e) {
      window.alert(e.message || 'Failed to delete incident type');
    }
  };

  return (
    <>
      <div className="page-header">
        <h2>Incident Types</h2>
        <p>Configure categories, severity weights, and their impact on trust scoring and DBSCAN clustering.</p>
      </div>

      <div className="alert alert-info">
        <span className="alert-icon">i</span>
        <div>Severity multiplier affects final trust score and prioritization.</div>
      </div>

      <div className="card">
        <div className="card-header">
          <div className="card-title">Incident Categories</div>
          <button className="btn btn-primary btn-sm" onClick={() => openModal('addIncident')}>Add Type</button>
        </div>

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Description</th>
                <th>Severity</th>
                <th>Level</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {types.map((t) => {
                const sev = Number(t.severity_weight ?? 1).toFixed(2);
                let level = 'Low';
                let badge = 'b-gray';
                const val = Number(t.severity_weight ?? 1);
                if (val >= 1.6) { level = 'Severe'; badge = 'b-red'; }
                else if (val >= 1.3) { level = 'High'; badge = 'b-orange'; }
                else if (val >= 1.1) { level = 'Medium'; badge = 'b-blue'; }

                return (
                  <tr key={t.incident_type_id}>
                    <td><strong>{t.type_name}</strong></td>
                    <td style={{ fontSize: '11px', color: 'var(--muted)' }}>{t.description || '—'}</td>
                    <td>
                      <span style={{ fontFamily: '"Syne", sans-serif', fontWeight: 800 }}>
                        {sev}
                      </span>
                    </td>
                    <td><span className={`badge ${badge}`}>{level}</span></td>
                    <td>
                      <span className={`badge ${t.is_active ? 'b-green' : 'b-red'}`}>
                        {t.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: '4px' }}>
                        <button
                          className="btn btn-outline btn-sm"
                          onClick={() => onEditIncidentType?.(t)}
                        >
                          Edit
                        </button>
                        <button
                          className="btn btn-outline btn-sm"
                          onClick={() => handleToggleActive(t)}
                        >
                          {t.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                        <button
                          className="btn btn-danger btn-sm"
                          onClick={() => handleDelete(t)}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {(!types.length && !loading) && (
                <tr>
                  <td colSpan={6} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    No incident types found.
                  </td>
                </tr>
              )}
              {loading && (
                <tr>
                  <td colSpan={6} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    Loading...
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
};

export default IncidentTypes;