#!/usr/bin/env python
"""Utility to delete seeded demo accounts/org without touching real users."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    ChatRoom,
    Deduction,
    Leave,
    Message,
    Organization,
    RollCall,
    Shift,
    User,
    WorkSession,
)

TARGET_ORG_NAME = "Demo Org"
TARGET_EMAILS = {
    "owner@example.com",
    "agent@example.com",
}


def purge_demo_org(session, *, force: bool) -> bool:
    org = session.query(Organization).filter(Organization.name == TARGET_ORG_NAME).one_or_none()
    extra_users = session.query(User).filter(User.email.in_(TARGET_EMAILS)).all()
    if not org and not extra_users:
        print("[remove_demo] Nothing to delete.")
        return False

    deletions = {}
    if org:
        org_id = org.id
        deletions = {
            "work_sessions": session.query(WorkSession).filter(WorkSession.org_id == org_id).count(),
            "roll_calls": session.query(RollCall).filter(RollCall.org_id == org_id).count(),
            "deductions": session.query(Deduction).filter(Deduction.org_id == org_id).count(),
            "messages": session.query(Message).filter(Message.org_id == org_id).count(),
            "leaves": session.query(Leave).filter(Leave.org_id == org_id).count(),
            "shifts": session.query(Shift).filter(Shift.org_id == org_id).count(),
            "chat_rooms": session.query(ChatRoom).filter(ChatRoom.org_id == org_id).count(),
            "users": session.query(User).filter(User.org_id == org_id).count(),
        }
        print(f"[remove_demo] Found demo org '{TARGET_ORG_NAME}' (id={org_id}).")
        for key, value in deletions.items():
            print(f"  - {key}: {value}")
    if extra_users:
        print("[remove_demo] Extra demo users outside Demo Org:")
        for user in extra_users:
            print(f"  - {user.full_name} <{user.email}> (org_id={user.org_id})")

    if not force:
        response = input("Proceed with deletion? Type 'yes' to continue: ").strip().lower()
        if response != "yes":
            print("[remove_demo] Aborted.")
            return False

    if org:
        org_id = org.id
        session.query(WorkSession).filter(WorkSession.org_id == org_id).delete(synchronize_session=False)
        session.query(RollCall).filter(RollCall.org_id == org_id).delete(synchronize_session=False)
        session.query(Deduction).filter(Deduction.org_id == org_id).delete(synchronize_session=False)
        session.query(Message).filter(Message.org_id == org_id).delete(synchronize_session=False)
        session.query(Leave).filter(Leave.org_id == org_id).delete(synchronize_session=False)
        session.query(Shift).filter(Shift.org_id == org_id).delete(synchronize_session=False)
        # delete chat rooms via ORM to cascade reads/members
        rooms = session.query(ChatRoom).filter(ChatRoom.org_id == org_id).all()
        for room in rooms:
            session.delete(room)
        session.query(User).filter(User.org_id == org_id).delete(synchronize_session=False)
        session.delete(org)

    if extra_users:
        extra_ids = [user.id for user in extra_users]
        if extra_ids:
            session.query(WorkSession).filter(WorkSession.user_id.in_(extra_ids)).delete(synchronize_session=False)
            session.query(RollCall).filter(RollCall.user_id.in_(extra_ids)).delete(synchronize_session=False)
            session.query(Deduction).filter(Deduction.user_id.in_(extra_ids)).delete(synchronize_session=False)
            session.query(Leave).filter(Leave.user_id.in_(extra_ids)).delete(synchronize_session=False)
            session.query(Shift).filter(Shift.user_id.in_(extra_ids)).delete(synchronize_session=False)
            session.query(Message).filter(Message.user_id.in_(extra_ids)).delete(synchronize_session=False)
            session.query(User).filter(User.id.in_(extra_ids)).delete(synchronize_session=False)

    session.commit()
    print("[remove_demo] Demo data removed.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete seeded demo accounts (Demo Org)")
    parser.add_argument("--force", action="store_true", help="skip confirmation prompt")
    args = parser.parse_args()
    session = SessionLocal()
    try:
        changed = purge_demo_org(session, force=args.force)
    finally:
        session.close()
    return 0 if changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
