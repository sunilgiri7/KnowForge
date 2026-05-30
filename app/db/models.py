from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Users & Auth
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    llm_active_provider: Mapped[str] = mapped_column(String(40), default="openrouter", nullable=False)
    # The workspace a user is currently working in
    active_workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    sessions: Mapped[list[ChatSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    workspace_memberships: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="WorkspaceMember.user_id"
    )


class EmailVerificationCode(Base):
    __tablename__ = "email_verification_codes"
    __table_args__ = (UniqueConstraint("user_id", "code", name="uq_user_verification_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(12), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UserLlmKey(Base):
    __tablename__ = "user_llm_keys"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_llm_provider"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    encrypted_key: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


# ---------------------------------------------------------------------------
# Workspaces & RBAC
# ---------------------------------------------------------------------------


class Workspace(Base):
    """A team workspace. Each user gets a personal 'default' workspace on signup."""

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    is_personal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    members: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    page_records: Mapped[list[WikiPageRecord]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMember(Base):
    """Maps users to workspaces with an RBAC role."""

    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Roles: owner > admin > editor > viewer
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="workspace_memberships", foreign_keys=[user_id])


class WorkspaceInvite(Base):
    """A pending email invite to join a workspace."""

    __tablename__ = "workspace_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    invited_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(36), index=True)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Sessions are now scoped to a workspace (nullable for backward compat)
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(180), default="New chat")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="sessions")
    messages: Mapped[list[ChatMessageRecord]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessageRecord.created_at",
    )


class ChatMessageRecord(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    interaction: Mapped[str] = mapped_column(String(20), default="message", nullable=False)
    route: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


# ---------------------------------------------------------------------------
# Wiki Version Ledger
# ---------------------------------------------------------------------------


class WikiPageRecord(Base):
    """One logical wiki page per workspace. The canonical slug identity."""

    __tablename__ = "wiki_page_records"
    __table_args__ = (UniqueConstraint("workspace_id", "slug", name="uq_workspace_page_slug"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255))
    # Points to the currently active version row
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # draft | approved | superseded | archived
    status: Mapped[str] = mapped_column(String(20), default="approved", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    workspace: Mapped[Workspace] = relationship(back_populates="page_records")
    versions: Mapped[list[WikiPageVersion]] = relationship(
        back_populates="page_record",
        cascade="all, delete-orphan",
        order_by="WikiPageVersion.version_number",
    )


class WikiPageVersion(Base):
    """Immutable snapshot of a page at a point in time. Never mutated once written."""

    __tablename__ = "wiki_page_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    page_record_id: Mapped[str] = mapped_column(
        ForeignKey("wiki_page_records.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")        # JSON array
    entities_json: Mapped[str] = mapped_column(Text, default="[]")    # JSON array
    source_ids_json: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Reason: compilation | manual_edit | rename | promotion | migration
    created_reason: Mapped[str] = mapped_column(String(50), default="compilation", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    page_record: Mapped[WikiPageRecord] = relationship(back_populates="versions")
    creator: Mapped[User | None] = relationship(foreign_keys=[created_by])


class WikiSupersessionLink(Base):
    """Records that one page (old_slug) was superseded by another (new_slug)."""

    __tablename__ = "wiki_supersession_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    old_slug: Mapped[str] = mapped_column(String(255), index=True)
    new_slug: Mapped[str] = mapped_column(String(255), index=True)
    # supersedes | replaces | amends | deprecates
    link_type: Mapped[str] = mapped_column(String(40), default="supersedes", nullable=False)
    detected_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


# ---------------------------------------------------------------------------
# Temporal Fact Events
# ---------------------------------------------------------------------------


class WikiFactEvent(Base):
    """
    A single extracted temporal fact from a wiki page.
    Enables time-aware Q&A: 'what was the policy as of March 2026?'
    """

    __tablename__ = "wiki_fact_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    page_slug: Mapped[str] = mapped_column(String(255), index=True)
    # effective_date | deadline | price_rate | assignment | policy_period | publication_date | other
    fact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[str] = mapped_column(String(255))
    predicate: Mapped[str] = mapped_column(String(255))
    object_val: Mapped[str] = mapped_column(Text)
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiration_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_quote: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


# ---------------------------------------------------------------------------
# Q&A → Knowledge Promotion
# ---------------------------------------------------------------------------


class WikiPromotion(Base):
    """
    A user-promoted chat answer that is staged for wiki inclusion.
    Approval states: draft | approved | rejected
    """

    __tablename__ = "wiki_promotions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    proposed_title: Mapped[str] = mapped_column(String(255), nullable=False)
    proposed_slug: Mapped[str] = mapped_column(String(255), nullable=False)
    proposed_content: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_tags_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    promoted_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    reviewed_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    review_note: Mapped[str] = mapped_column(Text, default="")
    target_page_slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    promoter: Mapped[User] = relationship(foreign_keys=[promoted_by])
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewed_by])


# ---------------------------------------------------------------------------
# Report Generator
# ---------------------------------------------------------------------------


class ReportTemplate(Base):
    """
    A reusable extraction template. Defines what fields to pull
    and from which page scopes, plus the export format.
    """

    __tablename__ = "report_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    # JSON: list of {key, label, instruction} column definitions
    columns_json: Mapped[str] = mapped_column(Text, default="[]")
    # JSON: list of {heading, instruction} section definitions (for DOCX/PDF)
    sections_json: Mapped[str] = mapped_column(Text, default="[]")
    # JSON: list of page slugs to scope extraction (empty = all pages)
    scope_slugs_json: Mapped[str] = mapped_column(Text, default="[]")
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ReportJob(Base):
    """
    A single report generation run against a template.
    Stores the extracted table and the path of the exported file.
    """

    __tablename__ = "report_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[str] = mapped_column(
        ForeignKey("report_templates.id", ondelete="CASCADE"), index=True
    )
    # pending | processing | done | failed
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    # JSON: list of extracted row dicts {col_key: {value, confidence, source_slug, quote}}
    results_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional JSON list of slugs chosen for this specific run.
    scope_slugs_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Relative path under storage root for the exported file
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # pdf | xlsx | docx
    export_format: Mapped[str] = mapped_column(String(10), default="xlsx", nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    template: Mapped[ReportTemplate] = relationship(foreign_keys=[template_id])
    creator: Mapped[User | None] = relationship(foreign_keys=[created_by])


# ---------------------------------------------------------------------------
# Tier 3: Research Intelligence Models
# ---------------------------------------------------------------------------


class ResearchPaper(Base):
    __tablename__ = "research_papers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    authors: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of author names
    venue: Mapped[str | None] = mapped_column(String(255), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    slug: Mapped[str] = mapped_column(String(255), index=True)  # Matches compiled wiki slug
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    sections: Mapped[list[ResearchPaperSection]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )
    methods: Mapped[list[ResearchMethod]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )
    claims: Mapped[list[ResearchClaim]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )


class ResearchPaperSection(Base):
    __tablename__ = "research_paper_sections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    paper_id: Mapped[str] = mapped_column(ForeignKey("research_papers.id", ondelete="CASCADE"), index=True)
    heading: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    section_type: Mapped[str] = mapped_column(String(50))  # e.g., introduction, methodology, results, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    paper: Mapped[ResearchPaper] = relationship(back_populates="sections")


class ResearchMethod(Base):
    __tablename__ = "research_methods"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("research_papers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_used: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    paper: Mapped[ResearchPaper] = relationship(back_populates="methods")


class ResearchClaim(Base):
    __tablename__ = "research_claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("research_papers.id", ondelete="CASCADE"), index=True)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="finding")  # finding, limitation, hypothesis, gap
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    grounding_level: Mapped[str] = mapped_column(String(40), default="fully_supported")  # fully_supported, partially_supported, unsupported
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    paper: Mapped[ResearchPaper] = relationship(back_populates="claims")


class ResearchPaperEdge(Base):
    __tablename__ = "research_paper_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    source_paper_id: Mapped[str] = mapped_column(ForeignKey("research_papers.id", ondelete="CASCADE"), index=True)
    target_paper_id: Mapped[str] = mapped_column(ForeignKey("research_papers.id", ondelete="CASCADE"), index=True)
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)  # cites, extends, contradicts, uses_method, baseline
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ResearchInsight(Base):
    __tablename__ = "research_insights"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    insight_type: Mapped[str] = mapped_column(String(50), nullable=False)  # comparison_matrix, literature_gap
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_json: Mapped[str] = mapped_column(Text, default="{}")  # JSON payload structure
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ResearchAnalysisJob(Base):
    __tablename__ = "research_analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("research_papers.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | processing | done | failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
