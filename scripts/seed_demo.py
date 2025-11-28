"""Seed a small demo org plus users/shifts into the configured database."""

from datetime import time

from app.db import SessionLocal
from app.models import Organization, Shift, User
from app.routers.auth import get_password_hash

OWNER_EMAIL = "owner@example.com"
MEMBER_EMAIL = "agent@example.com"
DEFAULT_PASSWORD = "demo1234"


def ensure_org(session) -> Organization:
    org = session.query(Organization).filter(Organization.name == "Demo Org").one_or_none()
    if org is None:
        org = Organization(name="Demo Org", settings={"rollcalls_per_hour": 5})
        session.add(org)
        session.flush()
    return org


def ensure_user(session, org: Organization, email: str, full_name: str, role: str) -> User:
    user = session.query(User).filter(User.email == email).one_or_none()
    if user:
        return user

    user = User(
        org_id=org.id,
        email=email,
        full_name=full_name,
        password_hash=get_password_hash(DEFAULT_PASSWORD),
        role=role,
        is_active=True,
    )
    session.add(user)
    session.flush()
    if role == "OWNER" and not org.owner_user_id:
        org.owner_user_id = user.id
    return user


def ensure_shift(session, org_id: int, user_id: int, day_of_week: int, start: time, end: time) -> None:
    exists = (
        session.query(Shift)
        .filter(
            Shift.org_id == org_id,
            Shift.user_id == user_id,
            Shift.day_of_week == day_of_week,
            Shift.start_time == start,
            Shift.end_time == end,
        )
        .one_or_none()
    )
    if exists:
        return
    session.add(
        Shift(
            org_id=org_id,
            user_id=user_id,
            day_of_week=day_of_week,
            start_time=start,
            end_time=end,
        )
    )


def main() -> None:
    session = SessionLocal()
    try:
        org = ensure_org(session)
        owner = ensure_user(session, org, OWNER_EMAIL, "Demo Owner", "OWNER")
        member = ensure_user(session, org, MEMBER_EMAIL, "Demo Agent", "MEMBER")
        ensure_shift(session, org.id, owner.id, 0, time(9, 0), time(17, 0))
        ensure_shift(session, org.id, member.id, 0, time(9, 0), time(17, 0))
        session.commit()
        print("Demo data ready:")
        print(f"  Owner login: {OWNER_EMAIL} / {DEFAULT_PASSWORD}")
        print(f"  Member login: {MEMBER_EMAIL} / {DEFAULT_PASSWORD}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
