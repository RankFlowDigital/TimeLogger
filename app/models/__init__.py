from sqlalchemy.orm import declarative_base

Base = declarative_base()

from .deduction import Deduction  # noqa: E402,F401
from .leave import Leave  # noqa: E402,F401
from .message import Message  # noqa: E402,F401
from .organization import Organization  # noqa: E402,F401
from .roll_call import RollCall  # noqa: E402,F401
from .shift import Shift  # noqa: E402,F401
from .user import User  # noqa: E402,F401
from .work_session import WorkSession  # noqa: E402,F401
