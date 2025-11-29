from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock

from alembic import command
from alembic.config import Config

from .config import get_settings

logger = logging.getLogger(__name__)
_run_lock = Lock()
_has_run = False


def run_migrations_once() -> None:
    """Apply Alembic migrations if they haven't been executed in this process."""
    global _has_run
    if _has_run:
        return

    with _run_lock:
        if _has_run:
            return

        project_root = Path(__file__).resolve().parents[1]
        alembic_ini = project_root / "alembic.ini"
        script_location = project_root / "alembic"

        cfg = Config(str(alembic_ini))
        cfg.set_main_option("script_location", str(script_location))
        cfg.set_main_option("sqlalchemy.url", get_settings().database_url)

        logger.info("Applying database migrations...")
        command.upgrade(cfg, "head")
        _has_run = True
        logger.info("Database schema is up to date.")
