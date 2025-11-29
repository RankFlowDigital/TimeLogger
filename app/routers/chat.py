from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ChatRoom, ChatRoomMember, Message, User
from ..schemas.chat import ChatRoomCreate, ChatRoomMembersPayload, ChatRoomUpdate

router = APIRouter(tags=["chat"])
templates = Path(__file__).resolve().parents[1] / "templates"

DEFAULT_ROOM_SETTINGS = {
    "allow_media": True,
    "allow_mentions": True,
    "allow_replies": True,
}


def _render(request: Request, template_name: str, context: dict) -> HTMLResponse:
    from starlette.templating import Jinja2Templates

    template = Jinja2Templates(directory=templates)
    return template.TemplateResponse(template_name, context)


def _require_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _is_org_admin(user_session: dict) -> bool:
    return user_session.get("role") in {"OWNER", "ADMIN"}


def _merge_settings(payload: dict | None) -> dict:
    settings = DEFAULT_ROOM_SETTINGS.copy()
    if payload:
        settings.update(payload)
    return settings


def _ensure_default_room(db: Session, user_session: dict) -> ChatRoom:
    room = (
        db.query(ChatRoom)
        .filter(ChatRoom.org_id == user_session["org_id"], ChatRoom.is_system.is_(True))
        .order_by(ChatRoom.id.asc())
        .first()
    )
    dirty = False
    if not room:
        room = ChatRoom(
            org_id=user_session["org_id"],
            name="Operations Hub",
            is_system=True,
            settings=DEFAULT_ROOM_SETTINGS.copy(),
        )
        db.add(room)
        db.flush()
        dirty = True
    membership = (
        db.query(ChatRoomMember)
        .filter(ChatRoomMember.room_id == room.id, ChatRoomMember.user_id == user_session["id"])
        .one_or_none()
    )
    if not membership:
        db.add(
            ChatRoomMember(
                room_id=room.id,
                user_id=user_session["id"],
                is_moderator=_is_org_admin(user_session),
            )
        )
        dirty = True
    if dirty:
        db.commit()
    return room


def _require_room_membership(db: Session, room_id: int, user_session: dict) -> tuple[ChatRoom, ChatRoomMember]:
    room = db.query(ChatRoom).filter(ChatRoom.id == room_id, ChatRoom.org_id == user_session["org_id"]).one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Chat room not found")
    membership = (
        db.query(ChatRoomMember)
        .filter(ChatRoomMember.room_id == room.id, ChatRoomMember.user_id == user_session["id"])
        .one_or_none()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this chat")
    return room, membership


def _serialize_room(room: ChatRoom, *, member_count: int, membership: ChatRoomMember | None, user_session: dict) -> dict:
    return {
        "id": room.id,
        "name": room.name,
        "is_direct": room.is_direct,
        "is_system": room.is_system,
        "member_count": member_count,
        "settings": room.settings or DEFAULT_ROOM_SETTINGS.copy(),
        "can_manage": _is_org_admin(user_session) or bool(membership and membership.is_moderator),
    }


@router.get("/chat", response_class=HTMLResponse)
async def chat_room(request: Request, db: Session = Depends(get_db)):
    try:
        user = _require_user(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    _ensure_default_room(db, user)
    messages = (
        db.query(Message)
        .join(ChatRoom, ChatRoom.id == Message.room_id)
        .filter(ChatRoom.org_id == user["org_id"])
        .order_by(Message.created_at.desc())
        .limit(50)
        .all()
    )
    return _render(
        request,
        "chat/room.html",
        {"request": request, "user": user, "messages": list(reversed(messages))},
    )


@router.get("/api/chat/rooms")
async def list_rooms(
    request: Request,
    include_users: bool = False,
    db: Session = Depends(get_db),
):
    user = _require_user(request)
    default_room = _ensure_default_room(db, user)

    rooms = (
        db.query(ChatRoom)
        .join(ChatRoomMember, ChatRoomMember.room_id == ChatRoom.id)
        .filter(ChatRoomMember.user_id == user["id"])
        .order_by(ChatRoom.is_system.desc(), ChatRoom.name.asc())
        .all()
    )
    room_ids = [room.id for room in rooms]
    member_counts: dict[int, int] = {}
    memberships: dict[int, ChatRoomMember] = {}
    if room_ids:
        member_counts = {
            room_id: count
            for room_id, count in db.query(ChatRoomMember.room_id, func.count(ChatRoomMember.id))
            .filter(ChatRoomMember.room_id.in_(room_ids))
            .group_by(ChatRoomMember.room_id)
            .all()
        }
        memberships = {
            membership.room_id: membership
            for membership in db.query(ChatRoomMember)
            .filter(ChatRoomMember.user_id == user["id"], ChatRoomMember.room_id.in_(room_ids))
            .all()
        }
    payload = {
        "rooms": [
            _serialize_room(
                room,
                member_count=member_counts.get(room.id, 0),
                membership=memberships.get(room.id),
                user_session=user,
            )
            for room in rooms
        ],
        "default_room_id": default_room.id,
        "active_room_id": user.get("active_room_id", default_room.id),
    }
    if include_users:
        members = (
            db.query(User)
            .filter(User.org_id == user["org_id"])
            .order_by(User.full_name.asc())
            .all()
        )
        payload["users"] = [
            {"id": member.id, "name": member.full_name, "role": member.role}
            for member in members
        ]
    return JSONResponse(payload)


@router.get("/api/chat/rooms/{room_id}")
async def fetch_room_details(
    request: Request,
    room_id: int,
    include_members: bool = False,
    db: Session = Depends(get_db),
):
    user = _require_user(request)
    room, membership = _require_room_membership(db, room_id, user)
    member_count = (
        db.query(func.count(ChatRoomMember.id))
        .filter(ChatRoomMember.room_id == room.id)
        .scalar()
    )
    payload: dict[str, Any] = {
        "room": _serialize_room(room, member_count=member_count, membership=membership, user_session=user)
    }
    if include_members:
        member_rows = (
            db.query(ChatRoomMember, User)
            .join(User, User.id == ChatRoomMember.user_id)
            .filter(ChatRoomMember.room_id == room.id)
            .order_by(User.full_name.asc())
            .all()
        )
        payload["members"] = [
            {
                "id": user_row.id,
                "name": user_row.full_name,
                "role": user_row.role,
                "is_moderator": member_row.is_moderator,
            }
            for member_row, user_row in member_rows
        ]
    return JSONResponse(payload)


@router.post("/api/chat/rooms")
async def create_room(
    request: Request,
    payload: ChatRoomCreate,
    db: Session = Depends(get_db),
):
    user = _require_user(request)
    if not _is_org_admin(user):
        raise HTTPException(status_code=403, detail="Only administrators can create group chats")

    org_id = user["org_id"]
    member_ids = set(payload.member_ids)
    member_ids.add(user["id"])
    members = (
        db.query(User)
        .filter(User.org_id == org_id, User.id.in_(member_ids))
        .all()
    )
    if len(members) != len(member_ids):
        raise HTTPException(status_code=400, detail="One or more members were not found")

    room = ChatRoom(
        org_id=org_id,
        name=payload.name,
        is_system=False,
        is_direct=False,
        created_by=user["id"],
        settings=_merge_settings(payload.settings.dict() if payload.settings else None),
    )
    db.add(room)
    db.flush()

    for member in members:
        db.add(
            ChatRoomMember(
                room_id=room.id,
                user_id=member.id,
                is_moderator=member.id == user["id"] or _is_org_admin(user),
                added_by=user["id"],
            )
        )
    db.commit()

    membership = (
        db.query(ChatRoomMember)
        .filter(ChatRoomMember.room_id == room.id, ChatRoomMember.user_id == user["id"])
        .one()
    )
    return JSONResponse(
        {
            "status": "created",
            "room": _serialize_room(
                room,
                member_count=len(member_ids),
                membership=membership,
                user_session=user,
            ),
        },
        status_code=status.HTTP_201_CREATED,
    )


@router.patch("/api/chat/rooms/{room_id}")
async def update_room(
    request: Request,
    room_id: int,
    payload: ChatRoomUpdate,
    db: Session = Depends(get_db),
):
    user = _require_user(request)
    room, membership = _require_room_membership(db, room_id, user)
    if not (_is_org_admin(user) or membership.is_moderator):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if room.is_system and payload.name:
        raise HTTPException(status_code=400, detail="Cannot rename the default operations chat")

    updated = False
    if payload.name and payload.name != room.name:
        room.name = payload.name
        updated = True
    if payload.settings:
        room.settings = _merge_settings(payload.settings.dict())
        updated = True
    if not updated:
        return JSONResponse({"status": "noop"})
    db.commit()
    return JSONResponse({"status": "updated"})


@router.post("/api/chat/rooms/{room_id}/members")
async def add_room_members(
    request: Request,
    room_id: int,
    payload: ChatRoomMembersPayload,
    db: Session = Depends(get_db),
):
    user = _require_user(request)
    room, membership = _require_room_membership(db, room_id, user)
    if not (_is_org_admin(user) or membership.is_moderator):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if not payload.user_ids:
        return JSONResponse({"status": "noop"})

    candidates = (
        db.query(User)
        .filter(User.org_id == user["org_id"], User.id.in_(payload.user_ids))
        .all()
    )
    if len(candidates) != len(set(payload.user_ids)):
        raise HTTPException(status_code=400, detail="Some users were not found")

    existing_member_ids = {
        m.user_id
        for m in db.query(ChatRoomMember)
        .filter(ChatRoomMember.room_id == room.id, ChatRoomMember.user_id.in_(payload.user_ids))
        .all()
    }

    for candidate in candidates:
        if candidate.id in existing_member_ids:
            continue
        db.add(
            ChatRoomMember(
                room_id=room.id,
                user_id=candidate.id,
                is_moderator=False,
                added_by=user["id"],
            )
        )
    db.commit()
    return JSONResponse({"status": "updated"})


@router.delete("/api/chat/rooms/{room_id}/members/{member_id}")
async def remove_room_member(
    request: Request,
    room_id: int,
    member_id: int,
    db: Session = Depends(get_db),
):
    user = _require_user(request)
    room, membership = _require_room_membership(db, room_id, user)
    if room.is_system:
        raise HTTPException(status_code=400, detail="Cannot modify membership for the default chat")
    if not (_is_org_admin(user) or membership.is_moderator):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    target = (
        db.query(ChatRoomMember)
        .filter(ChatRoomMember.room_id == room.id, ChatRoomMember.user_id == member_id)
        .one_or_none()
    )
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")
    if target.user_id == user["id"] and not _is_org_admin(user):
        raise HTTPException(status_code=400, detail="Use leave chat controls instead")
    db.delete(target)
    db.commit()
    return JSONResponse({"status": "removed"})


@router.get("/api/chat/messages")
async def fetch_messages(
    request: Request,
    since: str | None = None,
    room_id: int | None = None,
    db: Session = Depends(get_db),
):
    user = request.session.get("user")
    if not user:
        return JSONResponse({"messages": []})

    default_room = _ensure_default_room(db, user)
    active_room_id = room_id or default_room.id
    room, _ = _require_room_membership(db, active_room_id, user)

    query = (
        db.query(Message)
        .filter(Message.room_id == room.id)
        .order_by(Message.created_at.asc())
    )
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.filter(Message.created_at > since_dt)
        except ValueError:
            pass
    messages = query.limit(200).all()
    user_lookup = {}
    if messages:
        member_ids = {m.user_id for m in messages}
        members = db.query(User).filter(User.id.in_(member_ids)).all()
        user_lookup = {member.id: member for member in members}
    return JSONResponse(
        {
            "room_id": room.id,
            "messages": [
                {
                    "id": m.id,
                    "user_id": m.user_id,
                    "user_name": user_lookup.get(m.user_id).full_name if user_lookup.get(m.user_id) else "Unknown",
                    "user_role": user_lookup.get(m.user_id).role if user_lookup.get(m.user_id) else None,
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                }
                for m in messages
            ],
        }
    )


@router.post("/api/chat/messages")
async def post_message(
    request: Request,
    content: str = Form(""),
    room_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    user = _require_user(request)
    if not content.strip():
        return JSONResponse({"error": "empty"}, status_code=400)

    default_room = _ensure_default_room(db, user)
    active_room_id = room_id or default_room.id
    room, _ = _require_room_membership(db, active_room_id, user)

    message = Message(
        org_id=user["org_id"],
        room_id=room.id,
        user_id=user["id"],
        content=content.strip(),
    )
    db.add(message)
    db.commit()
    return JSONResponse({"status": "sent", "message_id": message.id})
