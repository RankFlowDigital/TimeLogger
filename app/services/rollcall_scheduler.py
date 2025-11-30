from __future__ import annotations

from datetime import datetime, timedelta
from random import choice, randint

from sqlalchemy import and_, extract
from sqlalchemy.orm import Session

from ..models import Leave, RollCall, User, WorkSession
from . import shifts as shift_service

RESPONSE_WINDOW_MINUTES = 5
MIN_GAP_MINUTES = 5
MAX_GAP_MINUTES = 16
MIN_ROLLCALLS_PER_HOUR = 1
DEFAULT_ROLLCALLS_PER_HOUR = 5
MAX_ROLLCALLS_PER_HOUR = max(MIN_ROLLCALLS_PER_HOUR, 60 // MIN_GAP_MINUTES)


def clamp_rollcall_target(value: int | None) -> int:
    try:
        parsed = int(value) if value is not None else None
    except (TypeError, ValueError):
        parsed = None

    if parsed is None:
        return DEFAULT_ROLLCALLS_PER_HOUR
    return max(MIN_ROLLCALLS_PER_HOUR, min(MAX_ROLLCALLS_PER_HOUR, parsed))


def target_from_settings(settings: dict | None) -> int:
    stored = None
    if settings:
        stored = settings.get("rollcalls_per_hour")
    return clamp_rollcall_target(stored)


def schedule_roll_calls_for_current_hour(
    db: Session,
    org_id: int,
    now: datetime | None = None,
    target_count: int | None = None,
    min_gap_minutes: int = MIN_GAP_MINUTES,
    max_gap_minutes: int = MAX_GAP_MINUTES,
) -> list[RollCall]:
    target_count = clamp_rollcall_target(target_count)

    now = now or datetime.utcnow()
    start_of_hour = now.replace(minute=0, second=0, microsecond=0)
    end_of_hour = start_of_hour + timedelta(hours=1)
    latest_allowed_start = end_of_hour - timedelta(minutes=RESPONSE_WINDOW_MINUTES)

    existing = (
        db.query(RollCall)
        .filter(
            RollCall.org_id == org_id,
            RollCall.triggered_at >= start_of_hour,
            RollCall.triggered_at < end_of_hour,
        )
        .order_by(RollCall.triggered_at.asc())
        .all()
    )
    if len(existing) >= target_count:
        return []

    active_users = _get_active_users(db, org_id, now)
    if not active_users:
        return []

    last_triggered_at = existing[-1].triggered_at if existing else None
    anchor = max(last_triggered_at or now, now)
    first_new_roll_call = last_triggered_at is None

    min_gap = timedelta(minutes=min_gap_minutes)
    max_gap = timedelta(minutes=max_gap_minutes)
    response_window = timedelta(minutes=RESPONSE_WINDOW_MINUTES)

    scheduled: list[RollCall] = []
    while len(existing) + len(scheduled) < target_count and active_users:
        if first_new_roll_call:
            target_time = anchor
            first_new_roll_call = False
        else:
            remaining_window = latest_allowed_start - anchor
            if remaining_window <= min_gap:
                break

            max_gap_allowed = min(max_gap, remaining_window)
            gap_seconds = randint(int(min_gap.total_seconds()), int(max_gap_allowed.total_seconds()))
            target_time = anchor + timedelta(seconds=gap_seconds)

        if target_time > latest_allowed_start:
            break

        user = choice(active_users)
        if _already_has_rollcall(existing + scheduled, user.id):
            active_users.remove(user)
            continue

        roll_call = RollCall(
            org_id=org_id,
            user_id=user.id,
            triggered_at=target_time,
            deadline_at=target_time + response_window,
            result="PENDING",
        )
        db.add(roll_call)
        db.flush()
        scheduled.append(roll_call)
        anchor = target_time

    db.commit()
    return scheduled


def expire_roll_calls(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    pending = (
        db.query(RollCall)
        .filter(RollCall.result == "PENDING", RollCall.deadline_at < now)
        .all()
    )
    for roll_call in pending:
        roll_call.result = "MISSED"
    if pending:
        db.commit()
    return len(pending)


def _already_has_rollcall(roll_calls: list[RollCall], user_id: int) -> bool:
    return any(rc.user_id == user_id for rc in roll_calls)


def _get_active_users(db: Session, org_id: int, now: datetime) -> list[User]:
    leave_today = (
        db.query(Leave.user_id)
        .filter(
            Leave.org_id == org_id,
            Leave.date == now.date(),
        )
        .subquery()
    )

    users = (
        db.query(User)
        .join(WorkSession, WorkSession.user_id == User.id)
        .filter(
            User.org_id == org_id,
            User.is_active.is_(True),
            WorkSession.session_type == "WORK",
            WorkSession.started_at <= now,
            WorkSession.ended_at.is_(None),
            ~User.id.in_(leave_today),
        )
        .all()
    )
    active = []
    for user in users:
        window = shift_service.get_shift_window_for_timestamp(db, user.id, now)
        if window:
            active.append(user)
    return active
