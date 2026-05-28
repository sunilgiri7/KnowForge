"""add user llm model

Revision ID: 20260528_0004
Revises: 20260528_0003
Create Date: 2026-05-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260528_0004"
down_revision: str | None = "20260528_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_llm_keys", sa.Column("model", sa.String(length=120), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("user_llm_keys", "model")

