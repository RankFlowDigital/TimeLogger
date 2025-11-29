from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Deduction, RollCall, User, WorkSession
from ..schemas.report import UserReport


def get_org_summary(db: Session, org_id: int, start_date: date, end_date: date) -> list[UserReport]:
    users = db.query(User).filter(User.org_id == org_id).all()
    reports: list[UserReport] = []
    for user in users:
        report = _build_user_summary(db, user, start_date, end_date)
        reports.append(report)
    return reports


def get_user_summary(db: Session, user_id: int, start_date: date, end_date: date) -> UserReport:
    """Build a report for a single user across the requested window."""
    normalized_start = min(start_date, end_date)
    normalized_end = max(start_date, end_date)
    user = db.query(User).filter(User.id == user_id).one_or_none()
    if not user:
        raise ValueError("User not found")
    return _build_user_summary(db, user, normalized_start, normalized_end)


def _build_user_summary(db: Session, user: User, start_date: date, end_date: date) -> UserReport:
    sessions = (
        db.query(WorkSession)
        .filter(
            WorkSession.user_id == user.id,
            WorkSession.started_at >= datetime.combine(start_date, datetime.min.time()),
            WorkSession.started_at <= datetime.combine(end_date, datetime.max.time()),
        )
        .all()
    )
    work_minutes = 0
    lunch_minutes = 0
    break_minutes = 0
    for session in sessions:
        if session.session_type != "WORK" or not session.started_at:
            if session.session_type == "LUNCH" and session.started_at:
                end_time = session.ended_at or datetime.utcnow()
                lunch_minutes += max(0, int((end_time - session.started_at).total_seconds() // 60))
            elif session.session_type == "SHORT_BREAK" and session.started_at:
                end_time = session.ended_at or datetime.utcnow()
                break_minutes += max(0, int((end_time - session.started_at).total_seconds() // 60))
            continue
        end_time = session.ended_at or datetime.utcnow()
        work_minutes += max(0, int((end_time - session.started_at).total_seconds() // 60))

    deductions = (
        db.query(Deduction)
        .filter(
            Deduction.user_id == user.id,
            Deduction.date >= start_date,
            Deduction.date <= end_date,
        )
        .all()
    )
    overbreak = sum(d.minutes for d in deductions if d.type == "OVERBREAK")
    rollcall_minutes = sum(d.minutes for d in deductions if d.type == "ROLLCALL")
    roll_calls = (
        db.query(RollCall)
        .filter(
            RollCall.user_id == user.id,
            RollCall.triggered_at >= datetime.combine(start_date, datetime.min.time()),
            RollCall.triggered_at <= datetime.combine(end_date, datetime.max.time()),
        )
        .all()
    )
    report = UserReport(
        user_id=user.id,
        full_name=user.full_name,
        total_hours=work_minutes / 60,
        lunch_minutes=lunch_minutes,
        break_minutes=break_minutes,
        overbreak_minutes=overbreak,
        rollcall_minutes=rollcall_minutes,
        net_hours=max(0.0, min(8.0, work_minutes / 60) - (overbreak + rollcall_minutes) / 60),
        sessions_count=len(sessions),
        rollcall_passed=sum(1 for rc in roll_calls if rc.result == "PASSED"),
        rollcall_late=sum(1 for rc in roll_calls if rc.result == "LATE"),
        rollcall_missed=sum(1 for rc in roll_calls if rc.result == "MISSED"),
    )
    return report


def get_reports_for_range(
    db: Session,
    org_id: int,
    start_date: date,
    end_date: date,
    user_id: int | None = None,
) -> list[UserReport]:
    normalized_start = min(start_date, end_date)
    normalized_end = max(start_date, end_date)
    query = db.query(User).filter(User.org_id == org_id)
    if user_id:
        query = query.filter(User.id == user_id)
    users = query.order_by(User.full_name.asc()).all()
    reports: list[UserReport] = []
    for user in users:
        reports.append(_build_user_summary(db, user, normalized_start, normalized_end))
    return reports
