from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, aliased

from ..db import get_db
from ..models import ChatRoom, ChatRoomMember, ChatRoomRead, Message, User
from ..schemas.chat import ChatMessagePayload, ChatRoomCreate, ChatRoomMembersPayload, ChatRoomUpdate

router = APIRouter(tags=["chat"])
templates = Path(__file__).resolve().parents[1] / "templates"

DEFAULT_ROOM_SETTINGS = {
    "allow_media": True,
    "allow_mentions": True,
    "allow_replies": True,
}


def _log_room_event(
    db: Session,
    room: ChatRoom,
    actor_id: int,
    content: str,
    *,
    message_type: str = "SYSTEM",
    metadata: dict | None = None,
) -> Message:
    event = Message(
        org_id=room.org_id,
        room_id=room.id,
        user_id=actor_id,
        content=content,
        message_type=message_type,
        metadata=metadata or {},
    )
    db.add(event)
    db.flush()
    return event


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


def _touch_room_read(
    db: Session, room_id: int, user_id: int, seen_at: datetime | None = None
) -> tuple[ChatRoomRead, bool]:
    seen_at = seen_at or datetime.utcnow()
    record = (
        db.query(ChatRoomRead)
        .filter(ChatRoomRead.room_id == room_id, ChatRoomRead.user_id == user_id)
        .one_or_none()
    )
    if record:
        if not record.last_read_at or record.last_read_at < seen_at:
            record.last_read_at = seen_at
            db.flush()
        return record, False
    record = ChatRoomRead(room_id=room_id, user_id=user_id, last_read_at=seen_at)
    db.add(record)
    db.flush()
    return record, True


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
    _, created_read = _touch_room_read(db, room.id, user_session["id"])
    if created_read:
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


def _serialize_room(
    room: ChatRoom,
    *,
    member_count: int,
    membership: ChatRoomMember | None,
    user_session: dict,
    last_message: dict | None = None,
    last_activity: datetime | None = None,
    unread_count: int = 0,
) -> dict:
    return {
        "id": room.id,
        "name": room.name,
        "is_direct": room.is_direct,
        "is_system": room.is_system,
        "member_count": member_count,
        "settings": room.settings or DEFAULT_ROOM_SETTINGS.copy(),
        "can_manage": _is_org_admin(user_session) or bool(membership and membership.is_moderator),
        "last_message": last_message,
        "last_activity": (last_activity or room.updated_at or room.created_at).isoformat()
        if (last_activity or room.updated_at or room.created_at)
        else None,
        "unread_count": unread_count,
    }


def _serialize_message(message: Message, user_lookup: dict[int, User]) -> dict:
    author = user_lookup.get(message.user_id)
    return {
        "id": message.id,
        "user_id": message.user_id,
        "user_name": author.full_name if author else f"User {message.user_id}",
        "user_role": author.role if author else None,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
        "message_type": message.message_type,
        "metadata": message.meta or {},
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
    search: str | None = None,
    db: Session = Depends(get_db),
):
    user = _require_user(request)
    default_room = _ensure_default_room(db, user)

    rooms_query = (
        db.query(ChatRoom)
        .join(ChatRoomMember, ChatRoomMember.room_id == ChatRoom.id)
        .filter(ChatRoomMember.user_id == user["id"])
    )
    if search:
        term = search.strip()
        if term:
            rooms_query = rooms_query.filter(ChatRoom.name.ilike(f"%{term}%"))
    rooms = rooms_query.all()

    room_ids = [room.id for room in rooms]
    member_counts: dict[int, int] = {}
    memberships: dict[int, ChatRoomMember] = {}
    last_activity_map: dict[int, datetime] = {}
    last_message_map: dict[int, dict] = {}
    unread_map: dict[int, int] = {}

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

        activity_rows = (
            db.query(Message.room_id, func.max(Message.created_at).label("last_created_at"))
            .filter(Message.room_id.in_(room_ids))
            .group_by(Message.room_id)
            .all()
        )
        last_activity_map = {room_id: last_created_at for room_id, last_created_at in activity_rows}

        activity_subq = (
            db.query(
                Message.room_id.label("room_id"),
                func.max(Message.created_at).label("last_created_at"),
            )
            .filter(Message.room_id.in_(room_ids))
            .group_by(Message.room_id)
            .subquery()
        )
        last_rows = (
            db.query(Message, User.full_name.label("author_name"))
            .join(
                activity_subq,
                (Message.room_id == activity_subq.c.room_id)
                & (Message.created_at == activity_subq.c.last_created_at),
            )
            .join(User, User.id == Message.user_id)
            .all()
        )
        last_message_map = {
            message.room_id: {
                "id": message.id,
                "content": message.content,
                "created_at": message.created_at.isoformat(),
                "author": author_name,
                "message_type": message.message_type,
            }
            for message, author_name in last_rows
        }

        reads_alias = aliased(ChatRoomRead)
        unread_rows = (
            db.query(Message.room_id, func.count(Message.id))
            .outerjoin(
                reads_alias,
                (reads_alias.room_id == Message.room_id) & (reads_alias.user_id == user["id"]),
            )
            .filter(Message.room_id.in_(room_ids))
            .filter(or_(reads_alias.last_read_at.is_(None), Message.created_at > reads_alias.last_read_at))
            .group_by(Message.room_id)
            .all()
        )
        unread_map = {room_id: count for room_id, count in unread_rows}

    def activity_value(room: ChatRoom) -> datetime:
        return (
            last_activity_map.get(room.id)
            or room.updated_at
            or room.created_at
            or datetime.min
        )

    rooms = sorted(rooms, key=activity_value, reverse=True)
    rooms.sort(key=lambda room: 0 if room.is_system else 1)

    payload = {
        "rooms": [
            _serialize_room(
                room,
                member_count=member_counts.get(room.id, 0),
                membership=memberships.get(room.id),
                user_session=user,
                last_message=last_message_map.get(room.id),
                last_activity=last_activity_map.get(room.id),
                unread_count=unread_map.get(room.id, 0),
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
    _log_room_event(
        db,
        room,
        user["id"],
        f"{user['full_name']} created {room.name}",
        metadata={"member_ids": list(member_ids)},
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
    previous_name = room.name
    changes: list[str] = []
    if payload.name and payload.name != room.name:
        room.name = payload.name
        changes.append(f"renamed group from {previous_name} to {payload.name}")
        updated = True
    if payload.settings:
        room.settings = _merge_settings(payload.settings.dict())
        changes.append("updated room settings")
        updated = True
    if not updated:
        return JSONResponse({"status": "noop"})
    db.flush()
    _log_room_event(
        db,
        room,
        user["id"],
        f"{user['full_name']} updated group settings",
        metadata={"changes": changes} if changes else None,
    )
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

    added_ids: list[int] = []
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
        added_ids.append(candidate.id)
    if not added_ids:
        return JSONResponse({"status": "noop"})
    db.flush()
    _log_room_event(
        db,
        room,
        user["id"],
        f"{user['full_name']} added members",
        metadata={"added": added_ids},
    )
    db.commit()
    return JSONResponse({"status": "updated", "added": added_ids})


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
    removed_id = target.user_id
    db.delete(target)
    db.flush()
    _log_room_event(
        db,
        room,
        user["id"],
        f"{user['full_name']} removed a member",
        metadata={"removed": [removed_id]},
    )
    db.commit()
    return JSONResponse({"status": "removed", "member_id": removed_id})


@router.post("/api/chat/rooms/{room_id}/leave")
async def leave_room(
    request: Request,
    room_id: int,
    db: Session = Depends(get_db),
):
    user = _require_user(request)
    room, membership = _require_room_membership(db, room_id, user)
    if room.is_system:
        raise HTTPException(status_code=400, detail="Cannot leave the default chat")
    db.delete(membership)
    db.flush()
    _log_room_event(
        db,
        room,
        user["id"],
        f"{user['full_name']} left the chat",
        metadata={"left": user["id"]},
    )
    db.commit()
    return JSONResponse({"status": "left"})


@router.delete("/api/chat/rooms/{room_id}")
async def delete_room(
    request: Request,
    room_id: int,
    db: Session = Depends(get_db),
):
    user = _require_user(request)
    room, membership = _require_room_membership(db, room_id, user)
    if room.is_system:
        raise HTTPException(status_code=400, detail="Cannot delete the default chat")
    if not (_is_org_admin(user) or room.created_by == user["id"]):
        raise HTTPException(status_code=403, detail="Only admins or creators can delete a group")
    name_snapshot = room.name
    org_id = room.org_id
    db.delete(room)
    db.commit()
    return JSONResponse({"status": "deleted", "room_id": room_id, "name": name_snapshot, "org_id": org_id})


@router.get("/api/chat/messages")
async def fetch_messages(
    request: Request,
    since: str | None = None,
    room_id: int | None = None,
    limit: int = 200,
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
    messages = query.limit(min(limit, 500)).all()
    user_lookup = {}
    if messages:
        member_ids = {m.user_id for m in messages}
        members = db.query(User).filter(User.id.in_(member_ids)).all()
        user_lookup = {member.id: member for member in members}

    if messages:
        latest_seen = messages[-1].created_at
        _, touched = _touch_room_read(db, room.id, user["id"], seen_at=latest_seen)
        if touched:
            db.commit()
        else:
            db.flush()
    return JSONResponse(
        {
            "room_id": room.id,
            "messages": [_serialize_message(m, user_lookup) for m in messages],
        }
    )


@router.post("/api/chat/messages")
async def post_message(
    request: Request,
    payload: ChatMessagePayload,
    db: Session = Depends(get_db),
):
    user = _require_user(request)
    default_room = _ensure_default_room(db, user)
    active_room_id = payload.room_id or default_room.id
    room, _ = _require_room_membership(db, active_room_id, user)

    metadata: dict[str, Any] = {}
    mention_ids = list({mid for mid in payload.mentions if isinstance(mid, int) and mid > 0})
    if mention_ids:
        members = (
            db.query(User.id, User.full_name)
            .filter(User.id.in_(mention_ids), User.org_id == user["org_id"])
            .all()
        )
        metadata["mentions"] = [
            {"id": member.id, "name": member.full_name}
            for member in members
        ]

    attachments: list[dict[str, Any]] = []
    if payload.attachments:
        if len(payload.attachments) > 5:
            raise HTTPException(status_code=400, detail="Too many attachments")
        for attachment in payload.attachments:
            attachments.append(
                {
                    "name": attachment.name,
                    "size": attachment.size,
                    "type": attachment.type,
                    "data": attachment.data,
                }
            )
    if attachments:
        metadata["attachments"] = attachments

    message = Message(
        org_id=user["org_id"],
        room_id=room.id,
        user_id=user["id"],
        content=payload.content.strip(),
        meta=metadata or None,
    )
    db.add(message)
    db.flush()
    _touch_room_read(db, room.id, user["id"], seen_at=message.created_at)
    db.commit()
    return JSONResponse({"status": "sent", "message_id": message.id})
