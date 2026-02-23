## TrustBond – Local setup guide
This is a **full project** with:

- `backend/` – FastAPI + PostgreSQL/PostGIS API
- `frontend/` – React + Vite Police Dashboard
- `mobile/` – Flutter citizen mobile app

Follow these steps in order: **database → backend → frontend → mobile**.

---

### 1. Prerequisites

- **PostgreSQL** with **PostGIS** extension (database name: `trustbond` is assumed)
- **Python** 3.11+ and `pip`
- **Node.js** (LTS) and `npm`
- **Flutter SDK** (for the `mobile/` app)

---

### 2. Backend – API + database

#### 2.1 Install dependencies

```bash
cd backend
python -m venv .venv
Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

#### 2.2 Configure environment

Create `backend/.env`:

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/trustbond
SECRET_KEY=change-me-to-a-long-random-string

# Optional but recommended for production:
# CORS_ORIGINS=https://your-dashboard-url
```

See `backend/SYSTEM_SETTINGS.md` for all available settings.

#### 2.3 Create tables and seed initial data

There are **two key tables** that must be populated before using the system:

- `incident_types` – types of incidents (Theft, Assault, etc.)
- `locations` – Musanze sectors, cells, villages with polygons

Run the init script once:

```bash
cd backend
python scripts/init_db.py
```

This script will:

1. Ensure **PostGIS** extension exists.
2. Run **Alembic migrations** (`alembic upgrade head`) to create all tables.
3. **Seed `incident_types`** (using `scripts/seed_incident_types.py`).
4. **Populate `locations`** (using `scripts/populate_locations.py` and the GeoJSON/CSV files).

You can re-run this script safely; it skips existing data when appropriate.

**Optional – sample data (1 device, 1 report, 3 evidence rows):**

```bash
psql -U postgres -d trustbond -f backend/scripts/seed_one_device_report_evidence.sql
```

Evidence URLs are placeholders; you can update them later with `UPDATE evidence_files SET file_url = '...' WHERE evidence_id = '...';`

#### 2.4 Run the backend

```bash
cd backend
uvicorn app.main:app --reload
```

API will be available at:

- Swagger docs: `http://localhost:8000/docs`
- Base URL: `http://localhost:8000/api/v1`

**How the API is used**

- Mobile app calls `…/api/v1/devices`, `…/api/v1/reports`, `…/api/v1/incident-types`.
- Police Dashboard calls `…/api/v1/auth`, `…/api/v1/reports`, `…/api/v1/hotspots`, etc.
- CORS is configured via `CORS_ORIGINS` in `.env`.

---

### 3. Frontend – Police Dashboard (React/Vite)

#### 3.1 Install dependencies

```bash
cd frontend
npm install
```

#### 3.2 Configure API URL

The dashboard uses `VITE_API_BASE_URL` to talk to the backend.

For local development:

```bash
cd frontend
npm run dev
```

Then open the printed URL (usually `http://localhost:5173`).

#### 3.3 Summary

- Dashboard login and all API calls go to `VITE_API_BASE_URL`.
- Backend and frontend can run on different ports; CORS must allow the frontend origin.

---

### 4. Mobile – Flutter app

> Make sure the backend is running and reachable (directly or via ngrok) before testing the app.

#### 4.1 Configure API URL

API URL is controlled by `API_BASE_URL` in `mobile/lib/config/api_config.dart`:

- Default: `http://localhost:8000/api/v1`
- For **real device** over ngrok, run Flutter with:

```bash
cd mobile
flutter run --dart-define=API_BASE_URL=https://YOUR_NGROK_URL/api/v1
```

This makes all mobile API calls go to `https://YOUR_NGROK_URL/api/v1`.

#### 4.2 Install dependencies & run

```bash
cd mobile
flutter pub get
flutter run
```

Select a simulator/emulator or a physical device.

#### 4.3 What the mobile app does

- **Registers the device** (`/devices/register`) the first time you open it.
- Allows citizens to **submit reports** with:
  - incident type
  - description
  - GPS location
  - evidence (photos/videos)
- Shows **“My Reports”** for that device (`/reports?device_id=…`) and lets the user:
  - view details and existing evidence
  - **add more evidence later** (within a time window, default 72h).

---

### 5. Quick start checklist

1. **PostgreSQL + PostGIS** installed; database `trustbond` created.
2. `backend/.env` configured with `DATABASE_URL` and `SECRET_KEY`.
3. From `backend/`:
   - `python -m venv .venv && source .venv/bin/activate`
   - `pip install -r requirements.txt`
   - `python scripts/init_db.py`
   - `uvicorn app.main:app --reload`
4. From `frontend/`:
   - `npm install`
   - `npm run dev`
5. From `mobile/`:
   - `flutter pub get`
   - `flutter run`

After that:

- Citizens can use the **mobile app** to send reports.
- Police can use the **dashboard** to log in, see reports, hotspots, and manage assignments/reviews.

