from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserBase(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: str

    class Config:
        orm_mode = True


class UserDetail(UserBase):
    created_at: datetime | None = None
    timezone: str | None = None


class TimezonePreference(BaseModel):
    timezone: str | None = None


class InviteUserRequest(BaseModel):
    email: EmailStr
    full_name: str
    role: str | None = "MEMBER"
    timezone: str | None = None
