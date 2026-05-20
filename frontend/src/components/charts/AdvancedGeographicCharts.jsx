import React, { useEffect, useRef } from 'react';
import { Chart } from 'chart.js/auto';
import 'chartjs-adapter-date-fns';
import zoomPlugin from 'chartjs-plugin-zoom';
import ChartDataLabels from 'chartjs-plugin-datalabels';

Chart.register(zoomPlugin, ChartDataLabels);

const EMPTY_MESSAGE =
  'No data available for this time range. Adjust the window or try again later.';

function hasChartData(type, data) {
  const d = data || {};
  switch (type) {
    case 'timeSeries':
      return Array.isArray(d.reportsByTime) && d.reportsByTime.length > 0;
    case 'sectorPerformance':
      return (
        (Array.isArray(d.performance_data) && d.performance_data.length > 0) ||
        (Array.isArray(d.sectors) && d.sectors.length > 0)
      );
    case 'personalPerformance':
      return Array.isArray(d.performance_data) && d.performance_data.length > 0;
    case 'behaviorRadar':
    case 'nightActivity':
      return Array.isArray(d.behaviorAnalysis) && d.behaviorAnalysis.length > 0;
    case 'incidentDistribution':
      return Array.isArray(d.incidentTypes) && d.incidentTypes.length > 0;
    case 'movementFlow':
      return Array.isArray(d.flowData) && d.flowData.length > 0;
    case 'speedAnalysis':
      return Array.isArray(d.speedData) && d.speedData.length > 0;
    case 'trustScoreDistribution':
      return (
        Array.isArray(d.trustScoreDistribution) &&
        d.trustScoreDistribution.some((n) => Number(n) > 0)
      );
    default:
      return Array.isArray(d.reportsByTime) && d.reportsByTime.length > 0;
  }
}

const AdvancedGeographicCharts = ({ data, type, timeWindow }) => {
  const chartRef = useRef(null);
  const chartInstance = useRef(null);
  const chartData = data || {};
  const showChart = hasChartData(type, chartData);

  useEffect(() => {
    if (!chartRef.current || !showChart) {
      if (chartInstance.current) {
        chartInstance.current.destroy();
        chartInstance.current = null;
      }
      return;
    }

    if (chartInstance.current) {
      chartInstance.current.destroy();
      chartInstance.current = null;
    }

    const ctx = chartRef.current.getContext('2d');
    if (!ctx) return;

    let config;
    switch (type) {
      case 'timeSeries':
        config = createTimeSeriesChart(chartData);
        break;
      case 'sectorPerformance':
        config = createSectorPerformanceChart(chartData);
        break;
      case 'personalPerformance':
        config = createPersonalPerformanceChart(chartData);
        break;
      case 'behaviorRadar':
        config = createBehaviorRadarChart(chartData);
        break;
      case 'incidentDistribution':
        config = createIncidentDistributionChart(chartData);
        break;
      case 'movementFlow':
        config = createMovementFlowChart(chartData);
        break;
      case 'speedAnalysis':
        config = createSpeedAnalysisChart(chartData);
        break;
      case 'nightActivity':
        config = createNightActivityChart(chartData);
        break;
      case 'trustScoreDistribution':
        config = createTrustScoreChart(chartData);
        break;
      default:
        config = createTimeSeriesChart(chartData);
    }

    try {
      if (config) {
        chartInstance.current = new Chart(ctx, config);
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
  }, [data, type, timeWindow, showChart]);

  const createTimeSeriesChart = (payload) => {
    const reportsByTime = payload.reportsByTime || [];

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

  const createPersonalPerformanceChart = (payload) => {
    const performanceData = payload.performance_data || [];

    return {
      type: 'line',
      data: {
        labels: performanceData.map((d) => d.date),
        datasets: [
          {
            label: 'Reports Processed',
            data: performanceData.map((d) => d.reports_processed || 0),
            borderColor: 'rgba(54, 162, 235, 1)',
            backgroundColor: 'rgba(54, 162, 235, 0.2)',
            borderWidth: 2,
            tension: 0.4,
            yAxisID: 'y'
          },
          {
            label: 'Avg Response Time (min)',
            data: performanceData.map((d) => d.avg_response_time || 0),
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

  const createSectorPerformanceChart = (payload) => {
    const sectors = payload.performance_data || payload.sectors || [];

    return {
      type: 'bar',
      data: {
        labels: sectors.map((s) => s.sector_name),
        datasets: [
          {
            label: 'Total Reports',
            data: sectors.map((s) => s.report_count || 0),
            backgroundColor: 'rgba(54, 162, 235, 0.8)',
            borderColor: 'rgba(54, 162, 235, 1)',
            borderWidth: 1
          },
          {
            label: 'Device Count',
            data: sectors.map((s) => s.device_count || 0),
            backgroundColor: 'rgba(255, 99, 132, 0.8)',
            borderColor: 'rgba(255, 99, 132, 1)',
            borderWidth: 1
          },
          {
            label: 'Avg Trust Score',
            data: sectors.map((s) => s.avg_trust_score || 0),
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

  const createBehaviorRadarChart = (payload) => {
    const behaviorAnalysis = payload.behaviorAnalysis || [];

    return {
      type: 'radar',
      data: {
        labels: ['Automation Score', 'Suspicious Score', 'Night Activity', 'High Speed', 'Frequency', 'Mobility'],
        datasets: behaviorAnalysis.slice(0, 3).map((device, index) => ({
          label: `Device ${device.device_hash || index + 1}`,
          data: [
            device.automation_score || 0,
            device.suspicious_score || 0,
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

  const createIncidentDistributionChart = (payload) => {
    const incidentTypes = payload.incidentTypes || [];

    return {
      type: 'doughnut',
      data: {
        labels: incidentTypes.map((t) => t.name),
        datasets: [{
          data: incidentTypes.map((t) => t.count),
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

  const createMovementFlowChart = (payload) => {
    const flowData = payload.flowData || [];

    return {
      type: 'bar',
      data: {
        labels: flowData.map(
          (f) => `${f.from_sector || 'Unknown'} → ${f.to_sector || 'Unknown'}`
        ),
        datasets: [{
          label: 'Movement Flow Strength',
          data: flowData.map((f) => f.flow_strength || 0),
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

  const createSpeedAnalysisChart = (payload) => {
    const speedData = payload.speedData || [];

    return {
      type: 'scatter',
      data: {
        datasets: [{
          label: 'Device Speeds',
          data: speedData.map((d) => ({
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

  const createNightActivityChart = (payload) => {
    const behaviorAnalysis = payload.behaviorAnalysis || [];

    return {
      type: 'bar',
      data: {
        labels: behaviorAnalysis.map((d) => d.device_hash || 'Unknown'),
        datasets: [
          {
            label: 'Night Activity (%)',
            data: behaviorAnalysis.map((d) => (d.night_activity_ratio || 0) * 100),
            backgroundColor: 'rgba(75, 192, 192, 0.8)',
            borderColor: 'rgba(75, 192, 192, 1)',
            borderWidth: 1
          },
          {
            label: 'Day Activity (%)',
            data: behaviorAnalysis.map((d) => (1 - (d.night_activity_ratio || 0)) * 100),
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

  const createTrustScoreChart = (payload) => {
    const trustScoreDistribution = payload.trustScoreDistribution || [];

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

  const emptyText = chartData.load_error
    ? 'Performance charts are unavailable right now. Check your connection or try again later.'
    : EMPTY_MESSAGE;

  return (
    <div style={{
      height: '400px',
      width: '100%',
      backgroundColor: '#fff',
      borderRadius: '8px',
      padding: '15px',
      boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
    }}>
      {showChart ? (
        <canvas ref={chartRef} />
      ) : (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          textAlign: 'center',
          color: '#64748b',
          fontSize: 13,
          lineHeight: 1.5,
          padding: '0 24px'
        }}>
          {emptyText}
        </div>
      )}
    </div>
  );
};

export default AdvancedGeographicCharts;
