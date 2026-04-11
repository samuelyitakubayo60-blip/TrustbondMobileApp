import React, { useEffect, useState } from 'react';
import api from '../../api/client';
import AdvancedGeographicCharts from '../charts/AdvancedGeographicCharts';
import AdvancedGeoMap from '../maps/AdvancedGeoMap';

const EnhancedGeographicIntelligence = () => {
  const [activeTab, setActiveTab] = useState('overview');
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [timeWindow, setTimeWindow] = useState(720);
  const [selectedSector, setSelectedSector] = useState('all');
  const [sectors, setSectors] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(false);

  // Auto-refresh effect
  useEffect(() => {
    if (!autoRefresh) return;
    
    const interval = setInterval(() => {
      loadData();
    }, 30000); // Refresh every 30 seconds

    return () => clearInterval(interval);
  }, [autoRefresh, activeTab, timeWindow, selectedSector]);

  // Load sectors for dropdown
  useEffect(() => {
    api.get('/api/v1/locations')
      .then(res => {
        const sectorList = (res || []).filter(loc => loc.location_type === 'sector');
        setSectors(sectorList);
      })
      .catch(() => setSectors([]));
  }, []);

  // Load data based on active tab
  useEffect(() => {
    loadData();
  }, [activeTab, timeWindow, selectedSector]);

  const loadData = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        time_window_hours: timeWindow,
        ...(selectedSector !== 'all' && { sector_id: selectedSector })
      });

      let endpoint;
      switch (activeTab) {
        case 'overview':
          // Load multiple endpoints for overview
          const [heatMap, sectorPerf, behavior, movement] = await Promise.all([
            api.get(`/api/v1/geographic-intelligence/heat-map?${params}`),
            api.get(`/api/v1/geographic-intelligence/sector-performance?${params}`),
            api.get(`/api/v1/geographic-intelligence/behavior-patterns?${params}`),
            api.get(`/api/v1/geographic-intelligence/movement-flows?${params}`)
          ]);
          
          setData({
            heatMapData: heatMap.heat_map_data,
            sectors: sectorPerf.performance_data,
            behaviorAnalysis: behavior.behavior_analysis,
            flowData: movement.flow_data,
            totalReports: heatMap.total_reports,
            totalDevices: behavior.devices_analyzed,
            timeWindow: heatMap.time_window_hours
          });
          break;

        case 'heat-map':
          endpoint = `/api/v1/geographic-intelligence/heat-map?${params}`;
          const heatData = await api.get(endpoint);
          setData({
            ...heatData,
            reportsByTime: generateTimeSeriesData(heatData.reports || [])
          });
          break;

        case 'movement-flows':
          endpoint = `/api/v1/geographic-intelligence/movement-flows?${params}`;
          const flowData = await api.get(endpoint);
          setData(flowData);
          break;

        case 'coverage':
          endpoint = `/api/v1/geographic-intelligence/coverage-analysis?${params}`;
          const coverageData = await api.get(endpoint);
          setData(coverageData);
          break;

        case 'sector-performance':
          endpoint = `/api/v1/geographic-intelligence/sector-performance?${params}`;
          const sectorData = await api.get(endpoint);
          setData(sectorData);
          break;

        case 'behavior-patterns':
          endpoint = `/api/v1/geographic-intelligence/behavior-patterns?${params}`;
          const behaviorData = await api.get(endpoint);
          setData(behaviorData);
          break;

        case 'speed-analysis':
          endpoint = `/api/v1/geographic-intelligence/speed-analysis?${params}`;
          const speedData = await api.get(endpoint);
          setData(speedData);
          break;

        case 'geographic-clustering':
          endpoint = `/api/v1/geographic-intelligence/geographic-clustering?${params}`;
          const clusterData = await api.get(endpoint);
          setData(clusterData);
          break;

        case 'frequency-analysis':
          endpoint = `/api/v1/geographic-intelligence/frequency-analysis?${params}`;
          const frequencyData = await api.get(endpoint);
          setData(frequencyData);
          break;

        default:
          endpoint = `/api/v1/geographic-intelligence/heat-map?${params}`;
          const defaultData = await api.get(endpoint);
          setData(defaultData);
      }
    } catch (error) {
      console.error('Error loading geographic intelligence data:', error);
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  // Helper function to generate time series data
  const generateTimeSeriesData = (reports) => {
    const timeGroups = {};
    reports.forEach(report => {
      const hour = new Date(report.reported_at).getTime();
      const hourKey = Math.floor(hour / (1000 * 60 * 60)) * (1000 * 60 * 60); // Round to hour
      timeGroups[hourKey] = (timeGroups[hourKey] || 0) + 1;
    });

    return Object.entries(timeGroups).map(([time, count]) => ({
      x: parseInt(time),
      y: count
    }));
  };

  const exportData = () => {
    if (!data) return;
    
    const dataStr = JSON.stringify(data, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `geographic-intelligence-${activeTab}-${new Date().toISOString().split('T')[0]}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const renderOverviewTab = () => (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Key Metrics */}
      <div className="col-span-2 grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white p-4 rounded-lg shadow border border-gray-200">
          <div className="text-sm text-gray-600">Total Reports</div>
          <div className="text-2xl font-bold text-blue-600">{data?.totalReports || 0}</div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow border border-gray-200">
          <div className="text-sm text-gray-600">Active Devices</div>
          <div className="text-2xl font-bold text-green-600">{data?.totalDevices || 0}</div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow border border-gray-200">
          <div className="text-sm text-gray-600">Sectors</div>
          <div className="text-2xl font-bold text-purple-600">{data?.sectors?.length || 0}</div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow border border-gray-200">
          <div className="text-sm text-gray-600">Time Window</div>
          <div className="text-2xl font-bold text-orange-600">{timeWindow}h</div>
        </div>
      </div>

      {/* Heat Map */}
      <div className="bg-white p-4 rounded-lg shadow">
        <h3 className="text-lg font-semibold mb-4">🗺️ Geographic Heat Map</h3>
        <AdvancedGeoMap data={data} mapType="heatmap" />
      </div>

      {/* Sector Performance Chart */}
      <div className="bg-white p-4 rounded-lg shadow">
        <h3 className="text-lg font-semibold mb-4">📊 Sector Performance</h3>
        <AdvancedGeographicCharts data={data} type="sectorPerformance" timeWindow={timeWindow} />
      </div>

      {/* Movement Flows */}
      <div className="bg-white p-4 rounded-lg shadow">
        <h3 className="text-lg font-semibold mb-4">🌊 Movement Flows</h3>
        <AdvancedGeoMap data={data} mapType="flows" />
      </div>

      {/* Behavior Patterns */}
      <div className="bg-white p-4 rounded-lg shadow">
        <h3 className="text-lg font-semibold mb-4">🧠 Behavior Patterns</h3>
        <AdvancedGeographicCharts data={data} type="behaviorRadar" timeWindow={timeWindow} />
      </div>
    </div>
  );

  const renderAdvancedTab = (chartType, mapType, title) => (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="bg-white p-4 rounded-lg shadow">
        <h3 className="text-lg font-semibold mb-4">📊 {title} Analysis</h3>
        <AdvancedGeographicCharts data={data} type={chartType} timeWindow={timeWindow} />
      </div>
      <div className="bg-white p-4 rounded-lg shadow">
        <h3 className="text-lg font-semibold mb-4">🗺️ {title} Map</h3>
        <AdvancedGeoMap data={data} mapType={mapType} onMarkerClick={setSelectedDevice} />
      </div>
    </div>
  );

  const renderContent = () => {
    if (loading) {
      return (
        <div className="flex justify-center items-center h-64">
          <div className="text-center">
            <i className="fa fa-spinner fa-spin fa-3x text-blue-500"></i>
            <p className="mt-4 text-gray-600">Loading advanced analytics...</p>
          </div>
        </div>
      );
    }

    if (!data) {
      return (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <div className="flex">
            <i className="fa fa-exclamation-triangle text-yellow-600 mr-3"></i>
            <div>
              <h3 className="text-sm font-medium text-yellow-800">No Data Available</h3>
              <p className="mt-1 text-sm text-yellow-700">
                No geographic intelligence data found for the selected time window and filters.
              </p>
            </div>
          </div>
        </div>
      );
    }

    switch (activeTab) {
      case 'overview':
        return renderOverviewTab();
      case 'heat-map':
        return renderAdvancedTab('timeSeries', 'heatmap', 'Heat Map');
      case 'movement-flows':
        return renderAdvancedTab('movementFlow', 'flows', 'Movement Flow');
      case 'coverage':
        return renderAdvancedTab('incidentDistribution', 'sectors', 'Coverage');
      case 'sector-performance':
        return renderAdvancedTab('sectorPerformance', 'sectors', 'Sector Performance');
      case 'behavior-patterns':
        return renderAdvancedTab('behaviorRadar', 'devices', 'Behavior Pattern');
      case 'speed-analysis':
        return renderAdvancedTab('speedAnalysis', 'devices', 'Speed Analysis');
      case 'geographic-clustering':
        return renderAdvancedTab('incidentDistribution', 'clusters', 'Geographic Clustering');
      case 'frequency-analysis':
        return renderAdvancedTab('nightActivity', 'devices', 'Frequency Analysis');
      default:
        return renderOverviewTab();
    }
  };

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">🧠 Advanced Geographic Intelligence</h1>
          <p className="text-gray-600">Comprehensive location analytics and pattern detection</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`px-4 py-2 rounded-lg font-medium ${
              autoRefresh 
                ? 'bg-green-500 text-white hover:bg-green-600' 
                : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
            }`}
          >
            <i className={`fa fa-${autoRefresh ? 'pause' : 'play'} mr-2`}></i>
            Auto-Refresh
          </button>
          <button
            onClick={exportData}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 font-medium"
          >
            <i className="fa fa-download mr-2"></i>
            Export Data
          </button>
          <button
            onClick={loadData}
            className="px-4 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 font-medium"
          >
            <i className="fa fa-refresh mr-2"></i>
            Refresh
          </button>
        </div>
      </div>

      {/* Controls */}
      <div className="bg-white p-4 rounded-lg shadow mb-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Time Window</label>
            <select 
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              value={timeWindow} 
              onChange={(e) => setTimeWindow(Number(e.target.value))}
            >
              <option value={1}>Last 1 Hour</option>
              <option value={6}>Last 6 Hours</option>
              <option value={24}>Last 24 Hours</option>
              <option value={168}>Last 7 Days</option>
              <option value={720}>Last 30 Days</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Sector Filter</label>
            <select 
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              value={selectedSector} 
              onChange={(e) => setSelectedSector(e.target.value)}
            >
              <option value="all">All Sectors</option>
              {sectors.map(sector => (
                <option key={sector.location_id} value={sector.location_id}>
                  {sector.location_name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Quick Actions</label>
            <div className="flex gap-2">
              <button
                onClick={() => setTimeWindow(24)}
                className="px-3 py-2 bg-gray-100 text-gray-700 rounded hover:bg-gray-200 text-sm"
              >
                Today
              </button>
              <button
                onClick={() => setTimeWindow(168)}
                className="px-3 py-2 bg-gray-100 text-gray-700 rounded hover:bg-gray-200 text-sm"
              >
                Week
              </button>
              <button
                onClick={() => setTimeWindow(720)}
                className="px-3 py-2 bg-gray-100 text-gray-700 rounded hover:bg-gray-200 text-sm"
              >
                Month
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Selected Device Info */}
      {selectedDevice && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
          <div className="flex justify-between items-start">
            <div>
              <h3 className="text-sm font-medium text-blue-800">Selected Device</h3>
              <p className="mt-1 text-sm text-blue-700">
                <strong>Device:</strong> {selectedDevice.device_hash}<br/>
                <strong>Status:</strong> {selectedDevice.suspicious_score > 50 ? '⚠️ Suspicious' : '✅ Normal'}<br/>
                <strong>Reports:</strong> {selectedDevice.total_reports}<br/>
                <strong>Trust Score:</strong> {selectedDevice.trust_score || 0}
              </p>
            </div>
            <button
              onClick={() => setSelectedDevice(null)}
              className="text-blue-600 hover:text-blue-800"
            >
              <i className="fa fa-times"></i>
            </button>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="bg-white rounded-lg shadow">
        <div className="border-b border-gray-200">
          <nav className="flex -mb-px">
            {[
              { id: 'overview', label: '📊 Overview', icon: 'dashboard' },
              { id: 'heat-map', label: '🔥 Heat Map', icon: 'fire' },
              { id: 'movement-flows', label: '🌊 Movement Flows', icon: 'exchange' },
              { id: 'coverage', label: '📈 Coverage', icon: 'map' },
              { id: 'sector-performance', label: '🏆 Sector Performance', icon: 'trophy' },
              { id: 'behavior-patterns', label: '🧠 Behavior Patterns', icon: 'brain' },
              { id: 'speed-analysis', label: '⚡ Speed Analysis', icon: 'tachometer' },
              { id: 'geographic-clustering', label: '🗺️ Clustering', icon: 'cluster' },
              { id: 'frequency-analysis', label: '📊 Frequency', icon: 'clock-o' }
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`py-3 px-4 border-b-2 font-medium text-sm ${
                  activeTab === tab.id
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                <i className={`fa fa-${tab.icon} mr-2`}></i>
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        {/* Tab Content */}
        <div className="p-6">
          {renderContent()}
        </div>
      </div>
    </div>
  );
};

export default EnhancedGeographicIntelligence;
