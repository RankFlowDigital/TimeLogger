from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..services.reporting import get_org_summary

router = APIRouter(tags=["reports"])
templates = Path(__file__).resolve().parents[1] / "templates"


def _render(request: Request, template_name: str, context: dict) -> HTMLResponse:
    from starlette.templating import Jinja2Templates

    template = Jinja2Templates(directory=templates)
    return template.TemplateResponse(template_name, context)


@router.get("/admin/reports", response_class=HTMLResponse)
async def admin_reports(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
):
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    user = db.query(User).filter(User.id == session_user["id"]).one_or_none()
    if not user or user.role not in {"OWNER", "ADMIN"}:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    start = date.fromisoformat(start_date) if start_date else date.today()
    end = date.fromisoformat(end_date) if end_date else date.today()
    if start > end:
        start, end = end, start

    reports = get_org_summary(db, user.org_id, start, end)
    return _render(
        request,
        "admin/reports.html",
        {
            "request": request,
            "user": session_user,
            "reports": reports,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    )
