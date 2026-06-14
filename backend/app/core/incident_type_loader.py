"""Load incident types via raw SQL when ORM columns lag production schema."""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.orm import Session


def fetch_incident_type_by_id(db: Session, incident_type_id: int) -> SimpleNamespace | None:
    """Return incident type row without requiring optional ORM columns (e.g. semantic_definition)."""
    row = db.execute(
        text(
            """
            SELECT incident_type_id, type_name, description, severity_weight, is_active
            FROM incident_types
            WHERE incident_type_id = :id
            """
        ),
        {"id": int(incident_type_id)},
    ).first()
    if not row:
        return None
    return SimpleNamespace(
        incident_type_id=int(row[0]),
        type_name=str(row[1] or ""),
        description=row[2],
        severity_weight=row[3],
        is_active=row[4] if row[4] is not None else True,
        semantic_definition=None,
    )


def fetch_active_incident_types(db: Session) -> list[SimpleNamespace]:
    """All active incident types for semantic / priority helpers."""
    rows = db.execute(
        text(
            """
            SELECT incident_type_id, type_name, description, severity_weight, is_active
            FROM incident_types
            WHERE is_active IS NOT FALSE
            ORDER BY incident_type_id
            """
        )
    ).fetchall()
    if not rows:
        rows = db.execute(
            text(
                """
                SELECT incident_type_id, type_name, description, severity_weight, is_active
                FROM incident_types
                ORDER BY incident_type_id
                """
            )
        ).fetchall()
    return [
        SimpleNamespace(
            incident_type_id=int(r[0]),
            type_name=str(r[1] or ""),
            description=r[2],
            severity_weight=r[3],
            is_active=r[4] if r[4] is not None else True,
            semantic_definition=None,
        )
        for r in rows
    ]


def semantic_definition_for_type(
    type_name: str,
    description: str | None,
    semantic_definition: str | None = None,
) -> str:
    """Build semantic text for embedding validation when DB column is absent."""
    semantic_def = (semantic_definition or "").strip()
    if semantic_def:
        return semantic_def
    name = (type_name or "").strip()
    desc = (description or "").strip()
    return f"{name}: {desc}" if desc else name
