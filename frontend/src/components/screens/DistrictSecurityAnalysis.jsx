import React, { useCallback, useEffect, useRef, useState } from 'react';
import Chart from 'chart.js/auto';
import api from '../../api/client';

const PERIOD_OPTIONS = [
  { label: 'Last 30 days', days: 30 },
  { label: 'Last 90 days', days: 90 },
  { label: 'Last 6 months', days: 180 },
  { label: 'All time', days: 0 },
];

const CHART_COLORS = [
  '#3b82f6',
  '#ef4444',
  '#22c55e',
  '#eab308',
  '#8b5cf6',
  '#f97316',
  '#06b6d4',
  '#ec4899',
];

const DistrictSecurityAnalysis = ({ wsRefreshKey }) => {
  const [daysBack, setDaysBack] = useState(90);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const typeChartRef = useRef(null);
  const trendChartRef = useRef(null);
  const typeChartInstance = useRef(null);
  const trendChartInstance = useRef(null);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    api
      .get(`/api/v1/stats/district-security-analysis?days_back=${daysBack}`)
      .then((res) => {
        setData(res || null);
        setLoading(false);
      })
      .catch((e) => {
        setError(e?.message || 'Failed to load district security analysis.');
        setData(null);
        setLoading(false);
      });
  }, [daysBack]);

  useEffect(() => {
    load();
  }, [load, wsRefreshKey]);

  useEffect(() => {
    if (typeChartInstance.current) {
      typeChartInstance.current.destroy();
      typeChartInstance.current = null;
    }
    if (trendChartInstance.current) {
      trendChartInstance.current.destroy();
      trendChartInstance.current = null;
    }

    if (!data?.by_type?.length || !typeChartRef.current) return;

    const labels = data.by_type.map((t) => t.type_name);
    const counts = data.by_type.map((t) => t.count);

    typeChartInstance.current = new Chart(typeChartRef.current, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [
          {
            data: counts,
            backgroundColor: labels.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]),
            borderWidth: 2,
            borderColor: 'rgba(15,23,42,0.9)',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } },
        },
      },
    });
  }, [data]);

  useEffect(() => {
    if (trendChartInstance.current) {
      trendChartInstance.current.destroy();
      trendChartInstance.current = null;
    }

    if (!data?.daily_trend?.length || !trendChartRef.current) return;

    trendChartInstance.current = new Chart(trendChartRef.current, {
      type: 'line',
      data: {
        labels: data.daily_trend.map((d) => d.date),
        datasets: [
          {
            label: 'Incidents',
            data: data.daily_trend.map((d) => d.count),
            borderColor: '#3b82f6',
            backgroundColor: 'rgba(59,130,246,0.15)',
            fill: true,
            tension: 0.3,
            pointRadius: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            ticks: { maxTicksLimit: 12, font: { size: 10 } },
          },
          y: {
            beginAtZero: true,
            ticks: { precision: 0 },
          },
        },
        plugins: {
          legend: { display: false },
        },
      },
    });
  }, [data]);

  useEffect(() => {
    return () => {
      typeChartInstance.current?.destroy();
      trendChartInstance.current?.destroy();
    };
  }, []);

  const summary = data?.summary || {};
  const periodLabel =
    PERIOD_OPTIONS.find((p) => p.days === daysBack)?.label || `Last ${daysBack} days`;

  return (
    <>
      <div className="page-header">
        <h2>District Security Analysis</h2>
        <p>
          Visual breakdown of incident trends and type distribution across Musanze District.
          {data?.scope === 'station' ? ' Showing your station coverage.' : ''}
        </p>
      </div>

      {error && (
        <div className="alert alert-danger" style={{ marginBottom: 16 }}>
          <span className="alert-icon">!</span>
          <div>{error}</div>
        </div>
      )}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: 12,
          marginBottom: 20,
        }}
      >
        <div className="stat-card">
          <div className="stat-label">Total Incidents</div>
          <div className="stat-value">{loading ? '…' : summary.total_incidents ?? 0}</div>
          <div className="stat-sub">{periodLabel}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Incident Types</div>
          <div className="stat-value">{loading ? '…' : summary.incident_types ?? 0}</div>
          <div className="stat-sub">Distinct categories</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Avg / Day</div>
          <div className="stat-value">{loading ? '…' : summary.avg_per_day ?? 0}</div>
          <div className="stat-sub">Daily incident rate</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Most Common</div>
          <div className="stat-value" style={{ fontSize: 18 }}>
            {loading ? '…' : summary.most_common_count ?? 0}
          </div>
          <div className="stat-sub">{summary.most_common_type || '—'}</div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
        {PERIOD_OPTIONS.map((opt) => (
          <button
            key={opt.days}
            type="button"
            className={`btn btn-sm ${daysBack === opt.days ? 'btn-primary' : 'btn-outline'}`}
            onClick={() => setDaysBack(opt.days)}
          >
            {opt.label}
          </button>
        ))}
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: 16,
        }}
      >
        <div className="card">
          <div className="card-header">
            <div className="card-title">Incident Type Distribution</div>
            <span className="badge b-blue">{summary.incident_types ?? 0} types</span>
          </div>
          <div className="card-body" style={{ height: 280 }}>
            {loading ? (
              <div style={{ color: 'var(--muted)', fontSize: 13 }}>Loading…</div>
            ) : data?.by_type?.length ? (
              <canvas ref={typeChartRef} />
            ) : (
              <div style={{ color: 'var(--muted)', fontSize: 13 }}>No incident data for this period.</div>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <div className="card-title">Daily Incident Trend</div>
          </div>
          <div className="card-sub" style={{ padding: '0 16px 8px', fontSize: 12, color: 'var(--muted)' }}>
            Every verified incident tracked day by day
          </div>
          <div className="card-body" style={{ height: 280 }}>
            {loading ? (
              <div style={{ color: 'var(--muted)', fontSize: 13 }}>Loading…</div>
            ) : data?.daily_trend?.length ? (
              <canvas ref={trendChartRef} />
            ) : (
              <div style={{ color: 'var(--muted)', fontSize: 13 }}>No incident data for this period.</div>
            )}
          </div>
        </div>
      </div>
    </>
  );
};

export default DistrictSecurityAnalysis;
