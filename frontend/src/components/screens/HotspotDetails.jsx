import React, { useEffect, useState } from 'react';
import api from '../../api/client';

// Strip Cloudinary transformation params to get raw upload URL
const stripCloudinaryTransforms = (url) => {
  if (!url || !url.includes('res.cloudinary.com')) return url;
  // Pattern: /image/upload/{transforms}/{rest}  → /image/upload/{rest}
  return url.replace(
    /(\/image\/upload\/)([^/]+\/)*?(v\d+\/|uploads\/)/,
    (_, prefix, _transforms, versionOrUploads) => `${prefix}${versionOrUploads}`
  );
};

const HotspotDetails = ({ hotspotId, wsRefreshKey }) => {
  const [hotspot, setHotspot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [currentEvidenceIndex, setCurrentEvidenceIndex] = useState(0);
  const [relatedReports, setRelatedReports] = useState([]);
  const [reportsLoading, setReportsLoading] = useState(true);
  const [locationNames, setLocationNames] = useState({});
  // imgErrors: { [index]: 'retry' | 'failed' }
  const [imgErrors, setImgErrors] = useState({});

  // Get location name for coordinates - use database fields like Reports page
  const getLocationName = async (lat, lng, report = null) => {
    const cacheKey = `${lat},${lng}`;
    if (locationNames[cacheKey]) {
      return locationNames[cacheKey];
    }

    // Use database fields directly like Reports page does
    if (report) {
      const dbLocation = {
        sector: report.sector_name || report.sector || 'Unknown',
        village: report.village_name || report.village || 'Unknown',
        cell: report.cell_name || report.cell || 'Unknown',
        display_name: `${report.sector_name || report.sector || 'Unknown'}, ${report.cell_name || report.cell || 'Unknown'} Cell, ${report.village_name || report.village || 'Unknown'} Village, Rwanda`
      };

      // Check if we have meaningful location data from database
      const hasRealLocationData =
        (dbLocation.sector && dbLocation.sector !== 'Unknown') ||
        (dbLocation.village && dbLocation.village !== 'Unknown') ||
        (dbLocation.cell && dbLocation.cell !== 'Unknown');

      if (hasRealLocationData) {
        // Cache the result
        setLocationNames(prev => ({
          ...prev,
          [cacheKey]: dbLocation
        }));

        return dbLocation;
      }
    }

    try {
      // Using BigDataCloud API for reverse geocoding (better CORS support)
      const response = await fetch(
        `https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=${lat}&longitude=${lng}&localityLanguage=en`,
        {
          headers: {
            'Accept': 'application/json'
          }
        }
      );

      if (response.ok) {
        const data = await response.json();

        // Initialize location info
        const locationInfo = {
          sector: data.locality || data.city || 'Unknown',
          village: data.suburb || 'Unknown',
          cell: data.cityDistrict || 'Unknown',
          display_name: data.display_name || `${data.locality || 'Unknown'}, ${data.countryName || 'Unknown'}`
        };

        // Enhanced parsing for Rwanda using localityInfo.administrative
        if (data.countryName === 'Rwanda' && data.localityInfo && data.localityInfo.administrative) {
          // Extract administrative levels from the array
          const adminLevels = data.localityInfo.administrative;

          // Parse administrative levels by adminLevel
          let province = '', district = '', sector = '', cell = '';

          adminLevels.forEach(level => {
            const name = level.name;
            const adminLevel = level.adminLevel;

            if (adminLevel === 2) {
              // Country level
            } else if (adminLevel === 4) {
              province = name; // Northern Province
            } else if (adminLevel === 6) {
              if (name.includes('District')) {
                district = name; // Musanze District
              } else {
                sector = name; // Musanze (city)
              }
            } else if (adminLevel === 8) {
              sector = name; // Muhoza (sector)
            }
          });

          // Map administrative levels to our structure
          let village = district || 'Unknown';
          cell = sector || 'Unknown';

          // If we found sector at level 8, use district for village
          if (adminLevels.some(level => level.adminLevel === 8)) {
            village = district || 'Unknown';
            cell = sector || 'Unknown';
          } else {
            village = sector || 'Unknown';
            cell = district || 'Unknown';
          }

          // Update with parsed values
          if (sector && sector !== '') locationInfo.sector = sector;
          if (village && village !== '') locationInfo.village = village;
          if (cell && cell !== '') locationInfo.cell = cell;
        }

        // Cache the result
        setLocationNames(prev => ({
          ...prev,
          [cacheKey]: locationInfo
        }));

        return locationInfo;
      }
    } catch (error) {
      // Geocoding failed; fall through to fallback
    }

    const fallbackLocation = {
      sector: 'Unknown',
      village: 'Unknown',
      cell: 'Unknown',
      display_name: 'Unknown location'
    };

    return fallbackLocation;
  };

  useEffect(() => {
    const loadHotspotDetails = async () => {
      try {
        setLoading(true);
        setError(null);

        // Clear location cache to ensure fresh data
        setLocationNames({});

        // Use the admin endpoint for location data (which works perfectly)
        const allHotspotsResponse = await api.get('/api/v1/hotspots/');

        // Find the specific hotspot by ID
        const hotspots = Array.isArray(allHotspotsResponse) ? allHotspotsResponse : [];
        const foundHotspot = hotspots.find(h => h.hotspot_id == hotspotId);

        // If admin API doesn't have evidence files in incident_points, try public API
        if (foundHotspot && (!foundHotspot.evidence_files || foundHotspot.evidence_files.length === 0)) {
          try {
            const publicResponse = await api.get(`/api/v1/public/hotspots/${hotspotId}`);
            if (publicResponse?.evidence_files && publicResponse.evidence_files.length > 0) {
              foundHotspot.evidence_files = publicResponse.evidence_files;
            }
          } catch (error) {
            // Public API unavailable; continue with admin data
          }
        }

        if (foundHotspot) {
          // Preload location names for all reports
          if (foundHotspot?.incident_points?.length > 0) {
            foundHotspot.incident_points.forEach(async (report) => {
              if (report.latitude && report.longitude) {
                await getLocationName(report.latitude, report.longitude, report);
              }
            });
          }

          setHotspot(foundHotspot);
          setImgErrors({});
          setCurrentEvidenceIndex(0);

          // If incident_points is not available, try to get reports by location
          if (!foundHotspot?.incident_points || foundHotspot.incident_points.length === 0) {
            try {
              // Try to get reports near the hotspot location
              const lat = foundHotspot?.center_lat || foundHotspot?.lat;
              const lng = foundHotspot?.center_long || foundHotspot?.lng;
              const radius = foundHotspot?.radius_meters || 500;

              // Query reports in the area
              const reportsResponse = await api.get(`/api/v1/reports/?limit=50&lat=${lat}&lng=${lng}&radius=${radius}`);

              // Handle different response formats
              const reports = Array.isArray(reportsResponse) ? reportsResponse : reportsResponse?.items || [];
              setRelatedReports(reports);
            } catch (locationError) {
              setRelatedReports([]);
            }
          } else {
            // Use incident_points if available
            setRelatedReports(foundHotspot.incident_points);
          }

          setError(null);
        } else {
          setError(`Hotspot #${hotspotId} not found`);
          setRelatedReports([]);
        }
      } catch (error) {
        setError('Failed to load hotspot details');
        setRelatedReports([]);
      } finally {
        setLoading(false);
        setReportsLoading(false);
      }
    };

    if (hotspotId) {
      loadHotspotDetails();
    } else {
      setLoading(false);
      setReportsLoading(false);
    }
  }, [hotspotId, wsRefreshKey]);

  const getRiskColor = (riskLevel) => {
    switch (riskLevel) {
      case 'high': return '#dc3545';
      case 'medium': return '#fd7e14';
      case 'low': return '#28a745';
      default: return '#6c757d';
    }
  };

  const getFormationStage = (hotspot) => {
    const count = Number(hotspot?.incident_count || 0);
    if (count >= 8) return "INTENSE";
    if (count >= 4) return "ACTIVE";
    return "EMERGING";
  };

  const handlePrevEvidence = () => {
    setCurrentEvidenceIndex((prev) => (prev > 0 ? prev - 1 : hotspot.evidence_files.length - 1));
  };

  const handleNextEvidence = () => {
    setCurrentEvidenceIndex((prev) => (prev < hotspot.evidence_files.length - 1 ? prev + 1 : 0));
  };

  if (loading) {
    return (
      <div className="card">
        <div style={{ padding: "40px", textAlign: "center", color: "var(--muted)" }}>
          Loading hotspot details...
        </div>
      </div>
    );
  }

  if (error || !hotspot) {
    return (
      <div className="card">
        <div style={{ padding: "40px", textAlign: "center", color: "var(--error)" }}>
          {error || 'Hotspot not found'}
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="page-header">
        <h2>Hotspot Details</h2>
        <p>Detailed analysis and evidence for detected crime hotspot #{hotspotId}.</p>
      </div>

      {/* Stats Row */}
      <div className="stats-row">
        <div className="stat-card c-red">
          <div className="stat-label">Risk Level</div>
          <div className="stat-value sv-red">{hotspot.risk_level?.toUpperCase() || "UNKNOWN"}</div>
          <div className="stat-change">Current assessment</div>
        </div>
        <div className="stat-card c-blue">
          <div className="stat-label">Total Reports</div>
          <div className="stat-value sv-blue">{hotspot.incident_count || 0}</div>
          <div className="stat-change">Incidents in cluster</div>
        </div>
        <div className="stat-card c-green">
          <div className="stat-label">Coverage Radius</div>
          <div className="stat-value sv-green">{hotspot.radius_meters || 0}m</div>
          <div className="stat-change">Detection area</div>
        </div>
        <div className="stat-card c-orange">
          <div className="stat-label">Formation Stage</div>
          <div className="stat-value sv-orange">{getFormationStage(hotspot)}</div>
          <div className="stat-change">Cluster development</div>
        </div>
      </div>

      {/* Main Content Grid */}
      <div className="g31">
        {/* Hotspot Overview Card */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">Hotspot Overview</div>
          </div>
          <div style={{ padding: "14px" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))", gap: "16px" }}>
              <div>
                <h4 style={{ margin: "0 0 8px 0", fontSize: "14px", color: "var(--muted)" }}>Incident Details</h4>
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ fontSize: "12px", color: "var(--muted)" }}>Type:</span>
                    <span style={{ fontSize: "12px", fontWeight: "600" }}>{hotspot.incident_type_name || 'Unknown'}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ fontSize: "12px", color: "var(--muted)" }}>First Detected:</span>
                    <span style={{ fontSize: "12px", fontWeight: "600" }}>
                      {hotspot.detected_at ? new Date(hotspot.detected_at).toLocaleString() : 'Unknown'}
                    </span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ fontSize: "12px", color: "var(--muted)" }}>Time Window:</span>
                    <span style={{ fontSize: "12px", fontWeight: "600" }}>{hotspot.time_window_hours || 0} hours</span>
                  </div>
                </div>
              </div>

              <div>
                <h4 style={{ margin: "0 0 8px 0", fontSize: "14px", color: "var(--muted)" }}>Location Information</h4>
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ fontSize: "12px", color: "var(--muted)" }}>Coordinates:</span>
                    <span style={{ fontSize: "12px", fontWeight: "600" }}>
                      {Number(hotspot.center_lat || hotspot.lat || 0).toFixed(4)}, {Number(hotspot.center_long || hotspot.lng || 0).toFixed(4)}
                    </span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ fontSize: "12px", color: "var(--muted)" }}>Radius:</span>
                    <span style={{ fontSize: "12px", fontWeight: "600" }}>{hotspot.radius_meters || 0}m</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: "12px", color: "var(--muted)" }}>Navigation:</span>
                    <div style={{ display: "flex", gap: "6px" }}>
                      <button
                        onClick={() => {
                          const lat = Number(hotspot.center_lat || hotspot.lat || 0);
                          const lng = Number(hotspot.center_long || hotspot.lng || 0);
                          // travelmode=driving opens Google Maps in turn-by-turn navigation mode
                          window.open(
                            `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}&travelmode=driving`,
                            '_blank'
                          );
                        }}
                        style={{
                          padding: "4px 8px",
                          fontSize: "10px",
                          backgroundColor: "var(--primary)",
                          color: "white",
                          border: "none",
                          borderRadius: "3px",
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          gap: "3px"
                        }}
                      >
                        Navigate
                      </button>
                      <button
                        onClick={() => {
                          const lat = Number(hotspot.center_lat || hotspot.lat || 0);
                          const lng = Number(hotspot.center_long || hotspot.lng || 0);
                          // search/?api=1&query= pins the exact coordinate on the map
                          window.open(
                            `https://www.google.com/maps/search/?api=1&query=${lat},${lng}`,
                            '_blank'
                          );
                        }}
                        style={{
                          padding: "4px 8px",
                          fontSize: "10px",
                          backgroundColor: "var(--secondary)",
                          color: "white",
                          border: "none",
                          borderRadius: "3px",
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          gap: "3px"
                        }}
                      >
                        View Map
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Risk Assessment Card */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">Risk Assessment</div>
          </div>
          <div style={{ padding: "14px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "16px", marginBottom: "12px" }}>
              <div
                style={{
                  width: "48px",
                  height: "48px",
                  borderRadius: "50%",
                  backgroundColor: getRiskColor(hotspot.risk_level),
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "20px"
                }}
              >
              </div>
              <div>
                <h3 style={{ margin: "0 0 4px 0", fontSize: "16px" }}>
                  {hotspot.risk_level?.toUpperCase() || "UNKNOWN"} RISK
                </h3>
                <p style={{ margin: 0, fontSize: "12px", color: "var(--muted)", lineHeight: "1.4" }}>
                  {hotspot.risk_level === 'high' ? 'High incident density and strong credibility indicators. Priority response needed.' :
                   hotspot.risk_level === 'medium' ? 'Moderate density. Requires active monitoring.' :
                   'Provisional cluster. Requires further observation.'}
                </p>
              </div>
            </div>

            {hotspot.hotspot_score && (
              <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderTop: "1px solid var(--border)" }}>
                <span style={{ fontSize: "12px", color: "var(--muted)" }}>Trust-Weighted Score:</span>
                <span style={{ fontSize: "12px", fontWeight: "600" }}>{Number(hotspot.hotspot_score).toFixed(1)}/100</span>
              </div>
            )}

            {hotspot.avg_trust_score && (
              <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0" }}>
                <span style={{ fontSize: "12px", color: "var(--muted)" }}>Average Trust Score:</span>
                <span style={{ fontSize: "12px", fontWeight: "600" }}>{Math.round(Number(hotspot.avg_trust_score))}/100</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Related Reports Section */}
      <div className="card" style={{ marginTop: "14px" }}>
        <div className="card-header">
          <div className="card-title">Related Reports ({relatedReports.length})</div>
          <span style={{ fontSize: "11px", color: "var(--muted)" }}>
            Individual reports that form this hotspot cluster
          </span>
        </div>
        <div style={{ padding: "14px" }}>
          {reportsLoading ? (
            <div style={{ textAlign: "center", padding: "20px", color: "var(--muted)" }}>
              Loading related reports...
            </div>
          ) : relatedReports.length === 0 ? (
            <div style={{ textAlign: "center", padding: "20px", color: "var(--muted)" }}>
              No related reports found for this hotspot.
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", minWidth: "700px" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--border)" }}>
                    <th style={{ textAlign: "left", padding: "8px", fontSize: "12px", color: "var(--muted)" }}>ID</th>
                    <th style={{ textAlign: "left", padding: "8px", fontSize: "12px", color: "var(--muted)" }}>Type</th>
                    <th style={{ textAlign: "left", padding: "8px", fontSize: "12px", color: "var(--muted)", width: "400px" }}>Location</th>
                    <th style={{ textAlign: "left", padding: "8px", fontSize: "12px", color: "var(--muted)" }}>Description</th>
                    <th style={{ textAlign: "left", padding: "8px", fontSize: "12px", color: "var(--muted)" }}>Date</th>
                    <th style={{ textAlign: "left", padding: "8px", fontSize: "12px", color: "var(--muted)" }}>Status</th>
                    <th style={{ textAlign: "left", padding: "8px", fontSize: "12px", color: "var(--muted)" }}>Trust</th>
                  </tr>
                </thead>
                <tbody>
                  {relatedReports.map((report, index) => (
                    <tr key={report.report_id || index} style={{ borderBottom: "1px solid var(--border2)" }}>
                      <td style={{ padding: "8px", fontSize: "12px" }}>
                        <span style={{ fontFamily: "monospace", fontSize: "10px", color: "var(--muted)" }}>
                          #{report.report_id?.substring(0, 8) || 'N/A'}
                        </span>
                      </td>
                      <td style={{ padding: "8px", fontSize: "12px" }}>
                        {report.incident_type_name || 'Unknown'}
                      </td>
                      <td style={{ padding: "8px", fontSize: "12px" }}>
                        <div style={{ maxWidth: "400px", wordBreak: "break-word", lineHeight: "1.3" }}>
                          {(() => {
                            const locationKey = `${report.latitude},${report.longitude}`;
                            const location = locationNames[locationKey];
                            if (location) {
                              return location.display_name || 'Unknown Location';
                            } else {
                              return report.latitude && report.longitude
                                ? `${Number(report.latitude).toFixed(4)}, ${Number(report.longitude).toFixed(4)}`
                                : 'No coordinates';
                            }
                          })()}
                        </div>
                      </td>
                      <td style={{ padding: "8px", fontSize: "12px" }}>
                        <div style={{ maxWidth: "200px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {report.description || 'No description'}
                        </div>
                      </td>
                      <td style={{ padding: "8px", fontSize: "12px" }}>
                        {report.reported_at ? new Date(report.reported_at).toLocaleDateString() : 'Unknown'}
                      </td>
                      <td style={{ padding: "8px" }}>
                        <span className={`risk-pill ${
                          report.trust_score >= 80 ? 'r-normal' :
                          report.trust_score >= 60 ? 'r-warning' : 'r-critical'
                        }`}>
                          {report.trust_score >= 80 ? 'HIGH' :
                           report.trust_score >= 60 ? 'MEDIUM' : 'LOW'} TRUST
                        </span>
                      </td>
                      <td style={{ padding: "8px", fontSize: "12px" }}>
                        <span style={{ color: report.trust_score >= 80 ? 'var(--success)' : report.trust_score >= 60 ? 'var(--warning)' : 'var(--danger)' }}>
                          {report.trust_score || 0}/100
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Evidence Section */}
      {hotspot.evidence_files && hotspot.evidence_files.length > 0 && (
        <div className="card" style={{ marginTop: "14px" }}>
          <div className="card-header">
            <div className="card-title">Evidence Files ({hotspot.evidence_files.length})</div>
          </div>
          <div style={{ padding: "14px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "16px", marginBottom: "16px" }}>
              <button
                className="btn btn-outline btn-sm"
                onClick={handlePrevEvidence}
                disabled={currentEvidenceIndex === 0}
              >
                ← Previous
              </button>
              <span style={{ fontSize: "12px", color: "var(--muted)" }}>
                {currentEvidenceIndex + 1} of {hotspot.evidence_files.length}
              </span>
              <button
                className="btn btn-outline btn-sm"
                onClick={handleNextEvidence}
                disabled={currentEvidenceIndex === hotspot.evidence_files.length - 1}
              >
                Next →
              </button>
            </div>

            <div style={{ textAlign: "center" }}>
              <div style={{
                marginBottom: "8px",
                fontSize: "12px",
                color: "var(--muted)",
                display: "flex",
                justifyContent: "center",
                gap: "8px"
              }}>
                <span className={`risk-pill ${hotspot.evidence_files[currentEvidenceIndex].file_type === 'photo' ? 'r-normal' : 'r-warning'}`}>
                  {hotspot.evidence_files[currentEvidenceIndex].file_type === 'photo' ? 'PHOTO' : 'VIDEO'}
                </span>
                <span style={{ fontSize: "11px" }}>
                  {hotspot.evidence_files[currentEvidenceIndex].uploaded_at ?
                    new Date(hotspot.evidence_files[currentEvidenceIndex].uploaded_at).toLocaleString() :
                    'Unknown date'
                  }
                </span>
              </div>

              {hotspot.evidence_files[currentEvidenceIndex].file_type === 'photo' ? (() => {
                const idx = currentEvidenceIndex;
                const origUrl = hotspot.evidence_files[idx].file_url;
                const rawUrl = stripCloudinaryTransforms(origUrl);
                const errState = imgErrors[idx]; // undefined | 'retry' | 'failed'

                if (errState === 'failed') {
                  // Both original and raw URL failed — show a friendly fallback
                  return (
                    <div style={{
                      padding: "24px 16px",
                      border: "1px dashed var(--border)",
                      borderRadius: "8px",
                      background: "var(--surface2)",
                      textAlign: "center",
                    }}>
                      <div style={{ fontSize: "13px", color: "var(--text)", marginBottom: "4px" }}>
                        Image preview unavailable
                      </div>
                      <div style={{ fontSize: "11px", color: "var(--muted)", marginBottom: "14px", wordBreak: "break-all" }}>
                        {origUrl}
                      </div>
                      <a
                        href={origUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          fontSize: "12px",
                          color: "white",
                          backgroundColor: "var(--primary)",
                          padding: "6px 14px",
                          borderRadius: "4px",
                          textDecoration: "none",
                          display: "inline-block",
                        }}
                      >
                        Open image in new tab →
                      </a>
                    </div>
                  );
                }

                // Decide which URL to use: on first retry use raw URL
                const src = errState === 'retry' && rawUrl !== origUrl ? rawUrl : origUrl;

                return (
                  <img
                    key={`${idx}-${errState || 'orig'}`}
                    src={src}
                    alt="Evidence"
                    crossOrigin="anonymous"
                    style={{
                      maxWidth: "100%",
                      maxHeight: "400px",
                      borderRadius: "4px",
                      border: "1px solid var(--border)",
                    }}
                    onError={() => {
                      setImgErrors(prev => {
                        const cur = prev[idx];
                        if (!cur) {
                          // First failure: retry with raw URL (if different)
                          if (rawUrl !== origUrl) return { ...prev, [idx]: 'retry' };
                          // Same URL (no transforms to strip) — go straight to failed
                          return { ...prev, [idx]: 'failed' };
                        }
                        // Second failure (retry also failed) — mark as failed
                        return { ...prev, [idx]: 'failed' };
                      });
                    }}
                  />
                );
              })()
              : (
                <div style={{ position: "relative" }}>
                  <video
                    controls
                    style={{
                      width: "100%",
                      maxHeight: "400px",
                      objectFit: "cover",
                      display: "block",
                      borderRadius: "4px",
                      border: "1px solid var(--border)"
                    }}
                  >
                    <source
                      src={hotspot.evidence_files[currentEvidenceIndex].file_url}
                      type="video/mp4"
                    />
                    Your browser does not support the video tag.
                  </video>

                  {/* Fallback for browsers that don't support video */}
                  <div style={{
                    display: "none",
                    padding: "40px",
                    border: "1px dashed var(--border)",
                    borderRadius: "4px",
                    background: "var(--surface2)",
                    textAlign: "center"
                  }}>
                    <div style={{ fontSize: "12px", color: "var(--muted)", marginBottom: "16px" }}>
                      Video evidence preview not available
                    </div>
                    {hotspot.evidence_files[currentEvidenceIndex].file_url && (
                      <a
                        href={hotspot.evidence_files[currentEvidenceIndex].file_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          fontSize: "12px",
                          color: "var(--accent)",
                          textDecoration: "none",
                          padding: "8px 16px",
                          border: "1px solid var(--accent)",
                          borderRadius: "4px",
                          display: "inline-block"
                        }}
                      >
                        Open Video in New Tab →
                      </a>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default HotspotDetails;
