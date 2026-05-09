"""
Add workflow columns (leader submit FK, case RIB fields) if missing.

From repo root:
  python -m scripts.ensure_workflow_leader_extensions
(from the backend directory, same as other scripts under scripts/)

Or with explicit path (still resolves imports):
  python scripts/ensure_workflow_leader_extensions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_backend_root = Path(__file__).resolve().parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from sqlalchemy import create_engine, text

from app.config import settings
from app.core.workflow_schema_extensions import (
    DDL_STATEMENTS,
    LEADER_VERIFIED_BACKFILL_SQL,
)


def main() -> None:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    with engine.begin() as conn:
        for s in DDL_STATEMENTS:
            conn.execute(text(s))
        conn.execute(text(LEADER_VERIFIED_BACKFILL_SQL))


if __name__ == "__main__":
    main()
