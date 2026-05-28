"""user active llm provider

Revision ID: 20260528_0005
Revises: 20260528_0004
Create Date: 2026-05-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260528_0005"
down_revision: str | None = "20260528_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "llm_active_provider",
            sa.String(length=40),
            nullable=False,
            server_default="openrouter",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "llm_active_provider")

