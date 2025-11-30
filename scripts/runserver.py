#!/usr/bin/env python
"""Utility script for container deployments.

When RUN_DB_MIGRATIONS=1 the script applies Alembic migrations
before launching the ASGI server (Uvicorn by default).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, cwd=PROJECT_ROOT)


def _maybe_run_migrations() -> None:
    if os.getenv("RUN_DB_MIGRATIONS") != "1":
        return
    print("[runserver] RUN_DB_MIGRATIONS=1 detected. Applying migrations...", flush=True)
    _run(["alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"])


def _server_command() -> list[str]:
    configured = os.getenv("RUNSERVER_CMD")
    if configured:
        return shlex.split(configured)
    host = os.getenv("HOST", "0.0.0.0")
    port = os.getenv("PORT", "8000")
    return [
        "uvicorn",
        "app.main:app",
        "--host",
        host,
        "--port",
        port,
    ]


def main() -> int:
    try:
        _maybe_run_migrations()
        command = _server_command()
        print(f"[runserver] Starting server: {' '.join(command)}", flush=True)
        subprocess.run(command, check=True, cwd=PROJECT_ROOT)
    except subprocess.CalledProcessError as exc:  # bubble up non-zero exit to orchestrator
        print(f"[runserver] command failed: {exc}", file=sys.stderr)
        return exc.returncode or 1
    except Exception as exc:  # pragma: no cover - defensive belt-and-suspenders
        print(f"[runserver] unexpected error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
