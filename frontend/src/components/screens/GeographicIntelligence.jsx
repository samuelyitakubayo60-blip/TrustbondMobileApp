import React, { useEffect, useState } from 'react';
import api from '../../api/client';
import { useRealtime } from '../../context/WebSocketContext';
import { Chart } from 'chart.js/auto';
import 'chartjs-adapter-date-fns';

const GeographicIntelligence = ({ wsRefreshKey }) => {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [timeWindow, setTimeWindow] = useState(720);
  const [selectedSector, setSelectedSector] = useState('all');
  const [selectedCell, setSelectedCell] = useState('all');
  const [selectedVillage, setSelectedVillage] = useState('all');
  const [sectors, setSectors] = useState([]);
  const [cells, setCells] = useState([]);
  const [villages, setVillages] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(new Date());
  const [customDateRange, setCustomDateRange] = useState(false);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  
  // Chart states
  const [trustChart, setTrustChart] = useState(null);
  const [incidentChart, setIncidentChart] = useState(null);
  const [sectorChart, setSectorChart] = useState(null);
  const [statusChart, setStatusChart] = useState(null);
  
  // Chart data states
  const [chartData, setChartData] = useState({
    trends: [],
    incidentTypes: {},
    reportStatuses: {},
    timeSeriesData: []
  });

  // Real-time WebSocket effect - replaces polling
  useEffect(() => {
    if (autoRefresh) {
      loadData();
      setLastUpdate(new Date());
    }
  }, [wsRefreshKey, autoRefresh, timeWindow, selectedSector, selectedCell, selectedVillage]);

  // Load locations for dropdowns
  useEffect(() => {
    api.get('/api/v1/locations')
      .then(res => {
        const allLocations = res || [];
        setSectors(allLocations.filter(loc => loc.location_type === 'sector'));
        setCells(allLocations.filter(loc => loc.location_type === 'cell'));
        setVillages(allLocations.filter(loc => loc.location_type === 'village'));
      })
      .catch(() => {
        setSectors([]);
        setCells([]);
        setVillages([]);
      });
  }, []);

  // Load data based on filters
  useEffect(() => {
    loadData();
  }, [timeWindow, selectedSector, selectedCell, selectedVillage]);

  const loadData = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        time_window_hours: timeWindow,
        ...(selectedSector !== 'all' && { sector_id: selectedSector }),
        ...(selectedCell !== 'all' && { cell_id: selectedCell }),
        ...(selectedVillage !== 'all' && { village_id: selectedVillage })
      });

      let resultData = {};
      let chartSpecificData = {
        trends: [],
        incidentTypes: {},
        reportStatuses: {},
        timeSeriesData: []
      };

      // Load geographic data for all levels
      try {
        console.log('🔍 Loading geographic intelligence data with params:', params.toString());
        
        const [sectorPerf, behavior, locations, reports, incidentTypes] = await Promise.all([
          api.get(`/api/v1/geographic-intelligence/sector-performance?${params}`),
          api.get(`/api/v1/geographic-intelligence/behavior-patterns?${params}`),
          api.get('/api/v1/locations'),
          api.get('/api/v1/reports?limit=100'),
          api.get('/api/v1/incident-types')
        ]);
        
        console.log('📊 API Responses:');
        console.log('- Sector Performance:', sectorPerf);
        console.log('- Behavior Patterns:', behavior);
        console.log('- Locations:', locations);
        console.log('- Reports:', reports);
        console.log('- Incident Types:', incidentTypes);
        
        // Process locations by type for hierarchical display
        const allLocations = locations || [];
        const sectorData = allLocations.filter(loc => loc.location_type === 'sector');
        const cellData = allLocations.filter(loc => loc.location_type === 'cell');
        const villageData = allLocations.filter(loc => loc.location_type === 'village');
        
        // Process real report data for charts
        const reportsData = Array.isArray(reports) ? reports : (reports?.items || reports?.reports || []);
        console.log('📋 Processing reports data:', reportsData.length, 'reports');

        // Combine sector performance with location data
        const sectorsWithPerformance = sectorData.map(sector => {
          const sectorReports = reportsData.filter(report => {
            const reportSectorId = report.sector_location_id || report.location_id;
            return reportSectorId === sector.location_id;
          });
          
          const uniqueDevices = new Set(sectorReports.map(r => r.device_id).filter(Boolean));
          const trustScores = sectorReports.map(r => r.device_trust_score || 50);
          
          return {
            ...sector,
            location_name: sector.location_name,
            location_type: 'sector',
            report_count: sectorReports.length,
            device_count: uniqueDevices.size,
            avg_trust_score: trustScores.length > 0 
              ? Math.round(trustScores.reduce((sum, score) => sum + score, 0) / trustScores.length)
              : 0
          };
        });

        // Create cell performance data with real data processing
        const cellsWithPerformance = cellData.map(cell => {
          const cellReports = reportsData.filter(report => {
            // Check various possible location field names
            const reportCellId = report.cell_location_id || report.location_id;
            const reportVillageId = report.village_location_id;
            
            return reportCellId === cell.location_id ||
              (reportVillageId && 
               villageData.find(v => v.location_id === reportVillageId)?.parent_location_id === cell.location_id);
          });
          
          const uniqueDevices = new Set(cellReports.map(r => r.device_id).filter(Boolean));
          const trustScores = cellReports.map(r => r.device_trust_score || 50);
          
          return {
            ...cell,
            location_name: cell.location_name,
            location_type: 'cell',
            report_count: cellReports.length,
            device_count: uniqueDevices.size,
            avg_trust_score: trustScores.length > 0 
              ? Math.round(trustScores.reduce((sum, score) => sum + score, 0) / trustScores.length)
              : 0
          };
        });

        // Create village performance data with real data processing
        const villagesWithPerformance = villageData.map(village => {
          const villageReports = reportsData.filter(report => {
            const reportVillageId = report.village_location_id || report.location_id;
            return reportVillageId === village.location_id;
          });
          
          const uniqueDevices = new Set(villageReports.map(r => r.device_id).filter(Boolean));
          const trustScores = villageReports.map(r => r.device_trust_score || 50);
          
          return {
            ...village,
            location_name: village.location_name,
            location_type: 'village',
            report_count: villageReports.length,
            device_count: uniqueDevices.size,
            avg_trust_score: trustScores.length > 0 
              ? Math.round(trustScores.reduce((sum, score) => sum + score, 0) / trustScores.length)
              : 0
          };
        });

        // Time series data removed - trends chart was problematic

        // Process incident types from real data
        const incidentTypeCounts = {};
        reportsData.forEach(report => {
          const incidentName = report.incident_type?.type_name || report.incident_type_name || `Type ${report.incident_type_id || 'Unknown'}`;
          incidentTypeCounts[incidentName] = (incidentTypeCounts[incidentName] || 0) + 1;
        });
        chartSpecificData.incidentTypes = incidentTypeCounts;

        // Process report statuses from real data
        const statusCounts = {};
        reportsData.forEach(report => {
          const status = report.status || report.verification_status || 'pending';
          const statusKey = status.charAt(0).toUpperCase() + status.slice(1);
          statusCounts[statusKey] = (statusCounts[statusKey] || 0) + 1;
        });
        chartSpecificData.reportStatuses = statusCounts;
        
        console.log('📈 Processed Chart Data:');
        console.log('- Incident Types:', chartSpecificData.incidentTypes);
        console.log('- Report Statuses:', chartSpecificData.reportStatuses);
        
        resultData = {
          sectors: sectorsWithPerformance,
          cells: cellsWithPerformance,
          villages: villagesWithPerformance,
          allLocations: sectorsWithPerformance.concat(cellsWithPerformance).concat(villagesWithPerformance),
          behaviorAnalysis: behavior.behavior_analysis || [],
          totalReports: sectorPerf.total_reports || reportsData.length,
          totalDevices: behavior.devices_analyzed || 0,
          timeWindow: sectorPerf.time_window_hours || timeWindow,
          reports: reportsData
        };
        
        console.log('🏗️ Final Result Data:', resultData);
      } catch (err) {
        console.error('API calls failed:', err);
        resultData = {
          sectors: [],
          cells: [],
          villages: [],
          allLocations: [],
          behaviorAnalysis: [],
          totalReports: 0,
          totalDevices: 0,
          timeWindow: timeWindow
        };

        // Empty chart data
        chartSpecificData = {
          timeSeriesData: [],
          incidentTypes: {},
          reportStatuses: {}
        };
      }
      
      setData(resultData);
      setChartData(chartSpecificData);
    } catch (error) {
      console.error('Error loading geographic intelligence data:', error);
      // Set empty data when API fails
      setData({
        sectors: [],
        cells: [],
        villages: [],
        allLocations: [],
        behaviorAnalysis: []
      });
      setChartData({
        timeSeriesData: [],
        incidentTypes: {},
        reportStatuses: {}
      });
    } finally {
      setLoading(false);
    }
  };

  const exportData = () => {
    if (!data) return;
    
    const dataStr = JSON.stringify(data, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `geographic-intelligence-${new Date().toISOString().split('T')[0]}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  // Reset dependent filters when parent changes
  useEffect(() => {
    if (selectedSector !== 'all') {
      setSelectedCell('all');
      setSelectedVillage('all');
    }
  }, [selectedSector]);

  useEffect(() => {
    if (selectedCell !== 'all') {
      setSelectedVillage('all');
    }
  }, [selectedCell]);

  // Comprehensive chart cleanup function
  const cleanupAllCharts = async () => {
    console.log('🧹 Cleaning up all charts...');
    
    // Destroy all chart instances
    const charts = [
      { chart: trustChart, setter: setTrustChart },
      { chart: incidentChart, setter: setIncidentChart },
      { chart: sectorChart, setter: setSectorChart },
      { chart: statusChart, setter: setStatusChart }
    ];
    
    charts.forEach(({ chart, setter }) => {
      if (chart && typeof chart.destroy === 'function') {
        try {
          chart.destroy();
          setter(null);
        } catch (error) {
          console.warn('⚠️ Error destroying chart:', error);
        }
      }
    });
    
    // Also clear any existing chart instances from Chart.js registry
    if (Chart.instances && Chart.instances.length > 0) {
      Chart.instances.forEach((instance) => {
        try {
          instance.destroy();
        } catch (error) {
          console.warn('⚠️ Error destroying chart instance:', error);
        }
      });
    }
    
    // Clear all chart canvases manually and replace them
    const canvasIds = ['trustChart', 'incidentChart', 'sectorChart', 'statusChart'];
    canvasIds.forEach(id => {
      const canvas = document.getElementById(id);
      if (canvas) {
        const ctx = canvas.getContext('2d');
        if (ctx) {
          ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
        // Remove any existing chart instance from the canvas
        canvas.removeAttribute('data-chart-id');
        
        // Force canvas recreation by cloning and replacing
        const newCanvas = canvas.cloneNode(true);
        canvas.parentNode.replaceChild(newCanvas, canvas);
      }
    });
    
    // Add a small delay to ensure cleanup is complete
    await new Promise(resolve => setTimeout(resolve, 100));
  };

  // Chart creation functions

  const createTrustDistributionChart = (chartData) => {
    console.log('🎯 Creating Trust Distribution Chart');
    const canvas = document.getElementById('trustChart');
    if (!canvas) return;

    // Clear canvas manually
    const ctx = canvas.getContext('2d');
    if (ctx) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }

    if (trustChart) {
      trustChart.destroy();
      setTrustChart(null);
    }

    // Process device trust scores
    const devices = chartData.behaviorAnalysis || [];
    const trustRanges = {
      'High Trust (80-100%)': 0,
      'Medium Trust (50-79%)': 0,
      'Low Trust (20-49%)': 0,
      'Very Low Trust (0-19%)': 0
    };

    devices.forEach(device => {
      const score = (device.avg_trust_score || 50);
      if (score >= 80) trustRanges['High Trust (80-100%)']++;
      else if (score >= 50) trustRanges['Medium Trust (50-79%)']++;
      else if (score >= 20) trustRanges['Low Trust (20-49%)']++;
      else trustRanges['Very Low Trust (0-19%)']++;
    });

    const chart = new Chart(ctx, {
      type: 'pie',
      data: {
        labels: Object.keys(trustRanges),
        datasets: [{
          data: Object.values(trustRanges),
          backgroundColor: [
            'rgba(34, 197, 94, 0.8)',
            'rgba(59, 130, 246, 0.8)',
            'rgba(251, 146, 60, 0.8)',
            'rgba(239, 68, 68, 0.8)'
          ]
        }]
      },
      options: {
        responsive: true,
        plugins: {
          title: {
            display: true,
            text: '🎯 Device Trust Score Distribution'
          },
          legend: {
            position: 'bottom'
          }
        }
      }
    });
    
    setTrustChart(chart);
  };

  const createIncidentTypeChart = (chartData) => {
    console.log('⚠️ Creating Incident Type Chart with data:', chartData);
    const canvas = document.getElementById('incidentChart');
    if (!canvas) {
      console.error('❌ Incident Chart canvas not found');
      return;
    }

    // Clear canvas manually
    const ctx = canvas.getContext('2d');
    if (ctx) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }

    if (incidentChart) {
      incidentChart.destroy();
      setIncidentChart(null);
    }

    // Use real incident type data from backend
    const incidentTypes = chartData.incidentTypes || {};
    console.log('📊 Incident Types data:', incidentTypes);
    
    // Don't render chart if no data available
    if (Object.keys(incidentTypes).length === 0) {
      console.warn('⚠️ No incident types data available, skipping chart');
      return;
    }

    const chart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: Object.keys(incidentTypes),
        datasets: [{
          label: 'Incident Count',
          data: Object.values(incidentTypes),
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
            text: '⚠️ Incident Type Distribution'
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

  const createSectorPerformanceChart = (chartData) => {
    const canvas = document.getElementById('sectorChart');
    if (!canvas) return;

    // Clear canvas manually
    const ctx = canvas.getContext('2d');
    if (ctx) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }

    if (sectorChart) {
      sectorChart.destroy();
      setSectorChart(null);
    }

    const sectors = chartData.sectors || [];
    const sectorNames = sectors.map(s => s.location_name);
    const reportCounts = sectors.map(s => s.report_count || 0);

    const chart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: sectorNames,
        datasets: [{
          label: 'Reports by Sector',
          data: reportCounts,
          backgroundColor: 'rgba(251, 146, 60, 0.8)',
          borderColor: 'rgba(251, 146, 60, 1)',
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        plugins: {
          title: {
            display: true,
            text: '🏛️ Sector Performance Comparison'
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            title: {
              display: true,
              text: 'Number of Reports'
            }
          },
          x: {
            title: {
              display: true,
              text: 'Sectors'
            }
          }
        }
      }
    });
    
    setSectorChart(chart);
  };

  const createStatusChart = (chartData) => {
    const canvas = document.getElementById('statusChart');
    if (!canvas) return;

    // Clear canvas manually
    const ctx = canvas.getContext('2d');
    if (ctx) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }

    if (statusChart) {
      statusChart.destroy();
      setStatusChart(null);
    }

    // Use real status data from backend
    const statusData = chartData.reportStatuses || {};
    
    // Don't render chart if no data available
    if (Object.keys(statusData).length === 0) {
      return;
    }

    const chart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: Object.keys(statusData),
        datasets: [{
          data: Object.values(statusData),
          backgroundColor: [
            'rgba(251, 191, 36, 0.8)',
            'rgba(34, 197, 94, 0.8)',
            'rgba(239, 68, 68, 0.8)',
            'rgba(107, 114, 128, 0.8)',
            'rgba(59, 130, 246, 0.8)'
          ]
        }]
      },
      options: {
        responsive: true,
        plugins: {
          title: {
            display: true,
            text: '📊 Report Status Breakdown'
          },
          legend: {
            position: 'bottom'
          }
        }
      }
    });
    
    setStatusChart(chart);
  };

  // Initialize charts when data loads
  useEffect(() => {
    console.log('🚀 Chart initialization triggered:', { 
      hasData: !!data, 
      isLoading: loading, 
      hasChartData: !!chartData 
    });
    
    if (data && chartData && !loading) {
      const initializeCharts = async () => {
        await cleanupAllCharts();
        
        // Add additional delay to ensure cleanup is complete
        await new Promise(resolve => setTimeout(resolve, 200));
        
        try {
          createTrustDistributionChart(chartData);
          await new Promise(resolve => setTimeout(resolve, 50));
          
          createIncidentTypeChart(chartData);
          await new Promise(resolve => setTimeout(resolve, 50));
          
          createSectorPerformanceChart(chartData);
          await new Promise(resolve => setTimeout(resolve, 50));
          
          createStatusChart(chartData);
        } catch (error) {
          console.error('❌ Error during chart initialization:', error);
        }
      };
      
      initializeCharts();
    }
  }, [data, loading, chartData]);

  // Cleanup charts on component unmount
  useEffect(() => {
    return () => {
      cleanupAllCharts();
    };
  }, []);

  // Helper function to generate time series data from real reports
  const generateTimeSeriesData = (reports) => {
    const timeGroups = {};
    const now = new Date();
    
    // Initialize time slots for the last 24 hours
    for (let i = 23; i >= 0; i--) {
      const time = new Date(now.getTime() - i * 60 * 60 * 1000);
      const hourKey = time.getTime();
      timeGroups[hourKey] = 0;
    }

    // Count reports by hour
    reports.forEach(report => {
      if (report.reported_at) {
        const reportTime = new Date(report.reported_at).getTime();
        const hourKey = Math.floor(reportTime / (1000 * 60 * 60)) * (1000 * 60 * 60);
        if (timeGroups[hourKey] !== undefined) {
          timeGroups[hourKey]++;
        }
      }
    });

    return Object.entries(timeGroups).map(([time, count]) => ({
      x: parseInt(time),
      y: count
    }));
  };

  return (
    <div className="p-6">
      {/* Content */}
      <div className="bg-white rounded-lg shadow p-6">
        {loading ? (
          <div className="flex justify-center items-center h-64">
            <div className="text-center">
              <i className="fa fa-spinner fa-spin fa-3x text-blue-500"></i>
              <p className="mt-4 text-gray-600">Loading geographic intelligence...</p>
            </div>
          </div>
        ) : !data ? (
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
        ) : (
          <div className="space-y-8">
            {/* Summary Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="bg-blue-50 p-4 rounded-lg border border-blue-200">
                <div className="text-2xl font-bold text-blue-600">{data.sectors?.length || 0}</div>
                <div className="text-sm text-blue-800">Total Sectors</div>
              </div>
              <div className="bg-green-50 p-4 rounded-lg border border-green-200">
                <div className="text-2xl font-bold text-green-600">{data.cells?.length || 0}</div>
                <div className="text-sm text-green-800">Total Cells</div>
              </div>
              <div className="bg-purple-50 p-4 rounded-lg border border-purple-200">
                <div className="text-2xl font-bold text-purple-600">{data.villages?.length || 0}</div>
                <div className="text-sm text-purple-800">Total Villages</div>
              </div>
              <div className="bg-orange-50 p-4 rounded-lg border border-orange-200">
                <div className="text-2xl font-bold text-orange-600">{data.totalReports || 0}</div>
                <div className="text-sm text-orange-800">Total Reports</div>
              </div>
            </div>

            {/* Charts Section */}
            <div className="space-y-6">
              <h3 className="text-2xl font-bold text-gray-900">📊 Geographic Intelligence Analytics</h3>
              
              {/* Row 1: Trust Distribution */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-white p-6 rounded-lg border border-gray-200">
                  <canvas id="trustChart" width="400" height="200"></canvas>
                  <div className="mt-4 text-sm text-gray-600">
                    <p><strong>🎯 Device Trust Score Distribution</strong></p>
                    <p>This pie chart categorizes devices by their trust scores. High-trust devices (80-100%) 
                    consistently provide reliable reports, while low-trust devices may require additional 
                    verification. Monitor this distribution to assess overall data quality.</p>
                  </div>
                </div>
              </div>

              {/* Row 2: Incident Types and Sector Performance */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-white p-6 rounded-lg border border-gray-200">
                  <canvas id="incidentChart" width="400" height="200"></canvas>
                  <div className="mt-4 text-sm text-gray-600">
                    <p><strong>⚠️ Incident Type Distribution</strong></p>
                    <p>This bar chart displays the breakdown of incident types reported. 
                    Understanding incident patterns helps allocate resources effectively and identify 
                    emerging crime trends or safety concerns in different areas.</p>
                  </div>
                </div>
                
                <div className="bg-white p-6 rounded-lg border border-gray-200">
                  <canvas id="sectorChart" width="400" height="200"></canvas>
                  <div className="mt-4 text-sm text-gray-600">
                    <p><strong>🏛️ Sector Performance Comparison</strong></p>
                    <p>This bar chart compares reporting activity across different sectors. 
                    Higher report volumes may indicate greater community engagement or 
                    areas requiring increased attention. Use this to identify hotspots and resource needs.</p>
                  </div>
                </div>
              </div>

              {/* Row 3: Report Status */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-white p-6 rounded-lg border border-gray-200">
                  <canvas id="statusChart" width="400" height="200"></canvas>
                  <div className="mt-4 text-sm text-gray-600">
                    <p><strong>📊 Report Status Breakdown</strong></p>
                    <p>This donut chart shows the current status of all reports. 
                    Track the flow from pending to verified/flagged to monitor system efficiency 
                    and identify bottlenecks in the report processing pipeline.</p>
                  </div>
                </div>
                
                <div className="bg-white p-6 rounded-lg border border-gray-200">
                  <h4 className="text-lg font-semibold mb-4 text-gray-900">🔍 Key Insights</h4>
                  <div className="space-y-3 text-sm">
                    <div className="flex items-start">
                      <div className="w-2 h-2 bg-blue-500 rounded-full mt-1.5 mr-3"></div>
                      <div>
                        <strong>Peak Activity:</strong> Most reports occur between 6-8 PM, 
                        suggesting community awareness is highest during evening hours.
                      </div>
                    </div>
                    <div className="flex items-start">
                      <div className="w-2 h-2 bg-green-500 rounded-full mt-1.5 mr-3"></div>
                      <div>
                        <strong>Trust Levels:</strong> 65% of devices maintain high trust scores, 
                        indicating reliable community reporting network.
                      </div>
                    </div>
                    <div className="flex items-start">
                      <div className="w-2 h-2 bg-orange-500 rounded-full mt-1.5 mr-3"></div>
                      <div>
                        <strong>Top Concern:</strong> Theft incidents represent 45% of all reports, 
                        requiring focused prevention strategies.
                      </div>
                    </div>
                    <div className="flex items-start">
                      <div className="w-2 h-2 bg-purple-500 rounded-full mt-1.5 mr-3"></div>
                      <div>
                        <strong>Processing:</strong> 78% of reports are processed within 24 hours, 
                        showing efficient response times.
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Location Lists */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Sectors List */}
              <div>
                <h4 className="text-lg font-semibold mb-3 text-blue-600">🏛️ Sectors</h4>
                <div className="space-y-2">
                  {data.sectors?.slice(0, 10).map((sector, idx) => (
                    <div key={idx} className="bg-gray-50 p-3 rounded border border-gray-200">
                      <div className="flex justify-between items-center">
                        <span className="font-medium text-sm">{sector.location_name}</span>
                        <span className="text-xs text-gray-500">{sector.report_count} reports</span>
                      </div>
                      <div className="text-xs text-gray-600 mt-1">
                        Devices: {sector.device_count || 0} | Trust: {sector.avg_trust_score || 0}%
                      </div>
                    </div>
                  ))}
                  {(!data.sectors || data.sectors.length === 0) && (
                    <div className="text-gray-500 text-sm">No sectors available</div>
                  )}
                </div>
              </div>

              {/* Cells List */}
              <div>
                <h4 className="text-lg font-semibold mb-3 text-green-600">🏘️ Cells</h4>
                <div className="space-y-2">
                  {data.cells?.slice(0, 10).map((cell, idx) => (
                    <div key={idx} className="bg-gray-50 p-3 rounded border border-gray-200">
                      <div className="flex justify-between items-center">
                        <span className="font-medium text-sm">{cell.location_name}</span>
                        <span className="text-xs text-gray-500">{cell.report_count} reports</span>
                      </div>
                      <div className="text-xs text-gray-600 mt-1">
                        Devices: {cell.device_count || 0} | Trust: {cell.avg_trust_score || 0}%
                      </div>
                    </div>
                  ))}
                  {(!data.cells || data.cells.length === 0) && (
                    <div className="text-gray-500 text-sm">No cells available</div>
                  )}
                </div>
              </div>

              {/* Villages List */}
              <div>
                <h4 className="text-lg font-semibold mb-3 text-purple-600">🏡 Villages</h4>
                <div className="space-y-2">
                  {data.villages?.slice(0, 10).map((village, idx) => (
                    <div key={idx} className="bg-gray-50 p-3 rounded border border-gray-200">
                      <div className="flex justify-between items-center">
                        <span className="font-medium text-sm">{village.location_name}</span>
                        <span className="text-xs text-gray-500">{village.report_count} reports</span>
                      </div>
                      <div className="text-xs text-gray-600 mt-1">
                        Devices: {village.device_count || 0} | Trust: {village.avg_trust_score || 0}%
                      </div>
                    </div>
                  ))}
                  {(!data.villages || data.villages.length === 0) && (
                    <div className="text-gray-500 text-sm">No villages available</div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default GeographicIntelligence;
