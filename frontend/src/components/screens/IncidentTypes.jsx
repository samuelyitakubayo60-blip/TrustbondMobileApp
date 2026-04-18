import React, { useEffect, useState } from 'react';
import api from '../../api/client';
import Chart from 'chart.js/auto';

const IncidentTypes = ({ openModal, onEditIncidentType, refreshKey, wsRefreshKey }) => {
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [incidentChart, setIncidentChart] = useState(null);
  const [chartData, setChartData] = useState({});
  const [sortBy, setSortBy] = useState('incidentType');
  const [sortOrder, setSortOrder] = useState('desc');

  const loadTypes = () => {
    Promise.resolve().then(() => setLoading(true));
    Promise.all([
      api.get('/api/v1/incident-types?include_inactive=true'),
      api.get('/api/v1/reports?limit=100')
    ])
      .then(([typesRes, reportsRes]) => {
        setTypes(typesRes || []);
        processChartData(reportsRes || []);
        setLoading(false);
      })
      .catch((error) => {
        console.error('Error loading data:', error);
        // Still set types even if reports fail
        api.get('/api/v1/incident-types?include_inactive=true')
          .then((typesRes) => {
            setTypes(typesRes || []);
            setLoading(false);
          })
          .catch(() => { setLoading(false); });
      });
  };

  const processChartData = (reports) => {
    console.log('📊 Processing chart data:', reports);
    
    // Handle different API response structures
    let reportsArray = [];
    if (Array.isArray(reports)) {
      reportsArray = reports;
    } else if (reports && reports.data && Array.isArray(reports.data)) {
      reportsArray = reports.data;
    } else if (reports && reports.items && Array.isArray(reports.items)) {
      reportsArray = reports.items;
    } else if (reports && reports.reports && Array.isArray(reports.reports)) {
      reportsArray = reports.reports;
    } else {
      console.warn('⚠️ No valid reports array found in response:', reports);
      setChartData({ incidentTypes: {} });
      return;
    }
    
    console.log('📊 Reports array to process:', reportsArray);
    
    const incidentTypeCounts = {};
    const sectorCounts = {};
    const stationCounts = {};
    
    reportsArray.forEach(report => {
      // Incident type counts
      const incidentName = report.incident_type?.type_name || report.incident_type_name || `Type ${report.incident_type_id || 'Unknown'}`;
      incidentTypeCounts[incidentName] = (incidentTypeCounts[incidentName] || 0) + 1;
      
      // Sector counts - Extract from backend location hierarchy
      let sectorName = 'Unknown Sector';
      
      // Use the sector_name provided by the backend from location hierarchy
      if (report.sector_name) {
        sectorName = report.sector_name;
      }
      // Fallback to direct sector references if available
      else if (report.sector) {
        sectorName = report.sector;
      }
      
      // Map to known Musanze sectors if possible
      const musanzeSectors = [
        'Busogo', 'Cyuve', 'Gaculiro', 'Gashaki', 'Gataraga', 
        'Kimonyi', 'Kinigi', 'Mukingo', 'Muhoza', 'Nkotsi', 
        'Nyange', 'Remera', 'Ruhengeri', 'Rwinzovu', 'Shingiro'
      ];
      
      if (musanzeSectors.includes(sectorName)) {
        sectorCounts[sectorName] = (sectorCounts[sectorName] || 0) + 1;
      } else if (sectorName !== 'Unknown Sector') {
        // Only use "Other/Unknown" if we have actual sector data but it's not in known list
        sectorCounts['Other/Unknown'] = (sectorCounts['Other/Unknown'] || 0) + 1;
      }
      // Don't count "Unknown Sector" - we'll handle this differently
      
      // Police station grouping - Extract from backend assigned_station data
      let stationName = 'Unknown Station';
      
      // Use the assigned_station provided by the backend from police user assignments
      if (report.assigned_station && report.assigned_station.station_name) {
        stationName = report.assigned_station.station_name;
      }
      // Fallback to direct station references if available
      else if (report.station_name) {
        stationName = report.station_name;
      } else if (report.station) {
        stationName = report.station;
      }
      
      // Known Musanze area police stations from station table
      const knownStations = [
        'Musanze Central Police Station', 'Kinigi Police Station', 
        'Busogo Police Station', 'Cyuve Police Station', 'Gashaki Police Station',
        'Ruhengeri Police Station', 'Muhoza Police Station'
      ];
      
      if (knownStations.includes(stationName)) {
        stationCounts[stationName] = (stationCounts[stationName] || 0) + 1;
      } else if (stationName !== 'Unknown Station') {
        // Count other stations that might exist in the database
        stationCounts[stationName] = (stationCounts[stationName] || 0) + 1;
      } else {
        // Only count as unassigned if no station assignment found
        stationCounts['Unassigned'] = (stationCounts['Unassigned'] || 0) + 1;
      }
    });
    
    console.log('📊 Processed data:', { incidentTypeCounts, sectorCounts, stationCounts });
    
    // Post-process to handle misleading labels
    const processedSectors = { ...sectorCounts };
    const processedStations = { ...stationCounts };
    
    // Handle sector data - if only "Other/Unknown" exists, rename it to be more descriptive
    const sectorKeys = Object.keys(processedSectors);
    if (sectorKeys.length === 1 && sectorKeys[0] === 'Other/Unknown') {
      processedSectors['No Sector Data Available'] = processedSectors['Other/Unknown'];
      delete processedSectors['Other/Unknown'];
    }
    
    // Handle station data - if only "Unassigned" exists, rename it to be more descriptive
    const stationKeys = Object.keys(processedStations);
    if (stationKeys.length === 1 && stationKeys[0] === 'Unassigned') {
      processedStations['No Station Assignment Data'] = processedStations['Unassigned'];
      delete processedStations['Unassigned'];
    }
    
    setChartData({
      incidentTypes: incidentTypeCounts,
      sectors: processedSectors,
      stations: processedStations
    });
  };

  const getSortedChartData = () => {
    let data = {};
    
    switch (sortBy) {
      case 'incidentType':
        data = chartData.incidentTypes || {};
        break;
      case 'sector':
        data = chartData.sectors || {};
        break;
      case 'stations':
        data = chartData.stations || {};
        break;
      default:
        data = chartData.incidentTypes || {};
    }
    
    // Sort the data
    const sortedEntries = Object.entries(data).sort((a, b) => {
      if (sortOrder === 'desc') {
        return b[1] - a[1];
      } else {
        return a[1] - b[1];
      }
    });
    
    return {
      labels: sortedEntries.map(([key]) => key),
      data: sortedEntries.map(([, value]) => value)
    };
  };

  const createIncidentChart = () => {
    const canvas = document.getElementById('incidentChart');
    if (!canvas) return;

    // Clear canvas manually
    const ctx = canvas.getContext('2d');
    if (ctx) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }

    // Destroy existing chart
    if (incidentChart) {
      incidentChart.destroy();
      setIncidentChart(null);
    }

    const sortedData = getSortedChartData();
    
    // Always render chart, even with no data
    const labels = sortedData.labels.length > 0 ? sortedData.labels : ['No Data'];
    const data = sortedData.data.length > 0 ? sortedData.data : [0];

    // Get chart title based on sort type
    const getChartTitle = () => {
      switch (sortBy) {
        case 'incidentType':
          return '⚠️ Incident Type Distribution';
        case 'sector':
          return '🏛️ Incident Distribution by Sector';
        case 'stations':
          return '🚔 Incident Distribution by Police Station';
        default:
          return '⚠️ Incident Type Distribution';
      }
    };

    const chart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Incident Count',
          data: data,
          backgroundColor: 'rgba(147, 51, 234, 0.8)',
          borderColor: 'rgba(147, 51, 234, 1)',
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        plugins: {
          title: {
            display: true,
            text: getChartTitle()
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            title: {
              display: true,
              text: 'Number of Incidents'
            }
          }
        }
      }
    });
    
    setIncidentChart(chart);
  };

  useEffect(() => {
    if (Object.keys(chartData).length > 0) {
      createIncidentChart();
    }
  }, [chartData, sortBy, sortOrder]);

  useEffect(() => {
    loadTypes();
  }, [refreshKey, wsRefreshKey]);

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
        <p>Configure categories and priority levels for incident reporting and analysis.</p>
      </div>

      <div className="alert alert-info">
        <span className="alert-icon">i</span>
        <div>Priority level affects incident ranking and alert severity.</div>
      </div>

      <div className="card">
        <div className="card-header">
          <div className="card-title">Incident Distribution Analysis</div>
        </div>
        <div className="card-body">
          {/* Sorting Controls */}
          <div className="mb-4" style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <label style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-primary)' }}>
                Sort by:
              </label>
              <select 
                value={sortBy} 
                onChange={(e) => setSortBy(e.target.value)}
                style={{ 
                  padding: '6px 10px', 
                  border: '1px solid var(--border)', 
                  borderRadius: '6px',
                  fontSize: '14px',
                  backgroundColor: 'var(--background)',
                  color: 'var(--text-primary)'
                }}
              >
                <option value="incidentType">Incident Type</option>
                <option value="sector">Sector</option>
                <option value="stations">Police Station</option>
              </select>
            </div>
            
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <label style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-primary)' }}>
                Order:
              </label>
              <select 
                value={sortOrder} 
                onChange={(e) => setSortOrder(e.target.value)}
                style={{ 
                  padding: '6px 10px', 
                  border: '1px solid var(--border)', 
                  borderRadius: '6px',
                  fontSize: '14px',
                  backgroundColor: 'var(--background)',
                  color: 'var(--text-primary)'
                }}
              >
                <option value="desc">Highest First</option>
                <option value="asc">Lowest First</option>
              </select>
            </div>
          </div>
          
          <canvas id="incidentChart" width="400" height="200"></canvas>
          <div className="mt-4 text-sm text-gray-600">
            <p><strong>📊 Incident Distribution Analysis</strong></p>
            <p>This interactive chart displays incident breakdown by different categories. 
            Use the sorting controls above to analyze patterns by incident type, sector, or severity level. 
            Understanding these distributions helps allocate resources effectively and identify emerging trends.</p>
          </div>
        </div>
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
                <th>#</th>
                <th>Name</th>
                <th>Description</th>
                <th>Severity</th>
                <th>Level</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {types.map((t, index) => {
                const sev = Number(t.severity_weight ?? 1).toFixed(2);
                let level = 'Low';
                let badge = 'b-gray';
                const val = Number(t.severity_weight ?? 1);
                if (val >= 1.6) { level = 'Severe'; badge = 'b-red'; }
                else if (val >= 1.3) { level = 'High'; badge = 'b-orange'; }
                else if (val >= 1.1) { level = 'Medium'; badge = 'b-blue'; }

                return (
                  <tr key={t.incident_type_id}>
                    <td style={{ fontSize: "12px", color: "var(--muted)", textAlign: "center" }}>
                      {index + 1}
                    </td>
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
                  <td colSpan={7} style={{ fontSize: '12px', color: 'var(--muted)', textAlign: 'center' }}>
                    No incident types found.
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

export default IncidentTypes;