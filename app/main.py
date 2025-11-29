import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from .config import get_settings
from .migration_runner import run_migrations_once
from .routers import (
    admin,
    auth,
    chat,
    dashboard,
    reports,
    roll_calls,
    sessions,
    users,
)

settings = get_settings()
base_path = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, session_cookie=settings.session_cookie)
app.mount("/static", StaticFiles(directory=base_path / "static"), name="static")
templates = Jinja2Templates(directory=base_path / "templates")


@app.get("/")
async def root(request: Request):
    user = request.session.get("user")
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url="/login", status_code=302)


@app.on_event("startup")
async def ensure_schema() -> None:
    try:
        run_migrations_once()
    except Exception as exc:  # pragma: no cover - startup failures should surface
        logger.exception("Database migration failed")
        raise


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(roll_calls.router)
app.include_router(admin.router)
app.include_router(reports.router)
app.include_router(users.router)
