import React, { useEffect, useRef } from 'react';
import { Chart } from 'chart.js/auto';
import 'chartjs-adapter-date-fns';
import zoomPlugin from 'chartjs-plugin-zoom';
import ChartDataLabels from 'chartjs-plugin-datalabels';

Chart.register(zoomPlugin, ChartDataLabels);

const EMPTY_MESSAGE =
  'No data available for this time range. Adjust the window or try again later.';

/* ── Read CSS custom properties at runtime ─────────────────────────── */
function getThemeColors() {
  const s = getComputedStyle(document.documentElement);
  const v = (name, fallback) => s.getPropertyValue(name).trim() || fallback;
  return {
    text:       v('--chart-text',       '#cbd5e1'),
    textDim:    v('--chart-text-dim',   '#94a3b8'),
    grid:       v('--chart-grid',       'rgba(148,163,184,0.08)'),
    tooltipBg:  v('--chart-tooltip-bg', 'rgba(15,23,42,0.95)'),
    tooltipBorder: v('--chart-tooltip-border', 'rgba(148,163,184,0.2)'),
    blue:       v('--chart-blue',       'rgba(54,162,235,0.8)'),
    blueSolid:  v('--chart-blue-solid', 'rgba(54,162,235,1)'),
    blueFill:   v('--chart-blue-fill',  'rgba(54,162,235,0.2)'),
    pink:       v('--chart-pink',       'rgba(255,99,132,0.8)'),
    pinkSolid:  v('--chart-pink-solid', 'rgba(255,99,132,1)'),
    pinkFill:   v('--chart-pink-fill',  'rgba(255,99,132,0.2)'),
    teal:       v('--chart-teal',       'rgba(75,192,192,0.8)'),
    tealSolid:  v('--chart-teal-solid', 'rgba(75,192,192,1)'),
    tealFill:   v('--chart-teal-fill',  'rgba(75,192,192,0.2)'),
    yellow:     v('--chart-yellow',     'rgba(255,205,86,0.8)'),
    yellowSolid:v('--chart-yellow-solid','rgba(255,205,86,1)'),
    purple:     v('--chart-purple',     'rgba(153,102,255,0.8)'),
    purpleSolid:v('--chart-purple-solid','rgba(153,102,255,1)'),
    orange:     v('--chart-orange',     'rgba(255,159,64,0.8)'),
    orangeSolid:v('--chart-orange-solid','rgba(255,159,64,1)'),
    pointBorder:v('--chart-point-border','#1e293b'),
  };
}

/* ── Shared option builders ────────────────────────────────────────── */
function darkPlugins(c, title) {
  return {
    title: {
      display: !!title,
      text: title || '',
      color: c.text,
      font: { size: 14, weight: '600' }
    },
    legend: {
      display: true,
      labels: { color: c.textDim, font: { size: 12 } }
    },
    tooltip: {
      backgroundColor: c.tooltipBg,
      titleColor: c.text,
      bodyColor: c.textDim,
      borderColor: c.tooltipBorder,
      borderWidth: 1
    }
  };
}

function darkScale(c, label) {
  return {
    grid: { color: c.grid },
    ticks: { color: c.textDim },
    ...(label ? { title: { display: true, text: label, color: c.textDim } } : {})
  };
}

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

    const c = getThemeColors();
    let config;
    switch (type) {
      case 'timeSeries':
        config = createTimeSeriesChart(chartData, c);
        break;
      case 'sectorPerformance':
        config = createSectorPerformanceChart(chartData, c);
        break;
      case 'personalPerformance':
        config = createPersonalPerformanceChart(chartData, c);
        break;
      case 'behaviorRadar':
        config = createBehaviorRadarChart(chartData, c);
        break;
      case 'incidentDistribution':
        config = createIncidentDistributionChart(chartData, c);
        break;
      case 'movementFlow':
        config = createMovementFlowChart(chartData, c);
        break;
      case 'speedAnalysis':
        config = createSpeedAnalysisChart(chartData, c);
        break;
      case 'nightActivity':
        config = createNightActivityChart(chartData, c);
        break;
      case 'trustScoreDistribution':
        config = createTrustScoreChart(chartData, c);
        break;
      default:
        config = createTimeSeriesChart(chartData, c);
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

  const createTimeSeriesChart = (payload, c) => {
    const reportsByTime = payload.reportsByTime || [];
    return {
      type: 'line',
      data: {
        datasets: [{
          label: 'Reports Over Time',
          data: reportsByTime,
          borderColor: c.tealSolid,
          backgroundColor: c.tealFill,
          tension: 0.4,
          fill: true,
          pointRadius: 4,
          pointHoverRadius: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: darkPlugins(c, `Report Trends - Last ${timeWindow || 720} Hours`),
        scales: {
          x: {
            type: 'time',
            time: { unit: 'hour', displayFormats: { hour: 'MMM dd, HH:mm' } },
            ...darkScale(c, 'Time')
          },
          y: { beginAtZero: true, ...darkScale(c, 'Number of Reports') }
        }
      }
    };
  };

  const createPersonalPerformanceChart = (payload, c) => {
    const performanceData = payload.performance_data || [];
    return {
      type: 'line',
      data: {
        labels: performanceData.map((d) => d.date),
        datasets: [
          {
            label: 'Reports Processed',
            data: performanceData.map((d) => d.reports_processed || 0),
            borderColor: c.blueSolid,
            backgroundColor: c.blueFill,
            borderWidth: 2,
            tension: 0.4,
            yAxisID: 'y'
          },
          {
            label: 'Avg Response Time (min)',
            data: performanceData.map((d) => d.avg_response_time || 0),
            borderColor: c.pinkSolid,
            backgroundColor: c.pinkFill,
            borderWidth: 2,
            tension: 0.4,
            yAxisID: 'y1'
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: darkPlugins(c),
        scales: {
          x: darkScale(c),
          y:  { type: 'linear', display: true, position: 'left',  ...darkScale(c, 'Reports Processed') },
          y1: { type: 'linear', display: true, position: 'right', grid: { drawOnChartArea: false }, ticks: { color: c.textDim }, title: { display: true, text: 'Response Time (min)', color: c.textDim } }
        }
      }
    };
  };

  const createSectorPerformanceChart = (payload, c) => {
    const sectors = payload.performance_data || payload.sectors || [];
    return {
      type: 'bar',
      data: {
        labels: sectors.map((s) => s.sector_name),
        datasets: [
          { label: 'Total Reports',  data: sectors.map((s) => s.report_count || 0),   backgroundColor: c.blue,   borderColor: c.blueSolid,  borderWidth: 1 },
          { label: 'Device Count',   data: sectors.map((s) => s.device_count || 0),   backgroundColor: c.pink,   borderColor: c.pinkSolid,  borderWidth: 1 },
          { label: 'Avg Trust Score', data: sectors.map((s) => s.avg_trust_score || 0), backgroundColor: c.teal,   borderColor: c.tealSolid,  borderWidth: 1 }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: darkPlugins(c, 'Sector Performance Comparison'),
        scales: {
          x: darkScale(c),
          y: { beginAtZero: true, ...darkScale(c, 'Count / Score') }
        }
      }
    };
  };

  const createBehaviorRadarChart = (payload, c) => {
    const behaviorAnalysis = payload.behaviorAnalysis || [];
    const hues = [200, 340, 160]; // blue, pink, green-ish
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
          backgroundColor: `hsla(${hues[index]}, 70%, 60%, 0.2)`,
          borderColor: `hsla(${hues[index]}, 70%, 60%, 1)`,
          borderWidth: 2,
          pointBackgroundColor: `hsla(${hues[index]}, 70%, 60%, 1)`,
          pointBorderColor: c.pointBorder,
          pointHoverBackgroundColor: c.pointBorder,
          pointHoverBorderColor: `hsla(${hues[index]}, 70%, 60%, 1)`
        }))
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: darkPlugins(c, 'Device Behavior Patterns'),
        scales: {
          r: {
            beginAtZero: true,
            max: 100,
            ticks: { stepSize: 20, color: c.textDim, backdropColor: 'transparent' },
            grid: { color: c.grid },
            angleLines: { color: c.grid },
            pointLabels: { color: c.textDim }
          }
        }
      }
    };
  };

  const createIncidentDistributionChart = (payload, c) => {
    const incidentTypes = payload.incidentTypes || [];
    const bgColors = [c.pink, c.blue, c.yellow, c.teal, c.purple, c.orange];
    const bdColors = [c.pinkSolid, c.blueSolid, c.yellowSolid, c.tealSolid, c.purpleSolid, c.orangeSolid];
    return {
      type: 'doughnut',
      data: {
        labels: incidentTypes.map((t) => t.name),
        datasets: [{
          data: incidentTypes.map((t) => t.count),
          backgroundColor: bgColors,
          borderColor: bdColors,
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          ...darkPlugins(c, 'Incident Type Distribution'),
          legend: { position: 'right', labels: { color: c.textDim, font: { size: 12 } } }
        }
      }
    };
  };

  const createMovementFlowChart = (payload, c) => {
    const flowData = payload.flowData || [];
    return {
      type: 'bar',
      data: {
        labels: flowData.map((f) => `${f.from_sector || 'Unknown'} → ${f.to_sector || 'Unknown'}`),
        datasets: [{
          label: 'Movement Flow Strength',
          data: flowData.map((f) => f.flow_strength || 0),
          backgroundColor: c.purple,
          borderColor: c.purpleSolid,
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: 'y',
        plugins: darkPlugins(c, 'Device Movement Flows Between Sectors'),
        scales: {
          x: { beginAtZero: true, ...darkScale(c, 'Flow Strength') },
          y: darkScale(c)
        }
      }
    };
  };

  const createSpeedAnalysisChart = (payload, c) => {
    const speedData = payload.speedData || [];
    return {
      type: 'scatter',
      data: {
        datasets: [{
          label: 'Device Speeds',
          data: speedData.map((d) => ({ x: d.device_id || 'Unknown', y: d.avg_speed || 0 })),
          backgroundColor: c.pink,
          borderColor: c.pinkSolid,
          pointRadius: 8,
          pointHoverRadius: 10
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: darkPlugins(c, 'Device Speed Analysis'),
        scales: {
          y: { beginAtZero: true, ...darkScale(c, 'Average Speed (km/h)') },
          x: darkScale(c, 'Device ID')
        }
      }
    };
  };

  const createNightActivityChart = (payload, c) => {
    const behaviorAnalysis = payload.behaviorAnalysis || [];
    return {
      type: 'bar',
      data: {
        labels: behaviorAnalysis.map((d) => d.device_hash || 'Unknown'),
        datasets: [
          {
            label: 'Night Activity (%)',
            data: behaviorAnalysis.map((d) => (d.night_activity_ratio || 0) * 100),
            backgroundColor: c.teal,
            borderColor: c.tealSolid,
            borderWidth: 1
          },
          {
            label: 'Day Activity (%)',
            data: behaviorAnalysis.map((d) => (1 - (d.night_activity_ratio || 0)) * 100),
            backgroundColor: c.yellow,
            borderColor: c.yellowSolid,
            borderWidth: 1
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: darkPlugins(c, 'Night vs Day Activity Patterns'),
        scales: {
          x: { stacked: true, ...darkScale(c, 'Devices') },
          y: { stacked: true, beginAtZero: true, max: 100, ...darkScale(c, 'Activity Percentage') }
        }
      }
    };
  };

  const createTrustScoreChart = (payload, c) => {
    const trustScoreDistribution = payload.trustScoreDistribution || [];
    return {
      type: 'bar',
      data: {
        labels: ['0-20', '21-40', '41-60', '61-80', '81-100'],
        datasets: [{
          label: 'Number of Devices',
          data: trustScoreDistribution,
          backgroundColor: c.blue,
          borderColor: c.blueSolid,
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: darkPlugins(c, 'Trust Score Distribution'),
        scales: {
          y: { beginAtZero: true, ...darkScale(c, 'Number of Devices') },
          x: darkScale(c, 'Trust Score Range')
        }
      }
    };
  };

  const emptyText = chartData.load_error
    ? 'Performance charts are unavailable right now. Check your connection or try again later.'
    : EMPTY_MESSAGE;

  return (
    <div className="geo-chart-container">
      {showChart ? (
        <canvas ref={chartRef} />
      ) : (
        <div className="geo-chart-empty">
          {emptyText}
        </div>
      )}
    </div>
  );
};

export default AdvancedGeographicCharts;
