"""Vercel entrypoint for the FastAPI application."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
	sys.path.append(str(ROOT_DIR))


_migration_lock = threading.Lock()
_migration_ran = False


def _run_migrations_once() -> None:
	global _migration_ran
	if _migration_ran:
		return
	with _migration_lock:
		if _migration_ran:
			return
		from app.migration_runner import run_migrations_once
		run_migrations_once()
		_migration_ran = True


_run_migrations_once()

from app.main import app as fastapi_app

# expose ASGI app for Vercel Python runtime
app = fastapi_app
