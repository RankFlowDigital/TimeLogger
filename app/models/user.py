from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, func

from . import Base

user_role_enum = Enum("OWNER", "ADMIN", "MEMBER", name="user_role")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(user_role_enum, nullable=False, default="MEMBER")
    is_active = Column(Boolean, default=True)
    timezone = Column(String, nullable=True)
    allow_unassigned_sessions = Column(Boolean, nullable=False, default=False, server_default="false")
    invited_at = Column(DateTime, nullable=True)
    joined_at = Column(DateTime, nullable=True)
    must_reset_password = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
