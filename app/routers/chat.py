from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Message

router = APIRouter(tags=["chat"])
templates = Path(__file__).resolve().parents[1] / "templates"


def _render(request: Request, template_name: str, context: dict) -> HTMLResponse:
    from starlette.templating import Jinja2Templates

    template = Jinja2Templates(directory=templates)
    return template.TemplateResponse(template_name, context)


@router.get("/chat", response_class=HTMLResponse)
async def chat_room(request: Request, db: Session = Depends(get_db)):
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    messages = db.query(Message).order_by(Message.created_at.desc()).limit(50).all()
    return _render(
        request,
        "chat/room.html",
        {"request": request, "user": user, "messages": list(reversed(messages))},
    )


@router.get("/api/chat/messages")
async def fetch_messages(request: Request, since: str | None = None, db: Session = Depends(get_db)):
    user = request.session.get("user")
    if not user:
        return JSONResponse({"messages": []})
    query = db.query(Message).filter(Message.org_id == user["org_id"]).order_by(Message.created_at.asc())
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.filter(Message.created_at > since_dt)
        except ValueError:
            pass
    messages = query.limit(100).all()
    return JSONResponse({
        "messages": [
            {
                "id": m.id,
                "user_id": m.user_id,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]
    })


@router.post("/api/chat/messages")
async def post_message(request: Request, content: str = Form(""), db: Session = Depends(get_db)):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not content.strip():
        return JSONResponse({"error": "empty"}, status_code=400)
    message = Message(org_id=user["org_id"], user_id=user["id"], content=content.strip())
    db.add(message)
    db.commit()
    return JSONResponse({"status": "sent", "message_id": message.id})
