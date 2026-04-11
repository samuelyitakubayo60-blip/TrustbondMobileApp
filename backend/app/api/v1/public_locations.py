from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, aliased
from sqlalchemy import func
import json

from app.database import get_db
from app.models.location import Location
from app.schemas.location import LocationResponse

router = APIRouter(prefix="/public/locations", tags=["public"])


@router.get("/", response_model=List[LocationResponse])
def list_public_locations(
    db: Session = Depends(get_db),
    location_type: Optional[str] = Query(None, description="Filter by type: sector, cell, village"),
    parent_id: Optional[int] = Query(None, description="Filter by parent_location_id"),
    limit: int = Query(500, ge=1, le=2000),
):
    """
    Public (no-auth) endpoint for mobile clients to browse Musanze hierarchy.
    Returns centroid_lat/centroid_long for map navigation.
    """
    query = db.query(Location).filter(Location.is_active == True)
    if location_type:
        query = query.filter(Location.location_type == location_type)
    if parent_id is not None:
        query = query.filter(Location.parent_location_id == parent_id)
    query = query.order_by(Location.location_type, Location.location_name)
    return query.limit(limit).all()


@router.get("/geojson")
def locations_geojson(
    db: Session = Depends(get_db),
    location_type: Optional[str] = Query(
        "village", description="sector | cell | village"
    ),
    parent_id: Optional[int] = Query(
        None, description="Return children of this parent_location_id"
    ),
    limit: int = Query(3000, ge=1, le=10000),
) -> Dict[str, Any]:
    """
    Return a GeoJSON FeatureCollection from PostGIS geometry in `locations`.

    - For villages: includes `sector`, `cell`, `village` properties for coloring and labeling.
    - For cells: includes `sector`, `cell`.
    - For sectors: includes `sector`.
    """
    lt = (location_type or "village").strip().lower()
    if lt not in ("sector", "cell", "village"):
        lt = "village"

    # Build joins so each feature includes its full hierarchy names, and also
    # select ST_AsGeoJSON in the same query to avoid N+1 calls.
    cell = aliased(Location)
    sector = aliased(Location)

    base_filter = [
        Location.is_active == True,
        Location.location_type == lt,
        Location.geometry.isnot(None),
    ]
    if parent_id is not None:
        base_filter.append(Location.parent_location_id == parent_id)

    geojson_col = func.ST_AsGeoJSON(Location.geometry).label("geojson")

    if lt == "village":
        query = (
            db.query(
                Location,
                cell.location_name.label("cell_name"),
                sector.location_name.label("sector_name"),
                geojson_col,
            )
            .filter(*base_filter)
            .join(cell, Location.parent_location_id == cell.location_id)
            .join(sector, cell.parent_location_id == sector.location_id)
            .order_by(Location.location_name)
            .limit(limit)
        )
        rows = query.all()
        features: List[Dict[str, Any]] = []
        for loc, cell_name, sector_name, geojson_text in rows:
            if not geojson_text:
                continue
            try:
                geometry = json.loads(geojson_text)
            except Exception:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {
                        "location_id": loc.location_id,
                        "location_type": lt,
                        "sector": sector_name,
                        "cell": cell_name,
                        "village": loc.location_name,
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}

    if lt == "cell":
        query = (
            db.query(
                Location,
                sector.location_name.label("sector_name"),
                geojson_col,
            )
            .filter(*base_filter)
            .join(sector, Location.parent_location_id == sector.location_id)
            .order_by(Location.location_name)
            .limit(limit)
        )
        rows = query.all()
        features = []
        for loc, sector_name, geojson_text in rows:
            if not geojson_text:
                continue
            try:
                geometry = json.loads(geojson_text)
            except Exception:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {
                        "location_id": loc.location_id,
                        "location_type": lt,
                        "sector": sector_name,
                        "cell": loc.location_name,
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}

    # sector
    query = (
        db.query(
            Location,
            geojson_col,
        )
        .filter(*base_filter)
        .order_by(Location.location_name)
        .limit(limit)
    )
    rows = query.all()
    features = []
    for loc, geojson_text in rows:
        if not geojson_text:
            continue
        try:
            geometry = json.loads(geojson_text)
        except Exception:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "location_id": loc.location_id,
                    "location_type": lt,
                    "sector": loc.location_name,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}

