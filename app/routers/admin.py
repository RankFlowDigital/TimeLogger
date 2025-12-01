from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, selectinload
from pydantic import BaseModel, Field

from ..db import get_db
from ..models import (
    ChatRoom,
    ChatRoomMember,
    ChatRoomRead,
    Deduction,
    Leave,
    Message,
    Organization,
    RollCall,
    ShiftAssignment,
    ShiftTemplate,
    User,
    WorkSession,
)
from ..services import rollcall_scheduler, shifts as shift_service
from ..config import get_settings
from ..constants import DEVICE_TIMEZONE

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Path(__file__).resolve().parents[1] / "templates"
settings = get_settings()
DAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SHORT_DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


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


def _resolve_viewer_timezone(session_user: dict, admin_user: User | None) -> str:
    candidate = None
    if admin_user and admin_user.timezone:
        candidate = admin_user.timezone
    if (not candidate or candidate == DEVICE_TIMEZONE) and session_user:
        candidate = session_user.get("timezone")
    if not candidate or candidate == DEVICE_TIMEZONE:
        candidate = settings.default_timezone
    return candidate


def _reference_date_for_weekday(target_weekday: int) -> date:
    today = date.today()
    delta = (target_weekday - today.weekday()) % 7
    return today + timedelta(days=delta)


def _format_shift_window_for_viewer(
    shift: ShiftTemplate,
    viewer_timezone: str,
    fallback_timezone: str,
) -> dict:
    base_date = _reference_date_for_weekday(shift.day_of_week)
    source_tz_value = shift.timezone or fallback_timezone or settings.default_timezone
    try:
        source_tz = ZoneInfo(source_tz_value)
    except Exception:
        source_tz = ZoneInfo(settings.default_timezone)
        source_tz_value = settings.default_timezone
    try:
        viewer_tz = ZoneInfo(viewer_timezone)
    except Exception:
        viewer_timezone = settings.default_timezone
        viewer_tz = ZoneInfo(settings.default_timezone)

    start_local = datetime.combine(base_date, shift.start_time, source_tz)
    end_local = datetime.combine(base_date, shift.end_time, source_tz)
    if end_local <= start_local:
        end_local += timedelta(days=1)

    start_view = start_local.astimezone(viewer_tz)
    end_view = end_local.astimezone(viewer_tz)

    def _label(dt: datetime) -> str:
        return dt.strftime("%I:%M %p").lstrip("0")

    return {
        "start_label": _label(start_view),
        "end_label": _label(end_view),
        "viewer_timezone": viewer_timezone,
        "source_timezone": source_tz_value,
    }


class DeleteUsersPayload(BaseModel):
    user_ids: list[int] = Field(..., min_length=1)


def _require_admin(request: Request, db: Session) -> tuple[dict, User]:
    session_user, admin_user = _get_admin(request, db)
    if not session_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if not admin_user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return session_user, admin_user


def _purge_user_dependencies(db: Session, org_id: int, user_ids: list[int]) -> None:
    if not user_ids:
        return
    db.query(WorkSession).filter(WorkSession.org_id == org_id, WorkSession.user_id.in_(user_ids)).delete(synchronize_session=False)
    assignments = (
        db.query(ShiftAssignment)
        .join(ShiftTemplate, ShiftAssignment.shift_id == ShiftTemplate.id)
        .filter(ShiftTemplate.org_id == org_id, ShiftAssignment.user_id.in_(user_ids))
        .all()
    )
    for assignment in assignments:
        db.delete(assignment)
    db.query(RollCall).filter(RollCall.org_id == org_id, RollCall.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(Leave).filter(Leave.org_id == org_id, Leave.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(Deduction).filter(Deduction.org_id == org_id, Deduction.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(Message).filter(Message.org_id == org_id, Message.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(ChatRoomMember).filter(ChatRoomMember.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(ChatRoomRead).filter(ChatRoomRead.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(ChatRoomMember).filter(ChatRoomMember.added_by.in_(user_ids)).update({ChatRoomMember.added_by: None}, synchronize_session=False)
    db.query(ChatRoom).filter(ChatRoom.created_by.in_(user_ids)).update({ChatRoom.created_by: None}, synchronize_session=False)


def _shift_duration_minutes(start_time, end_time) -> int:
    today = date.today()
    start_dt = datetime.combine(today, start_time)
    end_dt = datetime.combine(today, end_time)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return int((end_dt - start_dt).total_seconds() // 60)


def _handle_user_deletion(db: Session, admin_user: User, requested_ids: list[int]) -> dict:
    candidate_ids = sorted({user_id for user_id in requested_ids if isinstance(user_id, int) and user_id > 0})
    if not candidate_ids:
        return {"removed": [], "message": "No valid users selected."}

    users = (
        db.query(User)
        .filter(User.org_id == admin_user.org_id, User.id.in_(candidate_ids))
        .all()
    )
    found_ids = {user.id for user in users}
    not_found = sorted(set(candidate_ids) - found_ids)

    protected = {
        "self": [],
        "owner": [],
    }
    removable = []
    for user in users:
        if user.id == admin_user.id:
            protected["self"].append(user.id)
            continue
        if user.role == "OWNER":
            protected["owner"].append(user.id)
            continue
        removable.append(user)

    removed_ids = [user.id for user in removable]
    if removed_ids:
        _purge_user_dependencies(db, admin_user.org_id, removed_ids)
        for user in removable:
            db.delete(user)
        db.commit()

    message_parts: list[str] = []
    if removed_ids:
        message_parts.append(f"Removed {len(removed_ids)} user(s).")
    if protected["self"]:
        message_parts.append("Skipped removing your own account.")
    if protected["owner"]:
        message_parts.append("Organization owners cannot be removed.")
    if not_found:
        message_parts.append("Some users were not found.")

    return {
        "removed": removed_ids,
        "protected": {k: v for k, v in protected.items() if v},
        "not_found": not_found,
        "message": " ".join(message_parts) or "No users were removed.",
    }


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


@router.post("/users/delete")
async def delete_users(payload: DeleteUsersPayload, request: Request, db: Session = Depends(get_db)):
    _, admin_user = _require_admin(request, db)
    result = _handle_user_deletion(db, admin_user, payload.user_ids)
    if result.get("removed"):
        return result
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("message") or "No users removed")


@router.get("/shifts", response_class=HTMLResponse)
async def shifts_page(request: Request, db: Session = Depends(get_db)):
    session_user, admin_user = _get_admin(request, db)
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if not admin_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    org = db.query(Organization).filter(Organization.id == admin_user.org_id).one()
    members = (
        db.query(User)
        .filter(User.org_id == admin_user.org_id)
        .order_by(User.full_name.asc())
        .all()
    )
    shifts = (
        db.query(ShiftTemplate)
        .options(selectinload(ShiftTemplate.assignments).selectinload(ShiftAssignment.user))
        .filter(ShiftTemplate.org_id == admin_user.org_id)
        .order_by(ShiftTemplate.day_of_week, ShiftTemplate.start_time)
        .all()
    )

    viewer_timezone = _resolve_viewer_timezone(session_user, admin_user)
    org_timezone = org.timezone or settings.default_timezone

    shift_display_map: dict[int, dict] = {}
    for shift in shifts:
        shift_display_map[shift.id] = _format_shift_window_for_viewer(
            shift,
            viewer_timezone,
            org_timezone,
        )

    member_shift_map: dict[int, list[str]] = {member.id: [] for member in members}
    for shift in shifts:
        display = shift_display_map.get(shift.id)
        if display:
            label = (
                f"{DAY_LABELS[shift.day_of_week]} "
                f"{display['start_label']} – {display['end_label']}"
                f" ({display['viewer_timezone']})"
            )
        else:
            label = f"{DAY_LABELS[shift.day_of_week]} {shift.start_time.strftime('%H:%M')}–{shift.end_time.strftime('%H:%M')}"
        for assignment in shift.assignments:
            member_shift_map.setdefault(assignment.user_id, []).append(label)
    for assignments in member_shift_map.values():
        assignments.sort()

    return _render(
        request,
        "admin/shifts.html",
        {
            "request": request,
            "user": session_user,
            "members": members,
            "shifts": shifts,
            "shift_display_map": shift_display_map,
            "viewer_timezone": viewer_timezone,
            "member_shift_map": member_shift_map,
            "day_labels": DAY_LABELS,
            "shift_error": request.query_params.get("shift_error"),
            "shift_success": request.query_params.get("shift_success"),
            "shift_work_minutes": shift_service.SHIFT_WORK_MINUTES,
            "shift_break_minutes": shift_service.SHIFT_PAID_BREAK_MINUTES,
            "shift_lunch_minutes": shift_service.SHIFT_LUNCH_MINUTES,
            "shift_total_minutes": shift_service.SHIFT_TOTAL_WINDOW_MINUTES,
        },
    )


@router.post("/shifts")
async def create_shift(
    request: Request,
    user_ids: list[int] = Form(...),
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

    try:
        start = datetime.strptime(start_time, "%H:%M").time()
        end = datetime.strptime(end_time, "%H:%M").time()
    except ValueError:
        params = urlencode({"shift_error": "Invalid time format."})
        return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)

    duration = _shift_duration_minutes(start, end)
    if duration != shift_service.SHIFT_TOTAL_WINDOW_MINUTES:
        params = urlencode({"shift_error": "Shift must cover 7.5h work, 30m paid breaks, and 1h lunch (9h window)."})
        return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)

    if day_of_week < 0 or day_of_week > 6:
        params = urlencode({"shift_error": "Invalid day of week."})
        return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)

    parsed_ids: set[int] = set()
    for raw_id in user_ids:
        try:
            value = int(raw_id)
        except (TypeError, ValueError):
            continue
        if value > 0:
            parsed_ids.add(value)
    unique_user_ids = sorted(parsed_ids)
    if not unique_user_ids:
        params = urlencode({"shift_error": "Select at least one teammate."})
        return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)

    valid_users = (
        db.query(User.id)
        .filter(User.org_id == admin_user.org_id, User.id.in_(unique_user_ids))
        .all()
    )
    if len(valid_users) != len(unique_user_ids):
        params = urlencode({"shift_error": "One or more selected users are invalid."})
        return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)

    conflict = (
        db.query(User)
        .join(ShiftAssignment, ShiftAssignment.user_id == User.id)
        .join(ShiftTemplate, ShiftAssignment.shift_id == ShiftTemplate.id)
        .filter(
            User.org_id == admin_user.org_id,
            User.id.in_(unique_user_ids),
            ShiftTemplate.day_of_week == day_of_week,
            ShiftAssignment.effective_to.is_(None),
        )
        .first()
    )
    if conflict:
        params = urlencode({"shift_error": f"{conflict.full_name} already has a shift that day."})
        return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)

    org = db.query(Organization).filter(Organization.id == admin_user.org_id).one()
    user_defined_timezone = (
        admin_user.timezone
        if admin_user.timezone and admin_user.timezone != DEVICE_TIMEZONE
        else None
    )
    tz_value = user_defined_timezone or org.timezone or settings.default_timezone
    shift = ShiftTemplate(
        org_id=admin_user.org_id,
        name=f"{SHORT_DAY_LABELS[day_of_week]} {start.strftime('%H:%M')}",
        day_of_week=day_of_week,
        start_time=start,
        end_time=end,
        timezone=tz_value,
    )
    db.add(shift)
    db.flush()

    today = datetime.now(ZoneInfo(tz_value)).date()
    assignments = [
        ShiftAssignment(shift_id=shift.id, user_id=uid, effective_from=today)
        for uid in unique_user_ids
    ]
    db.add_all(assignments)
    db.commit()
    params = urlencode({"shift_success": "Shift created."})
    return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/shifts/assign")
async def assign_existing_shift(
    request: Request,
    shift_id: int = Form(...),
    user_ids: list[int] = Form(...),
    db: Session = Depends(get_db),
):
    session_user, admin_user = _get_admin(request, db)
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if not admin_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    shift = (
        db.query(ShiftTemplate)
        .filter(ShiftTemplate.id == shift_id, ShiftTemplate.org_id == admin_user.org_id)
        .one_or_none()
    )
    if not shift:
        params = urlencode({"shift_error": "Shift not found."})
        return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)

    parsed_ids: set[int] = set()
    for raw_id in user_ids:
        try:
            value = int(raw_id)
        except (TypeError, ValueError):
            continue
        if value > 0:
            parsed_ids.add(value)
    if not parsed_ids:
        params = urlencode({"shift_error": "Select at least one teammate."})
        return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)

    valid_users = (
        db.query(User.id)
        .filter(User.org_id == admin_user.org_id, User.id.in_(parsed_ids))
        .all()
    )
    if len(valid_users) != len(parsed_ids):
        params = urlencode({"shift_error": "One or more selected users are invalid."})
        return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)

    already_assigned = (
        db.query(User.full_name)
        .join(ShiftAssignment, ShiftAssignment.user_id == User.id)
        .filter(
            ShiftAssignment.shift_id == shift.id,
            ShiftAssignment.user_id.in_(parsed_ids),
            ShiftAssignment.effective_to.is_(None),
        )
        .first()
    )
    if already_assigned:
        params = urlencode({"shift_error": f"{already_assigned.full_name} is already on that shift."})
        return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)

    conflict = (
        db.query(User.full_name)
        .join(ShiftAssignment, ShiftAssignment.user_id == User.id)
        .join(ShiftTemplate, ShiftAssignment.shift_id == ShiftTemplate.id)
        .filter(
            User.org_id == admin_user.org_id,
            User.id.in_(parsed_ids),
            ShiftTemplate.day_of_week == shift.day_of_week,
            ShiftAssignment.effective_to.is_(None),
            ShiftAssignment.shift_id != shift.id,
        )
        .first()
    )
    if conflict:
        params = urlencode({"shift_error": f"{conflict.full_name} already has a shift that day."})
        return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)

    today = date.today()
    assignments = [
        ShiftAssignment(shift_id=shift.id, user_id=uid, effective_from=today)
        for uid in sorted(parsed_ids)
    ]
    db.add_all(assignments)
    db.commit()
    params = urlencode({"shift_success": f"Assigned shift to {len(assignments)} teammate(s)."})
    return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/shifts/{shift_id}/delete")
async def delete_shift(shift_id: int, request: Request, db: Session = Depends(get_db)):
    session_user, admin_user = _get_admin(request, db)
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if not admin_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    shift = (
        db.query(ShiftTemplate)
        .filter(ShiftTemplate.id == shift_id, ShiftTemplate.org_id == admin_user.org_id)
        .one_or_none()
    )
    if shift:
        db.delete(shift)
        db.commit()
    return RedirectResponse(url="/admin/shifts", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/shifts/assignments/{assignment_id}/delete")
async def delete_shift_assignment(assignment_id: int, request: Request, db: Session = Depends(get_db)):
    session_user, admin_user = _get_admin(request, db)
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if not admin_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    assignment = (
        db.query(ShiftAssignment)
        .join(ShiftTemplate, ShiftAssignment.shift_id == ShiftTemplate.id)
        .filter(ShiftAssignment.id == assignment_id, ShiftTemplate.org_id == admin_user.org_id)
        .one_or_none()
    )
    if assignment:
        db.delete(assignment)
        db.commit()
    return RedirectResponse(url="/admin/shifts", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/shifts/unassigned")
async def toggle_unassigned_access(
    request: Request,
    user_id: int = Form(...),
    action: str = Form(...),
    db: Session = Depends(get_db),
):
    session_user, admin_user = _get_admin(request, db)
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if not admin_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    if action not in {"allow", "revoke"}:
        params = urlencode({"shift_error": "Unsupported action."})
        return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)

    target = (
        db.query(User)
        .filter(User.org_id == admin_user.org_id, User.id == user_id)
        .one_or_none()
    )
    if not target:
        params = urlencode({"shift_error": "User not found."})
        return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)

    desired_state = action == "allow"
    target.allow_unassigned_sessions = desired_state
    db.commit()

    message = "Manual start enabled." if desired_state else "Manual start disabled."
    params = urlencode({"shift_success": f"{target.full_name}: {message}"})
    return RedirectResponse(url=f"/admin/shifts?{params}", status_code=status.HTTP_303_SEE_OTHER)


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
