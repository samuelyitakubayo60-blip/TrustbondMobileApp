import React, { useEffect, useState } from 'react';
import api from '../../api/client';

const StationDetailModal = ({ isOpen, onClose, station }) => {
  const [officers, setOfficers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    if (!isOpen || !station) return;
    
    setLoading(true);
    const fetchData = async () => {
      try {
        // Fetch officers assigned to this station
        console.log(`Fetching officers for station ${station.station_id}`);
        const officersRes = await api.get(`/api/v1/police-users/?station_id=${station.station_id}`);
        console.log('Officers API response:', officersRes);
        
        // Handle both direct array response and paginated response with items
        const officersList = Array.isArray(officersRes) ? officersRes : (officersRes?.items || []);
        console.log('Officers count:', officersList.length);
        setOfficers(officersList);

        // Fetch station-specific statistics (fallback to dashboard if station endpoint not available)
        let statsRes;
        try {
          statsRes = await api.get(`/api/v1/stats/station/${station.station_id}`);
        } catch (error) {
          if (error.response?.status === 404) {
            // Fallback to dashboard stats if station endpoint not deployed yet
            console.log('Station stats endpoint not available, using dashboard stats as fallback');
            statsRes = await api.get(`/api/v1/stats/dashboard`);
          } else {
            throw error;
          }
        }
        setStats(statsRes);
      } catch (error) {
        console.error('Failed to fetch station details:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [isOpen, station]);

  if (!isOpen || !station) return null;

  const formatDate = (dateString) => {
    if (!dateString) return '—';
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const formatCoordinates = (lat, long) => {
    if (!lat || !long) return '—';
    return `${parseFloat(lat).toFixed(6)}, ${parseFloat(long).toFixed(6)}`;
  };

  return (
    <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: '700px', width: '90%' }}>
        <div className="modal-header">
          <div className="modal-title">Station Details - {station.station_name}</div>
          <div className="modal-close" onClick={onClose}>✕</div>
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: '40px', color: 'var(--muted)' }}>
            Loading station details...
          </div>
        ) : (
          <div style={{ maxHeight: '70vh', overflowY: 'auto' }}>
            {/* Station Information */}
            <div className="card" style={{ marginBottom: '16px' }}>
              <div className="card-header">
                <div className="card-title">Station Information</div>
              </div>
              <div style={{ padding: '16px' }}>
                <div className="form-grid">
                  <div className="input-group">
                    <div className="input-label">Station Code</div>
                    <div style={{ fontSize: '14px', fontWeight: 'bold' }}>
                      {station.station_code || '—'}
                    </div>
                  </div>
                  <div className="input-group">
                    <div className="input-label">Station Type</div>
                    <div style={{ fontSize: '14px' }}>
                      <span className={`badge ${
                        station.station_type === 'headquarters' ? 'b-blue' :
                        station.station_type === 'station' ? 'b-green' :
                        'b-orange'
                      }`}>
                        {station.station_type || '—'}
                      </span>
                    </div>
                  </div>
                </div>

                <div style={{ marginTop: '16px' }}>
                  <div className="input-label">Geographic Coverage</div>
                  <div style={{ fontSize: '14px', marginTop: '4px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                      <strong>Primary Sector:</strong> {station.location_name || '—'}
                    </div>
                    {station.sector2_name && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <strong>Secondary Sector:</strong> {station.sector2_name}
                      </div>
                    )}
                    {!station.sector2_name && (
                      <div style={{ fontSize: '12px', color: 'var(--muted)', fontStyle: 'italic' }}>
                        No secondary sector assigned
                      </div>
                    )}
                  </div>
                </div>

                <div className="form-grid" style={{ marginTop: '16px' }}>
                  <div className="input-group">
                    <div className="input-label">Coordinates</div>
                    <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                      {formatCoordinates(station.latitude, station.longitude)}
                    </div>
                  </div>
                  <div className="input-group">
                    <div className="input-label">Status</div>
                    <div>
                      <span className={`badge ${station.is_active ? 'b-green' : 'b-red'}`}>
                        {station.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                  </div>
                </div>

                {station.address_text && (
                  <div style={{ marginTop: '16px' }}>
                    <div className="input-label">Address</div>
                    <div style={{ fontSize: '14px' }}>
                      {station.address_text}
                    </div>
                  </div>
                )}

                <div className="form-grid" style={{ marginTop: '16px' }}>
                  <div className="input-group">
                    <div className="input-label">Phone</div>
                    <div style={{ fontSize: '14px' }}>
                      {station.phone_number || '—'}
                    </div>
                  </div>
                  <div className="input-group">
                    <div className="input-label">Email</div>
                    <div style={{ fontSize: '14px' }}>
                      {station.email || '—'}
                    </div>
                  </div>
                </div>

                <div className="form-grid" style={{ marginTop: '16px' }}>
                  <div className="input-group">
                    <div className="input-label">Created</div>
                    <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                      {formatDate(station.created_at)}
                    </div>
                  </div>
                  <div className="input-group">
                    <div className="input-label">Last Updated</div>
                    <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                      {formatDate(station.updated_at)}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Assigned Officers */}
            <div className="card" style={{ marginBottom: '16px' }}>
              <div className="card-header">
                <div className="card-title">Assigned Officers ({officers.length})</div>
              </div>
              <div style={{ padding: '16px' }}>
                {officers.length === 0 ? (
                  <div style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center', padding: '20px' }}>
                    No officers assigned to this station
                  </div>
                ) : (
                  <div style={{ display: 'grid', gap: '8px' }}>
                    {officers.map((officer) => (
                      <div
                        key={officer.police_user_id}
                        style={{
                          padding: '8px 12px',
                          border: '1px solid var(--border)',
                          borderRadius: '4px',
                          fontSize: '13px'
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <div>
                            <strong>{officer.first_name} {officer.last_name}</strong>
                            {officer.badge_number && (
                              <span style={{ marginLeft: '8px', fontSize: '11px', color: 'var(--muted)' }}>
                                Badge: {officer.badge_number}
                              </span>
                            )}
                          </div>
                          <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                            <span className={`badge ${
                              officer.role === 'admin' ? 'b-purple' :
                              officer.role === 'supervisor' ? 'b-blue' :
                              'b-green'
                            }`} style={{ fontSize: '10px' }}>
                              {officer.role}
                            </span>
                            <span className={`badge ${officer.is_active ? 'b-green' : 'b-red'}`} style={{ fontSize: '10px' }}>
                              {officer.is_active ? 'Active' : 'Inactive'}
                            </span>
                          </div>
                        </div>
                        {officer.email && (
                          <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '2px' }}>
                            {officer.email}
                          </div>
                        )}
                        {officer.phone_number && (
                          <div style={{ fontSize: '11px', color: 'var(--muted)' }}>
                            {officer.phone_number}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Report Statistics */}
            {stats && (
              <div className="card">
                <div className="card-header">
                  <div className="card-title">Report Statistics</div>
                </div>
                <div style={{ padding: '16px' }}>
                  {/* Overview Stats */}
                  <div style={{ marginBottom: '20px' }}>
                    <div style={{ fontSize: '14px', fontWeight: 'bold', marginBottom: '8px', color: 'var(--muted)' }}>OVERVIEW</div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '8px' }}>
                      <div style={{ textAlign: 'center', padding: '8px', border: '1px solid var(--border)', borderRadius: '4px' }}>
                        <div style={{ fontSize: '18px', fontWeight: 'bold', color: 'var(--primary)' }}>
                          {stats.total_reports || 0}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--muted)' }}>Total Reports</div>
                      </div>
                      <div style={{ textAlign: 'center', padding: '8px', border: '1px solid var(--border)', borderRadius: '4px' }}>
                        <div style={{ fontSize: '18px', fontWeight: 'bold', color: 'var(--success)' }}>
                          {stats.verified_reports || 0}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--muted)' }}>Verified</div>
                      </div>
                      <div style={{ textAlign: 'center', padding: '8px', border: '1px solid var(--border)', borderRadius: '4px' }}>
                        <div style={{ fontSize: '18px', fontWeight: 'bold', color: 'var(--warning)' }}>
                          {stats.pending_reports || 0}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--muted)' }}>Pending</div>
                      </div>
                      <div style={{ textAlign: 'center', padding: '8px', border: '1px solid var(--border)', borderRadius: '4px' }}>
                        <div style={{ fontSize: '18px', fontWeight: 'bold', color: 'var(--danger)' }}>
                          {stats.rejected_reports || 0}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--muted)' }}>Rejected</div>
                      </div>
                      <div style={{ textAlign: 'center', padding: '8px', border: '1px solid var(--border)', borderRadius: '4px' }}>
                        <div style={{ fontSize: '18px', fontWeight: 'bold', color: 'var(--info)' }}>
                          {stats.active_cases || 0}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--muted)' }}>Active Cases</div>
                      </div>
                    </div>
                  </div>

                  {/* Verification Details */}
                  <div style={{ marginBottom: '20px' }}>
                    <div style={{ fontSize: '14px', fontWeight: 'bold', marginBottom: '8px', color: 'var(--muted)' }}>VERIFICATION DETAILS</div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '8px' }}>
                      <div style={{ textAlign: 'center', padding: '8px', border: '1px solid var(--border)', borderRadius: '4px' }}>
                        <div style={{ fontSize: '18px', fontWeight: 'bold', color: '#ff6b35' }}>
                          {stats.flagged_reports || 0}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--muted)' }}>Flagged</div>
                      </div>
                      <div style={{ textAlign: 'center', padding: '8px', border: '1px solid var(--border)', borderRadius: '4px' }}>
                        <div style={{ fontSize: '18px', fontWeight: 'bold', color: '#28a745' }}>
                          {stats.auto_confirmed_reports || 0}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--muted)' }}>Auto-Confirmed</div>
                      </div>
                      <div style={{ textAlign: 'center', padding: '8px', border: '1px solid var(--border)', borderRadius: '4px' }}>
                        <div style={{ fontSize: '18px', fontWeight: 'bold', color: '#007bff' }}>
                          {stats.officer_confirmed_reports || 0}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--muted)' }}>Officer Confirmed</div>
                      </div>
                    </div>
                  </div>

                  {/* Rejection Details */}
                  <div>
                    <div style={{ fontSize: '14px', fontWeight: 'bold', marginBottom: '8px', color: 'var(--muted)' }}>REJECTION DETAILS</div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '8px' }}>
                      <div style={{ textAlign: 'center', padding: '8px', border: '1px solid var(--border)', borderRadius: '4px' }}>
                        <div style={{ fontSize: '18px', fontWeight: 'bold', color: '#dc3545' }}>
                          {stats.auto_rejected_reports || 0}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--muted)' }}>Auto Rejected</div>
                      </div>
                      <div style={{ textAlign: 'center', padding: '8px', border: '1px solid var(--border)', borderRadius: '4px' }}>
                        <div style={{ fontSize: '18px', fontWeight: 'bold', color: '#6f42c1' }}>
                          {stats.manually_rejected_reports || 0}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--muted)' }}>Manually Rejected</div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '16px' }}>
          <button className="btn btn-primary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

export default StationDetailModal;
