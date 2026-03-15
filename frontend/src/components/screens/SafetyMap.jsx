import React, { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Tooltip, ZoomControl, Polygon } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import api from '../../api/client';

const RWANDA_CENTER = [-1.5, 29.6]; // near Musanze

const SafetyMap = () => {
  const [hotspots, setHotspots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState('all'); // 'all' | incident_type_name
  const [polygons, setPolygons] = useState([]);
  const [incidentTypes, setIncidentTypes] = useState([]);

  useEffect(() => {
    let mounted = true;
    api
      .get('/api/v1/hotspots')
      .then((res) => {
        if (!mounted) return;
        setHotspots(res || []);
        setLoading(false);
      })
      .catch(() => {
        if (!mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  // Load incident types from backend so filters match DB
  useEffect(() => {
    let mounted = true;
    api
      .get('/api/v1/incident-types')
      .then((res) => {
        if (!mounted || !Array.isArray(res)) return;
        setIncidentTypes(res);
      })
      .catch(() => {
        /* non-fatal; buttons fall back to just "All Types" */
      });
    return () => {
      mounted = false;
    };
  }, []);

  // Load village polygons from public GeoJSON for district boundaries
  useEffect(() => {
    let mounted = true;
    api
      .get('/api/v1/public/locations/geojson?location_type=village&limit=4000')
      .then((geo) => {
        if (!mounted || !geo?.features) return;
        const feats = geo.features || [];

        const polys = feats.map((f) => {
          const props = f.properties || {};
          const sector = props.sector || 'Unknown';
          const geom = f.geometry || {};
          const type = geom.type;
          const coords = geom.coordinates || [];

          const toLatLngRings = (rings) =>
            rings.map((ring) =>
              ring.map(([lng, lat]) => [Number(lat), Number(lng)]),
            );

          let positions = [];
          if (type === 'Polygon') {
            positions = toLatLngRings(coords);
          } else if (type === 'MultiPolygon') {
            positions = coords.map((poly) => toLatLngRings(poly));
          }

          return {
            id: props.location_id || `${sector}-${Math.random()}`,
            sector,
            positions,
          };
        });

        // Filter out any empty geometry
        setPolygons(polys.filter((p) => p.positions && p.positions.length));
      })
      .catch(() => {
        /* non-fatal: hotspots map still works */
      });

    return () => {
      mounted = false;
    };
  }, []);

  const filteredHotspots = useMemo(() => {
    if (typeFilter === 'all') return hotspots;
    return hotspots.filter((h) => (h.incident_type_name || '').toLowerCase() === typeFilter.toLowerCase());
  }, [hotspots, typeFilter]);

  const totalClusters = filteredHotspots.length;
  const reportsInClusters = filteredHotspots.reduce(
    (sum, h) => sum + (h.incident_count || 0),
    0,
  );
  const crit = filteredHotspots.filter((h) => h.risk_level === 'high').length;
  const warn = filteredHotspots.filter((h) => h.risk_level === 'medium').length;
  const normal = filteredHotspots.filter((h) => h.risk_level === 'low').length;
  const topForSide = filteredHotspots.slice(0, 5);

  const getRiskClass = (risk) => {
    if (risk === 'high' || risk === 'critical') return 'cl-crit';
    if (risk === 'medium') return 'cl-warn';
    return 'cl-ok';
  };

  const getCircleColor = (risk) => {
    // Leaflet needs real color values, not CSS variables.
    // These hex codes should match your --danger / --warning / --success theme colors.
    if (risk === 'high' || risk === 'critical') return '#f87171'; // Critical (red)
    if (risk === 'medium') return '#fb923c';                       // Warning (orange)
    return '#34d399';                                              // Normal (green)
  };

  const getSectorColor = (sector) => {
    const palette = [
      '#00e5b4',
      '#0099ff',
      '#ff6b35',
      '#6c63ff',
      '#00ced1',
      '#ff3b5c',
      '#ffd700',
      '#48b8d0',
      '#f472b6',
      '#34d399',
      '#a78bfa',
      '#fbbf24',
      '#38bdf8',
      '#f87171',
      '#818cf8',
    ];
    if (!sector) return palette[0];
    const hash = Array.from(sector).reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
    return palette[hash % palette.length];
  };

  return (
    <>
      <div className="page-header">
        <h2>Community Safety Map</h2>
        <p>Live anonymized crime cluster visualization — Musanze District. This is also the public-facing view available to citizens.</p>
      </div>
      
      <div className="map-container">
        <div className="map-box">
          <div style={{ position: 'absolute', top: '10px', left: '10px', zIndex: 1000, display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            <button
              className={`btn btn-sm ${typeFilter === 'all' ? 'btn-primary' : 'btn-outline'}`}
              onClick={() => setTypeFilter('all')}
            >
              All Types
            </button>
            {incidentTypes.map((t) => {
              const name = t.type_name || t.incident_type_name || '';
              if (!name) return null;
              const active = typeFilter === name;
              return (
                <button
                  key={t.incident_type_id || name}
                  className={`btn btn-sm ${active ? 'btn-primary' : 'btn-outline'}`}
                  style={{ background: 'rgba(15, 22, 35, 0.85)' }}
                  onClick={() => setTypeFilter(name)}
                >
                  {name}
                </button>
              );
            })}
          </div>

          <div style={{ width: '100%', height: '100%', position: 'relative', overflow: 'hidden', borderRadius: '14px' }}>
            <MapContainer
              center={RWANDA_CENTER}
              zoom={11}
              minZoom={9}
              maxZoom={18}
              scrollWheelZoom
              style={{ width: '100%', height: '100%' }}
              zoomControl={false}
            >
              <TileLayer
                attribution='&copy; OpenStreetMap contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <ZoomControl position="topright" />

              {polygons.map((p) => {
                const color = getSectorColor(p.sector);
                return (
                  <Polygon
                    // positions can be Polygon or MultiPolygon-style arrays
                    key={p.id}
                    positions={p.positions}
                    pathOptions={{
                      color,
                      weight: 1,
                      fillColor: color,
                      fillOpacity: 0.15,
                    }}
                  />
                );
              })}

              {filteredHotspots.map((h) => {
                if (!h.center_lat || !h.center_long) return null;
                const pos = [Number(h.center_lat), Number(h.center_long)];
                const count = h.incident_count || 0;
                const radius = 14 + Math.min(count, 24); // visual radius
                const color = getCircleColor(h.risk_level);
                return (
                  <CircleMarker
                    key={h.hotspot_id}
                    center={pos}
                    radius={radius / 3}
                    pathOptions={{
                      color,
                      fillColor: color,
                      fillOpacity: 0.8,
                      weight: 2,
                    }}
                  >
                    {/* Number label in the bubble, like your design */}
                    <Tooltip
                      permanent
                      direction="center"
                      className="cluster-count-label"
                    >
                      <span>{count}</span>
                    </Tooltip>
                    {/* Hover tooltip with extra detail */}
                    <Tooltip direction="top" offset={[0, -4]} opacity={0.9}>
                      <div style={{ fontSize: '11px' }}>
                        <strong>{h.incident_type_name || 'Cluster'}</strong>
                        <br />
                        Reports: {count}
                        <br />
                        Risk: {h.risk_level || 'low'}
                      </div>
                    </Tooltip>
                  </CircleMarker>
                );
              })}
            </MapContainer>

            <div style={{ position: 'absolute', bottom: '10px', left: '10px', background: 'rgba(15, 22, 35, 0.95)', border: '1px solid var(--border)', borderRadius: '7px', padding: '8px 12px', fontSize: '11px' }}>
              <div style={{ fontWeight: 700, marginBottom: '5px', color: 'var(--text-dim)', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '1px' }}>Risk Level</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '11px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                  <div style={{ width: '9px', height: '9px', borderRadius: '50%', background: 'var(--danger)' }}></div>
                  Critical
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                  <div style={{ width: '9px', height: '9px', borderRadius: '50%', background: 'var(--warning)' }}></div>
                  Warning
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                  <div style={{ width: '9px', height: '9px', borderRadius: '50%', background: 'var(--success)' }}></div>
                  Normal
                </div>
              </div>
            </div>
          </div>
        </div>
        
        <div className="map-side">
          <div className="card">
            <div className="card-header">
              <div className="card-title">Active Clusters</div>
            </div>
            {topForSide.map((h, idx) => (
              <div className="hs-item" key={h.hotspot_id}>
                <div className="hs-rank">{String(idx + 1).padStart(2, '0')}</div>
                <div className="hs-info">
                  <div className="hs-name">
                    {h.incident_type_name || 'Cluster'} #{h.hotspot_id}
                  </div>
                  <div className="hs-meta">
                    {h.incident_count} · {h.risk_level || 'low'}
                  </div>
                </div>
                <span
                  className={`risk-pill ${
                    h.risk_level === 'high'
                      ? 'r-critical'
                      : h.risk_level === 'medium'
                      ? 'r-warning'
                      : 'r-normal'
                  }`}
                >
                  {(h.risk_level || 'ok').toUpperCase().slice(0, 4)}
                </span>
              </div>
            ))}
            {(!topForSide.length && !loading) && (
              <div style={{ fontSize: '12px', color: 'var(--muted)', padding: '10px 14px' }}>
                No active clusters.
              </div>
            )}
            {loading && (
              <div style={{ fontSize: '12px', color: 'var(--muted)', padding: '10px 14px' }}>
                Loading…
              </div>
            )}
          </div>
          
          <div className="card">
            <div className="card-header">
              <div className="card-title">District Summary</div>
            </div>
            <div className="status-row">
              <span>Total clusters</span><strong>{totalClusters}</strong>
            </div>
            <div className="status-row">
              <span>Reports in clusters</span><strong>{reportsInClusters}</strong>
            </div>
            <div className="status-row">
              <span>Critical / Warning / Normal</span>
              <strong>{crit} / {warn} / {normal}</strong>
            </div>
            <div className="status-row">
              <span>Avg cluster trust</span><strong style={{ color: 'var(--success)' }}>76 / 100</strong>
            </div>
            <div className="status-row">
              <span>Last DBSCAN run</span><strong>—</strong>
            </div>
            <button className="btn btn-outline btn-full" style={{ marginTop: '10px' }}>Export Map PDF</button>
          </div>
        </div>
      </div>
    </>
  );
};

export default SafetyMap;