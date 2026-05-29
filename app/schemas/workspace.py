"""
schemas/workspace.py — Pydantic models for Tier 2 features:
  Workspaces, RBAC, Wiki Versions/Diff, Promotions, Reports.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

WorkspaceRole = Literal["owner", "admin", "editor", "viewer"]
PageStatus = Literal["draft", "approved", "superseded", "archived"]
PromotionStatus = Literal["draft", "approved", "rejected"]
ReportFormat = Literal["pdf", "xlsx", "docx"]
JobStatus = Literal["pending", "processing", "done", "failed"]


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class WorkspaceOut(BaseModel):
    id: str
    name: str
    slug: str
    is_personal: bool
    created_at: datetime
    your_role: WorkspaceRole | None = None


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceOut]
    active_workspace_id: str | None = None


class WorkspaceMemberOut(BaseModel):
    id: str
    user_id: str
    user_name: str
    user_email: str
    role: WorkspaceRole
    created_at: datetime


class InviteCreate(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    role: WorkspaceRole = "editor"


class InviteOut(BaseModel):
    id: str
    email: str
    role: WorkspaceRole
    code: str
    expires_at: datetime
    created_at: datetime


class WorkspaceSwitchRequest(BaseModel):
    workspace_id: str


class MemberRoleUpdate(BaseModel):
    role: WorkspaceRole


# ---------------------------------------------------------------------------
# Wiki Version Ledger
# ---------------------------------------------------------------------------


class WikiVersionListItem(BaseModel):
    id: str
    version_number: int
    content_hash: str
    summary: str
    created_reason: str
    created_by_name: str | None = None
    created_at: datetime


class WikiVersionDetail(WikiVersionListItem):
    content: str
    tags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class WikiDiffHunk(BaseModel):
    kind: Literal["equal", "insert", "delete", "replace"]
    old_lines: list[str] = Field(default_factory=list)
    new_lines: list[str] = Field(default_factory=list)


class WikiSemanticDiff(BaseModel):
    from_version: int
    to_version: int
    line_hunks: list[WikiDiffHunk] = Field(default_factory=list)
    # LLM-produced human summary of what actually changed
    semantic_summary: str = ""
    changed_facts: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"


# ---------------------------------------------------------------------------
# Promotions
# ---------------------------------------------------------------------------


class PromotionCreate(BaseModel):
    session_id: str | None = None
    message_id: str | None = None
    proposed_title: str = Field(min_length=2, max_length=255)
    proposed_slug: str | None = None
    proposed_content: str = Field(min_length=10)
    proposed_tags: list[str] = Field(default_factory=list)
    # If set, content is appended to this existing page instead of creating a new one
    target_page_slug: str | None = None


class PromotionReview(BaseModel):
    status: Literal["approved", "rejected"]
    review_note: str = ""


class PromotionOut(BaseModel):
    id: str
    proposed_title: str
    proposed_slug: str
    proposed_content: str
    proposed_tags: list[str] = Field(default_factory=list)
    status: PromotionStatus
    promoted_by_name: str
    target_page_slug: str | None = None
    review_note: str = ""
    created_at: datetime
    reviewed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Report Templates & Jobs
# ---------------------------------------------------------------------------


class ReportColumnDef(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=120)
    instruction: str = Field(min_length=1)


class ReportSectionDef(BaseModel):
    heading: str = Field(min_length=1, max_length=120)
    instruction: str = Field(min_length=1)


class ReportTemplateCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = ""
    columns: list[ReportColumnDef] = Field(min_length=1)
    sections: list[ReportSectionDef] = Field(default_factory=list)
    scope_slugs: list[str] = Field(default_factory=list)


class ReportTemplateOut(BaseModel):
    id: str
    name: str
    description: str
    columns: list[ReportColumnDef]
    sections: list[ReportSectionDef]
    scope_slugs: list[str]
    created_at: datetime


class ReportGenerateRequest(BaseModel):
    template_id: str
    export_format: ReportFormat = "xlsx"
    # Override scope slugs for this run only
    scope_slugs: list[str] = Field(default_factory=list)


class ExtractedCell(BaseModel):
    value: str
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source_slug: str | None = None
    quote: str | None = None


class ExtractedRow(BaseModel):
    page_slug: str
    page_title: str
    cells: dict[str, ExtractedCell]


class ReportJobOut(BaseModel):
    id: str
    template_id: str
    template_name: str | None = None
    status: JobStatus
    export_format: ReportFormat
    results: list[ExtractedRow] | None = None
    error_message: str | None = None
    file_path: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
