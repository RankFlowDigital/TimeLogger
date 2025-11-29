from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..services.reporting import get_reports_for_range

router = APIRouter(tags=["reports"])
templates = Path(__file__).resolve().parents[1] / "templates"


def _render(request: Request, template_name: str, context: dict) -> HTMLResponse:
    from starlette.templating import Jinja2Templates

    template = Jinja2Templates(directory=templates)
    return template.TemplateResponse(template_name, context)


def _resolve_dates(start_value: str | None, end_value: str | None, preset: str | None) -> tuple[date, date, str]:
    today = date.today()
    norm_preset = (preset or "").lower()
    if not start_value and not end_value:
        if norm_preset == "week":
            start = today - timedelta(days=6)
            end = today
        else:
            start = today
            end = today
            norm_preset = "day"
    else:
        start = date.fromisoformat(start_value) if start_value else today
        end = date.fromisoformat(end_value) if end_value else today
        norm_preset = "custom"
    if start > end:
        start, end = end, start
    return start, end, norm_preset or "day"


def _serialize_report_row(report) -> dict:
    net_minutes = int(round(report.net_hours * 60))
    total_minutes = int(round(report.total_hours * 60))
    roll_call_total = report.rollcall_passed + report.rollcall_late + report.rollcall_missed
    return {
        "user_id": report.user_id,
        "user": report.full_name,
        "total_hours": round(report.total_hours, 2),
        "total_minutes": total_minutes,
        "lunch_minutes": report.lunch_minutes,
        "break_minutes": report.break_minutes,
        "overbreak_minutes": report.overbreak_minutes,
        "rollcall_minutes": report.rollcall_minutes,
        "net_hours": round(report.net_hours, 2),
        "net_minutes": net_minutes,
        "sessions": report.sessions_count,
        "rollcall_passed": report.rollcall_passed,
        "rollcall_late": report.rollcall_late,
        "rollcall_missed": report.rollcall_missed,
        "rollcall_total": roll_call_total,
    }


def _compute_summary(rows: list[dict]) -> dict:
    total_users = len(rows)
    if not total_users:
        return {"total_users": 0, "avg_net_hours": 0.0, "total_deductions": 0}
    avg_net = sum(row["net_hours"] for row in rows) / total_users
    total_deductions = sum(row["overbreak_minutes"] + row["rollcall_minutes"] for row in rows)
    return {
        "total_users": total_users,
        "avg_net_hours": round(avg_net, 2),
        "total_deductions": total_deductions,
    }


def _user_selector_options(db: Session, org_id: int) -> list[dict]:
    records = (
        db.query(User.id, User.full_name)
        .filter(User.org_id == org_id)
        .order_by(User.full_name.asc())
        .all()
    )
    return [{"id": row.id, "name": row.full_name} for row in records]


@router.get("/reports", response_class=HTMLResponse)
async def reports_home(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    user_id: str | None = None,
    preset: str | None = None,
    db: Session = Depends(get_db),
):
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    db_user = db.query(User).filter(User.id == session_user["id"]).one_or_none()
    if not db_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    start, end, active_preset = _resolve_dates(start_date, end_date, preset)
    is_admin = db_user.role in {"OWNER", "ADMIN"}
    target_user_id = None
    if is_admin and user_id and user_id != "all":
        try:
            target_user_id = int(user_id)
        except ValueError:
            target_user_id = None
    if not is_admin:
        target_user_id = db_user.id

    reports = get_reports_for_range(db, db_user.org_id, start, end, target_user_id)
    rows = [_serialize_report_row(report) for report in reports]
    summary = _compute_summary(rows)
    user_options = _user_selector_options(db, db_user.org_id) if is_admin else []

    return _render(
        request,
        "admin/reports.html",
        {
            "request": request,
            "user": session_user,
            "reports": rows,
            "summary": summary,
            "filters": {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "user_id": str(target_user_id) if target_user_id else "all",
                "preset": active_preset,
            },
            "is_admin": is_admin,
            "user_options": user_options,
        },
    )


@router.get("/reports/export")
async def export_reports(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    user_id: str | None = None,
    preset: str | None = None,
    db: Session = Depends(get_db),
):
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    db_user = db.query(User).filter(User.id == session_user["id"]).one_or_none()
    if not db_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    start, end, _ = _resolve_dates(start_date, end_date, preset)
    is_admin = db_user.role in {"OWNER", "ADMIN"}
    target_user_id = None
    if is_admin and user_id and user_id != "all":
        try:
            target_user_id = int(user_id)
        except ValueError:
            target_user_id = None
    if not is_admin:
        target_user_id = db_user.id

    reports = get_reports_for_range(db, db_user.org_id, start, end, target_user_id)
    rows = [_serialize_report_row(report) for report in reports]

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "User",
            "Total Hours Worked",
            "Lunch Minutes",
            "Break Minutes",
            "Overbreak Minutes",
            "Roll Call Deductions",
            "Net Work Hours",
            "Sessions",
            "Roll Calls (P/L/M)",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["user"],
                row["total_hours"],
                row["lunch_minutes"],
                row["break_minutes"],
                row["overbreak_minutes"],
                row["rollcall_minutes"],
                row["net_hours"],
                row["sessions"],
                f"{row['rollcall_passed']}/{row['rollcall_late']}/{row['rollcall_missed']}",
            ]
        )

    buffer.seek(0)
    filename = f"report_{start.isoformat()}_{end.isoformat()}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
        },
    )
