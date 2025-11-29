from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, validator


class ChatRoomSettings(BaseModel):
    allow_media: bool = True
    allow_mentions: bool = True
    allow_replies: bool = True


class ChatRoomCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=120)
    member_ids: List[int] = Field(default_factory=list)
    settings: Optional[ChatRoomSettings] = None

    @validator("name")
    def name_strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Name is required")
        return cleaned


class ChatRoomUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=120)
    settings: Optional[ChatRoomSettings] = None

    @validator("name")
    def name_strip(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Name is required")
        return cleaned


class ChatRoomMembersPayload(BaseModel):
    user_ids: List[int] = Field(default_factory=list)

    @validator("user_ids", each_item=True)
    def ensure_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Invalid user id")
        return value
