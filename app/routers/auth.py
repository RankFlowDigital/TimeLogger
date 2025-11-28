from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
import bcrypt

from ..db import get_db
from ..models import Organization, User

router = APIRouter(tags=["auth"])
templates = Path(__file__).resolve().parents[1] / "templates"


def _render(request: Request, template_name: str, context: dict, status_code: int = 200) -> HTMLResponse:
    from starlette.templating import Jinja2Templates

    template = Jinja2Templates(directory=templates)
    return template.TemplateResponse(template_name, context, status_code=status_code)


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


@router.get("/signup", response_class=HTMLResponse)
async def signup_form(request: Request):
    return _render(request, "auth/signup.html", {"request": request})


@router.post("/signup")
async def signup(
    request: Request,
    email: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == email.lower()).one_or_none()
    if existing:
        return _render(
            request,
            "auth/signup.html",
            {"request": request, "error": "Email already registered"},
            status.HTTP_400_BAD_REQUEST,
        )

    org = db.query(Organization).first()
    role = "MEMBER"
    if not org:
        org = Organization(name="Default Org")
        db.add(org)
        db.flush()
        role = "OWNER"

    user = User(
        org_id=org.id,
        email=email.lower(),
        full_name=full_name,
        password_hash=get_password_hash(password),
        role=role,
    )
    db.add(user)
    db.commit()

    request.session["user"] = {
        "id": user.id,
        "org_id": user.org_id,
        "role": user.role,
        "full_name": user.full_name,
    }
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return _render(request, "auth/login.html", {"request": request})


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email.lower()).one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return _render(
            request,
            "auth/login.html",
            {"request": request, "error": "Invalid credentials"},
            status.HTTP_400_BAD_REQUEST,
        )

    request.session["user"] = {
        "id": user.id,
        "org_id": user.org_id,
        "role": user.role,
        "full_name": user.full_name,
    }
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
