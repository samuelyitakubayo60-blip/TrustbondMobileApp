# Location Population Script

## Purpose
Populates the `locations` table with Musanze administrative boundaries (sectors, cells, villages) from GeoJSON and CSV files.

## Prerequisites
1. Database `trustbond` exists
2. PostGIS extension is installed
3. Tables are created (run `alembic upgrade head`)

## Usage

```bash
cd backend
python scripts/populate_locations.py
```

## What it does

1. **Loads CSV mappings** (`label_map_sector.csv`, `label_map_cell.csv`, `label_map_village.csv`)
2. **Loads village coordinates** from `Musanze_Villages_Coordinates.csv` for centroids
3. **Loads GeoJSON** from `musanze_boundaries.geojson` for polygon geometries
4. **Creates hierarchy**:
   - **Sectors** (no parent)
   - **Cells** (parent = sector)
   - **Villages** (parent = cell) with PostGIS geometry polygons
5. **Stores centroids** from CSV for quick lookups

## Result

After running, the `locations` table will have:
- ~15 sectors
- ~65 cells  
- ~430 villages (with PostGIS geometry polygons)

This enables:
- Point-in-polygon queries (GPS → village lookup)
- Spatial queries for hotspot detection
- Location-based filtering for police users
