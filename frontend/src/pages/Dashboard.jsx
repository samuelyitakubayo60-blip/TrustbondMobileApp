import { useState, useEffect } from 'react';
import Layout from '../components/Layout.jsx';
import { useAuth } from '../contexts/AuthContext.jsx';
import { apiService } from '../services/apiService.js';
import '../styles/colors.css';

export default function Dashboard() {
  const { user, isOfficer } = useAuth();
  const [stats, setStats] = useState(null);
  const [incidentGroups, setIncidentGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    apiService
      .getDashboardStats()
      .then((data) => {
        if (!cancelled) setStats(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load stats');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (isOfficer) return;
    let cancelled = false;
    apiService
      .getIncidentGroups({ limit: 10 })
      .then((list) => {
        if (!cancelled) setIncidentGroups(Array.isArray(list) ? list : []);
      })
      .catch(() => {
        if (!cancelled) setIncidentGroups([]);
      });
    return () => { cancelled = true; };
  }, [isOfficer]);

  return (
    <Layout>
      <div className="page-dashboard">
        <h2>Welcome, {user?.first_name}!</h2>
        {loading && <p className="loading">Loading stats…</p>}
        {error && <p className="error-message">{error}</p>}
        {!loading && !error && stats && (
          <div className="stats-cards">
            <div className="stat-card">
              <span className="stat-value">{stats.total_reports ?? 0}</span>
              <span className="stat-label">{isOfficer ? 'Assigned to you' : 'Total reports'}</span>
            </div>
            <div className="stat-card">
              <span className="stat-value">{stats.reports_last_7_days ?? 0}</span>
              <span className="stat-label">{isOfficer ? 'Last 7 days (yours)' : 'Last 7 days'}</span>
            </div>
            <div className="stat-card highlight">
              <span className="stat-value">{stats.by_status?.pending ?? 0}</span>
              <span className="stat-label">Pending</span>
            </div>
            <div className="stat-card">
              <span className="stat-value">{stats.by_status?.passed ?? 0}</span>
              <span className="stat-label">Passed</span>
            </div>
            <div className="stat-card">
              <span className="stat-value">{stats.by_status?.flagged ?? 0}</span>
              <span className="stat-label">Flagged</span>
            </div>
          </div>
        )}
        {!loading && !isOfficer && incidentGroups.length > 0 && (
          <div className="dashboard-section">
            <h3>Recent incident groups</h3>
            <p className="form-hint">Spatial-temporal clusters of incidents.</p>
            <div className="table-wrap">
              <table className="users-table">
                <thead>
                  <tr>
                    <th>Type ID</th>
                    <th>Center (lat, long)</th>
                    <th>Reports</th>
                    <th>Time window</th>
                  </tr>
                </thead>
                <tbody>
                  {incidentGroups.map((g) => (
                    <tr key={g.group_id}>
                      <td>{g.incident_type_id}</td>
                      <td>{Number(g.center_lat).toFixed(4)}, {Number(g.center_long).toFixed(4)}</td>
                      <td>{g.report_count}</td>
                      <td>{g.start_time && g.end_time ? `${new Date(g.start_time).toLocaleDateString()} – ${new Date(g.end_time).toLocaleDateString()}` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}
