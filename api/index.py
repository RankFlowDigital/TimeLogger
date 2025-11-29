"""Vercel entrypoint for the FastAPI application."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
	sys.path.append(str(ROOT_DIR))

from app.main import app as fastapi_app

# expose both names for compatibility with Vercel runtimes
app = fastapi_app
handler = fastapi_app
