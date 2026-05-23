"""Resolve which police station owns a geographic point (cell coverage + fallback)."""

from __future__ import annotations

import math
from typing import Optional

from sqlalchemy.orm import Session

from app.models.location import Location
from app.models.station import Station
from app.models.station_coverage import StationCoverageCell


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _cell_id_for_village(db: Session, village_location_id: int | None) -> int | None:
    if village_location_id is None:
        return None
    village = (
        db.query(Location)
        .filter(
            Location.location_id == village_location_id,
            Location.location_type == "village",
        )
        .first()
    )
    if not village or village.parent_location_id is None:
        return None
    return int(village.parent_location_id)


def station_id_for_cell(db: Session, cell_location_id: int | None) -> int | None:
    if cell_location_id is None:
        return None
    row = (
        db.query(StationCoverageCell.station_id)
        .join(Station, Station.station_id == StationCoverageCell.station_id)
        .filter(
            StationCoverageCell.cell_location_id == cell_location_id,
            Station.is_active.is_(True),
        )
        .first()
    )
    return int(row[0]) if row else None


def nearest_active_station_id(db: Session, latitude: float, longitude: float) -> int | None:
    stations = db.query(Station).filter(Station.is_active.is_(True)).all()
    best_id: int | None = None
    best_dist = float("inf")
    for st in stations:
        if st.latitude is None or st.longitude is None:
            continue
        dist = _haversine_km(
            latitude,
            longitude,
            float(st.latitude),
            float(st.longitude),
        )
        if dist < best_dist:
            best_dist = dist
            best_id = int(st.station_id)
    return best_id


def resolve_station_id(
    db: Session,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    village_location_id: int | None = None,
    location_id: int | None = None,
) -> int | None:
    """
    Determine station from village/cell coverage, else nearest station by coordinates.
    """
    cell_id = _cell_id_for_village(db, village_location_id)
    if cell_id is None and location_id is not None:
        loc = db.query(Location).filter(Location.location_id == location_id).first()
        if loc:
            if loc.location_type == "cell":
                cell_id = int(loc.location_id)
            elif loc.location_type == "village":
                cell_id = _cell_id_for_village(db, int(loc.location_id))

    station_id = station_id_for_cell(db, cell_id)
    if station_id is not None:
        return station_id

    if latitude is not None and longitude is not None:
        try:
            lat, lon = float(latitude), float(longitude)
            if abs(lat) <= 90 and abs(lon) <= 180:
                from app.core.village_lookup import get_village_location_id

                vid = get_village_location_id(db, lat, lon)
                cell_id = _cell_id_for_village(db, vid)
                station_id = station_id_for_cell(db, cell_id)
                if station_id is not None:
                    return station_id
                return nearest_active_station_id(db, lat, lon)
        except (TypeError, ValueError):
            pass
    return None
