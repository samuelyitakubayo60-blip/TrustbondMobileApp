from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, aliased
from sqlalchemy import func

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

    # Build joins so each feature includes its full hierarchy names.
    cell = aliased(Location)
    sector = aliased(Location)

    query = db.query(Location).filter(
        Location.is_active == True,
        Location.location_type == lt,
        Location.geometry.isnot(None),
    )
    if parent_id is not None:
        query = query.filter(Location.parent_location_id == parent_id)

    if lt == "village":
        query = (
            query.join(cell, Location.parent_location_id == cell.location_id)
            .join(sector, cell.parent_location_id == sector.location_id)
            .add_columns(
                cell.location_name.label("cell_name"),
                sector.location_name.label("sector_name"),
            )
        )
    elif lt == "cell":
        query = (
            query.join(sector, Location.parent_location_id == sector.location_id)
            .add_columns(sector.location_name.label("sector_name"))
        )
    else:
        query = query.add_columns(Location.location_name.label("sector_name"))

    rows = query.order_by(Location.location_name).limit(limit).all()

    features: List[Dict[str, Any]] = []
    for row in rows:
        # Row shape depends on lt
        if lt == "village":
            loc, cell_name, sector_name = row
            props = {
                "location_id": loc.location_id,
                "location_type": lt,
                "sector": sector_name,
                "cell": cell_name,
                "village": loc.location_name,
            }
        elif lt == "cell":
            loc, sector_name = row
            props = {
                "location_id": loc.location_id,
                "location_type": lt,
                "sector": sector_name,
                "cell": loc.location_name,
            }
        else:
            loc, sector_name = row
            props = {
                "location_id": loc.location_id,
                "location_type": lt,
                "sector": sector_name,
            }

        geojson_text = db.scalar(func.ST_AsGeoJSON(loc.geometry))
        if not geojson_text:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": geojson_text if isinstance(geojson_text, dict) else None,
                "properties": props,
            }
        )

    # ST_AsGeoJSON returns a JSON string in Postgres; parse into dict via SQL side
    # by calling ST_AsGeoJSON then casting to jsonb for structured output.
    # To keep it DB-agnostic here, we re-query geometry per feature as jsonb.
    # If geometry parsing is missing, fallback to client-side parsing.
    # NOTE: We'll handle proper jsonb below in a second pass.
    if features:
        # Rebuild with jsonb geometry to ensure valid GeoJSON objects
        ids = [f["properties"]["location_id"] for f in features]
        geom_rows = db.query(
            Location.location_id,
            func.ST_AsGeoJSON(Location.geometry).label("geom"),
        ).filter(Location.location_id.in_(ids)).all()
        geom_map = {gid: g for gid, g in geom_rows}
        for f in features:
            gid = f["properties"]["location_id"]
            gtxt = geom_map.get(gid)
            try:
                import json

                f["geometry"] = json.loads(gtxt) if isinstance(gtxt, str) else gtxt
            except Exception:
                f["geometry"] = None

    # Drop any entries where geometry failed to parse
    features = [f for f in features if f.get("geometry")]

    return {"type": "FeatureCollection", "features": features}

