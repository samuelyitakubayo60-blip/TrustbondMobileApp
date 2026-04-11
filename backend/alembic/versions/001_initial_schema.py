"""Initial schema - all 14 tables

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create PostGIS extension
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    
    op.create_table(
        "devices",
        sa.Column("device_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("device_hash", sa.String(255), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("total_reports", sa.Integer(), default=0),
        sa.Column("trusted_reports", sa.Integer(), default=0),
        sa.Column("flagged_reports", sa.Integer(), default=0),
        sa.Column("device_trust_score", sa.Numeric(5, 2), default=50.00),
    )
    op.create_index("ix_devices_device_hash", "devices", ["device_hash"], unique=True)

    op.create_table(
        "incident_types",
        sa.Column("incident_type_id", sa.SmallInteger(), autoincrement=True, primary_key=True),
        sa.Column("type_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("severity_weight", sa.Numeric(3, 2), default=1.00),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Create locations table with PostGIS GEOMETRY
    op.execute("""
        CREATE TABLE locations (
            location_id SERIAL PRIMARY KEY,
            location_type VARCHAR(20) NOT NULL,
            location_name VARCHAR(100) NOT NULL,
            parent_location_id INTEGER REFERENCES locations(location_id),
            geometry geometry(MULTIPOLYGON, 4326),
            centroid_lat NUMERIC(10, 7),
            centroid_long NUMERIC(10, 7),
            is_active BOOLEAN DEFAULT TRUE
        )
    """)

    op.create_table(
        "reports",
        sa.Column("report_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("incident_type_id", sa.SmallInteger(), sa.ForeignKey("incident_types.incident_type_id"), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("gps_accuracy", sa.Numeric(6, 2)),
        sa.Column("motion_level", sa.String(20)),
        sa.Column("movement_speed", sa.Numeric(6, 2)),
        sa.Column("was_stationary", sa.Boolean()),
        sa.Column("village_location_id", sa.Integer(), sa.ForeignKey("locations.location_id")),
        sa.Column("reported_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("rule_status", sa.String(20), default="pending"),
        sa.Column("is_flagged", sa.Boolean(), default=False),
        sa.Column("feature_vector", postgresql.JSONB()),
        sa.Column("ai_ready", sa.Boolean(), default=False),
        sa.Column("features_extracted", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_reports_reported_at", "reports", ["reported_at"])
    op.create_index("ix_reports_device_id", "reports", ["device_id"])
    op.create_index("ix_reports_rule_status", "reports", ["rule_status"])

    op.create_table(
        "evidence_files",
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reports.report_id"), nullable=False),
        sa.Column("file_url", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(20), nullable=False),
        sa.Column("media_latitude", sa.Numeric(10, 7)),
        sa.Column("media_longitude", sa.Numeric(10, 7)),
        sa.Column("captured_at", sa.DateTime(timezone=True)),
        sa.Column("is_live_capture", sa.Boolean(), default=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("perceptual_hash", sa.String(128)),
        sa.Column("blur_score", sa.Numeric(6, 3)),
        sa.Column("tamper_score", sa.Numeric(6, 3)),
        sa.Column("ai_quality_label", sa.String(20)),
        sa.Column("ai_checked_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "ml_predictions",
        sa.Column("prediction_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reports.report_id"), nullable=False),
        sa.Column("trust_score", sa.Numeric(5, 2)),
        sa.Column("prediction_label", sa.String(20)),
        sa.Column("model_version", sa.String(50)),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("confidence", sa.Numeric(5, 2)),
        sa.Column("explanation", postgresql.JSONB()),
        sa.Column("processing_time", sa.Integer()),
        sa.Column("model_type", sa.String(50)),
        sa.Column("is_final", sa.Boolean(), default=False),
    )

    op.create_table(
        "police_users",
        sa.Column("police_user_id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("first_name", sa.String(150), nullable=False),
        sa.Column("middle_name", sa.String(150)),
        sa.Column("last_name", sa.String(150), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone_number", sa.String(20)),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("badge_number", sa.String(50)),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("assigned_location_id", sa.Integer(), sa.ForeignKey("locations.location_id")),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_police_users_email", "police_users", ["email"], unique=True)

    op.create_table(
        "police_reviews",
        sa.Column("review_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reports.report_id"), nullable=False),
        sa.Column("police_user_id", sa.Integer(), sa.ForeignKey("police_users.police_user_id"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("review_note", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ground_truth_label", sa.String(10)),
        sa.Column("confidence_level", sa.Numeric(5, 2)),
        sa.Column("used_for_training", sa.Boolean(), default=False),
    )

    op.create_table(
        "hotspots",
        sa.Column("hotspot_id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("center_lat", sa.Numeric(10, 7), nullable=False),
        sa.Column("center_long", sa.Numeric(10, 7), nullable=False),
        sa.Column("radius_meters", sa.Numeric(8, 2), nullable=False),
        sa.Column("incident_count", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("time_window_hours", sa.Integer(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "hotspot_reports",
        sa.Column("hotspot_id", sa.Integer(), sa.ForeignKey("hotspots.hotspot_id"), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reports.report_id"), primary_key=True),
    )

    op.create_table(
        "incident_groups",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_type_id", sa.SmallInteger(), sa.ForeignKey("incident_types.incident_type_id"), nullable=False),
        sa.Column("center_lat", sa.Numeric(10, 7), nullable=False),
        sa.Column("center_long", sa.Numeric(10, 7), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("report_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "report_assignments",
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reports.report_id"), nullable=False),
        sa.Column("police_user_id", sa.Integer(), sa.ForeignKey("police_users.police_user_id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "notifications",
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("police_user_id", sa.Integer(), sa.ForeignKey("police_users.police_user_id"), nullable=False),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("related_entity_type", sa.String(50)),
        sa.Column("related_entity_id", sa.String(36)),
        sa.Column("is_read", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "audit_logs",
        sa.Column("log_id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.Integer()),
        sa.Column("action_type", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50)),
        sa.Column("entity_id", sa.String(36)),
        sa.Column("action_details", postgresql.JSONB()),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    # Drop PostGIS extension (optional - comment out if you want to keep it)
    # op.execute("DROP EXTENSION IF EXISTS postgis")
    
    op.drop_table("audit_logs")
    op.drop_table("notifications")
    op.drop_table("report_assignments")
    op.drop_table("incident_groups")
    op.drop_table("hotspot_reports")
    op.drop_table("hotspots")
    op.drop_table("police_reviews")
    op.drop_table("police_users")
    op.drop_table("ml_predictions")
    op.drop_table("evidence_files")
    op.drop_table("reports")
    op.drop_table("locations")
    op.drop_table("incident_types")
    op.drop_table("devices")
