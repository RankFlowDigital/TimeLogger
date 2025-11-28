from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import RollCall, WorkSession
from ..services.attendance import build_summary_for_day

router = APIRouter(tags=["dashboard"])
templates = Path(__file__).resolve().parents[1] / "templates"


def _ensure_auth(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return user


def _render(request: Request, template_name: str, context: dict, status_code: int = 200) -> HTMLResponse:
    from starlette.templating import Jinja2Templates

    template = Jinja2Templates(directory=templates)
    return template.TemplateResponse(template_name, context, status_code=status_code)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_home(request: Request, db: Session = Depends(get_db)):
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    open_session = (
        db.query(WorkSession)
        .filter(WorkSession.user_id == user_session["id"], WorkSession.ended_at.is_(None))
        .one_or_none()
    )
    summary = build_summary_for_day(db, user_session["id"], date.today())

    return _render(
        request,
        "dashboard/index.html",
        {
            "request": request,
            "user": user_session,
            "open_session": open_session,
            "summary": summary,
        },
    )


@router.get("/dashboard/history", response_class=HTMLResponse)
async def dashboard_history(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    preset: str | None = None,
    db: Session = Depends(get_db),
):
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    today = date.today()
    if preset == "week":
        start = today - timedelta(days=6)
        end = today
    elif preset == "month":
        start = today - timedelta(days=29)
        end = today
    else:
        start = date.fromisoformat(start_date) if start_date else today - timedelta(days=6)
        end = date.fromisoformat(end_date) if end_date else today
    if start > end:
        start, end = end, start

    sessions = (
        db.query(WorkSession)
        .filter(
            WorkSession.user_id == user_session["id"],
            WorkSession.started_at >= datetime.combine(start, datetime.min.time()),
            WorkSession.started_at <= datetime.combine(end, datetime.max.time()),
        )
        .order_by(WorkSession.started_at.desc())
        .all()
    )

    unique_days = sorted({s.started_at.date() for s in sessions if s.started_at})
    daily_summaries = [
        {"date": day, "summary": build_summary_for_day(db, user_session["id"], day)}
        for day in unique_days
    ]

    return _render(
        request,
        "dashboard/history.html",
        {
            "request": request,
            "user": user_session,
            "sessions": sessions,
            "daily_summaries": daily_summaries,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    )


@router.get("/dashboard/profile", response_class=HTMLResponse)
async def dashboard_profile(request: Request, target_date: str | None = None, db: Session = Depends(get_db)):
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    day = date.fromisoformat(target_date) if target_date else date.today()
    summary = build_summary_for_day(db, user_session["id"], day)
    sessions = (
        db.query(WorkSession)
        .filter(
            WorkSession.user_id == user_session["id"],
            WorkSession.started_at >= datetime.combine(day, datetime.min.time()),
            WorkSession.started_at <= datetime.combine(day, datetime.max.time()),
        )
        .order_by(WorkSession.started_at.asc())
        .all()
    )
    roll_calls = (
        db.query(RollCall)
        .filter(
            RollCall.user_id == user_session["id"],
            RollCall.triggered_at >= datetime.combine(day, datetime.min.time()),
            RollCall.triggered_at <= datetime.combine(day, datetime.max.time()),
        )
        .order_by(RollCall.triggered_at.asc())
        .all()
    )

    return _render(
        request,
        "dashboard/profile.html",
        {
            "request": request,
            "user": user_session,
            "target_date": day.isoformat(),
            "summary": summary,
            "sessions": sessions,
            "roll_calls": roll_calls,
        },
    )
