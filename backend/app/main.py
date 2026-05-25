import os
import warnings

# Before any ultralytics import: writable config dir (Docker sets YOLO_CONFIG_DIR=/app/.ultralytics)
if not os.environ.get("YOLO_CONFIG_DIR"):
    _yolo_cfg = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".ultralytics"))
    try:
        os.makedirs(_yolo_cfg, exist_ok=True)
        os.environ["YOLO_CONFIG_DIR"] = _yolo_cfg
    except OSError:
        pass

from contextlib import asynccontextmanager
from sqlalchemy import text
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import engine, Base
from app.middleware.request_logging import RequestLogMiddleware, configure_app_logging

configure_app_logging()
warnings.filterwarnings(
    "ignore",
    message="remove second argument of ws_handler",
    category=DeprecationWarning,
    module=r"websockets\.legacy\.server",
)
from app.core.workflow_schema_extensions import apply_workflow_schema_ddl
from app.models import (
    Device,
    IncidentType,
    Location,
    Report,
    EvidenceFile,
    MLPrediction,
    PoliceUser,
    Hotspot,
    ReportAssignment,
    Notification,
    AuditLog,
)
from app.api.v1 import (
    auth,
    devices,
    incident_types,
    police_users,
    reports,
    stats,
    hotspots,
    notifications,
    audit,
    locations,
    cases,
    stations,
    system_config,
    public_locations,
    public_hotspots,
    public_alerts,
    ws,
    geographic_intelligence,
    leader_auth,
    leader_reports,
    local_leaders_admin,
    deployment_decisions,
    special_assignment_units,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging

    _log = logging.getLogger(__name__)

    # ── Run Alembic migrations automatically on every startup ────────────────
    try:
        import pathlib
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_command

        _repo_root = pathlib.Path(__file__).resolve().parent.parent.parent
        _ini = _repo_root / "alembic.ini"
        _scripts = _repo_root / "backend" / "alembic"
        if _ini.exists() and _scripts.is_dir():
            _alembic_cfg = AlembicConfig(str(_ini))
            _alembic_cfg.set_main_option("script_location", str(_scripts))
            alembic_command.upgrade(_alembic_cfg, "head")
            _log.info("Alembic migrations applied (upgrade head).")
        else:
            _log.warning(
                "Alembic skipped (ini=%s exists=%s, scripts=%s exists=%s). "
                "Relying on workflow_schema_extensions DDL.",
                _ini,
                _ini.exists(),
                _scripts,
                _scripts.is_dir(),
            )
    except Exception as _mig_exc:
        _log.warning("Alembic auto-migration failed (DB may not be ready yet): %s", _mig_exc)

    # Create PostGIS extension first (required for geometry type)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.commit()

    # Align DB with ORM (ADD COLUMN IF NOT EXISTS). Required when Alembic is not in the image (HF Spaces).
    try:
        apply_workflow_schema_ddl(engine)
        from app.core.workflow_schema_extensions import ensure_hotspot_cluster_columns

        ensure_hotspot_cluster_columns(engine)
    except Exception as exc:
        _log.warning("Workflow schema DDL ensure failed (check DB permissions): %s", exc)

    try:
        from app.database import SessionLocal
        from app.core.case_station_backfill import backfill_case_station_ids

        with SessionLocal() as db:
            result = backfill_case_station_ids(db, limit=2000)
            if result.get("updated"):
                _log.info("Startup case station backfill: %s", result)
    except Exception as exc:
        _log.warning("Case station backfill on startup skipped: %s", exc)

    # Warm-up AI narrative/semantic components on startup (best-effort).
    try:
        from app.api.v1.reports import warmup_narrative_models_on_startup
        warmup_narrative_models_on_startup()
    except Exception:
        pass
    
    # Download and cache ML models on startup (optional — set PRELOAD_ML_ON_STARTUP=false on Render)
    if getattr(settings, "preload_ml_on_startup", True):
        try:
            _log.info("Preloading ML models on startup...")
            from app.core.model_manager import ensure_yolo_model

            ensure_yolo_model("yolov8n.pt")
            _log.info("YOLO model ready")
        except Exception as e:
            _log.warning("ML preload skipped or failed: %s", e)
    else:
        _log.info("ML preload disabled (PRELOAD_ML_ON_STARTUP=false); models load on first use")

    import asyncio
    from app.database import SessionLocal
    from app.models.report import Report
    from sqlalchemy import or_

    logger = _log

    async def process_existing_reports():
        """Backlog: run unified verification orchestrator on stale pending rows."""
        if not getattr(settings, "verification_startup_backlog_enabled", True):
            return
        try:
            from app.api.v1.reports import _compute_threshold_scorecard
            from app.core.verification_orchestrator import process_backlog_report

            db = SessionLocal()
            try:
                pending_reports = (
                    db.query(Report)
                    .filter(
                        or_(Report.ai_ready.is_(None), Report.ai_ready.is_(False)),
                        Report.verification_status.in_(("pending", "under_review")),
                    )
                    .limit(50)
                    .all()
                )
                logger.info("Verification backlog: %s report(s)", len(pending_reports))
                for report in pending_reports:
                    try:
                        process_backlog_report(
                            db,
                            report,
                            compute_scorecard_fn=_compute_threshold_scorecard,
                        )
                    except Exception as row_exc:
                        logger.warning(
                            "Backlog verification failed for %s: %s",
                            report.report_id,
                            row_exc,
                        )
                db.commit()
                try:
                    from app.api.v1.reports import run_auto_case_realtime

                    run_auto_case_realtime()
                except Exception as catchup_err:
                    logger.warning("Startup auto-case catch-up failed: %s", catchup_err)
            finally:
                db.close()
        except Exception as e:
            logger.error("Verification backlog error: %s", e)

    asyncio.create_task(process_existing_reports())

    _log.info(
        "TrustBond API ready (access_log=%s, preload_ml=%s)",
        getattr(settings, "request_access_log", True),
        getattr(settings, "preload_ml_on_startup", True),
    )

    yield
    # shutdown if needed


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

# Per-request access lines on stdout (complements uvicorn --access-log)
app.add_middleware(RequestLogMiddleware)

_cors_origins = settings.get_cors_origins_list()
# When no specific origins are configured, allow all via regex so that
# allow_credentials=True remains valid (allow_origins=["*"] + credentials is illegal in CORS spec).
_cors_regex = r".*" if not _cors_origins else None

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)

# Mount static files for evidence uploads
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Include API routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(devices.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(incident_types.router, prefix="/api/v1")
app.include_router(police_users.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")
app.include_router(hotspots.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(locations.router, prefix="/api/v1")
app.include_router(cases.router, prefix="/api/v1")
app.include_router(stations.router, prefix="/api/v1")
app.include_router(system_config.router, prefix="/api/v1/system-config")
app.include_router(public_locations.router, prefix="/api/v1")
app.include_router(public_hotspots.router, prefix="/api/v1")
app.include_router(public_alerts.router, prefix="/api/v1")
app.include_router(ws.router, prefix="/api/v1")
app.include_router(geographic_intelligence.router, prefix="/api/v1/geographic-intelligence")
app.include_router(leader_auth.router, prefix="/api/v1")
app.include_router(leader_reports.router, prefix="/api/v1")
app.include_router(local_leaders_admin.router, prefix="/api/v1")
app.include_router(deployment_decisions.router, prefix="/api/v1/deployment-decisions")
app.include_router(special_assignment_units.router, prefix="/api/v1/special-assignment-units")

@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}

@app.options("/health")
def health_options():
    return {"status": "ok"}
@app.get("")
def home():
    return {""}