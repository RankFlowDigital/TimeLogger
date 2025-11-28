from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import RollCall, User, WorkSession
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


def _day_window(target: date | None = None) -> tuple[datetime, datetime]:
    target = target or date.today()
    start = datetime.combine(target, datetime.min.time())
    end = start + timedelta(days=1)
    return start, end


def _event_label(session_type: str, phase: str) -> str:
    mapping = {
        ("WORK", "start"): "Start Work",
        ("WORK", "end"): "Stop Work",
        ("LUNCH", "start"): "Start Lunch",
        ("LUNCH", "end"): "End Lunch",
        ("SHORT_BREAK", "start"): "Start Break",
        ("SHORT_BREAK", "end"): "End Break",
    }
    return mapping.get((session_type, phase), f"{phase.title()} {session_type.title()}")


def _build_dashboard_payload(db: Session, user_session: dict) -> dict:
    user_record = db.query(User).filter(User.id == user_session["id"]).one()
    user_session.setdefault("timezone", user_record.timezone)

    summary = build_summary_for_day(db, user_session["id"], date.today())
    open_session = (
        db.query(WorkSession)
        .filter(WorkSession.user_id == user_session["id"], WorkSession.ended_at.is_(None))
        .one_or_none()
    )
    start, end = _day_window()
    sessions = (
        db.query(WorkSession)
        .filter(
            WorkSession.user_id == user_session["id"],
            WorkSession.started_at >= start,
            WorkSession.started_at < end,
        )
        .order_by(WorkSession.started_at.asc())
        .all()
    )
    roll_calls = (
        db.query(RollCall)
        .filter(
            RollCall.user_id == user_session["id"],
            RollCall.triggered_at >= start,
            RollCall.triggered_at < end,
        )
        .order_by(RollCall.triggered_at.asc())
        .all()
    )
    pending_roll_call = (
        db.query(RollCall)
        .filter(
            RollCall.user_id == user_session["id"],
            RollCall.result == "PENDING",
            RollCall.deadline_at > datetime.utcnow(),
        )
        .order_by(RollCall.triggered_at.desc())
        .first()
    )

    active_sessions = (
        db.query(WorkSession)
        .filter(WorkSession.org_id == user_session["org_id"], WorkSession.ended_at.is_(None))
        .all()
    )
    active_lookup = {session.user_id: session for session in active_sessions}
    roster_members = (
        db.query(User)
        .filter(User.org_id == user_session["org_id"])
        .order_by(User.full_name.asc())
        .all()
    )

    team_roster = []
    for member in roster_members:
        live_session = active_lookup.get(member.id)
        team_roster.append(
            {
                "id": member.id,
                "name": member.full_name,
                "role": member.role,
                "timezone": member.timezone,
                "status": live_session.session_type if live_session else "OFFLINE",
                "since": live_session.started_at.isoformat() if live_session else None,
            }
        )

    session_rows = []
    timeline_events = []
    for record in sessions:
        duration_minutes = 0
        if record.ended_at:
            duration_minutes = max(0, int((record.ended_at - record.started_at).total_seconds() // 60))
        session_rows.append(
            {
                "id": record.id,
                "type": record.session_type,
                "started_at": record.started_at.isoformat(),
                "ended_at": record.ended_at.isoformat() if record.ended_at else None,
                "duration_minutes": duration_minutes,
                "source": record.source,
            }
        )
        timeline_events.append(
            {
                "id": f"{record.id}-start",
                "session_id": record.id,
                "type": record.session_type,
                "phase": "start",
                "label": _event_label(record.session_type, "start"),
                "timestamp": record.started_at.isoformat(),
            }
        )
        if record.ended_at:
            timeline_events.append(
                {
                    "id": f"{record.id}-end",
                    "session_id": record.id,
                    "type": record.session_type,
                    "phase": "end",
                    "label": _event_label(record.session_type, "end"),
                    "timestamp": record.ended_at.isoformat(),
                }
            )

    roll_call_rows = []
    for rc in roll_calls:
        roll_call_rows.append(
            {
                "id": rc.id,
                "triggered_at": rc.triggered_at.isoformat(),
                "deadline_at": rc.deadline_at.isoformat(),
                "responded_at": rc.responded_at.isoformat() if rc.responded_at else None,
                "result": rc.result,
                "delay_seconds": rc.response_delay_seconds,
            }
        )
        timeline_events.append(
            {
                "id": f"rollcall-{rc.id}",
                "type": "ROLL_CALL",
                "phase": rc.result,
                "label": f"Roll-call {rc.result.title()}",
                "timestamp": rc.triggered_at.isoformat(),
            }
        )

    timeline_events.sort(key=lambda entry: entry["timestamp"])

    payload = {
        "user": {
            "id": user_record.id,
            "full_name": user_record.full_name,
            "role": user_record.role,
            "timezone": user_record.timezone,
        },
        "summary": summary.dict(),
        "server_time": datetime.utcnow().isoformat(),
        "open_session": None,
        "sessions": session_rows,
        "roll_calls": roll_call_rows,
        "timeline_events": timeline_events,
        "team_roster": team_roster,
        "pending_roll_call": None,
    }
    if open_session:
        payload["open_session"] = {
            "id": open_session.id,
            "type": open_session.session_type,
            "started_at": open_session.started_at.isoformat(),
        }
    if pending_roll_call:
        payload["pending_roll_call"] = {
            "id": pending_roll_call.id,
            "triggered_at": pending_roll_call.triggered_at.isoformat(),
            "deadline_at": pending_roll_call.deadline_at.isoformat(),
        }
    return payload


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_home(request: Request, db: Session = Depends(get_db)):
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    payload = _build_dashboard_payload(db, user_session)

    return _render(
        request,
        "dashboard/index.html",
        {
            "request": request,
            "user": user_session,
            "dashboard_state": payload,
        },
    )


@router.get("/api/dashboard/state")
async def dashboard_state_api(request: Request, db: Session = Depends(get_db)):
    user_session = request.session.get("user")
    if not user_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = _build_dashboard_payload(db, user_session)
    return JSONResponse(payload)


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
