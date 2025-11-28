from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Organization, RollCall, WorkSession
from ..schemas.roll_call import RollCallResponse
from ..services import rollcall_scheduler
from ..services.attendance import create_rollcall_deduction

router = APIRouter(prefix="/api", tags=["roll_calls"])
settings = get_settings()


def _require_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.get("/me/pending-rollcall")
async def get_pending_roll_call(request: Request, db: Session = Depends(get_db)):
    user = request.session.get("user")
    if not user:
        return JSONResponse({"pending": None})
    now = datetime.utcnow()
    roll_call = (
        db.query(RollCall)
        .filter(
            RollCall.user_id == user["id"],
            RollCall.result == "PENDING",
            RollCall.triggered_at <= now,
            RollCall.deadline_at > now,
        )
        .order_by(RollCall.triggered_at.desc())
        .first()
    )
    if not roll_call:
        return JSONResponse({"pending": None})
    return JSONResponse(
        {
            "pending": {
                "id": roll_call.id,
                "triggered_at": roll_call.triggered_at.isoformat(),
                "deadline_at": roll_call.deadline_at.isoformat(),
            }
        }
    )


@router.post("/roll-calls/respond")
async def respond_roll_call(
    request: Request,
    payload: RollCallResponse,
    db: Session = Depends(get_db),
):
    user = _require_user(request)
    roll_call = (
        db.query(RollCall)
        .filter(RollCall.id == payload.roll_call_id, RollCall.user_id == user["id"])
        .one_or_none()
    )
    if not roll_call or roll_call.result != "PENDING":
        return JSONResponse({"status": "invalid"}, status_code=400)

    now = datetime.utcnow()
    roll_call.responded_at = now
    delay_seconds = int((now - roll_call.triggered_at).total_seconds())

    if delay_seconds <= 300:
        roll_call.result = "PASSED"
    elif now <= roll_call.deadline_at:
        roll_call.result = "LATE"
        roll_call.response_delay_seconds = delay_seconds - 300
        create_rollcall_deduction(
            db,
            org_id=roll_call.org_id,
            user_id=user["id"],
            occurred_at=roll_call.triggered_at,
            delay_seconds=delay_seconds - 300,
            roll_call_id=roll_call.id,
        )
    else:
        roll_call.result = "LATE"
        roll_call.response_delay_seconds = delay_seconds - 300
        create_rollcall_deduction(
            db,
            org_id=roll_call.org_id,
            user_id=user["id"],
            occurred_at=roll_call.triggered_at,
            delay_seconds=delay_seconds - 300,
            roll_call_id=roll_call.id,
        )
    db.commit()
    return JSONResponse({"status": roll_call.result})


@router.post("/internal/rollcall-tick")
async def rollcall_tick(request: Request, db: Session = Depends(get_db)):
    token = request.headers.get("x-rollcall-token") or request.query_params.get("token")
    if settings.rollcall_tick_token and token != settings.rollcall_tick_token:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    org_ids = [org_id for (org_id,) in db.query(WorkSession.org_id).distinct()]
    org_settings = {}
    if org_ids:
        org_settings = {
            org.id: org.settings or {}
            for org in db.query(Organization).filter(Organization.id.in_(org_ids)).all()
        }
    scheduled = []
    for org_id in org_ids:
        target = rollcall_scheduler.target_from_settings(org_settings.get(org_id))
        scheduled.extend(
            rollcall_scheduler.schedule_roll_calls_for_current_hour(
                db,
                org_id,
                target_count=target,
            )
        )
    return JSONResponse({"scheduled": len(scheduled)})


@router.post("/internal/rollcall-expire")
async def rollcall_expire(request: Request, db: Session = Depends(get_db)):
    token = request.headers.get("x-rollcall-token") or request.query_params.get("token")
    if settings.rollcall_tick_token and token != settings.rollcall_tick_token:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    expired = rollcall_scheduler.expire_roll_calls(db)
    return JSONResponse({"expired": expired})
