import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Fix for default markers in Leaflet
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const AdvancedGeoMap = ({ data, mapType, onMarkerClick, onAreaClick }) => {
  const mapRef = useRef(null);
  const mapInstance = useRef(null);
  const markersRef = useRef([]);
  const heatmapLayerRef = useRef(null);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedMarker, setSelectedMarker] = useState(null);

  useEffect(() => {
    if (!mapRef.current) return;

    setIsLoading(true);

    // Initialize map if it doesn't exist
    if (!mapInstance.current) {
      mapInstance.current = L.map(mapRef.current).setView([-1.5042, 29.6380], 12);

      // Add tile layer with better styling
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19,
      }).addTo(mapInstance.current);

      // Add scale control
      L.control.scale().addTo(mapInstance.current);
    }

    // Clear existing markers and layers
    markersRef.current.forEach(marker => mapInstance.current.removeLayer(marker));
    markersRef.current = [];
    if (heatmapLayerRef.current) {
      mapInstance.current.removeLayer(heatmapLayerRef.current);
    }

    // Add data based on map type
    switch (mapType) {
      case 'heatmap':
        createHeatMap();
        break;
      case 'clusters':
        createClusterMap();
        break;
      case 'flows':
        createFlowMap();
        break;
      case 'sectors':
        createSectorMap();
        break;
      case 'devices':
        createDeviceMap();
        break;
      default:
        createHeatMap();
    }

    setIsLoading(false);

    return () => {
      // Cleanup is handled by clearing markers above
    };
  }, [data, mapType]);

  const createHeatMap = () => {
    if (!data?.heatMapData) return;

    const heatData = data.heatMapData.map(point => [
      point.latitude,
      point.longitude,
      point.intensity || point.report_count || 1
    ]);

    // Create gradient circles for heat effect
    heatData.forEach(([lat, lng, intensity]) => {
      const radius = Math.sqrt(intensity) * 500; // Scale radius by intensity
      const opacity = Math.min(intensity / 10, 0.8); // Scale opacity by intensity

      const circle = L.circle([lat, lng], {
        color: 'red',
        fillColor: '#f03',
        fillOpacity: opacity,
        radius: radius
      }).addTo(mapInstance.current);

      circle.bindPopup(`
        <strong>Heat Point</strong><br>
        Reports: ${intensity}<br>
        Location: ${lat.toFixed(4)}, ${lng.toFixed(4)}
      `);

      markersRef.current.push(circle);
    });

    // Fit map to show all points
    if (heatData.length > 0) {
      const bounds = L.latLngBounds(heatData.map(([lat, lng]) => [lat, lng]));
      mapInstance.current.fitBounds(bounds, { padding: [50, 50] });
    }
  };

  const createClusterMap = () => {
    if (!data?.clusters) return;

    const colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD'];

    data.clusters.forEach((cluster, index) => {
      const color = colors[index % colors.length];
      
      // Create cluster circle
      const circle = L.circle([cluster.center_lat, cluster.center_lng], {
        color: color,
        fillColor: color,
        fillOpacity: 0.3,
        radius: cluster.radius || 1000
      }).addTo(mapInstance.current);

      circle.bindPopup(`
        <strong>Cluster ${index + 1}</strong><br>
        Devices: ${cluster.device_count}<br>
        Reports: ${cluster.report_count}<br>
        Center: ${cluster.center_lat.toFixed(4)}, ${cluster.center_lng.toFixed(4)}
      `);

      // Add center marker
      const marker = L.marker([cluster.center_lat, cluster.center_lng], {
        icon: L.divIcon({
          className: 'custom-div-icon',
          html: `<div style="background-color: ${color}; width: 20px; height: 20px; border-radius: 50%; border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);"></div>`,
          iconSize: [20, 20],
          iconAnchor: [10, 10]
        })
      }).addTo(mapInstance.current);

      marker.bindPopup(`
        <strong>Cluster Center</strong><br>
        ${cluster.device_count} devices<br>
        ${cluster.report_count} reports
      `);

      markersRef.current.push(circle, marker);
    });
  };

  const createFlowMap = () => {
    if (!data?.flowData) return;

    // Create curved lines for flows
    data.flowData.forEach(flow => {
      if (!flow.from_lat || !flow.from_lng || !flow.to_lat || !flow.to_lng) return;

      const weight = Math.max(2, Math.min(10, flow.flow_strength / 2));
      const opacity = Math.min(0.8, flow.flow_strength / 10);

      // Create curved path
      const latlngs = [
        [flow.from_lat, flow.from_lng],
        [flow.to_lat, flow.to_lng]
      ];

      const polyline = L.polyline(latlngs, {
        color: '#FF6B6B',
        weight: weight,
        opacity: opacity,
        smoothFactor: 1
      }).addTo(mapInstance.current);

      polyline.bindPopup(`
        <strong>Movement Flow</strong><br>
        From: ${flow.from_sector || 'Unknown'}<br>
        To: ${flow.to_sector || 'Unknown'}<br>
        Strength: ${flow.flow_strength}<br>
        Devices: ${flow.device_count || 0}
      `);

      // Add arrow marker at the end
      const arrowMarker = L.marker([flow.to_lat, flow.to_lng], {
        icon: L.divIcon({
          className: 'flow-arrow',
          html: `<div style="color: #FF6B6B; font-size: 16px; transform: rotate(${flow.angle || 0}deg);">➤</div>`,
          iconSize: [20, 20],
          iconAnchor: [10, 10]
        })
      }).addTo(mapInstance.current);

      markersRef.current.push(polyline, arrowMarker);
    });

    // Add sector markers
    if (data.sectors) {
      data.sectors.forEach(sector => {
        if (!sector.latitude || !sector.longitude) return;

        const marker = L.marker([sector.latitude, sector.longitude], {
          icon: L.divIcon({
            className: 'sector-marker',
            html: `<div style="background-color: #4ECDC4; color: white; padding: 5px 10px; border-radius: 15px; font-size: 12px; font-weight: bold; white-space: nowrap;">${sector.sector_name}</div>`,
            iconSize: [100, 30],
            iconAnchor: [50, 15]
          })
        }).addTo(mapInstance.current);

        marker.bindPopup(`
          <strong>${sector.sector_name}</strong><br>
          Reports: ${sector.report_count}<br>
          Devices: ${sector.device_count}
        `);

        markersRef.current.push(marker);
      });
    }
  };

  const createSectorMap = () => {
    if (!data?.sectors) return;

    const colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7'];

    data.sectors.forEach((sector, index) => {
      const color = colors[index % colors.length];
      
      // Create sector circle (approximate)
      const radius = Math.sqrt(sector.report_count || 1) * 200;
      const circle = L.circle([sector.latitude || -1.5042, sector.longitude || 29.6380], {
        color: color,
        fillColor: color,
        fillOpacity: 0.4,
        radius: radius
      }).addTo(mapInstance.current);

      circle.bindPopup(`
        <strong>${sector.sector_name}</strong><br>
        Reports: ${sector.report_count}<br>
        Devices: ${sector.device_count}<br>
        Avg Trust Score: ${sector.avg_trust_score}<br>
        Response Time: ${sector.avg_response_time}h
      `);

      // Add sector label
      const label = L.marker([sector.latitude || -1.5042, sector.longitude || 29.6380], {
        icon: L.divIcon({
          className: 'sector-label',
          html: `<div style="background-color: ${color}; color: white; padding: 8px 12px; border-radius: 20px; font-size: 14px; font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.3); white-space: nowrap;">${sector.sector_name}</div>`,
          iconSize: [120, 35],
          iconAnchor: [60, 17]
        })
      }).addTo(mapInstance.current);

      markersRef.current.push(circle, label);
    });
  };

  const createDeviceMap = () => {
    if (!data?.devices) return;

    // Device status colors
    const getStatusColor = (device) => {
      if (device.suspicious_score > 50) return '#FF6B6B'; // Red for suspicious
      if (device.automation_score > 80) return '#FFA500'; // Orange for automated
      if (device.avg_speed > 50) return '#FFD700'; // Yellow for high speed
      return '#4ECDC4'; // Green for normal
    };

    data.devices.forEach(device => {
      if (!device.last_latitude || !device.last_longitude) return;

      const color = getStatusColor(device);
      
      const marker = L.marker([device.last_latitude, device.last_longitude], {
        icon: L.divIcon({
          className: 'device-marker',
          html: `<div style="background-color: ${color}; width: 12px; height: 12px; border-radius: 50%; border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);"></div>`,
          iconSize: [12, 12],
          iconAnchor: [6, 6]
        })
      }).addTo(mapInstance.current);

      const statusText = device.suspicious_score > 50 ? 'Suspicious' : 
                        device.automation_score > 80 ? 'Automated' : 
                        device.avg_speed > 50 ? 'High Speed' : 'Normal';

      marker.bindPopup(`
        <strong>Device ${device.device_hash}</strong><br>
        Status: <span style="color: ${color}; font-weight: bold;">${statusText}</span><br>
        Reports: ${device.total_reports}<br>
        Avg Speed: ${device.avg_speed?.toFixed(1) || 0} km/h<br>
        Trust Score: ${device.trust_score || 0}<br>
        Last Seen: ${new Date(device.last_seen_at).toLocaleString()}<br>
        Night Activity: ${((device.night_activity_ratio || 0) * 100).toFixed(1)}%
      `);

      marker.on('click', () => {
        setSelectedMarker(device);
        if (onMarkerClick) onMarkerClick(device);
      });

      markersRef.current.push(marker);
    });
  };

  if (isLoading) {
    return (
      <div style={{ 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center', 
        height: '500px',
        backgroundColor: '#f8f9fa',
        borderRadius: '8px',
        border: '1px solid #dee2e6'
      }}>
        <div>
          <i className="fa fa-spinner fa-spin fa-2x" style={{ color: '#007bff' }}></i>
          <p style={{ marginTop: '10px', color: '#6c757d' }}>Loading advanced map...</p>
        </div>
      </div>
    );
  }

  return (
    <div style={{ position: 'relative' }}>
      {/* Map Controls */}
      <div style={{
        position: 'absolute',
        top: '10px',
        right: '10px',
        zIndex: 1000,
        backgroundColor: 'white',
        padding: '10px',
        borderRadius: '8px',
        boxShadow: '0 2px 4px rgba(0,0,0,0.2)',
        fontSize: '12px'
      }}>
        <div style={{ marginBottom: '5px' }}>
          <strong>Map Type:</strong> {mapType}
        </div>
        {selectedMarker && (
          <div style={{ marginTop: '10px', padding: '5px', backgroundColor: '#f8f9fa', borderRadius: '4px' }}>
            <strong>Selected:</strong><br/>
            Device: {selectedMarker.device_hash}<br/>
            Status: {selectedMarker.suspicious_score > 50 ? 'Suspicious' : 'Normal'}
          </div>
        )}
      </div>

      {/* Map Container */}
      <div 
        ref={mapRef} 
        style={{ 
          height: '500px', 
          width: '100%',
          borderRadius: '8px',
          overflow: 'hidden',
          border: '1px solid #dee2e6'
        }}
      />
    </div>
  );
};

export default AdvancedGeoMap;
