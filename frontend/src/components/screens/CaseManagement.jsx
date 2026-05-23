import React, { useCallback, useEffect, useRef, useState } from 'react';
import Chart from 'chart.js/auto';
import ChartDataLabels from 'chartjs-plugin-datalabels';
import api from '../../api/client';

/** Fill every calendar date between start and end with 0 if missing. */
const fillDailyGaps = (countsByDate) => {
  const keys = Object.keys(countsByDate).sort();
  if (!keys.length) return {};
  const start = new Date(keys[0]);
  const end   = new Date();
  const result = {};
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    const key = d.toISOString().slice(0, 10);
    result[key] = countsByDate[key] ?? 0;
  }
  return result;
};

/**
 * Generate colors ranked by frequency: most common → warm (red/orange),
 * least common → cool (blue/slate). Colors are auto-assigned by rank so
 * adding new incident types never breaks the palette.
 */
const RANKED_PALETTE = [
  '#EF4444', // rank 1 – highest (red)
  '#F97316', // rank 2
  '#F59E0B', // rank 3
  '#EAB308', // rank 4
  '#84CC16', // rank 5
  '#10B981', // rank 6
  '#06B6D4', // rank 7
  '#3B82F6', // rank 8
  '#0EA5E9', // rank 9
  '#64748B', // rank 10+ (slate)
];

const getRankedColor = (rank) =>
  RANKED_PALETTE[Math.min(rank, RANKED_PALETTE.length - 1)];

const RANGE_OPTIONS = [
  { label: 'Last 30 days',  days: 30  },
  { label: 'Last 90 days',  days: 90  },
  { label: 'Last 6 months', days: 180 },
  { label: 'All time',      days: null },
];

const DistrictSecurityAnalysis = ({ wsRefreshKey }) => {
  const [reports, setReports]     = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');
  const [range, setRange]         = useState(null); // default: all time

  const pieRef    = useRef(null);
  const lineRef   = useRef(null);
  const pieChart  = useRef(null);
  const lineChart = useRef(null);

  /* ── Load data ── */
  const load = useCallback(() => {
    setLoading(true);
    setError('');
    api.get('/api/v1/reports/?limit=500')
      .then((reportsRes) => {
        let arr = [];
        if (Array.isArray(reportsRes))  arr = reportsRes;
        else if (reportsRes?.items)     arr = reportsRes.items;
        else if (reportsRes?.reports)   arr = reportsRes.reports;
        else if (reportsRes?.data)      arr = reportsRes.data;
        setReports(arr);
        setLoading(false);
      })
      .catch((e) => {
        setError(e?.message || 'Failed to load reports.');
        setLoading(false);
      });
  }, []);

  useEffect(() => { load(); }, [load, wsRefreshKey]);

  /* ── Derived data ── */
  const filteredReports = reports.filter((r) => {
    if (!range) return true;
    const date = new Date(r.reported_at || r.created_at || r.timestamp);
    return date >= new Date(Date.now() - range * 86_400_000);
  });

  // Count by incident type, sorted high → low
  const typeCounts = {};
  filteredReports.forEach((r) => {
    // API returns a flat field r.incident_type_name
    const name = r.incident_type_name || r.incident_type?.type_name || r.incident_type?.name || 'Unknown';
    typeCounts[name] = (typeCounts[name] || 0) + 1;
  });
  const typeEntries = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]);

  // Assign colors by rank (index in sorted array)
  const typeColors = typeEntries.map((_, i) => getRankedColor(i));

  // Line: count by day
  const dailyRaw = {};
  filteredReports.forEach((r) => {
    const raw = r.reported_at || r.created_at || r.timestamp;
    if (!raw) return;
    const day = new Date(raw).toISOString().slice(0, 10);
    dailyRaw[day] = (dailyRaw[day] || 0) + 1;
  });
  const daily       = fillDailyGaps(dailyRaw);
  const dailyLabels = Object.keys(daily);
  const dailyValues = Object.values(daily);

  /* ── Pie / Doughnut chart ── */
  useEffect(() => {
    if (!pieRef.current || loading) return;
    if (pieChart.current) { pieChart.current.destroy(); pieChart.current = null; }
    if (!typeEntries.length) return;

    const total = filteredReports.length;

    pieChart.current = new Chart(pieRef.current, {
      type: 'doughnut',
      plugins: [ChartDataLabels],
      data: {
        labels: typeEntries.map(([k]) => k),
        datasets: [{
          data: typeEntries.map(([, v]) => v),
          backgroundColor: typeColors,
          borderColor: typeColors.map(c => c + 'cc'),
          borderWidth: 2,
          hoverOffset: 10,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '50%',
        plugins: {
          legend: {
            position: 'right',
            labels: {
              font: { size: 11 },
              padding: 12,
              color: getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#1e293b',
              boxWidth: 12,
              borderRadius: 3,
              generateLabels: (chart) => {
                const ds = chart.data.datasets[0];
                return chart.data.labels.map((label, i) => ({
                  text: `${label}  ·  ${ds.data[i]} (${((ds.data[i] / total) * 100).toFixed(0)}%)`,
                  fillStyle: ds.backgroundColor[i],
                  strokeStyle: ds.borderColor[i],
                  lineWidth: 1,
                  index: i,
                  hidden: false,
                }));
              },
            },
          },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const count = ctx.parsed;
                const pct   = ((count / total) * 100).toFixed(1);
                return ` ${ctx.label}: ${count} incident${count !== 1 ? 's' : ''} (${pct}%)`;
              },
            },
          },
          datalabels: {
            color: '#ffffff',
            font: { size: 11, weight: 'bold' },
            formatter: (value) => {
              const pct = ((value / total) * 100).toFixed(0);
              // Only show label if slice is big enough to fit text
              return pct >= 5 ? `${pct}%` : '';
            },
            textShadowColor: 'rgba(0,0,0,0.4)',
            textShadowBlur: 3,
          },
        },
      },
    });

    return () => { if (pieChart.current) { pieChart.current.destroy(); pieChart.current = null; } };
  }, [JSON.stringify(typeEntries), loading, range]);

  /* ── Line chart ── */
  useEffect(() => {
    if (!lineRef.current || loading) return;
    if (lineChart.current) { lineChart.current.destroy(); lineChart.current = null; }
    if (!dailyLabels.length) return;

    const style  = getComputedStyle(document.documentElement);
    const accent = style.getPropertyValue('--accent').trim() || '#3b82f6';
    const muted  = style.getPropertyValue('--muted').trim()  || '#94a3b8';
    const border = style.getPropertyValue('--border').trim() || '#e2e8f0';

    lineChart.current = new Chart(lineRef.current, {
      type: 'line',
      data: {
        labels: dailyLabels,
        datasets: [{
          label: 'Incidents per day',
          data: dailyValues,
          borderColor: accent,
          backgroundColor: `${accent}22`,
          borderWidth: 2,
          pointRadius: dailyLabels.length > 60 ? 0 : 3,
          pointHoverRadius: 5,
          fill: true,
          tension: 0.35,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          datalabels: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => ` ${ctx.parsed.y} incident${ctx.parsed.y !== 1 ? 's' : ''}`,
            },
          },
        },
        scales: {
          x: {
            ticks: {
              color: muted,
              font: { size: 10 },
              maxTicksLimit: 12,
              maxRotation: 30,
            },
            grid: { display: false },
          },
          y: {
            beginAtZero: true,
            ticks: { color: muted, font: { size: 11 }, stepSize: 1 },
            grid: { color: border },
          },
        },
      },
    });

    return () => { if (lineChart.current) { lineChart.current.destroy(); lineChart.current = null; } };
  }, [dailyLabels.join(','), loading, range]);

  /* ── Summary counts ── */
  const totalIncidents = filteredReports.length;
  const topType   = typeEntries[0]?.[0] ?? '—';
  const topCount  = typeEntries[0]?.[1] ?? 0;
  const avgPerDay = dailyLabels.length
    ? (totalIncidents / dailyLabels.length).toFixed(1)
    : '0';
  const peakDayIdx = dailyValues.indexOf(Math.max(...dailyValues, 0));
  const peakDay    = dailyLabels[peakDayIdx] ?? '—';

  return (
    <>
      <div className="page-header">
        <h2>District Security Analysis</h2>
        <p>Visual breakdown of incident trends and type distribution across Musanze District.</p>
      </div>

      {error && (
        <div className="alert alert-danger" style={{ marginBottom: 12 }}>
          <span className="alert-icon">!</span>
          <div>{error}</div>
        </div>
      )}

      {/* Summary stat cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        {[
          { label: 'Total Incidents',  value: totalIncidents, sub: range ? `Last ${range} days` : 'All time',  cls: 'sb-blue'   },
          { label: 'Incident Types',   value: typeEntries.length, sub: 'Distinct categories',                  cls: 'sb-orange' },
          { label: 'Avg / Day',        value: avgPerDay,      sub: 'Daily incident rate',                      cls: 'sb-green'  },
          { label: 'Most Common',      value: topCount,       sub: topType,                                    cls: 'sb-red'    },
        ].map((s) => (
          <div key={s.label} className={`stat-btn ${s.cls}`} style={{ cursor: 'default' }}>
            <div className="stat-btn-label">{s.label}</div>
            <div className="stat-btn-value">{s.value}</div>
            <div className="stat-btn-sub">{s.sub}</div>
          </div>
        ))}
      </div>

      {/* Range selector */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 500 }}>Time range:</span>
        {RANGE_OPTIONS.map((opt) => (
          <button
            key={opt.label}
            type="button"
            className={`btn btn-sm ${range === opt.days ? 'btn-primary' : 'btn-outline'}`}
            onClick={() => setRange(opt.days)}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Charts row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.6fr', gap: 16, marginBottom: 16 }}>

        {/* Pie / Doughnut */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">Incident Type Distribution</div>
            <span className="badge b-blue" style={{ fontSize: 10 }}>
              {typeEntries.length} type{typeEntries.length !== 1 ? 's' : ''}
            </span>
          </div>
          <div style={{ padding: '12px 16px 4px' }}>
            {loading ? (
              <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)', fontSize: 12 }}>
                Loading…
              </div>
            ) : typeEntries.length === 0 ? (
              <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)', fontSize: 12 }}>
                No incident data for this period.
              </div>
            ) : (
              <div style={{ height: 260, position: 'relative' }}>
                <canvas ref={pieRef} />
              </div>
            )}
          </div>

          {/* Color-rank legend */}
          {!loading && typeEntries.length > 0 && (
            <div style={{ borderTop: '1px solid var(--border)', padding: '8px 16px 12px' }}>
              <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 6, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Ranked by frequency — red = highest
              </div>
              {typeEntries.map(([name, count], i) => {
                const pct = ((count / totalIncidents) * 100).toFixed(1);
                return (
                  <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 0' }}>
                    <div style={{ width: 10, height: 10, borderRadius: 2, flexShrink: 0, background: typeColors[i] }} />
                    <span style={{ flex: 1, fontSize: 11 }}>{name}</span>
                    <span style={{ fontSize: 11, fontWeight: 700 }}>{count}</span>
                    <span style={{ fontSize: 10, color: 'var(--muted)', minWidth: 36, textAlign: 'right' }}>{pct}%</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Daily trend line */}
        <div className="card">
          <div className="card-header" style={{ flexWrap: 'wrap', gap: 6 }}>
            <div>
              <div className="card-title">Daily Incident Trend</div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                Every reported incident tracked day by day
                {peakDay && peakDay !== '—' && (
                  <> · Peak: <strong>{peakDay}</strong> ({dailyValues[peakDayIdx]} incidents)</>
                )}
              </div>
            </div>
          </div>
          <div style={{ padding: '12px 16px 16px' }}>
            {loading ? (
              <div style={{ height: 310, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)', fontSize: 12 }}>
                Loading…
              </div>
            ) : dailyLabels.length === 0 ? (
              <div style={{ height: 310, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)', fontSize: 12 }}>
                No incident data for this period.
              </div>
            ) : (
              <div style={{ height: 310, position: 'relative' }}>
                <canvas ref={lineRef} />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Type breakdown table */}
      {!loading && typeEntries.length > 0 && (
        <div className="card">
          <div className="card-header">
            <div className="card-title">Incident Type Breakdown</div>
            <span style={{ fontSize: 11, color: 'var(--muted)' }}>Colors auto-ranked: red = most frequent</span>
          </div>
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Incident Type</th>
                  <th>Count</th>
                  <th>Share</th>
                  <th>Distribution</th>
                </tr>
              </thead>
              <tbody>
                {typeEntries.map(([name, count], i) => {
                  const pct   = ((count / totalIncidents) * 100).toFixed(1);
                  const color = typeColors[i];
                  return (
                    <tr key={name}>
                      <td style={{ fontSize: 12, color: 'var(--muted)', textAlign: 'center', width: 40 }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
                          <div style={{ width: 10, height: 10, borderRadius: 2, flexShrink: 0, background: color }} />
                          {i + 1}
                        </div>
                      </td>
                      <td>
                        <span style={{ fontWeight: 600, fontSize: 13 }}>{name}</span>
                      </td>
                      <td style={{ fontWeight: 700, fontSize: 14 }}>{count}</td>
                      <td><span className="badge b-blue" style={{ fontSize: 10 }}>{pct}%</span></td>
                      <td style={{ minWidth: 120 }}>
                        <div style={{ background: 'var(--border)', borderRadius: 3, height: 6 }}>
                          <div style={{
                            height: 6, borderRadius: 3,
                            width: `${pct}%`,
                            background: color,
                            transition: 'width 0.4s ease',
                          }} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
};

export default DistrictSecurityAnalysis;
