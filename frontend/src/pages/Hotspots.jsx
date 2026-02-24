import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout.jsx';
import { useAuth } from '../contexts/AuthContext.jsx';
import { apiService } from '../services/apiService.js';
import EvidenceCarousel from '../components/EvidenceCarousel.jsx';
import '../styles/colors.css';

export default function Hotspots() {
  const { canSeeHotspots } = useAuth();
  const navigate = useNavigate();
  const [hotspots, setHotspots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filterRisk, setFilterRisk] = useState('');
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [evidenceItems, setEvidenceItems] = useState([]);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState(null);
  const [activeHotspot, setActiveHotspot] = useState(null);

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

  const openEvidence = (hotspot) => {
    setActiveHotspot(hotspot);
    setEvidenceOpen(true);
    setEvidenceLoading(true);
    setEvidenceError(null);
    setEvidenceItems([]);
    apiService
      .getHotspotEvidence(hotspot.hotspot_id)
      .then((items) => setEvidenceItems(Array.isArray(items) ? items : []))
      .catch((err) => setEvidenceError(err.message || 'Failed to load evidence for hotspot'))
      .finally(() => setEvidenceLoading(false));
  };

  const closeEvidence = () => {
    setEvidenceOpen(false);
    setActiveHotspot(null);
    setEvidenceItems([]);
    setEvidenceError(null);
  };

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
                  <th>Evidence</th>
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
                    <td>
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => openEvidence(h)}
                      >
                        View evidence
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {evidenceOpen && (
        <div className="modal-overlay" onClick={closeEvidence}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>
              Hotspot evidence
              {activeHotspot?.incident_type_name && ` – ${activeHotspot.incident_type_name}`}
            </h3>
            {evidenceLoading && <p className="loading">Loading evidence…</p>}
            {evidenceError && <p className="error-message">{evidenceError}</p>}
            {!evidenceLoading && !evidenceError && evidenceItems.length === 0 && (
              <p className="empty">No evidence for this hotspot.</p>
            )}
            {!evidenceLoading && !evidenceError && evidenceItems.length > 0 && (
              <EvidenceCarousel items={evidenceItems} />
            )}
            <div className="form-actions" style={{ marginTop: '1rem', justifyContent: 'flex-end' }}>
              <button type="button" onClick={closeEvidence}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
