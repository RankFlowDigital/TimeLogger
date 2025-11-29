from __future__ import annotations

import logging
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..routers.auth import get_password_hash, verify_password
from ..schemas.report import UserReportQuery
from ..schemas.user import ChangePasswordRequest, InviteUserRequest, TimezonePreference
from ..services.mailer import send_invitation_email
from ..services.reporting import get_user_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])


def _require_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _validate_timezone(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    try:
        ZoneInfo(candidate)
    except Exception as exc:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=400, detail="Invalid timezone selection") from exc
    return candidate


@router.post("/timezone")
async def update_timezone(
    request: Request,
    payload: TimezonePreference,
    db: Session = Depends(get_db),
):
    user_session = _require_user(request)
    tz_value = _validate_timezone(payload.timezone)
    user = db.query(User).filter(User.id == user_session["id"]).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.timezone = tz_value
    db.commit()
    user_session["timezone"] = tz_value
    return JSONResponse({"status": "updated", "timezone": tz_value})


@router.post("/invite")
async def invite_user(
    request: Request,
    payload: InviteUserRequest,
    db: Session = Depends(get_db),
):
    inviter = _require_user(request)
    if inviter.get("role") not in {"OWNER", "ADMIN"}:
        raise HTTPException(status_code=403, detail="Only admins can invite members")

    normalized_email = payload.email.lower()
    existing = db.query(User).filter(User.email == normalized_email).one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")

    timezone_value = _validate_timezone(payload.timezone)
    role = (payload.role or "MEMBER").upper()
    if role not in {"MEMBER", "ADMIN"}:
        raise HTTPException(status_code=400, detail="Unsupported role")

    temp_password = secrets.token_urlsafe(10)
    invited = User(
        org_id=inviter["org_id"],
        email=normalized_email,
        full_name=payload.full_name.strip(),
        password_hash=get_password_hash(temp_password),
        role=role,
        timezone=timezone_value,
        invited_at=datetime.utcnow(),
        must_reset_password=True,
    )
    db.add(invited)
    db.commit()

    login_url = str(request.url_for("login_form"))
    email_sent = True
    try:
        send_invitation_email(invited.email, login_url, temp_password)
    except Exception as exc:  # pragma: no cover - network failures logged for admins
        logger.exception("Invite email failed for %s", invited.email)
        email_sent = False

    return JSONResponse(
        {
            "status": "created",
            "user": {
                "id": invited.id,
                "full_name": invited.full_name,
                "email": invited.email,
                "role": invited.role,
                "timezone": invited.timezone,
            },
            "temp_password": temp_password,
            "email_sent": email_sent,
        },
        status_code=201,
    )


@router.post("/change-password")
async def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
):
    user_session = _require_user(request)
    user = db.query(User).filter(User.id == user_session["id"]).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different")

    user.password_hash = get_password_hash(payload.new_password)
    db.commit()
    return JSONResponse({"status": "updated"})


@router.post("/report")
async def user_report(
    request: Request,
    payload: UserReportQuery,
    db: Session = Depends(get_db),
):
    user_session = _require_user(request)
    try:
        report = get_user_summary(db, user_session["id"], payload.start_date, payload.end_date)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(report.dict())
