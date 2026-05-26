"""chat message thread kind

Revision ID: 20260526_0002
Revises: 20260526_0001
Create Date: 2026-05-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260526_0002"
down_revision: str | None = "20260526_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column(
            "interaction",
            sa.String(length=20),
            nullable=False,
            server_default="message",
        ),
    )
    op.alter_column("chat_messages", "interaction", server_default=None)


def downgrade() -> None:
    op.drop_column("chat_messages", "interaction")
