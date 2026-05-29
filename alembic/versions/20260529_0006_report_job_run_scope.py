"""add report job run scope

Revision ID: 20260529_0006
Revises: 51d983f8efa0
Create Date: 2026-05-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260529_0006"
down_revision: Union[str, Sequence[str], None] = "51d983f8efa0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("report_jobs", sa.Column("scope_slugs_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("report_jobs", "scope_slugs_json")
