from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Leave, Organization, Shift, User, WorkSession
from ..services import rollcall_scheduler
from ..config import get_settings

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Path(__file__).resolve().parents[1] / "templates"
settings = get_settings()


def _get_admin(request: Request, db: Session) -> tuple[dict | None, User | None]:
    session_user = request.session.get("user")
    if not session_user:
        return None, None
    user = db.query(User).filter(User.id == session_user["id"]).one_or_none()
    if not user or user.role not in {"OWNER", "ADMIN"}:
        return session_user, None
    return session_user, user


def _render(request: Request, template_name: str, context: dict) -> HTMLResponse:
    from starlette.templating import Jinja2Templates

    template = Jinja2Templates(directory=templates)
    ctx = dict(context)
    ctx.setdefault("user", request.session.get("user"))
    ctx.setdefault("default_timezone", settings.default_timezone)
    return template.TemplateResponse(template_name, ctx)


@router.get("", response_class=HTMLResponse)
async def admin_home(request: Request, db: Session = Depends(get_db)):
    session_user, admin_user = _get_admin(request, db)
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if not admin_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    org = db.query(Organization).filter(Organization.id == admin_user.org_id).one()
    settings = org.settings or {}
    rollcall_target = rollcall_scheduler.target_from_settings(settings)
    can_edit_rollcalls = admin_user.role == "OWNER"

    users = db.query(User).filter(User.org_id == admin_user.org_id).all()
    statuses = []
    for member in users:
        open_session = (
            db.query(WorkSession)
            .filter(WorkSession.user_id == member.id, WorkSession.ended_at.is_(None))
            .one_or_none()
        )
        if not open_session:
            statuses.append({"user": member, "status": "OFFLINE", "since": None})
        else:
            statuses.append(
                {
                    "user": member,
                    "status": open_session.session_type,
                    "since": open_session.started_at,
                }
            )
    return _render(
        request,
        "admin/users.html",
        {
            "request": request,
            "user": session_user,
            "statuses": statuses,
            "rollcall_target": rollcall_target,
            "can_edit_rollcalls": can_edit_rollcalls,
            "settings_updated": request.query_params.get("rc_updated"),
        },
    )


@router.get("/shifts", response_class=HTMLResponse)
async def shifts_page(request: Request, db: Session = Depends(get_db)):
    session_user, admin_user = _get_admin(request, db)
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if not admin_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    members = db.query(User).filter(User.org_id == admin_user.org_id).all()
    member_lookup = {member.id: member for member in members}
    shifts = (
        db.query(Shift)
        .filter(Shift.org_id == admin_user.org_id)
        .order_by(Shift.user_id, Shift.day_of_week, Shift.start_time)
        .all()
    )
    return _render(
        request,
        "admin/shifts.html",
        {
            "request": request,
            "user": session_user,
            "members": members,
            "member_lookup": member_lookup,
            "shifts": shifts,
        },
    )


@router.post("/shifts")
async def create_shift(
    request: Request,
    user_id: int = Form(...),
    day_of_week: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    db: Session = Depends(get_db),
):
    session_user, admin_user = _get_admin(request, db)
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if not admin_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    start = datetime.strptime(start_time, "%H:%M").time()
    end = datetime.strptime(end_time, "%H:%M").time()
    shift = Shift(
        org_id=admin_user.org_id,
        user_id=user_id,
        day_of_week=day_of_week,
        start_time=start,
        end_time=end,
    )
    db.add(shift)
    db.commit()
    return RedirectResponse(url="/admin/shifts", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/shifts/{shift_id}/delete")
async def delete_shift(shift_id: int, request: Request, db: Session = Depends(get_db)):
    session_user, admin_user = _get_admin(request, db)
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if not admin_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    shift = (
        db.query(Shift)
        .filter(Shift.id == shift_id, Shift.org_id == admin_user.org_id)
        .one_or_none()
    )
    if shift:
        db.delete(shift)
        db.commit()
    return RedirectResponse(url="/admin/shifts", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/leaves", response_class=HTMLResponse)
async def leaves_page(request: Request, db: Session = Depends(get_db)):
    session_user, admin_user = _get_admin(request, db)
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if not admin_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    members = db.query(User).filter(User.org_id == admin_user.org_id).all()
    member_lookup = {member.id: member for member in members}
    leaves = (
        db.query(Leave)
        .filter(Leave.org_id == admin_user.org_id)
        .order_by(Leave.date.desc())
        .limit(50)
        .all()
    )
    return _render(
        request,
        "admin/leaves.html",
        {
            "request": request,
            "user": session_user,
            "members": members,
            "member_lookup": member_lookup,
            "leaves": leaves,
        },
    )


@router.post("/leaves")
async def create_leave(
    request: Request,
    user_id: int = Form(...),
    leave_date: str = Form(...),
    leave_type: str = Form(...),
    db: Session = Depends(get_db),
):
    session_user, admin_user = _get_admin(request, db)
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if not admin_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    leave = Leave(
        org_id=admin_user.org_id,
        user_id=user_id,
        date=datetime.fromisoformat(leave_date).date(),
        type=leave_type,
    )
    db.add(leave)
    db.commit()
    return RedirectResponse(url="/admin/leaves", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/settings/rollcalls")
async def update_rollcall_settings(
    request: Request,
    rollcalls_per_hour: int = Form(...),
    db: Session = Depends(get_db),
):
    session_user, admin_user = _get_admin(request, db)
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if not admin_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    if admin_user.role != "OWNER":
        return RedirectResponse(url="/admin", status_code=status.HTTP_302_FOUND)

    org = db.query(Organization).filter(Organization.id == admin_user.org_id).one()
    settings = dict(org.settings or {})
    settings["rollcalls_per_hour"] = rollcall_scheduler.clamp_rollcall_target(rollcalls_per_hour)
    org.settings = settings
    db.commit()
    return RedirectResponse(url="/admin?rc_updated=1", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/leaves/{leave_id}/delete")
async def delete_leave(leave_id: int, request: Request, db: Session = Depends(get_db)):
    session_user, admin_user = _get_admin(request, db)
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if not admin_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    leave = (
        db.query(Leave)
        .filter(Leave.id == leave_id, Leave.org_id == admin_user.org_id)
        .one_or_none()
    )
    if leave:
        db.delete(leave)
        db.commit()
    return RedirectResponse(url="/admin/leaves", status_code=status.HTTP_303_SEE_OTHER)
