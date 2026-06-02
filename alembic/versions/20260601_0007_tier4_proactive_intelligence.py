"""tier4 proactive intelligence

Revision ID: 20260601_0007
Revises: 45f4c2db259d
Create Date: 2026-06-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260601_0007"
down_revision: Union[str, Sequence[str], None] = "45f4c2db259d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("wiki_fact_events", sa.Column("review_status", sa.String(length=30), nullable=False, server_default="pending_review"))
    op.add_column("wiki_fact_events", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wiki_fact_events", sa.Column("reviewed_by", sa.String(length=36), nullable=True))
    op.add_column("wiki_fact_events", sa.Column("review_note", sa.Text(), nullable=False, server_default=""))
    op.create_foreign_key("fk_wiki_fact_events_reviewed_by_users", "wiki_fact_events", "users", ["reviewed_by"], ["id"], ondelete="SET NULL")

    op.create_table(
        "knowledge_health_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column("freshness_score", sa.Integer(), nullable=False),
        sa.Column("accuracy_score", sa.Integer(), nullable=False),
        sa.Column("completeness_score", sa.Integer(), nullable=False),
        sa.Column("staleness_score", sa.Integer(), nullable=False),
        sa.Column("integrity_score", sa.Integer(), nullable=False),
        sa.Column("action_items_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_health_snapshots_workspace_id"), "knowledge_health_snapshots", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_knowledge_health_snapshots_created_at"), "knowledge_health_snapshots", ["created_at"], unique=False)

    op.create_table(
        "knowledge_digests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("digest_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", "digest_date", name="uq_digest_workspace_user_date"),
    )
    op.create_index(op.f("ix_knowledge_digests_workspace_id"), "knowledge_digests", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_knowledge_digests_user_id"), "knowledge_digests", ["user_id"], unique=False)
    op.create_index(op.f("ix_knowledge_digests_digest_date"), "knowledge_digests", ["digest_date"], unique=False)

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("notification_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=True),
        sa.Column("target_id", sa.String(length=80), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifications_workspace_id"), "notifications", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
    op.create_index(op.f("ix_notifications_created_at"), "notifications", ["created_at"], unique=False)

    op.create_table(
        "flashcards",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("page_slug", sa.String(length=255), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("difficulty", sa.String(length=20), nullable=False),
        sa.Column("source_quote", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_flashcards_workspace_id"), "flashcards", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_flashcards_page_slug"), "flashcards", ["page_slug"], unique=False)
    op.create_index(op.f("ix_flashcards_source_hash"), "flashcards", ["source_hash"], unique=False)

    op.create_table(
        "flashcard_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("card_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("ease_factor", sa.Float(), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("repetitions", sa.Integer(), nullable=False),
        sa.Column("next_review_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_result", sa.String(length=20), nullable=True),
        sa.Column("result_history_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["flashcards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("card_id", "user_id", name="uq_flashcard_user_progress"),
    )
    op.create_index(op.f("ix_flashcard_reviews_card_id"), "flashcard_reviews", ["card_id"], unique=False)
    op.create_index(op.f("ix_flashcard_reviews_user_id"), "flashcard_reviews", ["user_id"], unique=False)
    op.create_index(op.f("ix_flashcard_reviews_next_review_date"), "flashcard_reviews", ["next_review_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_flashcard_reviews_next_review_date"), table_name="flashcard_reviews")
    op.drop_index(op.f("ix_flashcard_reviews_user_id"), table_name="flashcard_reviews")
    op.drop_index(op.f("ix_flashcard_reviews_card_id"), table_name="flashcard_reviews")
    op.drop_table("flashcard_reviews")
    op.drop_index(op.f("ix_flashcards_source_hash"), table_name="flashcards")
    op.drop_index(op.f("ix_flashcards_page_slug"), table_name="flashcards")
    op.drop_index(op.f("ix_flashcards_workspace_id"), table_name="flashcards")
    op.drop_table("flashcards")
    op.drop_index(op.f("ix_notifications_created_at"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_workspace_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_knowledge_digests_digest_date"), table_name="knowledge_digests")
    op.drop_index(op.f("ix_knowledge_digests_user_id"), table_name="knowledge_digests")
    op.drop_index(op.f("ix_knowledge_digests_workspace_id"), table_name="knowledge_digests")
    op.drop_table("knowledge_digests")
    op.drop_index(op.f("ix_knowledge_health_snapshots_created_at"), table_name="knowledge_health_snapshots")
    op.drop_index(op.f("ix_knowledge_health_snapshots_workspace_id"), table_name="knowledge_health_snapshots")
    op.drop_table("knowledge_health_snapshots")
    op.drop_constraint("fk_wiki_fact_events_reviewed_by_users", "wiki_fact_events", type_="foreignkey")
    op.drop_column("wiki_fact_events", "review_note")
    op.drop_column("wiki_fact_events", "reviewed_by")
    op.drop_column("wiki_fact_events", "reviewed_at")
    op.drop_column("wiki_fact_events", "review_status")
