from datetime import datetime

from pydantic import BaseModel


class RollCallRead(BaseModel):
    id: int
    triggered_at: datetime
    deadline_at: datetime
    result: str

    class Config:
        orm_mode = True


class RollCallResponse(BaseModel):
    roll_call_id: int
