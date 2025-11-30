from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import RollCall, User, WorkSession
from ..services.attendance import build_summary_for_day
from ..services.reporting import get_user_summary
from ..config import get_settings
from ..constants import DEVICE_TIMEZONE

router = APIRouter(tags=["dashboard"])
templates = Path(__file__).resolve().parents[1] / "templates"
settings = get_settings()


def _ensure_auth(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        return None
    if not user.get("timezone"):
        user["timezone"] = settings.default_timezone
        request.session["user"] = user
    return user


def _render(request: Request, template_name: str, context: dict, status_code: int = 200) -> HTMLResponse:
    from starlette.templating import Jinja2Templates

    template = Jinja2Templates(directory=templates)
    ctx = dict(context)
    ctx.setdefault("user", request.session.get("user"))
    ctx.setdefault("default_timezone", settings.default_timezone)
    return template.TemplateResponse(template_name, ctx, status_code=status_code)


def _to_iso(value: datetime | None) -> str | None:
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
    timezone_value = user_record.timezone or user_session.get("timezone") or settings.default_timezone
    user_session["timezone"] = timezone_value

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
    now = datetime.utcnow()
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
    org_active_roll_calls = (
        db.query(RollCall, User.full_name)
        .join(User, User.id == RollCall.user_id)
        .filter(
            RollCall.org_id == user_session["org_id"],
            RollCall.result == "PENDING",
            RollCall.triggered_at <= now,
            RollCall.deadline_at > now,
        )
        .order_by(RollCall.triggered_at.desc())
        .all()
    )
    org_roll_call_history = (
        db.query(RollCall, User.full_name)
        .join(User, User.id == RollCall.user_id)
        .filter(RollCall.org_id == user_session["org_id"])
        .order_by(RollCall.triggered_at.desc())
        .limit(12)
        .all()
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
        display_timezone = (
            "Device time"
            if member.timezone == DEVICE_TIMEZONE
            else member.timezone or settings.default_timezone
        )
        team_roster.append(
            {
                "id": member.id,
                "name": member.full_name,
                "role": member.role,
                "timezone": display_timezone,
                "status": live_session.session_type if live_session else "OFFLINE",
                "since": live_session.started_at.isoformat() if live_session else None,
            }
        )

    session_rows = []
    timeline_events = []
    work_carry_seconds = 0
    for record in sessions:
        duration_seconds = 0
        if record.ended_at:
            duration_seconds = max(0, int((record.ended_at - record.started_at).total_seconds()))
        duration_minutes = duration_seconds // 60
        session_rows.append(
            {
                "id": record.id,
                "type": record.session_type,
                "started_at": _to_iso(record.started_at),
                "ended_at": _to_iso(record.ended_at) if record.ended_at else None,
                "duration_minutes": duration_minutes,
                "source": record.source,
            }
        )
        if record.session_type == "WORK" and record.ended_at:
            work_carry_seconds += duration_seconds
        timeline_events.append(
            {
                "id": f"{record.id}-start",
                "session_id": record.id,
                "type": record.session_type,
                "phase": "start",
                "label": _event_label(record.session_type, "start"),
                "timestamp": _to_iso(record.started_at),
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
                    "timestamp": _to_iso(record.ended_at),
                }
            )

    roll_call_rows = []
    for rc in roll_calls:
        roll_call_rows.append(
            {
                "id": rc.id,
                "triggered_at": _to_iso(rc.triggered_at),
                "deadline_at": _to_iso(rc.deadline_at),
                "responded_at": _to_iso(rc.responded_at) if rc.responded_at else None,
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
                "timestamp": _to_iso(rc.triggered_at),
            }
        )

    timeline_events.sort(key=lambda entry: entry["timestamp"])

    active_roll_call_payload = [
        {
            "id": rc.id,
            "user_id": rc.user_id,
            "user_name": name,
            "result": rc.result,
            "triggered_at": _to_iso(rc.triggered_at),
            "deadline_at": _to_iso(rc.deadline_at),
            "responded_at": _to_iso(rc.responded_at),
        }
        for rc, name in org_active_roll_calls
    ]
    org_roll_call_history_payload = [
        {
            "id": rc.id,
            "user_id": rc.user_id,
            "user_name": name,
            "result": rc.result,
            "triggered_at": _to_iso(rc.triggered_at),
            "deadline_at": _to_iso(rc.deadline_at),
            "responded_at": _to_iso(rc.responded_at),
        }
        for rc, name in org_roll_call_history
    ]

    payload = {
        "user": {
            "id": user_record.id,
            "full_name": user_record.full_name,
            "role": user_record.role,
            "timezone": timezone_value,
        },
        "summary": summary.dict(),
        "server_time": _to_iso(datetime.utcnow()),
        "open_session": None,
        "sessions": session_rows,
        "roll_calls": roll_call_rows,
        "timeline_events": timeline_events,
        "team_roster": team_roster,
        "pending_roll_call": None,
        "active_roll_calls": active_roll_call_payload,
        "org_roll_call_history": org_roll_call_history_payload,
        "work_carry_seconds": work_carry_seconds,
    }
    if open_session:
        payload["open_session"] = {
            "id": open_session.id,
            "type": open_session.session_type,
            "started_at": _to_iso(open_session.started_at),
        }
    if pending_roll_call:
        payload["pending_roll_call"] = {
            "id": pending_roll_call.id,
            "triggered_at": _to_iso(pending_roll_call.triggered_at),
            "deadline_at": _to_iso(pending_roll_call.deadline_at),
        }
    return payload


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_home(request: Request, db: Session = Depends(get_db)):
    user_session = _ensure_auth(request)
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
    user_session = _ensure_auth(request)
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
    user_session = _ensure_auth(request)
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
    user_session = _ensure_auth(request)
    if not user_session:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    user_record = db.query(User).filter(User.id == user_session["id"]).one_or_none()
    if not user_record:
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

    range_start = day - timedelta(days=6)
    range_end = day
    user_report = get_user_summary(db, user_session["id"], range_start, range_end)

    return _render(
        request,
        "dashboard/profile.html",
        {
            "request": request,
            "user": user_session,
            "profile_user": user_record,
            "target_date": day.isoformat(),
            "summary": summary,
            "sessions": sessions,
            "roll_calls": roll_calls,
            "report": user_report,
            "report_start": range_start.isoformat(),
            "report_end": range_end.isoformat(),
        },
    )
