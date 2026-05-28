"""per-user llm keys

Revision ID: 20260528_0003
Revises: 20260526_0002
Create Date: 2026-05-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260528_0003"
down_revision: str | None = "20260526_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_llm_keys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_llm_provider"),
    )
    op.create_index(op.f("ix_user_llm_keys_provider"), "user_llm_keys", ["provider"])
    op.create_index(op.f("ix_user_llm_keys_user_id"), "user_llm_keys", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_user_llm_keys_user_id"), table_name="user_llm_keys")
    op.drop_index(op.f("ix_user_llm_keys_provider"), table_name="user_llm_keys")
    op.drop_table("user_llm_keys")

