import os

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
from app.core.workflow_schema_extensions import apply_workflow_schema_ddl
from app.models import (
    Device,
    IncidentType,
    Location,
    Report,
    EvidenceFile,
    MLPrediction,
    PoliceUser,
    PoliceReview,
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
    submission_guidance,
    leader_auth,
    leader_reports,
    local_leaders_admin,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging

    _log = logging.getLogger(__name__)

    # Create PostGIS extension first (required for geometry type)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.commit()

    # Align DB with ORM (ADD COLUMN IF NOT EXISTS) so deploys don't 500 before manual migrations.
    try:
        apply_workflow_schema_ddl(engine)
    except Exception as exc:
        _log.warning("Workflow schema DDL ensure failed (check DB permissions): %s", exc)

    # Warm-up AI narrative/semantic components on startup (best-effort).
    try:
        from app.api.v1.reports import warmup_narrative_models_on_startup
        warmup_narrative_models_on_startup()
    except Exception:
        pass
    
    # Download and cache ML models on startup
    try:
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info("Downloading and caching ML models on startup...")
        
        # Ensure sentence transformer model is available
        from app.core.model_manager import ensure_sentence_transformer_model
        semantic_model = ensure_sentence_transformer_model("all-MiniLM-L6-v2")
        logger.info(f"Sentence transformer model loaded: {semantic_model}")
        
        # Ensure YOLO model is available (will be downloaded by ultralytics on first use)
        from app.core.model_manager import ensure_yolo_model
        yolo_model = ensure_yolo_model("yolov8n.pt")
        logger.info("YOLO model ready for use")
        
        logger.info("ML models successfully downloaded and cached")
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to preload some ML models: {e}")
        logger.info("Models will be downloaded on first use")

    # Process existing pending reports through AI on startup
    import asyncio
    import logging
    from app.utils.ml_evaluator import ml_evaluator
    from app.database import SessionLocal
    from app.models.report import Report
    from sqlalchemy import or_
    from datetime import datetime, timezone
    
    logger = logging.getLogger(__name__)
    
    async def process_existing_reports():
        """Process existing reports that haven't been AI-evaluated"""
        try:
            logger.info("Processing existing reports through AI automation...")
            
            db = SessionLocal()
            try:
                # Get reports that haven't been processed by AI
                pending_reports = db.query(Report).filter(
                    or_(
                        Report.ai_ready.is_(None),
                        Report.ai_ready == False
                    ),
                    Report.verification_status.in_(['pending', 'under_review'])
                ).limit(50).all()
                
                logger.info(f"Found {len(pending_reports)} reports to process through AI")
                
                for report in pending_reports:
                    # Never auto-promote reports that were already rule-flagged/rejected.
                    current_rule_status = (report.rule_status or "").strip().lower()
                    if current_rule_status in {"flagged", "rejected"}:
                        report.verification_status = (
                            "rejected" if current_rule_status == "rejected" else "under_review"
                        )
                        report.status = "rejected" if current_rule_status == "rejected" else "pending"
                        continue

                    # Run ML evaluation
                    ml_result = ml_evaluator.evaluate_report(report)
                    trust_score = float(ml_result['trust_score'])
                    
                    # Update report with AI results
                    report.feature_vector = {
                        'trust_score': trust_score,
                        'prediction_label': ml_result['prediction_label'],
                        'confidence': float(ml_result['confidence']),
                        'reasoning': ml_result['reasoning']
                    }
                    report.ai_ready = True
                    report.features_extracted_at = datetime.now(timezone.utc)
                    
                    # Auto-verify high-trust reports, auto-reject low-trust
                    if trust_score >= 70.0:
                        report.verification_status = 'verified'
                        report.status = 'verified'
                        report.rule_status = 'passed'
                        logger.info(f"Auto-verified report {report.report_id} (trust: {trust_score})")
                    elif trust_score < 30.0:
                        report.verification_status = 'rejected'
                        report.status = 'rejected'
                        report.rule_status = 'failed'
                        logger.info(f"Auto-rejected report {report.report_id} (trust: {trust_score})")
                    else:
                        report.verification_status = 'under_review'
                        report.rule_status = 'pending'
                
                db.commit()
                
                # Auto-case/hotspot creation runs on live report/review events.
                # Startup stays focused on AI backlog hydration for older pending rows.
                # Safety catch-up: process already-verified unlinked reports once per startup.
                try:
                    from app.api.v1.reports import run_auto_case_realtime
                    run_auto_case_realtime()
                    logger.info("Startup auto-case catch-up completed")
                except Exception as catchup_err:
                    logger.warning(f"Startup auto-case catch-up failed: {catchup_err}")
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error processing existing reports: {e}")
    
    # Process existing reports in background
    asyncio.create_task(process_existing_reports())
    
    yield
    # shutdown if needed


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)
# Debug: Log the actual CORS origins being used
cors_origins = settings.get_cors_origins_list()
print(f"DEBUG: CORS origins loaded: {cors_origins}")
print(f"DEBUG: FRONTEND_URL setting: {settings.frontend_url}")
print(f"DEBUG: cors_origins setting: {settings.cors_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins_list(),  # Dynamic origins from environment
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,  # Allow credentials with specific origins
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,  # Cache preflight for 10 minutes
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
app.include_router(submission_guidance.router, prefix="/api/v1")
app.include_router(leader_auth.router, prefix="/api/v1")
app.include_router(leader_reports.router, prefix="/api/v1")
app.include_router(local_leaders_admin.router, prefix="/api/v1")

@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}

@app.options("/health")
def health_options():
    return {"status": "ok"}
@app.get("")
def home():
    return {""}