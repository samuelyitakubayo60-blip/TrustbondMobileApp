import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const IncidentTypes = ({ openModal, onEditIncidentType, refreshKey }) => {
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    api.get('/api/v1/incident-types?include_inactive=true')
      .then((res) => { if (mounted) { setTypes(res || []); setLoading(false); } })
      .catch(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [refreshKey]);

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