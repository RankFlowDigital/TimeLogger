from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..constants import DEVICE_TIMEZONE
from ..models import Organization, ShiftAssignment, ShiftTemplate, User

SHIFT_WORK_MINUTES = 450  # 7.5 hours
SHIFT_PAID_BREAK_MINUTES = 30
SHIFT_LUNCH_MINUTES = 60  # unpaid
SHIFT_TOTAL_WINDOW_MINUTES = SHIFT_WORK_MINUTES + SHIFT_PAID_BREAK_MINUTES + SHIFT_LUNCH_MINUTES

settings = get_settings()


@dataclass(frozen=True)
class ShiftWindow:
    shift_id: int
    assignment_id: int
    org_id: int
    user_id: int
    timezone: str
    local_start: datetime
    local_end: datetime
    start_utc: datetime
    end_utc: datetime

    def contains(self, timestamp: datetime) -> bool:
        return self.start_utc <= timestamp < self.end_utc


def get_active_shift_window(db: Session, user_id: int, reference: Optional[datetime] = None) -> Optional[ShiftWindow]:
    reference = reference or datetime.utcnow()
    windows = _windows_for_assignments(db, user_id, reference)
    for window in windows:
        if window.contains(reference):
            return window
    return None


def get_shift_windows_for_day(db: Session, user_id: int, target_date: date) -> List[ShiftWindow]:
    day_start = datetime(target_date.year, target_date.month, target_date.day)
    day_end = day_start + timedelta(days=1)
    windows = _windows_for_assignments(db, user_id, day_end)
    active: List[ShiftWindow] = []
    for window in windows:
        if window.end_utc <= day_start or window.start_utc >= day_end:
            continue
        active.append(window)
    active.sort(key=lambda w: w.start_utc)
    if not active:
        fallback = build_unassigned_window_for_day(db, user_id, target_date)
        if fallback:
            return [fallback]
    return active


def get_shift_window_for_timestamp(db: Session, user_id: int, reference: datetime) -> Optional[ShiftWindow]:
    return get_active_shift_window(db, user_id, reference)


def _windows_for_assignments(db: Session, user_id: int, reference: datetime) -> Sequence[ShiftWindow]:
    aware_reference = _as_utc(reference)
    assignments = (
        db.query(ShiftAssignment)
        .join(ShiftTemplate, ShiftAssignment.shift)
        .options(joinedload(ShiftAssignment.shift))
        .filter(ShiftAssignment.user_id == user_id)
        .all()
    )
    org_ids = {assignment.shift.org_id for assignment in assignments if assignment.shift}
    org_timezones: dict[int, str | None] = {}
    if org_ids:
        rows = (
            db.query(Organization.id, Organization.timezone)
            .filter(Organization.id.in_(org_ids))
            .all()
        )
        org_timezones = {org_id: tz for org_id, tz in rows}
    windows: list[ShiftWindow] = []
    seen_keys: set[tuple[int, datetime]] = set()
    for assignment in assignments:
        template = assignment.shift
        if not template:
            continue
        org_tz = template.timezone or org_timezones.get(template.org_id)
        tz_value = org_tz or settings.default_timezone
        tz = ZoneInfo(tz_value)
        local_reference = aware_reference.astimezone(tz)
        candidate_dates = _candidate_dates(local_reference.date(), template.day_of_week)
        for candidate in candidate_dates:
            if assignment.effective_from and candidate < assignment.effective_from:
                continue
            if assignment.effective_to and candidate > assignment.effective_to:
                continue
            window = _build_window(template, assignment, tz_value, tz, candidate)
            key = (template.id, window.start_utc)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            windows.append(window)
    return windows


def _candidate_dates(reference_date: date, target_weekday: int) -> Iterable[date]:
    delta = (reference_date.weekday() - target_weekday) % 7
    candidate = reference_date - timedelta(days=delta)
    yield candidate
    yield candidate - timedelta(days=7)
    yield candidate + timedelta(days=7)


def _build_window(
    template: ShiftTemplate,
    assignment: ShiftAssignment,
    tz_value: str,
    tz: ZoneInfo,
    candidate: date,
) -> ShiftWindow:
    start_local = datetime.combine(candidate, template.start_time, tz)
    end_local = datetime.combine(candidate, template.end_time, tz)
    if end_local <= start_local:
        end_local += timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return ShiftWindow(
        shift_id=template.id,
        assignment_id=assignment.id,
        org_id=template.org_id,
        user_id=assignment.user_id,
        timezone=tz_value,
        local_start=start_local,
        local_end=end_local,
        start_utc=start_utc,
        end_utc=end_utc,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo:
        return value.astimezone(timezone.utc)
    return value.replace(tzinfo=timezone.utc)


def describe_user_schedule(db: Session, user_id: int, days_ahead: int = 7) -> list[dict]:
    """Return upcoming shift windows as UTC timestamps for display conversions."""

    window_limit = max(1, min(31, days_ahead))
    today = date.today()
    schedule: list[dict] = []
    for offset in range(window_limit):
        target = today + timedelta(days=offset)
        for window in get_shift_windows_for_day(db, user_id, target):
            # Skip synthetic windows created for manual overrides.
            if window.assignment_id == 0:
                continue
            start_utc = _as_utc(window.start_utc)
            end_utc = _as_utc(window.end_utc)
            schedule.append(
                {
                    "start_utc": _iso_utc(start_utc),
                    "end_utc": _iso_utc(end_utc),
                    "source_timezone": window.timezone,
                }
            )
    schedule.sort(key=lambda item: item["start_utc"])
    return schedule


def _iso_utc(value: datetime) -> str:
    aware = _as_utc(value)
    return aware.isoformat().replace("+00:00", "Z")


def user_has_unassigned_access(db: Session, user_id: int) -> bool:
    return bool(
        db.query(User.allow_unassigned_sessions)
        .filter(User.id == user_id, User.allow_unassigned_sessions.is_(True))
        .scalar()
    )


def build_unassigned_window_for_day(db: Session, user_id: int, target_date: date) -> Optional[ShiftWindow]:
    if not user_has_unassigned_access(db, user_id):
        return None

    user_row = (
        db.query(User.org_id, User.timezone)
        .filter(User.id == user_id)
        .one_or_none()
    )
    if not user_row:
        return None

    org_timezone = (
        db.query(Organization.timezone)
        .filter(Organization.id == user_row.org_id)
        .scalar()
    )
    tz_value = _resolve_timezone(user_row.timezone, org_timezone)
    tz = ZoneInfo(tz_value)
    start_local = datetime.combine(target_date, datetime.min.time(), tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)

    return ShiftWindow(
        shift_id=0,
        assignment_id=0,
        org_id=user_row.org_id,
        user_id=user_id,
        timezone=tz_value,
        local_start=start_local,
        local_end=end_local,
        start_utc=start_utc,
        end_utc=end_utc,
    )


def _resolve_timezone(user_tz: Optional[str], org_tz: Optional[str]) -> str:
    if user_tz and user_tz != DEVICE_TIMEZONE:
        return user_tz
    if org_tz:
        return org_tz
    return settings.default_timezone


def can_start_within_pre_shift_window(
    db: Session,
    user_id: int,
    tolerance_minutes: int = 5,
) -> bool:
    """Return True when user has a shift starting within the tolerance window on the same day."""

    tolerance = max(0, min(30, tolerance_minutes or 0))
    if tolerance == 0:
        return False

    now_utc = datetime.utcnow()
    future_reference = now_utc + timedelta(minutes=tolerance)
    windows = _windows_for_assignments(db, user_id, future_reference)
    for window in windows:
        # Only consider real shift assignments, not manual override windows.
        if window.assignment_id == 0:
            continue
        start_utc = _as_utc(window.start_utc)
        if start_utc <= now_utc:
            continue
        minutes_until = (start_utc - now_utc).total_seconds() / 60.0
        if minutes_until <= 0 or minutes_until > tolerance:
            continue
        tz = window.local_start.tzinfo or ZoneInfo(window.timezone)
        now_local = datetime.now(tz)
        if now_local.date() != window.local_start.date():
            continue
        return True
    return False
