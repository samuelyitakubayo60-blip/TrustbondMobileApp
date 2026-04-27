"""
Compatibility entrypoint for environments that execute `python app.py`.

The actual API application lives in `backend/app/main.py`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


_MAIN_PATH = Path(__file__).resolve().parent / "backend" / "app" / "main.py"
_SPEC = importlib.util.spec_from_file_location("trustbond_backend_main", _MAIN_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load backend app from {_MAIN_PATH}")

_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

app = _MODULE.app  # FastAPI instance for ASGI servers
