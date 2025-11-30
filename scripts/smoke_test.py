#!/usr/bin/env python
"""CI smoke test to catch migration or connectivity issues before deployment."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from app.db import SessionLocal  # noqa: E402  (import after sys.path tweak)


def _verify_migration_state() -> None:
    cfg = Config(str(ROOT_DIR / "alembic.ini"))
    command.current(cfg)


def _verify_database() -> None:
    with SessionLocal() as session:
        session.execute(text("SELECT 1 FROM organizations LIMIT 1"))


def main() -> int:
    try:
        _verify_migration_state()
        _verify_database()
    except Exception as exc:
        print(f"[smoke_test] failure: {exc}", file=sys.stderr)
        return 1
    print("[smoke_test] passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
