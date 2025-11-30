"""Legacy conversation otp baseline placeholder

Revision ID: 0005_conversation_otp
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op  # noqa: F401 - imported for completeness
import sqlalchemy as sa  # noqa: F401 - imported for completeness


# revision identifiers, used by Alembic.
revision: str = "0005_conversation_otp"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# This placeholder keeps Alembic history compatible with older databases
# that were previously migrated up to revision "0005_conversation_otp".
# No schema changes are defined here because the original migration
# existed in a different repository.

def upgrade() -> None:  # pragma: no cover - placeholder
    pass


def downgrade() -> None:  # pragma: no cover - placeholder
    pass
