from __future__ import annotations

from datetime import date, datetime, timedelta
from math import ceil

from sqlalchemy import and_, extract
from sqlalchemy.orm import Session

from ..models import Deduction, WorkSession
from . import shifts as shift_service
from ..schemas.session import SessionSummary

ALLOWED_LUNCH_MINUTES = 60
ALLOWED_SHORT_BREAK_MINUTES = 30


def build_summary_for_day(db: Session, user_id: int, target_date: date, *, sync_deductions: bool = True) -> SessionSummary:
    sessions = (
        db.query(WorkSession)
        .filter(
            WorkSession.user_id == user_id,
            extract("year", WorkSession.started_at) == target_date.year,
            extract("month", WorkSession.started_at) == target_date.month,
            extract("day", WorkSession.started_at) == target_date.day,
        )
        .all()
    )
    shift_windows = shift_service.get_shift_windows_for_day(db, user_id, target_date)
    summary = SessionSummary()
    session_ids = []
    org_id = sessions[0].org_id if sessions else None
    for session in sessions:
        session_ids.append(session.id)
        minutes = _minutes_in_windows(session.started_at, session.ended_at, shift_windows)
        if minutes <= 0:
            continue
        if session.session_type == "WORK":
            summary.work_minutes += minutes
        elif session.session_type == "LUNCH":
            summary.lunch_minutes += minutes
        elif session.session_type == "SHORT_BREAK":
            summary.short_break_minutes += minutes

    over_lunch = max(0, summary.lunch_minutes - ALLOWED_LUNCH_MINUTES)
    over_short = max(0, summary.short_break_minutes - ALLOWED_SHORT_BREAK_MINUTES)
    summary.overbreak_minutes = over_lunch + over_short

    rollcall_deductions = (
        db.query(Deduction)
        .filter(
            Deduction.user_id == user_id,
            Deduction.date == target_date,
            Deduction.type == "ROLLCALL",
        )
        .all()
    )
    summary.rollcall_deduction_minutes = sum(d.minutes for d in rollcall_deductions)

    raw_hours = summary.work_minutes / 60.0
    deduction_hours = (summary.overbreak_minutes + summary.rollcall_deduction_minutes) / 60.0
    summary.net_hours = max(0.0, min(8.0, raw_hours) - deduction_hours)

    if sync_deductions:
        _sync_overbreak_deduction(db, user_id, org_id, target_date, summary.overbreak_minutes, session_ids)
    return summary


def build_summary_for_range(db: Session, user_id: int, start_date: date, end_date: date) -> SessionSummary:
    """Aggregate daily summaries across a window without mutating deductions."""

    window_start = min(start_date, end_date)
    window_end = max(start_date, end_date)
    aggregate = SessionSummary()
    current = window_start
    while current <= window_end:
        daily = build_summary_for_day(db, user_id, current, sync_deductions=False)
        aggregate.work_minutes += daily.work_minutes
        aggregate.lunch_minutes += daily.lunch_minutes
        aggregate.short_break_minutes += daily.short_break_minutes
        aggregate.overbreak_minutes += daily.overbreak_minutes
        aggregate.rollcall_deduction_minutes += daily.rollcall_deduction_minutes
        aggregate.net_hours += daily.net_hours
        current += timedelta(days=1)
    # keep a predictable precision for display purposes
    aggregate.net_hours = round(aggregate.net_hours, 2)
    return aggregate


def _sync_overbreak_deduction(db: Session, user_id: int, org_id: int | None, target_date: date, minutes: int, session_ids: list[int]):
    existing = (
        db.query(Deduction)
        .filter(
            Deduction.user_id == user_id,
            Deduction.date == target_date,
            Deduction.type == "OVERBREAK",
        )
        .one_or_none()
    )
    if minutes <= 0:
        if existing:
            db.delete(existing)
            db.commit()
        return

    description = f"Overbreak accrued from sessions {session_ids}" if session_ids else "Overbreak accrued"
    if existing:
        existing.minutes = minutes
        existing.description = description
    else:
        db.add(
            Deduction(
                org_id=org_id,
                user_id=user_id,
                date=target_date,
                type="OVERBREAK",
                minutes=minutes,
                description=description,
            )
        )
    db.commit()


def create_rollcall_deduction(db: Session, *, org_id: int, user_id: int, occurred_at: datetime, delay_seconds: int, roll_call_id: int):
    minutes = ceil(delay_seconds / 60)
    deduction = Deduction(
        org_id=org_id,
        user_id=user_id,
        date=occurred_at.date(),
        type="ROLLCALL",
        minutes=minutes,
        description="Roll-call late response",
        related_roll_call_id=roll_call_id,
    )
    db.add(deduction)
    db.commit()


def _minutes_in_windows(start: datetime, end: datetime | None, windows: list[shift_service.ShiftWindow]) -> int:
    if not windows:
        return 0
    effective_end = end or datetime.utcnow()
    total = 0
    for window in windows:
        overlap_start = max(start, window.start_utc)
        overlap_end = min(effective_end, window.end_utc)
        if overlap_end <= overlap_start:
            continue
        total += max(0, int((overlap_end - overlap_start).total_seconds() // 60))
    return total
