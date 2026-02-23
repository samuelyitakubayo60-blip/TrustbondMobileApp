"""
Point-in-polygon lookup: given (lat, lon), find the village (location_type='village')
whose geometry contains the point. Used to set report.village_location_id.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.location import Location


def get_village_location_id(db: Session, latitude: float, longitude: float) -> int | None:
    """
    Return location_id of the village containing the point (lat, lon), or None if none.
    Uses PostGIS ST_Contains with WGS84 (SRID 4326). ST_MakePoint(longitude, latitude).
    """
    q = text("""
        SELECT location_id
        FROM locations
        WHERE location_type = 'village'
          AND is_active = true
          AND geometry IS NOT NULL
          AND ST_Contains(
              geometry,
              ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
          )
        LIMIT 1
    """)
    row = db.execute(q, {"lat": latitude, "lon": longitude}).fetchone()
    return int(row[0]) if row else None


def get_village_location_info(db: Session, latitude: float, longitude: float) -> dict | None:
    """
    Return village name and parent hierarchy (cell, sector) for the point (lat, lon).
    Returns None if point is not inside any village.
    Returns dict with: location_id, village_name, cell_name (optional), sector_name (optional).
    """
    loc_id = get_village_location_id(db, latitude, longitude)
    if loc_id is None:
        return None
    village = db.query(Location).filter(Location.location_id == loc_id).first()
    if not village:
        return None
    out = {
        "location_id": loc_id,
        "village_name": village.location_name,
        "cell_name": None,
        "sector_name": None,
    }
    if village.parent_location_id:
        cell = db.query(Location).filter(Location.location_id == village.parent_location_id).first()
        if cell:
            out["cell_name"] = cell.location_name
            if cell.parent_location_id:
                sector = db.query(Location).filter(Location.location_id == cell.parent_location_id).first()
                if sector:
                    out["sector_name"] = sector.location_name
    return out
