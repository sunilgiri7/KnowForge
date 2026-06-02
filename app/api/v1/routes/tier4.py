from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_active_workspace_dep, get_current_user, wiki_store_for_workspace
from app.core.config import settings
from app.core.errors import KnowForgeError
from app.db.models import User, Workspace
from app.db.session import get_db
from app.services.tier4 import (
    DailyDigestService,
    FactTimelineService,
    FlashcardService,
    KnowledgeHealthScorer,
    NotificationService,
    digest_out,
)
from app.services.workspace import get_member, require_role

router = APIRouter(tags=["tier4"])


class FactReviewRequest(BaseModel):
    review_note: str = Field(default="", max_length=2000)


class FactBulkReviewRequest(BaseModel):
    status: str = Field(default="all", max_length=20)
    days_ahead: int = Field(default=90, ge=1, le=365)
    review_note: str = Field(default="Reviewed in bulk from timeline", max_length=2000)


class FlashcardGenerateRequest(BaseModel):
    page_slugs: list[str] = Field(default_factory=list, max_length=50)


class FlashcardReviewRequest(BaseModel):
    result: Literal["again", "hard", "easy"]


def _member(db: Session, workspace: Workspace, user: User):
    return get_member(db, workspace_id=workspace.id, user_id=user.id)


@router.get("/wiki/facts/timeline", response_model=dict)
async def fact_timeline(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    days_ahead: int = 90,
    status: str = "all",
) -> dict:
    require_role(_member(db, workspace, user), "viewer")
    if status not in {"all", "expired", "expiring", "current", "undated", "reviewed"}:
        raise KnowForgeError("Invalid timeline status filter.", status_code=400, code="invalid_status")
    days_ahead = max(1, min(days_ahead, 365))
    return FactTimelineService(db).list_timeline(workspace_id=workspace.id, days_ahead=days_ahead, status=status)


@router.patch("/wiki/facts/review-bulk", response_model=dict)
async def review_facts_bulk(
    payload: FactBulkReviewRequest,
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    require_role(_member(db, workspace, user), "editor")
    if payload.status not in {"all", "expired", "expiring", "current", "undated"}:
        raise KnowForgeError("Invalid timeline status filter.", status_code=400, code="invalid_status")
    return FactTimelineService(db).mark_many_reviewed(
        workspace_id=workspace.id,
        user_id=user.id,
        status=payload.status,
        days_ahead=payload.days_ahead,
        review_note=payload.review_note,
    )


@router.patch("/wiki/facts/{fact_id}/review", response_model=dict)
async def review_fact(
    fact_id: str,
    payload: FactReviewRequest,
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    require_role(_member(db, workspace, user), "editor")
    result = FactTimelineService(db).mark_reviewed(
        fact_id=fact_id,
        workspace_id=workspace.id,
        user_id=user.id,
        review_note=payload.review_note,
    )
    if not result:
        raise KnowForgeError("Fact not found.", status_code=404, code="fact_not_found")
    return result


@router.get("/wiki/health", response_model=dict)
async def wiki_health(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    require_role(_member(db, workspace, user), "viewer")
    return KnowledgeHealthScorer(db, wiki_store_for_workspace(workspace)).calculate(workspace_id=workspace.id, persist=False)


@router.post("/wiki/health/recalculate", response_model=dict)
async def recalculate_wiki_health(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    require_role(_member(db, workspace, user), "viewer")
    return KnowledgeHealthScorer(db, wiki_store_for_workspace(workspace)).calculate(workspace_id=workspace.id, persist=True)


@router.get("/notifications", response_model=dict)
async def notifications(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    require_role(_member(db, workspace, user), "viewer")
    return NotificationService(db).list_for_user(workspace_id=workspace.id, user_id=user.id)


@router.patch("/notifications/{notification_id}/read", response_model=dict)
async def read_notification(
    notification_id: str,
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    require_role(_member(db, workspace, user), "viewer")
    row = NotificationService(db).mark_read(notification_id=notification_id, workspace_id=workspace.id, user_id=user.id)
    if not row:
        raise KnowForgeError("Notification not found.", status_code=404, code="notification_not_found")
    return NotificationService._out(row)


@router.get("/digests/latest", response_model=dict | None)
async def latest_digest(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict | None:
    require_role(_member(db, workspace, user), "viewer")
    return digest_out(DailyDigestService(db, wiki_store_for_workspace(workspace)).latest_for_user(workspace_id=workspace.id, user_id=user.id))


@router.post("/digests/generate", response_model=dict)
async def generate_digest(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    require_role(_member(db, workspace, user), "viewer")
    row = DailyDigestService(db, wiki_store_for_workspace(workspace)).generate_for_user(workspace=workspace, user=user, send_email=settings.tier4_digest_email_enabled)
    return digest_out(row) or {}


@router.get("/flashcards/due", response_model=list[dict])
async def due_flashcards(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict]:
    require_role(_member(db, workspace, user), "viewer")
    return FlashcardService(db, wiki_store_for_workspace(workspace)).due(workspace_id=workspace.id, user_id=user.id)


@router.post("/flashcards/generate", response_model=dict)
async def generate_flashcards(
    payload: FlashcardGenerateRequest,
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    require_role(_member(db, workspace, user), "editor")
    slugs = payload.page_slugs or None
    return FlashcardService(db, wiki_store_for_workspace(workspace)).generate(workspace_id=workspace.id, user_id=user.id, page_slugs=slugs)


@router.post("/flashcards/{card_id}/review", response_model=dict)
async def review_flashcard(
    card_id: str,
    payload: FlashcardReviewRequest,
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    require_role(_member(db, workspace, user), "viewer")
    result = FlashcardService(db, wiki_store_for_workspace(workspace)).review(card_id=card_id, workspace_id=workspace.id, user_id=user.id, result=payload.result)
    if not result:
        raise KnowForgeError("Flashcard not found.", status_code=404, code="flashcard_not_found")
    return result


@router.get("/flashcards/stats", response_model=dict)
async def flashcard_stats(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    require_role(_member(db, workspace, user), "viewer")
    return FlashcardService(db, wiki_store_for_workspace(workspace)).stats(workspace_id=workspace.id, user_id=user.id)
