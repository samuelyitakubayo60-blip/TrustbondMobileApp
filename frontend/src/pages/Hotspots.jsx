import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout.jsx';
import { useAuth } from '../contexts/AuthContext.jsx';
import { apiService } from '../services/apiService.js';
import '../styles/colors.css';

export default function Hotspots() {
  const { canSeeHotspots } = useAuth();
  const navigate = useNavigate();
  const [hotspots, setHotspots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filterRisk, setFilterRisk] = useState('');

  useEffect(() => {
    if (!canSeeHotspots) navigate('/dashboard', { replace: true });
  }, [canSeeHotspots, navigate]);

  const loadHotspots = useCallback(() => {
    setLoading(true);
    setError(null);
    const params = { limit: 100 };
    if (filterRisk) params.risk_level = filterRisk;
    apiService
      .getHotspots(params)
      .then((list) => setHotspots(Array.isArray(list) ? list : []))
      .catch((err) => setError(err.message || 'Failed to load hotspots'))
      .finally(() => setLoading(false));
  }, [filterRisk]);

  useEffect(() => {
    loadHotspots();
  }, [loadHotspots]);

  function formatDate(s) {
    if (!s) return '—';
    return new Date(s).toLocaleString();
  }

  function mapUrl(lat, lng) {
    return `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}&zoom=15`;
  }

  if (!canSeeHotspots) return null;
  return (
    <Layout>
      <div className="page-hotspots">
        <h2>Hotspots</h2>
        <p className="form-hint">Hotspots are created automatically when many reports of the same place and the same incident type are submitted. No manual creation.</p>
        <div className="hotspots-toolbar">
          <select value={filterRisk} onChange={(e) => setFilterRisk(e.target.value)} className="filter-select">
            <option value="">All risk levels</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </div>
        {error && <p className="error-message">{error}</p>}
        {loading && <p className="loading">Loading hotspots…</p>}
        {!loading && hotspots.length === 0 && <p className="empty">No hotspots yet. They will appear when the system detects areas that meet hotspot criteria.</p>}
        {!loading && hotspots.length > 0 && (
          <div className="table-wrap">
            <table className="users-table">
              <thead>
                <tr>
                  <th>Incident type</th>
                  <th>Center (lat, long)</th>
                  <th>Radius</th>
                  <th>Count</th>
                  <th>Risk</th>
                  <th>Window (h)</th>
                  <th>Detected at</th>
                  <th>Map</th>
                </tr>
              </thead>
              <tbody>
                {hotspots.map((h) => (
                  <tr key={h.hotspot_id}>
                    <td>{h.incident_type_name ?? (h.incident_type_id != null ? `Type ${h.incident_type_id}` : '—')}</td>
                    <td>{Number(h.center_lat).toFixed(5)}, {Number(h.center_long).toFixed(5)}</td>
                    <td>{h.radius_meters} m</td>
                    <td>{h.incident_count}</td>
                    <td><span className={`risk-badge risk-${h.risk_level}`}>{h.risk_level}</span></td>
                    <td>{h.time_window_hours}</td>
                    <td>{formatDate(h.detected_at)}</td>
                    <td>
                      <a href={mapUrl(Number(h.center_lat), Number(h.center_long))} target="_blank" rel="noopener noreferrer" className="link-button">
                        View on map
                      </a>
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
