import { useMemo, useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Fix default marker icons in bundler (e.g. Vite)
const defaultIcon = L.icon({
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});
L.Marker.prototype.options.icon = defaultIcon;

const incidentIcon = L.divIcon({
  className: 'incident-marker',
  html: '<span class="marker-dot marker-incident" title="Incident location"/>',
  iconSize: [24, 24],
  iconAnchor: [12, 12],
});
const reporterIcon = L.divIcon({
  className: 'reporter-marker',
  html: '<span class="marker-dot marker-reporter" title="Reporter"/>',
  iconSize: [20, 20],
  iconAnchor: [10, 10],
});
const evidenceIcon = L.divIcon({
  className: 'evidence-marker',
  html: '<span class="marker-dot marker-evidence" title="Evidence location"/>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

function FitBounds({ points }) {
  const map = useMap();
  useEffect(() => {
    if (!points || points.length < 2) return;
    const bounds = L.latLngBounds(points.map((p) => [p.lat, p.lng]));
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 16 });
  }, [map, points]);
  return null;
}

export default function IncidentMap({
  incidentLat,
  incidentLon,
  reporterLat,
  reporterLon,
  evidencePoints = [],
  height = '280px',
  zoom = 15,
}) {
  const incident = useMemo(() => {
    const lat = incidentLat != null ? Number(incidentLat) : null;
    const lon = incidentLon != null ? Number(incidentLon) : null;
    return lat != null && lon != null ? { lat, lng: lon } : null;
  }, [incidentLat, incidentLon]);

  const reporter = useMemo(() => {
    if (reporterLat == null || reporterLon == null) return null;
    const lat = Number(reporterLat);
    const lon = Number(reporterLon);
    if (incident && Math.abs(lat - incident.lat) < 1e-6 && Math.abs(lon - incident.lng) < 1e-6) return null;
    return { lat, lng: lon };
  }, [reporterLat, reporterLon, incident]);

  const evidence = useMemo(
    () =>
      (evidencePoints || [])
        .filter((p) => p?.lat != null && p?.lng != null)
        .map((p) => ({ lat: Number(p.lat), lng: Number(p.lng), label: p.label })),
    [evidencePoints]
  );

  const center = incident || reporter || (evidence[0] ? { lat: evidence[0].lat, lng: evidence[0].lng } : null);
  const allPoints = [incident, reporter, ...evidence.map((e) => ({ lat: e.lat, lng: e.lng }))].filter(Boolean);

  if (!center) {
    return (
      <div className="incident-map incident-map-empty" style={{ height }}>
        No location data to display.
      </div>
    );
  }

  return (
    <div className="incident-map" style={{ height }}>
      <MapContainer
        center={[center.lat, center.lng]}
        zoom={zoom}
        style={{ height: '100%', width: '100%', borderRadius: '8px' }}
        scrollWheelZoom
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {allPoints.length >= 2 && <FitBounds points={allPoints} />}
        {incident && (
          <Marker position={[incident.lat, incident.lng]} icon={incidentIcon}>
            <Popup>Incident location (combined)</Popup>
          </Marker>
        )}
        {reporter && (
          <Marker position={[reporter.lat, reporter.lng]} icon={reporterIcon}>
            <Popup>Reporter location</Popup>
          </Marker>
        )}
        {evidence.map((p, i) => (
          <Marker key={i} position={[p.lat, p.lng]} icon={evidenceIcon}>
            <Popup>{p.label || `Evidence ${i + 1}`}</Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}
