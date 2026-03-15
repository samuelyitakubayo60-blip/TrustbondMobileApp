import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const Stations = ({ openModal }) => {
  const [stations, setStations] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api.get('/api/v1/stations')
      .then((res) => {
        setStations(res?.items || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const handleToggleActive = async (station) => {
    try {
      const updated = await api.put(`/api/v1/stations/${station.station_id}`, {
        is_active: !station.is_active,
      });
      setStations((prev) =>
        prev.map((s) =>
          s.station_id === updated.station_id ? updated : s
        )
      );
    } catch (e) {
      window.alert(e.message || 'Failed to update station status');
    }
  };

  const handleDelete = async (station) => {
    if (!window.confirm(`Delete station "${station.station_name}"? This cannot be undone.`)) {
      return;
    }
    try {
      await api.delete(`/api/v1/stations/${station.station_id}`);
      setStations((prev) =>
        prev.filter((s) => s.station_id !== station.station_id)
      );
    } catch (e) {
      window.alert(e.message || 'Failed to delete station');
    }
  };

  return (
    <>
      <div className="page-header">
        <h2>Stations</h2>
        <p>Manage police stations and posts mapped to Musanze locations.</p>
      </div>

      <div className="card">
        <div className="card-header">
          <div className="card-title">Registered Stations</div>
          <button className="btn btn-primary btn-sm" onClick={() => openModal('addStation')}>Add Station</button>
        </div>

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>Code</th>
                <th>Name</th>
                <th>Type</th>
                <th>Sector / Location</th>
                <th>Contact</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {stations.map((s) => (
                <tr key={s.station_id}>
                  <td><span className="badge b-blue">{s.station_code}</span></td>
                  <td><strong>{s.station_name}</strong></td>
                  <td style={{ fontSize: '11px', color: 'var(--muted)' }}>{s.station_type}</td>
                  <td style={{ fontSize: '11px', color: 'var(--muted)' }}>{s.location_name || '—'}</td>
                  <td style={{ fontSize: '11px', color: 'var(--muted)' }}>
                    {s.phone_number || '—'}
                    {s.email ? ` · ${s.email}` : ''}
                  </td>
                  <td>
                    <span className={`badge ${s.is_active ? 'b-green' : 'b-red'}`}>
                      {s.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: '4px' }}>
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={() => openModal('editStation', s)}
                      >
                        Edit
                      </button>
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={() => handleToggleActive(s)}
                      >
                        {s.is_active ? 'Deactivate' : 'Activate'}
                      </button>
                      <button
                        className="btn btn-danger btn-sm"
                        onClick={() => handleDelete(s)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {(!stations.length && !loading) && (
                <tr>
                  <td colSpan={7} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    No stations registered yet.
                  </td>
                </tr>
              )}
              {loading && (
                <tr>
                  <td colSpan={7} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
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

export default Stations;

