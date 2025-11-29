from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import WorkSession
from ..schemas.session import SessionStart

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
templates = Path(__file__).resolve().parents[1] / "templates"


def _require_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _close_open_session(db: Session, user_id: int, session_type: str | None = None):
    query = db.query(WorkSession).filter(WorkSession.user_id == user_id, WorkSession.ended_at.is_(None))
    if session_type:
        query = query.filter(WorkSession.session_type == session_type)
    sessions = query.all()
    now = datetime.utcnow()
    for session in sessions:
        session.ended_at = now
    if sessions:
        db.commit()


def _start_session(db: Session, user: dict, session_type: str, task_description: str | None = None) -> WorkSession:
    session = WorkSession(
        org_id=user["org_id"],
        user_id=user["id"],
        started_at=datetime.utcnow(),
        session_type=session_type,
        task_description=task_description,
        source="UI",
    )
    db.add(session)
    db.commit()
    return session


def _today_window() -> tuple[datetime, datetime]:
    now = datetime.utcnow()
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=1)
    return start, end


def _total_break_minutes(db: Session, user_id: int) -> int:
    start, end = _today_window()
    sessions = (
        db.query(WorkSession)
        .filter(
            WorkSession.user_id == user_id,
            WorkSession.session_type == "SHORT_BREAK",
            WorkSession.started_at >= start,
            WorkSession.started_at < end,
        )
        .all()
    )
    total = 0
    for session in sessions:
        finish = session.ended_at or datetime.utcnow()
        total += max(0, int((finish - session.started_at).total_seconds() // 60))
    return total


@router.post("/start")
async def start_work(
    request: Request,
    payload: SessionStart | None = Body(default=None),
    db: Session = Depends(get_db),
):
    user = _require_user(request)
    _close_open_session(db, user["id"])
    session = _start_session(db, user, "WORK", payload.task_description if payload else None)
    return JSONResponse({"status": "started", "session_id": session.id})


@router.post("/stop")
async def stop_work(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request)
    open_session = (
        db.query(WorkSession)
        .filter(
            WorkSession.user_id == user["id"],
            WorkSession.session_type == "WORK",
            WorkSession.ended_at.is_(None),
        )
        .one_or_none()
    )
    if not open_session:
        return JSONResponse({"status": "no_active_session"})
    open_session.ended_at = datetime.utcnow()
    db.commit()
    return JSONResponse({"status": "stopped"})


@router.post("/start-lunch")
async def start_lunch(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request)
    open_work = (
        db.query(WorkSession)
        .filter(
            WorkSession.user_id == user["id"],
            WorkSession.session_type == "WORK",
            WorkSession.ended_at.is_(None),
        )
        .one_or_none()
    )
    if not open_work:
        raise HTTPException(status_code=400, detail="Start a work session before lunch")

    _close_open_session(db, user["id"], "WORK")
    session = _start_session(db, user, "LUNCH")
    return JSONResponse({"status": "lunch_started", "session_id": session.id})


@router.post("/end-lunch")
async def end_lunch(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request)
    open_lunch = (
        db.query(WorkSession)
        .filter(
            WorkSession.user_id == user["id"],
            WorkSession.session_type == "LUNCH",
            WorkSession.ended_at.is_(None),
        )
        .one_or_none()
    )
    if not open_lunch:
        raise HTTPException(status_code=400, detail="No lunch in progress")
    open_lunch.ended_at = datetime.utcnow()
    db.commit()
    return JSONResponse({"status": "lunch_ended"})


@router.post("/start-break")
async def start_break(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request)
    open_work = (
        db.query(WorkSession)
        .filter(
            WorkSession.user_id == user["id"],
            WorkSession.session_type == "WORK",
            WorkSession.ended_at.is_(None),
        )
        .one_or_none()
    )
    if not open_work:
        raise HTTPException(status_code=400, detail="Start a work session before taking a break")

    _close_open_session(db, user["id"], "WORK")
    session = _start_session(db, user, "SHORT_BREAK")
    return JSONResponse({"status": "break_started", "session_id": session.id})


@router.post("/end-break")
async def end_break(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request)
    open_break = (
        db.query(WorkSession)
        .filter(
            WorkSession.user_id == user["id"],
            WorkSession.session_type == "SHORT_BREAK",
            WorkSession.ended_at.is_(None),
        )
        .one_or_none()
    )
    if not open_break:
        raise HTTPException(status_code=400, detail="No break in progress")
    open_break.ended_at = datetime.utcnow()
    db.commit()
    return JSONResponse({"status": "break_ended"})
