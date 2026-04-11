"""
Geographic Intelligence API

Provides advanced location analytics for fraud detection and geographic insights:
- Heat maps for device density and reporting hotspots
- Movement flow analysis between sectors
- Coverage analysis and gap detection
- Sector performance metrics
- Device behavior pattern analysis
"""

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, desc, asc
from collections import defaultdict
import math
from geopy.distance import geodesic

from app.database import get_db
from app.models.device import Device
from app.models.report import Report
from app.models.report_assignment import ReportAssignment
from app.models.location import Location
from app.models.station import Station
from app.models.incident_type import IncidentType
from app.api.v1.auth import get_current_admin_or_supervisor, get_current_user
from typing import Annotated

router = APIRouter()

# Helper functions for geographic calculations
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in kilometers"""
    R = 6371.0
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

def get_sector_bounds(db: Session, sector_id: int) -> Optional[Dict[str, float]]:
    """Get bounding box for a sector"""
    locations = db.query(Location).filter(
        Location.location_id == sector_id,
        Location.is_active == True
    ).first()
    
    if not locations or not locations.latitude or not locations.longitude:
        return None
    
    # For now, return a 5km radius around the sector center
    # TODO: Implement proper polygon bounds from location data
    radius_km = 5.0
    return {
        'min_lat': locations.latitude - (radius_km / 111),
        'max_lat': locations.latitude + (radius_km / 111),
        'min_lon': locations.longitude - (radius_km / (111 * math.cos(math.radians(locations.latitude)))),
        'max_lon': locations.longitude + (radius_km / (111 * math.cos(math.radians(locations.latitude))))
    }

@router.get("/heat-map")
def get_heat_map(
    current_user: Annotated[Any, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
    time_window_hours: int = Query(720, description="Time window in hours (default: 30 days)"),
    grid_size: float = Query(0.5, description="Grid size in degrees"),
    min_reports_per_cell: int = Query(1, description="Minimum reports per cell"),
    sector_id: Optional[int] = Query(None, description="Filter by sector")
):
    """
    Generate heat map data for device density and reporting hotspots
    Returns grid cells with report counts and device density
    """
    
    # Calculate time window
    since = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
    
    # Base query for reports with location data
    query = db.query(Report).filter(
        Report.reported_at >= since,
        Report.latitude.isnot(None),
        Report.longitude.isnot(None),
        Report.village_location_id.isnot(None)
    )
    
    # Filter by sector if specified
    if sector_id:
        sector_bounds = get_sector_bounds(db, sector_id)
        if sector_bounds:
            query = query.filter(
                Report.latitude >= sector_bounds['min_lat'],
                Report.latitude <= sector_bounds['max_lat'],
                Report.longitude >= sector_bounds['min_lon'],
                Report.longitude <= sector_bounds['max_lon']
            )
    
    reports = query.all()
    
    # Create grid cells
    grid_cells = defaultdict(lambda: {'reports': [], 'devices': set(), 'incident_types': defaultdict(int)})
    
    for report in reports:
        # Calculate grid cell coordinates (convert Decimal to float)
        lat_cell = math.floor(float(report.latitude) / grid_size) * grid_size
        lon_cell = math.floor(float(report.longitude) / grid_size) * grid_size
        
        cell_key = (lat_cell, lon_cell)
        grid_cells[cell_key]['reports'].append(report)
        grid_cells[cell_key]['devices'].add(report.device_id)
        grid_cells[cell_key]['incident_types'][report.incident_type_id] += 1
    
    # Build heat map data
    heat_map_data = []
    for (lat_cell, lon_cell), cell_data in grid_cells.items():
        if len(cell_data['reports']) >= min_reports_per_cell:
            # Calculate cell center
            center_lat = lat_cell + grid_size / 2
            center_lon = lon_cell + grid_size / 2
            
            # Calculate device density (reports per unique device)
            device_density = len(cell_data['reports']) / len(cell_data['devices']) if cell_data['devices'] else 0
            
            # Get top incident type
            top_incident_type_id = max(cell_data['incident_types'].items(), key=lambda x: x[1])[0] if cell_data['incident_types'] else None
            
            heat_map_data.append({
                'lat': center_lat,
                'lng': center_lon,
                'report_count': len(cell_data['reports']),
                'device_count': len(cell_data['devices']),
                'device_density': round(device_density, 2),
                'top_incident_type_id': top_incident_type_id,
                'incident_type_distribution': dict(cell_data['incident_types'])
            })
    
    return {
        'time_window_hours': time_window_hours,
        'grid_size': grid_size,
        'total_reports': len(reports),
        'total_cells': len(heat_map_data),
        'heat_map_data': heat_map_data
    }

@router.get("/movement-flows")
def get_movement_flows(
    current_user: Annotated[Any, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
    time_window_hours: int = Query(720, description="Time window in hours (default: 30 days)"),
    min_flow_strength: int = Query(2, description="Minimum flow strength to include"),
    sector_id: Optional[int] = Query(None, description="Filter by sector")
):
    """
    Analyze device movement patterns between sectors
    Returns flow data showing device movements between locations
    """
    
    since = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
    
    # Get devices with location history
    devices_query = db.query(Device).filter(
        Device.metadata_json.isnot(None),
        Device.last_seen_at >= since
    )
    
    # Filter by sector if specified
    if sector_id:
        devices_query = devices_query.filter(
            Device.metadata_json['current_sector_location_id'].astext.cast(Integer) == sector_id
        )
    
    devices = devices_query.all()
    
    # Analyze movement flows
    sector_flows = defaultdict(lambda: {'from_count': 0, 'to_count': 0, 'devices': set()})
    device_movements = []
    
    for device in devices:
        metadata = device.metadata_json or {}
        location_history = metadata.get('location_history', [])
        
        if len(location_history) < 2:
            continue
        
        # Get sector information for each location in history
        for i in range(1, len(location_history)):
            prev_location = location_history[i-1]
            curr_location = location_history[i]
            
            # Get sector IDs for locations (simplified - would need proper geocoding)
            prev_sector = f"sector_{prev_location.get('latitude', 0):.2f}_{prev_location.get('longitude', 0):.2f}"
            curr_sector = f"sector_{curr_location.get('latitude', 0):.2f}_{curr_location.get('longitude', 0):.2f}"
            
            if prev_sector != curr_sector:
                distance = haversine_distance(
                    prev_location['latitude'], prev_location['longitude'],
                    curr_location['latitude'], curr_location['longitude']
                )
                
                time_diff = (datetime.fromisoformat(curr_location['timestamp'].replace('Z', '+00:00')) - 
                           datetime.fromisoformat(prev_location['timestamp'].replace('Z', '+00:00'))).total_seconds() / 3600
                
                if time_diff > 0:
                    speed = distance / time_diff
                    
                    device_movements.append({
                        'device_id': device.device_id,
                        'from_sector': prev_sector,
                        'to_sector': curr_sector,
                        'distance_km': round(distance, 2),
                        'time_hours': round(time_diff, 2),
                        'speed_kmh': round(speed, 2),
                        'timestamp': curr_location['timestamp']
                    })
                    
                    sector_flows[(prev_sector, curr_sector)]['devices'].add(device.device_id)
                    sector_flows[(prev_sector, curr_sector)]['from_count'] += 1
    
    # Build flow data
    flow_data = []
    for (from_sector, to_sector), flow_info in sector_flows.items():
        if len(flow_info['devices']) >= min_flow_strength:
            # Calculate average speed and distance for this flow
            flow_movements = [m for m in device_movements if m['from_sector'] == from_sector and m['to_sector'] == to_sector]
            avg_speed = sum(m['speed_kmh'] for m in flow_movements) / len(flow_movements) if flow_movements else 0
            avg_distance = sum(m['distance_km'] for m in flow_movements) / len(flow_movements) if flow_movements else 0
            
            flow_data.append({
                'from_sector': from_sector,
                'to_sector': to_sector,
                'device_count': len(flow_info['devices']),
                'movement_count': flow_info['from_count'],
                'avg_speed_kmh': round(avg_speed, 2),
                'avg_distance_km': round(avg_distance, 2),
                'flow_strength': len(flow_info['devices'])
            })
    
    # Sort by flow strength
    flow_data.sort(key=lambda x: x['flow_strength'], reverse=True)
    
    return {
        'time_window_hours': time_window_hours,
        'total_devices_analyzed': len(devices),
        'total_flows': len(flow_data),
        'flow_data': flow_data[:50]  # Top 50 flows
    }

@router.get("/coverage-analysis")
def get_coverage_analysis(
    current_user: Annotated[Any, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
    time_window_hours: int = Query(720, description="Time window in hours (default: 30 days)"),
    sector_id: Optional[int] = Query(None, description="Filter by sector")
):
    """
    Analyze geographic coverage and identify gaps/overlaps
    Returns coverage metrics and gap analysis
    """
    
    since = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
    
    # Get all active sectors
    sectors_query = db.query(Location).filter(
        Location.location_type == 'sector',
        Location.is_active == True
    )
    
    if sector_id:
        sectors_query = sectors_query.filter(Location.location_id == sector_id)
    
    sectors = sectors_query.all()
    
    coverage_data = []
    
    for sector in sectors:
        # Get reports in this sector
        sector_reports = db.query(Report).filter(
            Report.reported_at >= since,
            Report.village_location_id.in_(
                db.query(Location.location_id).filter(
                    or_(
                        Location.parent_location_id == sector.location_id,
                        Location.location_id == sector.location_id,
                        Location.parent_location_id.in_(
                            db.query(Location.location_id).filter(
                                Location.parent_location_id == sector.location_id
                            )
                        )
                    )
                )
            )
        ).all()
        
        # Calculate coverage metrics
        unique_devices = set(r.device_id for r in sector_reports)
        incident_types = defaultdict(int)
        
        for report in sector_reports:
            incident_types[report.incident_type_id] += 1
        
        # Calculate geographic spread
        if sector_reports:
            lats = [float(r.latitude) for r in sector_reports if r.latitude]
            lngs = [float(r.longitude) for r in sector_reports if r.longitude]
            
            if lats and lngs:
                lat_spread = max(lats) - min(lats)
                lng_spread = max(lngs) - min(lngs)
                geographic_area = lat_spread * lng_spread * 111 * 111  # Rough km²
            else:
                geographic_area = 0
        else:
            geographic_area = 0
        
        coverage_data.append({
            'sector_id': sector.location_id,
            'sector_name': sector.location_name,
            'report_count': len(sector_reports),
            'device_count': len(unique_devices),
            'incident_type_diversity': len(incident_types),
            'geographic_area_km2': round(geographic_area, 2),
            'reports_per_km2': round(len(sector_reports) / geographic_area, 2) if geographic_area > 0 else 0,
            'devices_per_km2': round(len(unique_devices) / geographic_area, 2) if geographic_area > 0 else 0,
            'incident_type_distribution': dict(incident_types)
        })
    
    # Identify coverage gaps and overlaps
    total_reports = sum(d['report_count'] for d in coverage_data)
    total_devices = sum(d['device_count'] for d in coverage_data)
    
    gaps = [d for d in coverage_data if d['report_count'] < 5]  # Low activity sectors
    overlaps = [d for d in coverage_data if d['reports_per_km2'] > 10]  # High density sectors
    
    return {
        'time_window_hours': time_window_hours,
        'total_sectors': len(coverage_data),
        'total_reports': total_reports,
        'total_devices': total_devices,
        'coverage_data': coverage_data,
        'coverage_gaps': gaps,
        'coverage_overlaps': overlaps,
        'avg_reports_per_sector': round(total_reports / len(coverage_data), 2) if coverage_data else 0,
        'avg_devices_per_sector': round(total_devices / len(coverage_data), 2) if coverage_data else 0
    }

@router.get("/sector-performance")
def get_sector_performance(
    current_user: Annotated[Any, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
    time_window_hours: int = Query(720, description="Time window in hours (default: 30 days)"),
    sector_id: Optional[int] = Query(None, description="Filter by sector")
):
    """
    Get performance metrics by sector
    Returns comparative analytics between sectors
    """
    
    since = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
    
    # Get sectors with their performance data
    if current_user.role == "admin":
        # Admin sees all sectors
        sectors_query = db.query(Location).filter(Location.location_type == "sector")
        if sector_id:
            sectors_query = sectors_query.filter(Location.location_id == sector_id)
        sectors = sectors_query.all()
    else:
        # Supervisor sees only sectors in their station
        sectors_query = db.query(Location).filter(
            Location.location_type == "sector",
            Location.parent_location_id == current_user.station_id
        )
        if sector_id:
            sectors_query = sectors_query.filter(Location.location_id == sector_id)
        sectors = sectors_query.all()
    
    performance_data = []
    
    for sector in sectors:
        # Get reports in this sector
        sector_reports = db.query(Report).filter(
            Report.reported_at >= since,
            Report.village_location_id.in_(
                db.query(Location.location_id).filter(
                    or_(
                        Location.parent_location_id == sector.location_id,
                        Location.location_id == sector.location_id,
                        Location.parent_location_id.in_(
                            db.query(Location.location_id).filter(
                                Location.parent_location_id == sector.location_id
                            )
                        )
                    )
                )
            )
        ).all()
        
        # Calculate performance metrics
        unique_devices = set(r.device_id for r in sector_reports)
        
        # Trust score analysis
        device_trust_scores = []
        for device_id in unique_devices:
            device = db.query(Device).filter(Device.device_id == device_id).first()
            if device and device.device_trust_score is not None:
                device_trust_scores.append(device.device_trust_score)
        
        avg_trust_score = sum(device_trust_scores) / len(device_trust_scores) if device_trust_scores else 0
        
        # Report quality metrics
        confirmed_reports = sum(1 for r in sector_reports if r.verification_status == 'confirmed')
        flagged_reports = sum(1 for r in sector_reports if r.verification_status in ['flagged', 'rejected'])
        
        # Response time analysis (time to first review)
        response_times = []
        for report in sector_reports:
            if report.verified_at:
                response_time = (report.verified_at - report.reported_at).total_seconds() / 3600
                response_times.append(response_time)
        
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        performance_data.append({
            'sector_id': sector.location_id,
            'sector_name': sector.location_name,
            'report_count': len(sector_reports),
            'device_count': len(unique_devices),
            'avg_trust_score': round(avg_trust_score, 2),
            'confirmed_reports': confirmed_reports,
            'flagged_reports': flagged_reports,
            'confirmation_rate': round(confirmed_reports / len(sector_reports) * 100, 2) if sector_reports else 0,
            'flag_rate': round(flagged_reports / len(sector_reports) * 100, 2) if sector_reports else 0,
            'avg_response_time_hours': round(avg_response_time, 2),
            'reports_per_device': round(len(sector_reports) / len(unique_devices), 2) if unique_devices else 0
        })
    
    # Sort by performance (you can change the sorting criteria)
    performance_data.sort(key=lambda x: x['avg_trust_score'], reverse=True)
    
    return {
        'time_window_hours': time_window_hours,
        'total_sectors': len(performance_data),
        'performance_data': performance_data,
        'top_performing_sectors': performance_data[:5],
        'bottom_performing_sectors': performance_data[-5:] if len(performance_data) > 5 else []
    }

@router.get("/station-performance")
def get_station_performance(
    current_user: Annotated[Any, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
    time_window_hours: int = Query(720, description="Time window in hours (default: 30 days)"),
):
    """
    Get performance metrics for supervisor's station
    Returns analytics for sectors within the supervisor's station only
    """
    
    since = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
    
    # Get the station's location first
    station = db.query(Station).filter(Station.station_id == current_user.station_id).first()
    if not station:
        return {
            'time_window_hours': time_window_hours,
            'total_sectors': 0,
            'performance_data': [],
            'top_performing_sectors': [],
            'bottom_performing_sectors': [],
            'station_name': 'Unknown Station',
            'debug_info': {'error': 'Station not found', 'station_id': current_user.station_id}
        }
    
    # Get sectors within the station's jurisdiction
    # This assumes sectors are children of the station's location or the station location itself
    station_location_id = station.location_id
    
    # Debug: Get all locations to understand the hierarchy
    all_locations = db.query(Location).all()
    location_hierarchy = []
    for loc in all_locations:
        location_hierarchy.append({
            'location_id': loc.location_id,
            'location_name': loc.location_name,
            'location_type': loc.location_type,
            'parent_location_id': loc.parent_location_id
        })
    
    # Get sectors that are either:
    # 1. Direct children of the station's location
    # 2. The station's location itself if it's a sector
    sectors_query = db.query(Location).filter(
        Location.location_type == "sector",
        or_(
            Location.parent_location_id == station_location_id,
            Location.location_id == station_location_id
        )
    )
    
    sectors = sectors_query.all()
    
    # If no sectors found, try different approaches
    if not sectors:
        # Try to find sectors under cells that are under the station location
        cells_under_station = db.query(Location).filter(
            Location.location_type == "cell",
            Location.parent_location_id == station_location_id
        ).all()
        
        if cells_under_station:
            cell_ids = [cell.location_id for cell in cells_under_station]
            sectors = db.query(Location).filter(
                Location.location_type == "sector",
                Location.parent_location_id.in_(cell_ids)
            ).all()
    
    # If still no sectors, try to find villages directly under station
    if not sectors:
        # For supervisor, show village-level performance instead of sector
        villages_query = db.query(Location).filter(
            Location.location_type == "village",
            or_(
                Location.parent_location_id == station_location_id,
                Location.parent_location_id.in_(
                    db.query(Location.location_id).filter(
                        Location.parent_location_id == station_location_id
                    )
                )
            )
        )
        sectors = villages_query.all()  # Use sectors variable for compatibility
    
    performance_data = []
    
    for sector in sectors:
        # Get reports in this sector
        sector_reports = db.query(Report).filter(
            Report.reported_at >= since,
            Report.village_location_id.in_(
                db.query(Location.location_id).filter(
                    or_(
                        Location.parent_location_id == sector.location_id,
                        Location.location_id == sector.location_id,
                        Location.parent_location_id.in_(
                            db.query(Location.location_id).filter(
                                Location.parent_location_id == sector.location_id
                            )
                        )
                    )
                )
            )
        ).all()
        
        # Calculate performance metrics
        unique_devices = set(r.device_id for r in sector_reports)
        
        # Trust score analysis
        device_trust_scores = []
        for device_id in unique_devices:
            device = db.query(Device).filter(Device.device_id == device_id).first()
            if device and device.device_trust_score is not None:
                device_trust_scores.append(device.device_trust_score)
        
        avg_trust_score = sum(device_trust_scores) / len(device_trust_scores) if device_trust_scores else 0
        
        # Report quality metrics
        confirmed_reports = sum(1 for r in sector_reports if r.verification_status == 'confirmed')
        flagged_reports = sum(1 for r in sector_reports if r.verification_status in ['flagged', 'rejected'])
        
        # Response time analysis (time to first review)
        response_times = []
        for report in sector_reports:
            if report.verified_at:
                response_time = (report.verified_at - report.reported_at).total_seconds() / 3600
                response_times.append(response_time)
        
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        performance_data.append({
            'sector_id': sector.location_id,
            'sector_name': sector.location_name,
            'report_count': len(sector_reports),
            'device_count': len(unique_devices),
            'avg_trust_score': round(avg_trust_score, 2),
            'confirmed_reports': confirmed_reports,
            'flagged_reports': flagged_reports,
            'confirmation_rate': round(confirmed_reports / len(sector_reports) * 100, 2) if sector_reports else 0,
            'flag_rate': round(flagged_reports / len(sector_reports) * 100, 2) if sector_reports else 0,
            'avg_response_time_hours': round(avg_response_time, 2),
            'reports_per_device': round(len(sector_reports) / len(unique_devices), 2) if unique_devices else 0
        })
    
    # Sort by performance (you can change the sorting criteria)
    performance_data.sort(key=lambda x: x['avg_trust_score'], reverse=True)
    
    return {
        'time_window_hours': time_window_hours,
        'total_sectors': len(performance_data),
        'performance_data': performance_data,
        'top_performing_sectors': performance_data[:5],
        'bottom_performing_sectors': performance_data[-5:] if len(performance_data) > 5 else [],
        'station_name': station.station_name,
        'debug_info': {
            'station_id': current_user.station_id,
            'station_location_id': station_location_id,
            'sectors_found': len(sectors),
            'sector_names': [s.location_name for s in sectors],
            'location_hierarchy': location_hierarchy,
            'data_type': 'village' if not sectors and any(s.location_type == 'village' for s in sectors) else 'sector'
        }
    }

@router.get("/officer-performance")
def get_officer_performance(
    current_user: Annotated[Any, Depends(get_current_user)],
    db: Session = Depends(get_db),
    time_window_hours: int = Query(720, description="Time window in hours (default: 30 days)"),
):
    """
    Get performance metrics for officer
    Returns personal analytics for the logged-in officer
    """
    
    from datetime import date, timedelta
    since = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
    
    # Get reports verified by this officer within the time window
    print(f"DEBUG: Officer {current_user.police_user_id} ({current_user.first_name} {current_user.last_name}) requesting performance data")
    print(f"DEBUG: Time window: {time_window_hours} hours, since: {since}")
    
    officer_reports = db.query(Report).filter(
        Report.verified_by == current_user.police_user_id,
        Report.verified_at >= since  # Filter by verification date, not report date
    ).all()
    
    print(f"DEBUG: Found {len(officer_reports)} reports verified by officer {current_user.police_user_id}")
    
    # Also check all reports verified by this officer (no time limit)
    all_officer_reports = db.query(Report).filter(
        Report.verified_by == current_user.police_user_id
    ).all()
    print(f"DEBUG: Total reports verified by officer {current_user.police_user_id} (all time): {len(all_officer_reports)}")
    
    # Show some sample reports
    for i, report in enumerate(all_officer_reports[:3]):
        print(f"DEBUG: Sample report {i+1}: ID={report.report_id}, reported_at={report.reported_at}, verified_at={report.verified_at}, status={report.status}")
    
    # Check if there are any reports with verified_by set at all
    reports_with_verifier = db.query(Report).filter(Report.verified_by.isnot(None)).count()
    print(f"DEBUG: Total reports in database with any verifier: {reports_with_verifier}")
    
    # Calculate daily performance metrics
    daily_metrics = {}
    for report in officer_reports:
        day_key = report.reported_at.strftime('%Y-%m-%d')
        day_name = report.reported_at.strftime('%a')  # Mon, Tue, etc.
        
        if day_key not in daily_metrics:
            daily_metrics[day_key] = {
                'date': day_name,
                'reports_processed': 0,
                'total_response_time': 0,
                'verified_count': 0,
                'flagged_count': 0
            }
        
        daily_metrics[day_key]['reports_processed'] += 1
        
        # Calculate response time (time from assignment to verification)
        if report.verified_at:
            # Get the assignment record for this report and officer
            assignment = db.query(ReportAssignment).filter(
                ReportAssignment.report_id == report.report_id,
                ReportAssignment.police_user_id == current_user.police_user_id
            ).first()
            
            if assignment and assignment.assigned_at:
                response_time = (report.verified_at - assignment.assigned_at).total_seconds() / 3600  # in hours
                print(f"DEBUG: Response time calculation for report {str(report.report_id)[:8]}...")
                print(f"  Assigned at: {assignment.assigned_at}")
                print(f"  Verified at: {report.verified_at}")
                print(f"  Time difference: {report.verified_at - assignment.assigned_at}")
                print(f"  Response time (hours): {response_time}")
                daily_metrics[day_key]['total_response_time'] += response_time
            else:
                print(f"DEBUG: No assignment found for report {str(report.report_id)[:8]}, using report submission time")
                # Fallback to report submission time if no assignment found
                response_time = (report.verified_at - report.reported_at).total_seconds() / 3600  # in hours
                print(f"  Reported at: {report.reported_at}")
                print(f"  Verified at: {report.verified_at}")
                print(f"  Response time (hours): {response_time}")
                daily_metrics[day_key]['total_response_time'] += response_time
        
        # Count verification status
        if report.verification_status == 'confirmed':
            daily_metrics[day_key]['verified_count'] += 1
        elif report.verification_status in ['flagged', 'rejected']:
            daily_metrics[day_key]['flagged_count'] += 1
    
    # Convert to list and calculate averages
    performance_data = []
    for day_key in sorted(daily_metrics.keys()):
        metrics = daily_metrics[day_key]
        avg_response_time = metrics['total_response_time'] / metrics['reports_processed'] if metrics['reports_processed'] > 0 else 0
        
        performance_data.append({
            'date': metrics['date'],
            'reports_processed': metrics['reports_processed'],
            'avg_response_time': round(avg_response_time, 2),
            'verified_count': metrics['verified_count'],
            'flagged_count': metrics['flagged_count']
        })
    
    # If no data, provide fallback for last 5 days
    if not performance_data:
        fallback_data = []
        for i in range(5):
            day = date.today() - timedelta(days=4-i)
            fallback_data.append({
                'date': day.strftime('%a'),
                'reports_processed': 0,
                'avg_response_time': 0,
                'verified_count': 0,
                'flagged_count': 0
            })
        performance_data = fallback_data
    
    return {
        'time_window_hours': time_window_hours,
        'officer_id': current_user.police_user_id,
        'officer_name': f"{current_user.first_name} {current_user.last_name}",
        'total_reports': len(officer_reports),
        'performance_data': performance_data,
        'debug_info': {
            'officer_role': current_user.role,
            'station_id': current_user.station_id,
            'assigned_location_id': current_user.assigned_location_id
        }
    }

# ==================== DEVICE BEHAVIOR PATTERN ANALYSIS ====================

@router.get("/behavior-patterns")
def get_behavior_patterns(
    current_user: Annotated[Any, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
    time_window_hours: int = Query(720, description="Time window in hours (default: 30 days)"),
    device_id: Optional[str] = Query(None, description="Analyze specific device"),
    sector_id: Optional[int] = Query(None, description="Filter by sector")
):
    """
    Analyze device behavior patterns including time-based analysis, 
    reporting patterns, and anomaly detection
    """
    
    since = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
    
    # Get devices to analyze
    devices_query = db.query(Device).filter(
        Device.last_seen_at >= since
    )
    
    if device_id:
        devices_query = devices_query.filter(Device.device_id == device_id)
    
    if sector_id:
        devices_query = devices_query.filter(
            Device.metadata_json['current_sector_location_id'].astext.cast(Integer) == sector_id
        )
    
    devices = devices_query.all()
    
    behavior_analysis = []
    
    for device in devices:
        # Get device's reports in time window
        device_reports = db.query(Report).filter(
            Report.device_id == device.device_id,
            Report.reported_at >= since
        ).order_by(Report.reported_at).all()
        
        if not device_reports:
            continue
        
        # Time-based pattern analysis
        hour_distribution = defaultdict(int)
        day_distribution = defaultdict(int)
        weekday_distribution = defaultdict(int)
        
        for report in device_reports:
            report_time = report.reported_at
            hour_distribution[report_time.hour] += 1
            day_distribution[report_time.day] += 1
            weekday_distribution[report_time.weekday()] += 1  # 0=Monday, 6=Sunday
        
        # Calculate pattern metrics
        total_reports = len(device_reports)
        time_span_hours = (device_reports[-1].reported_at - device_reports[0].reported_at).total_seconds() / 3600
        
        # Reporting frequency (reports per hour)
        avg_frequency = total_reports / time_span_hours if time_span_hours > 0 else total_reports
        
        # Peak activity detection
        peak_hour = max(hour_distribution.items(), key=lambda x: x[1])[0] if hour_distribution else 0
        peak_weekday = max(weekday_distribution.items(), key=lambda x: x[1])[0] if weekday_distribution else 0
        
        # Night vs Day activity (6am-6pm = day, 6pm-6am = night)
        day_reports = sum(count for hour, count in hour_distribution.items() if 6 <= hour < 18)
        night_reports = total_reports - day_reports
        day_activity_ratio = day_reports / total_reports if total_reports > 0 else 0
        
        # Weekend vs Weekday activity
        weekend_reports = sum(count for weekday, count in weekday_distribution.items() if weekday >= 5)
        weekday_reports = total_reports - weekend_reports
        weekend_activity_ratio = weekend_reports / total_reports if total_reports > 0 else 0
        
        # Geographic clustering analysis
        if len(device_reports) >= 2:
            # Calculate average distance between consecutive reports
            total_distance = 0
            max_distance = 0
            speeds = []
            
            for i in range(1, len(device_reports)):
                prev_report = device_reports[i-1]
                curr_report = device_reports[i]
                
                if prev_report.latitude and prev_report.longitude and curr_report.latitude and curr_report.longitude:
                    distance = geodesic(
                        (float(prev_report.latitude), float(prev_report.longitude)),
                        (float(curr_report.latitude), float(curr_report.longitude))
                    ).kilometers                  
                    time_diff = (curr_report.reported_at - prev_report.reported_at).total_seconds() / 3600
                    
                    total_distance += distance
                    max_distance = max(max_distance, distance)
                    
                    if time_diff > 0:
                        speed = distance / time_diff
                        speeds.append(speed)
            
            avg_distance = total_distance / (len(device_reports) - 1) if len(device_reports) > 1 else 0
            avg_speed = sum(speeds) / len(speeds) if speeds else 0
            
            # Detect impossible speeds (>200 km/h)
            impossible_movements = sum(1 for speed in speeds if speed > 200)
        else:
            avg_distance = 0
            max_distance = 0
            avg_speed = 0
            impossible_movements = 0
        
        # Automated vs Human detection (consistent intervals)
        if len(device_reports) >= 3:
            intervals = []
            for i in range(1, len(device_reports)):
                interval = (device_reports[i].reported_at - device_reports[i-1].reported_at).total_seconds()
                intervals.append(interval)
            
            # Calculate coefficient of variation for intervals
            avg_interval = sum(intervals) / len(intervals)
            interval_variance = sum((x - avg_interval) ** 2 for x in intervals) / len(intervals)
            interval_cv = (math.sqrt(interval_variance) / avg_interval) if avg_interval > 0 else 0
            
            # Low CV suggests automated behavior
            automation_score = max(0, 100 - (interval_cv * 100))
        else:
            automation_score = 0
        
        # Night activity analysis (reports between 10 PM - 6 AM)
        night_reports = sum(1 for r in device_reports if r.reported_at.hour >= 22 or r.reported_at.hour < 6)
        night_activity_ratio = night_reports / len(device_reports) if device_reports else 0
        
        # Suspicious behavior scoring
        suspicious_score = 0
        suspicious_indicators = []
        
        if impossible_movements > 0:
            suspicious_score += 30
            suspicious_indicators.append(f"Impossible movements: {impossible_movements}")
        
        if automation_score > 80:
            suspicious_score += 25
            suspicious_indicators.append("Highly automated pattern")
        
        if avg_frequency > 10:  # More than 10 reports per hour
            suspicious_score += 20
            suspicious_indicators.append("High frequency reporting")
        
        if night_activity_ratio > 0.8:  # Mostly night activity
            suspicious_score += 15
            suspicious_indicators.append("Predominantly night activity")
        
        if max_distance > 100:  # Very large movements
            suspicious_score += 10
            suspicious_indicators.append("Large geographic movements")
        
        behavior_analysis.append({
            'device_id': device.device_id,
            'device_hash': device.device_hash[:8] + '...',
            'total_reports': total_reports,
            'time_span_hours': round(time_span_hours, 2),
            'avg_frequency_reports_per_hour': round(avg_frequency, 2),
            'peak_hour': peak_hour,
            'peak_weekday': peak_weekday,
            'day_activity_ratio': round(day_activity_ratio, 2),
            'weekend_activity_ratio': round(weekend_activity_ratio, 2),
            'avg_distance_km': round(avg_distance, 2),
            'max_distance_km': round(max_distance, 2),
            'avg_speed_kmh': round(avg_speed, 2),
            'impossible_movements': impossible_movements,
            'automation_score': round(automation_score, 2),
            'suspicious_score': suspicious_score,
            'suspicious_indicators': suspicious_indicators,
            'trust_score': device.device_trust_score or 0
        })
    
    # Sort by suspicious score (highest first)
    behavior_analysis.sort(key=lambda x: x['suspicious_score'], reverse=True)
    
    return {
        'time_window_hours': time_window_hours,
        'devices_analyzed': len(behavior_analysis),
        'behavior_analysis': behavior_analysis,
        'high_risk_devices': [d for d in behavior_analysis if d['suspicious_score'] > 50],
        'automated_devices': [d for d in behavior_analysis if d['automation_score'] > 80],
        'high_mobility_devices': [d for d in behavior_analysis if d['avg_distance_km'] > 50]
    }

@router.get("/speed-analysis")
def get_speed_analysis(
    current_user: Annotated[Any, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
    time_window_hours: int = Query(720, description="Time window in hours (default: 30 days)"),
    max_speed_kmh: int = Query(200, description="Maximum realistic speed in km/h"),
    sector_id: Optional[int] = Query(None, description="Filter by sector")
):
    """
    Analyze device movement speeds and detect impossible movements
    """
    
    since = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
    
    # Get devices with location history
    devices_query = db.query(Device).filter(
        Device.metadata_json.isnot(None),
        Device.last_seen_at >= since
    )
    
    if sector_id:
        devices_query = devices_query.filter(
            Device.metadata_json['current_sector_location_id'].astext.cast(Integer) == sector_id
        )
    
    devices = devices_query.all()
    
    speed_anomalies = []
    speed_statistics = {
        'total_devices': len(devices),
        'devices_with_location_history': 0,
        'total_movements_analyzed': 0,
        'impossible_movements': 0,
        'high_speed_movements': 0,
        'avg_speed_kmh': 0,
        'max_speed_kmh': 0
    }
    
    all_speeds = []
    
    for device in devices:
        metadata = device.metadata_json or {}
        location_history = metadata.get('location_history', [])
        
        if len(location_history) < 2:
            continue
        
        speed_statistics['devices_with_location_history'] += 1
        
        device_movements = []
        
        # Analyze movements in location history
        for i in range(1, len(location_history)):
            prev_location = location_history[i-1]
            curr_location = location_history[i]
            
            if ('latitude' not in prev_location or 'longitude' not in prev_location or
                'latitude' not in curr_location or 'longitude' not in curr_location):
                continue
            
            distance = haversine_distance(
                prev_location['latitude'], prev_location['longitude'],
                curr_location['latitude'], curr_location['longitude']
            )
            
            try:
                prev_time = datetime.fromisoformat(prev_location['timestamp'].replace('Z', '+00:00'))
                curr_time = datetime.fromisoformat(curr_location['timestamp'].replace('Z', '+00:00'))
                time_diff = (curr_time - prev_time).total_seconds() / 3600
            except:
                continue
            
            if time_diff <= 0:
                continue
            
            speed = distance / time_diff
            all_speeds.append(speed)
            speed_statistics['total_movements_analyzed'] += 1
            
            movement_data = {
                'device_id': device.device_id,
                'device_hash': device.device_hash[:8] + '...',
                'from_lat': prev_location['latitude'],
                'from_lng': prev_location['longitude'],
                'to_lat': curr_location['latitude'],
                'to_lng': curr_location['longitude'],
                'distance_km': round(distance, 2),
                'time_hours': round(time_diff, 2),
                'speed_kmh': round(speed, 2),
                'timestamp': curr_location['timestamp']
            }
            
            device_movements.append(movement_data)
            
            # Check for impossible movements
            if speed > max_speed_kmh:
                speed_statistics['impossible_movements'] += 1
                speed_anomalies.append({
                    **movement_data,
                    'anomaly_type': 'impossible_speed',
                    'severity': 'high' if speed > max_speed_kmh * 2 else 'medium'
                })
            
            # Check for high speeds (suspicious but possible)
            elif speed > max_speed_kmh * 0.7:
                speed_statistics['high_speed_movements'] += 1
                speed_anomalies.append({
                    **movement_data,
                    'anomaly_type': 'high_speed',
                    'severity': 'medium'
                })
        
        # Update device-level statistics
        if device_movements:
            device_avg_speed = sum(m['speed_kmh'] for m in device_movements) / len(device_movements)
            device_max_speed = max(m['speed_kmh'] for m in device_movements)
            
            speed_statistics['max_speed_kmh'] = max(speed_statistics['max_speed_kmh'], device_max_speed)
    
    # Calculate overall statistics
    if all_speeds:
        speed_statistics['avg_speed_kmh'] = round(sum(all_speeds) / len(all_speeds), 2)
        speed_statistics['max_speed_kmh'] = round(max(all_speeds), 2)
    
    # Sort anomalies by speed (highest first)
    speed_anomalies.sort(key=lambda x: x['speed_kmh'], reverse=True)
    
    return {
        'time_window_hours': time_window_hours,
        'max_speed_threshold': max_speed_kmh,
        'speed_statistics': speed_statistics,
        'speed_anomalies': speed_anomalies[:100],  # Top 100 anomalies
        'summary': {
            'devices_with_impossible_movements': len(set(a['device_id'] for a in speed_anomalies if a['anomaly_type'] == 'impossible_speed')),
            'total_impossible_movements': speed_statistics['impossible_movements'],
            'total_high_speed_movements': speed_statistics['high_speed_movements']
        }
    }

@router.get("/geographic-clustering")
def get_geographic_clustering(
    current_user: Annotated[Any, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
    time_window_hours: int = Query(720, description="Time window in hours (default: 30 days)"),
    cluster_radius_km: float = Query(1.0, description="Radius for clustering in km"),
    min_cluster_size: int = Query(3, description="Minimum devices per cluster"),
    sector_id: Optional[int] = Query(None, description="Filter by sector")
):
    """
    Find geographic clusters of devices and unusual patterns
    """
    
    since = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
    
    # Get recent reports with location data
    reports_query = db.query(Report).filter(
        Report.reported_at >= since,
        Report.latitude.isnot(None),
        Report.longitude.isnot(None)
    )
    
    if sector_id:
        sector_bounds = get_sector_bounds(db, sector_id)
        if sector_bounds:
            reports_query = reports_query.filter(
                Report.latitude >= sector_bounds['min_lat'],
                Report.latitude <= sector_bounds['max_lat'],
                Report.longitude >= sector_bounds['min_lon'],
                Report.longitude <= sector_bounds['max_lon']
            )
    
    reports = reports_query.all()
    
    # Simple clustering based on geographic proximity
    clusters = []
    processed_reports = set()
    
    for i, report in enumerate(reports):
        if report.report_id in processed_reports:
            continue
        
        # Find all reports within cluster radius
        cluster_reports = [report]
        cluster_devices = {report.device_id}
        
        for other_report in reports[i+1:]:
            if other_report.report_id in processed_reports:
                continue
            
            distance = haversine_distance(
                float(report.latitude), float(report.longitude),
                float(other_report.latitude), float(other_report.longitude)
            )
            
            if distance <= cluster_radius_km:
                cluster_reports.append(other_report)
                cluster_devices.add(other_report.device_id)
        
        # Only keep clusters with minimum devices
        if len(cluster_devices) >= min_cluster_size:
            # Calculate cluster center
            center_lat = sum(float(r.latitude) for r in cluster_reports) / len(cluster_reports)
            center_lng = sum(float(r.longitude) for r in cluster_reports) / len(cluster_reports)
            
            # Calculate cluster metrics
            incident_types = defaultdict(int)
            trust_scores = []
            
            for cluster_report in cluster_reports:
                incident_types[cluster_report.incident_type_id] += 1
                
                device = db.query(Device).filter(Device.device_id == cluster_report.device_id).first()
                if device and device.device_trust_score is not None:
                    trust_scores.append(device.device_trust_score)
            
            avg_trust_score = sum(trust_scores) / len(trust_scores) if trust_scores else 0
            
            # Calculate cluster density
            cluster_area = math.pi * (cluster_radius_km ** 2)
            report_density = len(cluster_reports) / cluster_area
            device_density = len(cluster_devices) / cluster_area
            
            clusters.append({
                'cluster_id': len(clusters) + 1,
                'center_lat': round(center_lat, 6),
                'center_lng': round(center_lng, 6),
                'radius_km': cluster_radius_km,
                'report_count': len(cluster_reports),
                'device_count': len(cluster_devices),
                'report_density_per_km2': round(report_density, 2),
                'device_density_per_km2': round(device_density, 2),
                'incident_type_diversity': len(incident_types),
                'avg_trust_score': round(avg_trust_score, 2),
                'incident_type_distribution': dict(incident_types),
                'time_span_hours': round(
                    (max(r.reported_at for r in cluster_reports) - 
                     min(r.reported_at for r in cluster_reports)).total_seconds() / 3600, 2
                ) if len(cluster_reports) > 1 else 0
            })
            
            # Mark reports as processed
            for cluster_report in cluster_reports:
                processed_reports.add(cluster_report.report_id)
    
    # Sort clusters by device count (largest first)
    clusters.sort(key=lambda x: x['device_count'], reverse=True)
    
    # Identify unusual clusters
    unusual_clusters = []
    for cluster in clusters:
        unusual_score = 0
        unusual_indicators = []
        
        if cluster['device_density_per_km2'] > 10:
            unusual_score += 30
            unusual_indicators.append("Very high device density")
        
        if cluster['avg_trust_score'] < 30:
            unusual_score += 25
            unusual_indicators.append("Low average trust score")
        
        if cluster['time_span_hours'] < 1 and cluster['report_count'] > 10:
            unusual_score += 20
            unusual_indicators.append("Rapid burst reporting")
        
        if cluster['incident_type_diversity'] == 1:
            unusual_score += 15
            unusual_indicators.append("Single incident type focus")
        
        if unusual_score > 30:
            unusual_clusters.append({
                **cluster,
                'unusual_score': unusual_score,
                'unusual_indicators': unusual_indicators
            })
    
    return {
        'time_window_hours': time_window_hours,
        'cluster_radius_km': cluster_radius_km,
        'min_cluster_size': min_cluster_size,
        'total_reports_analyzed': len(reports),
        'clusters_found': len(clusters),
        'clusters': clusters,
        'unusual_clusters': unusual_clusters,
        'summary': {
            'total_devices_in_clusters': sum(c['device_count'] for c in clusters),
            'total_reports_in_clusters': sum(c['report_count'] for c in clusters),
            'avg_cluster_size': round(sum(c['device_count'] for c in clusters) / len(clusters), 2) if clusters else 0,
            'unusual_clusters_count': len(unusual_clusters)
        }
    }

@router.get("/frequency-analysis")
def get_frequency_analysis(
    current_user: Annotated[Any, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
    time_window_hours: int = Query(720, description="Time window in hours (default: 30 days)"),
    automation_threshold: float = Query(0.2, description="CV threshold for automation detection"),
    sector_id: Optional[int] = Query(None, description="Filter by sector")
):
    """
    Analyze reporting frequency to detect automated vs human behavior
    """
    
    since = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
    
    # Get devices with sufficient reports
    devices_query = db.query(Device).filter(
        Device.last_seen_at >= since
    )
    
    if sector_id:
        devices_query = devices_query.filter(
            Device.metadata_json['current_sector_location_id'].astext.cast(Integer) == sector_id
        )
    
    devices = devices_query.all()
    
    frequency_analysis = []
    automated_devices = []
    human_devices = []
    
    for device in devices:
        # Get device's reports in time window
        device_reports = db.query(Report).filter(
            Report.device_id == device.device_id,
            Report.reported_at >= since
        ).order_by(Report.reported_at).all()
        
        if len(device_reports) < 3:  # Need at least 3 reports for frequency analysis
            continue
        
        # Calculate reporting intervals
        intervals = []
        for i in range(1, len(device_reports)):
            interval = (device_reports[i].reported_at - device_reports[i-1].reported_at).total_seconds()
            intervals.append(interval)
        
        if not intervals:
            continue
        
        # Calculate frequency statistics
        avg_interval = sum(intervals) / len(intervals)
        min_interval = min(intervals)
        max_interval = max(intervals)
        
        # Calculate coefficient of variation (CV)
        variance = sum((x - avg_interval) ** 2 for x in intervals) / len(intervals)
        std_dev = math.sqrt(variance)
        cv = (std_dev / avg_interval) if avg_interval > 0 else 0
        
        # Calculate reporting rate (reports per hour)
        time_span = (device_reports[-1].reported_at - device_reports[0].reported_at).total_seconds() / 3600
        reporting_rate = len(device_reports) / time_span if time_span > 0 else 0
        
        # Detect patterns
        is_automated = cv < automation_threshold
        is_bursting = min_interval < 60  # Less than 1 minute between reports
        is_periodic = False
        
        # Check for periodic patterns (reports at regular intervals)
        if len(intervals) >= 5:
            # Group intervals by similarity (within 10% of average)
            similar_intervals = sum(1 for interval in intervals if abs(interval - avg_interval) / avg_interval < 0.1)
            is_periodic = similar_intervals / len(intervals) > 0.7
        
        # Calculate automation confidence
        automation_confidence = 0
        if is_automated:
            automation_confidence += 40
        if is_periodic:
            automation_confidence += 30
        if is_bursting:
            automation_confidence += 20
        if reporting_rate > 5:  # More than 5 reports per hour
            automation_confidence += 10
        
        analysis_data = {
            'device_id': device.device_id,
            'device_hash': device.device_hash[:8] + '...',
            'total_reports': len(device_reports),
            'time_span_hours': round(time_span, 2),
            'reporting_rate_per_hour': round(reporting_rate, 2),
            'avg_interval_seconds': round(avg_interval, 2),
            'min_interval_seconds': round(min_interval, 2),
            'max_interval_seconds': round(max_interval, 2),
            'coefficient_of_variation': round(cv, 3),
            'is_automated': is_automated,
            'is_bursting': is_bursting,
            'is_periodic': is_periodic,
            'automation_confidence': automation_confidence,
            'trust_score': device.device_trust_score or 0
        }
        
        frequency_analysis.append(analysis_data)
        
        if automation_confidence > 70:
            automated_devices.append(analysis_data)
        elif automation_confidence < 30:
            human_devices.append(analysis_data)
    
    # Sort by automation confidence (highest first)
    frequency_analysis.sort(key=lambda x: x['automation_confidence'], reverse=True)
    
    return {
        'time_window_hours': time_window_hours,
        'automation_threshold': automation_threshold,
        'devices_analyzed': len(frequency_analysis),
        'frequency_analysis': frequency_analysis,
        'automated_devices': automated_devices,
        'human_devices': human_devices,
        'summary': {
            'total_automated_devices': len(automated_devices),
            'total_human_devices': len(human_devices),
            'automation_rate': round(len(automated_devices) / len(frequency_analysis) * 100, 2) if frequency_analysis else 0,
            'avg_reporting_rate': round(sum(d['reporting_rate_per_hour'] for d in frequency_analysis) / len(frequency_analysis), 2) if frequency_analysis else 0
        }
    }
