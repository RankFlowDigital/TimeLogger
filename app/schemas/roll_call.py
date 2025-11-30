from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RollCallRead(BaseModel):
    id: int
    triggered_at: datetime
    deadline_at: datetime
    result: str

    model_config = ConfigDict(from_attributes=True)


class RollCallResponse(BaseModel):
    roll_call_id: int
