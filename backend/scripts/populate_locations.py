"""
Script to populate locations table from Musanze GeoJSON and CSV files.
Run: python scripts/populate_locations.py
"""
import json
import csv
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from shapely.geometry import shape
from app.config import settings

# Load CSV mappings
def load_csv_mapping(file_path):
    mapping = {}
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = list(row.keys())[0]  # First column is name
            id_col = list(row.keys())[1]  # Second column is ID
            mapping[row[name]] = int(row[id_col])
    return mapping

def populate_locations():
    engine = create_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        def get_or_create_location(location_type: str, name: str, parent_id: int | None) -> int:
            existing_id = db.execute(
                text(
                    """
                    SELECT location_id
                    FROM locations
                    WHERE location_type = :type
                      AND location_name = :name
                      AND parent_location_id IS NOT DISTINCT FROM :parent_id
                    LIMIT 1
                    """
                ),
                {"type": location_type, "name": name, "parent_id": parent_id},
            ).scalar()
            if existing_id:
                return int(existing_id)

            result = db.execute(
                text(
                    """
                    INSERT INTO locations (location_type, location_name, parent_location_id, is_active)
                    VALUES (:type, :name, :parent_id, TRUE)
                    RETURNING location_id
                    """
                ),
                {"type": location_type, "name": name, "parent_id": parent_id},
            )
            new_id = int(result.scalar())
            db.commit()
            return new_id

        # Load mappings
        base_path = Path(__file__).parent.parent / "musanze"
        sector_map = load_csv_mapping(base_path / "label_map_sector.csv")
        cell_map = load_csv_mapping(base_path / "label_map_cell.csv")
        village_map = load_csv_mapping(base_path / "label_map_village.csv")

        # Load village coordinates for centroids
        village_coords = {}
        with open(base_path / "Musanze_Villages_Coordinates.csv", 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = f"{row['Sector']}|{row['Cell']}|{row['Village']}"
                village_coords[key] = {
                    'lat': float(row['Latitude']),
                    'lon': float(row['Longitude']),
                }

        # Load GeoJSON
        with open(base_path / "musanze_boundaries.geojson", 'r', encoding='utf-8') as f:
            geojson_data = json.load(f)

        # Track created locations to build hierarchy
        sector_ids = {}  # sector_name -> location_id
        cell_ids = {}    # (sector_name, cell_name) -> location_id
        village_ids = {} # (sector_name, cell_name, village_name) -> location_id

        # Step 1: Create Sectors (no parent)
        print("Creating sectors...")
        sectors = set()
        for feature in geojson_data['features']:
            sector = feature['properties']['Sector']
            if sector not in sectors:
                sectors.add(sector)
                location_id = get_or_create_location("sector", sector, None)
                sector_ids[sector] = location_id
                print(f"  Created sector: {sector} (ID: {location_id})")

        # Step 2: Create Cells (parent = sector)
        print("\nCreating cells...")
        cells = set()
        for feature in geojson_data['features']:
            sector = feature['properties']['Sector']
            cell = feature['properties']['Cell']
            key = (sector, cell)
            if key not in cells:
                cells.add(key)
                parent_id = sector_ids[sector]
                location_id = get_or_create_location("cell", cell, parent_id)
                cell_ids[key] = location_id
                print(f"  Created cell: {cell} in {sector} (ID: {location_id})")

        # Step 3: Create Villages (parent = cell) with geometry
        print("\nCreating villages with geometry...")
        for feature in geojson_data['features']:
            props = feature['properties']
            sector = props['Sector']
            cell = props['Cell']
            village = props['Village']
            
            # Get centroid from CSV
            coord_key = f"{sector}|{cell}|{village}"
            centroid = village_coords.get(coord_key, {})
            
            parent_id = cell_ids[(sector, cell)]
            
            # Skip if village already exists (resumable runs)
            existing_village_id = db.execute(
                text(
                    """
                    SELECT location_id
                    FROM locations
                    WHERE location_type = 'village'
                      AND location_name = :name
                      AND parent_location_id = :parent_id
                    LIMIT 1
                    """
                ),
                {"name": village, "parent_id": parent_id},
            ).scalar()
            if existing_village_id:
                village_ids[(sector, cell, village)] = int(existing_village_id)
                continue

            # Convert GeoJSON geometry to PostGIS; support Polygon or MultiPolygon
            geom = feature["geometry"]
            _ = shape(geom)  # validate geometry with shapely

            # Insert with PostGIS geometry
            result = db.execute(
                text("""
                    INSERT INTO locations (
                        location_type, location_name, parent_location_id,
                        geometry, centroid_lat, centroid_long, is_active
                    )
                    VALUES (
                        :type, :name, :parent_id,
                        ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geom_json), 4326))::geometry(MULTIPOLYGON, 4326),
                        :centroid_lat, :centroid_lon, TRUE
                    )
                    RETURNING location_id
                """),
                {
                    "type": "village",
                    "name": village,
                    "parent_id": parent_id,
                    "geom_json": json.dumps(geom),
                    "centroid_lat": centroid.get('lat'),
                    "centroid_lon": centroid.get('lon'),
                }
            )
            location_id = result.scalar()
            db.commit()
            village_ids[(sector, cell, village)] = location_id
            print(f"  Created village: {village} in {cell}, {sector} (ID: {location_id})")

        print(f"\n✅ Successfully populated locations:")
        print(f"   - {len(sector_ids)} sectors")
        print(f"   - {len(cell_ids)} cells")
        print(f"   - {len(village_ids)} villages")

    except Exception as e:
        db.rollback()
        print(f"\n❌ Error: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    populate_locations()
