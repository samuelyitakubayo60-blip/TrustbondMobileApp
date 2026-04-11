import React, { useEffect, useRef } from 'react';
import { Chart } from 'chart.js/auto';
import 'chartjs-adapter-date-fns';
import zoomPlugin from 'chartjs-plugin-zoom';
import ChartDataLabels from 'chartjs-plugin-datalabels';

// Register Chart.js plugins
Chart.register(zoomPlugin, ChartDataLabels);

const AdvancedGeographicCharts = ({ data, type, timeWindow }) => {
  console.log('AdvancedGeographicCharts rendered with:', { type, data, timeWindow });
  
  const chartRef = useRef(null);
  const chartInstance = useRef(null);
  const chartConfig = useRef(null);

  useEffect(() => {
    if (!chartRef.current) return;

    // Destroy existing chart
    if (chartInstance.current) {
      chartInstance.current.destroy();
      chartInstance.current = null;
    }

    const ctx = chartRef.current.getContext('2d');
    if (!ctx) return;

    let chartConfig;
    
    // Use fallback data if no data provided
    const chartData = data || {};
    
    switch (type) {
      case 'timeSeries':
        chartConfig = createTimeSeriesChart(chartData);
        break;
      case 'sectorPerformance':
        chartConfig = createSectorPerformanceChart(chartData);
        break;
      case 'personalPerformance':
        chartConfig = createPersonalPerformanceChart(chartData);
        break;
      case 'behaviorRadar':
        chartConfig = createBehaviorRadarChart(chartData);
        break;
      case 'incidentDistribution':
        chartConfig = createIncidentDistributionChart(chartData);
        break;
      case 'movementFlow':
        chartConfig = createMovementFlowChart(chartData);
        break;
      case 'speedAnalysis':
        chartConfig = createSpeedAnalysisChart(chartData);
        break;
      case 'nightActivity':
        chartConfig = createNightActivityChart(chartData);
        break;
      case 'trustScoreDistribution':
        chartConfig = createTrustScoreChart(chartData);
        break;
      default:
        chartConfig = createTimeSeriesChart(chartData);
    }

    try {
      if (chartConfig) {
        chartInstance.current = new Chart(ctx, chartConfig);
      }
    } catch (err) {
      console.error('Chart error:', err);
    }

    return () => {
      if (chartInstance.current) {
        chartInstance.current.destroy();
        chartInstance.current = null;
      }
    };
  }, [data, type, timeWindow]);

  // Chart Configuration Functions
  const createTimeSeriesChart = (data) => {
    const reportsByTime = data.reportsByTime || [
      { x: Date.now() - 86400000, y: 5 },
      { x: Date.now() - 43200000, y: 8 },
      { x: Date.now(), y: 12 }
    ];
    
    return {
      type: 'line',
      data: {
        datasets: [{
          label: 'Reports Over Time',
          data: reportsByTime,
          borderColor: 'rgb(75, 192, 192)',
          backgroundColor: 'rgba(75, 192, 192, 0.2)',
          tension: 0.4,
          fill: true,
          pointRadius: 4,
          pointHoverRadius: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'index',
          intersect: false,
        },
        plugins: {
          title: {
            display: true,
            text: `Report Trends - Last ${timeWindow || 720} Hours`
          },
          legend: {
            display: true
          }
        },
        scales: {
          x: {
            type: 'time',
            time: {
              unit: 'hour',
              displayFormats: {
                hour: 'MMM dd, HH:mm'
              }
            },
            title: {
              display: true,
              text: 'Time'
            }
          },
          y: {
            beginAtZero: true,
            title: {
              display: true,
              text: 'Number of Reports'
            }
          }
        }
      }
    };
  };

  const createPersonalPerformanceChart = (data) => {
  const performanceData = data.performance_data || [
    { date: 'Mon', reports_processed: 8, avg_response_time: 15 },
    { date: 'Tue', reports_processed: 12, avg_response_time: 12 },
    { date: 'Wed', reports_processed: 10, avg_response_time: 18 },
    { date: 'Thu', reports_processed: 15, avg_response_time: 10 },
    { date: 'Fri', reports_processed: 9, avg_response_time: 20 }
  ];
  
  return {
    type: 'line',
    data: {
      labels: performanceData.map(d => d.date),
      datasets: [
        {
          label: 'Reports Processed',
          data: performanceData.map(d => d.reports_processed || 0),
          borderColor: 'rgba(54, 162, 235, 1)',
          backgroundColor: 'rgba(54, 162, 235, 0.2)',
          borderWidth: 2,
          tension: 0.4,
          yAxisID: 'y'
        },
        {
          label: 'Avg Response Time (min)',
          data: performanceData.map(d => d.avg_response_time || 0),
          borderColor: 'rgba(255, 99, 132, 1)',
          backgroundColor: 'rgba(255, 99, 132, 0.2)',
          borderWidth: 2,
          tension: 0.4,
          yAxisID: 'y1'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false,
      },
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: {
            color: '#fff',
            font: {
              size: 12
            }
          }
        },
        tooltip: {
          backgroundColor: 'rgba(0, 0, 0, 0.8)',
          titleColor: '#fff',
          bodyColor: '#fff',
          borderColor: 'rgba(255, 255, 255, 0.2)',
          borderWidth: 1
        }
      },
      scales: {
        x: {
          grid: {
            color: 'rgba(255, 255, 255, 0.1)'
          },
          ticks: {
            color: '#fff'
          }
        },
        y: {
          type: 'linear',
          display: true,
          position: 'left',
          title: {
            display: true,
            text: 'Reports Processed',
            color: '#fff'
          },
          grid: {
            color: 'rgba(255, 255, 255, 0.1)'
          },
          ticks: {
            color: '#fff'
          }
        },
        y1: {
          type: 'linear',
          display: true,
          position: 'right',
          title: {
            display: true,
            text: 'Response Time (min)',
            color: '#fff'
          },
          grid: {
            drawOnChartArea: false,
          },
          ticks: {
            color: '#fff'
          }
        }
      }
    }
  };
};

  const createSectorPerformanceChart = (data) => {
    const sectors = data.performance_data || data.sectors || [
      { sector_name: 'Sector A', report_count: 15, device_count: 5, avg_trust_score: 75 },
      { sector_name: 'Sector B', report_count: 23, device_count: 8, avg_trust_score: 82 },
      { sector_name: 'Sector C', report_count: 8, device_count: 3, avg_trust_score: 68 }
    ];
    
    return {
      type: 'bar',
      data: {
        labels: sectors.map(s => s.sector_name),
        datasets: [
          {
            label: 'Total Reports',
            data: sectors.map(s => s.report_count || 0),
            backgroundColor: 'rgba(54, 162, 235, 0.8)',
            borderColor: 'rgba(54, 162, 235, 1)',
            borderWidth: 1
          },
          {
            label: 'Device Count',
            data: sectors.map(s => s.device_count || 0),
            backgroundColor: 'rgba(255, 99, 132, 0.8)',
            borderColor: 'rgba(255, 99, 132, 1)',
            borderWidth: 1
          },
          {
            label: 'Avg Trust Score',
            data: sectors.map(s => s.avg_trust_score || 0),
            backgroundColor: 'rgba(75, 192, 192, 0.8)',
            borderColor: 'rgba(75, 192, 192, 1)',
            borderWidth: 1
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: {
            display: true,
            text: 'Sector Performance Comparison'
          },
          legend: {
            display: true
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            title: {
              display: true,
              text: 'Count / Score'
            }
          }
        }
      }
    };
  };

  const createBehaviorRadarChart = (data) => {
    const behaviorAnalysis = data.behaviorAnalysis || [
      { device_hash: 'DEV001', automation_score: 30, suspicious_score: 20, night_activity_ratio: 0.3 },
      { device_hash: 'DEV002', automation_score: 80, suspicious_score: 60, night_activity_ratio: 0.7 }
    ];
    
    return {
      type: 'radar',
      data: {
        labels: ['Automation Score', 'Suspicious Score', 'Night Activity', 'High Speed', 'Frequency', 'Mobility'],
        datasets: behaviorAnalysis.slice(0, 3).map((device, index) => ({
          label: `Device ${device.device_hash || (index + 1)}`,
          data: [
            device.automation_score || Math.random() * 100,
            device.suspicious_score || Math.random() * 100,
            (device.night_activity_ratio || 0) * 100,
            device.avg_speed > 50 ? 80 : (device.avg_speed || 0) * 1.6,
            device.avg_frequency > 5 ? 90 : (device.avg_frequency || 0) * 18,
            device.avg_distance > 20 ? 85 : (device.avg_distance || 0) * 4.25
          ],
          backgroundColor: `hsla(${index * 60}, 70%, 60%, 0.2)`,
          borderColor: `hsla(${index * 60}, 70%, 60%, 1)`,
          borderWidth: 2,
          pointBackgroundColor: `hsla(${index * 60}, 70%, 60%, 1)`,
          pointBorderColor: '#fff',
          pointHoverBackgroundColor: '#fff',
          pointHoverBorderColor: `hsla(${index * 60}, 70%, 60%, 1)`
        }))
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: {
            display: true,
            text: 'Device Behavior Patterns'
          }
        },
        scales: {
          r: {
            beginAtZero: true,
            max: 100,
            ticks: {
              stepSize: 20
            }
          }
        }
      }
    };
  };

  const createIncidentDistributionChart = (data) => {
    const incidentTypes = data.incidentTypes || [
      { name: 'Theft', count: 25 },
      { name: 'Assault', count: 15 },
      { name: 'Vandalism', count: 10 },
      { name: 'Other', count: 8 }
    ];
    
    return {
      type: 'doughnut',
      data: {
        labels: incidentTypes.map(t => t.name),
        datasets: [{
          data: incidentTypes.map(t => t.count),
          backgroundColor: [
            'rgba(255, 99, 132, 0.8)',
            'rgba(54, 162, 235, 0.8)',
            'rgba(255, 205, 86, 0.8)',
            'rgba(75, 192, 192, 0.8)',
            'rgba(153, 102, 255, 0.8)',
            'rgba(255, 159, 64, 0.8)'
          ],
          borderColor: [
            'rgba(255, 99, 132, 1)',
            'rgba(54, 162, 235, 1)',
            'rgba(255, 205, 86, 1)',
            'rgba(75, 192, 192, 1)',
            'rgba(153, 102, 255, 1)',
            'rgba(255, 159, 64, 1)'
          ],
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: {
            display: true,
            text: 'Incident Type Distribution'
          },
          legend: {
            position: 'right'
          }
        }
      }
    };
  };

  const createMovementFlowChart = (data) => {
    const flowData = data.flowData || [
      { from_sector: 'Sector A', to_sector: 'Sector B', flow_strength: 5 },
      { from_sector: 'Sector B', to_sector: 'Sector C', flow_strength: 3 },
      { from_sector: 'Sector C', to_sector: 'Sector A', flow_strength: 2 }
    ];
    
    return {
      type: 'bar',
      data: {
        labels: flowData.map(f => `${f.from_sector || 'Unknown'} → ${f.to_sector || 'Unknown'}`),
        datasets: [{
          label: 'Movement Flow Strength',
          data: flowData.map(f => f.flow_strength || 0),
          backgroundColor: 'rgba(153, 102, 255, 0.8)',
          borderColor: 'rgba(153, 102, 255, 1)',
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: 'y',
        plugins: {
          title: {
            display: true,
            text: 'Device Movement Flows Between Sectors'
          }
        },
        scales: {
          x: {
            beginAtZero: true,
            title: {
              display: true,
              text: 'Flow Strength'
            }
          }
        }
      }
    };
  };

  const createSpeedAnalysisChart = (data) => {
    const speedData = data.speedData || [
      { device_id: 'DEV001', avg_speed: 25 },
      { device_id: 'DEV002', avg_speed: 45 },
      { device_id: 'DEV003', avg_speed: 15 }
    ];
    
    return {
      type: 'scatter',
      data: {
        datasets: [{
          label: 'Device Speeds',
          data: speedData.map(d => ({
            x: d.device_id || 'Unknown',
            y: d.avg_speed || 0
          })),
          backgroundColor: 'rgba(255, 99, 132, 0.6)',
          borderColor: 'rgba(255, 99, 132, 1)',
          pointRadius: 8,
          pointHoverRadius: 10
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: {
            display: true,
            text: 'Device Speed Analysis'
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            title: {
              display: true,
              text: 'Average Speed (km/h)'
            }
          },
          x: {
            title: {
              display: true,
              text: 'Device ID'
            }
          }
        }
      }
    };
  };

  const createNightActivityChart = (data) => {
    const behaviorAnalysis = data.behaviorAnalysis || [
      { device_hash: 'DEV001', night_activity_ratio: 0.3 },
      { device_hash: 'DEV002', night_activity_ratio: 0.7 },
      { device_hash: 'DEV003', night_activity_ratio: 0.5 }
    ];
    
    return {
      type: 'bar',
      data: {
        labels: behaviorAnalysis.map(d => d.device_hash || 'Unknown'),
        datasets: [
          {
            label: 'Night Activity (%)',
            data: behaviorAnalysis.map(d => (d.night_activity_ratio || 0) * 100),
            backgroundColor: 'rgba(75, 192, 192, 0.8)',
            borderColor: 'rgba(75, 192, 192, 1)',
            borderWidth: 1
          },
          {
            label: 'Day Activity (%)',
            data: behaviorAnalysis.map(d => (1 - (d.night_activity_ratio || 0)) * 100),
            backgroundColor: 'rgba(255, 205, 86, 0.8)',
            borderColor: 'rgba(255, 205, 86, 1)',
            borderWidth: 1
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: {
            display: true,
            text: 'Night vs Day Activity Patterns'
          }
        },
        scales: {
          x: {
            stacked: true,
            title: {
              display: true,
              text: 'Devices'
            }
          },
          y: {
            stacked: true,
            beginAtZero: true,
            max: 100,
            title: {
              display: true,
              text: 'Activity Percentage'
            }
          }
        }
      }
    };
  };

  const createTrustScoreChart = (data) => {
    const trustScoreDistribution = data.trustScoreDistribution || [3, 8, 12, 6, 2];
    
    return {
      type: 'bar',
      data: {
        labels: ['0-20', '21-40', '41-60', '61-80', '81-100'],
        datasets: [{
          label: 'Number of Devices',
          data: trustScoreDistribution,
          backgroundColor: 'rgba(54, 162, 235, 0.8)',
          borderColor: 'rgba(54, 162, 235, 1)',
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: {
            display: true,
            text: 'Trust Score Distribution'
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            title: {
              display: true,
              text: 'Number of Devices'
            }
          },
          x: {
            title: {
              display: true,
              text: 'Trust Score Range'
            }
          }
        }
      }
    };
  };

  return (
    <div style={{ 
      height: '400px', 
      width: '100%',
      backgroundColor: '#fff',
      borderRadius: '8px',
      padding: '15px',
      boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
    }}>
      <canvas ref={chartRef}></canvas>
    </div>
  );
};

export default AdvancedGeographicCharts;
