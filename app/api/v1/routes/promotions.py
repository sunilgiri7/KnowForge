"""
routes/promotions.py — Q&A → Wiki promotion workflow.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_active_workspace_dep, get_current_user, wiki_store_for_workspace
from app.core.errors import KnowForgeError
from app.db.models import User, WikiPromotion, Workspace
from app.db.session import get_db
from app.llmwiki.markdown import now_iso
from app.llmwiki.temporal import WikiVersionLedger
from app.llmwiki.text import slugify
from app.schemas.workspace import PromotionCreate, PromotionOut, PromotionReview
from app.services.workspace import get_member, require_role

router = APIRouter(prefix="/promotions", tags=["promotions"])


def _promo_out(p: WikiPromotion) -> PromotionOut:
    return PromotionOut(
        id=p.id,
        proposed_title=p.proposed_title,
        proposed_slug=p.proposed_slug,
        proposed_content=p.proposed_content,
        proposed_tags=json.loads(p.proposed_tags_json or "[]"),
        status=p.status,  # type: ignore[arg-type]
        promoted_by_name=p.promoter.name if p.promoter else "Unknown",
        target_page_slug=p.target_page_slug,
        review_note=p.review_note,
        created_at=p.created_at,
        reviewed_at=p.reviewed_at,
    )


@router.post("", response_model=PromotionOut, status_code=201)
def create_promotion(
    payload: PromotionCreate,
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> PromotionOut:
    member = get_member(db, workspace_id=workspace.id, user_id=user.id)
    require_role(member, "editor")

    slug = payload.proposed_slug or slugify(payload.proposed_title)
    promo = WikiPromotion(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        session_id=payload.session_id,
        message_id=payload.message_id,
        proposed_title=payload.proposed_title,
        proposed_slug=slug,
        proposed_content=payload.proposed_content,
        proposed_tags_json=json.dumps(payload.proposed_tags),
        status="draft",
        promoted_by=user.id,
        target_page_slug=payload.target_page_slug,
    )
    db.add(promo)
    db.commit()
    db.refresh(promo)
    return _promo_out(promo)


@router.get("", response_model=list[PromotionOut])
def list_promotions(
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> list[PromotionOut]:
    member = get_member(db, workspace_id=workspace.id, user_id=user.id)
    require_role(member, "viewer")
    promos = (
        db.query(WikiPromotion)
        .filter_by(workspace_id=workspace.id)
        .order_by(WikiPromotion.created_at.desc())
        .limit(100)
        .all()
    )
    return [_promo_out(p) for p in promos]


@router.post("/{promotion_id}/review", response_model=PromotionOut)
async def review_promotion(
    promotion_id: str,
    payload: PromotionReview,
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> PromotionOut:
    member = get_member(db, workspace_id=workspace.id, user_id=user.id)
    require_role(member, "admin")

    promo: WikiPromotion | None = db.get(WikiPromotion, promotion_id)
    if not promo or promo.workspace_id != workspace.id:
        raise KnowForgeError("Promotion not found.", status_code=404, code="promotion_not_found")
    if promo.status != "draft":
        raise KnowForgeError(
            f"Promotion is already {promo.status}.",
            status_code=400,
            code="already_reviewed",
        )

    promo.status = payload.status
    promo.review_note = payload.review_note
    promo.reviewed_by = user.id
    promo.reviewed_at = datetime.now(UTC)
    db.commit()

    # If approved, write to wiki store and record version
    if payload.status == "approved":
        store = wiki_store_for_workspace(workspace)
        tags = json.loads(promo.proposed_tags_json or "[]")
        page = store.make_page(
            title=promo.proposed_title,
            slug=promo.proposed_slug,
            content=promo.proposed_content,
            tags=tags,
            confidence="medium",
        )
        page.meta.last_compiled_at = now_iso()
        if promo.target_page_slug:
            try:
                existing = store.read_page(promo.target_page_slug)
                existing.content = existing.content.rstrip() + "\n\n## Team Notes\n\n" + promo.proposed_content
                page = store.upsert_page(existing)
            except Exception:
                page = store.upsert_page(page)
        else:
            page = store.upsert_page(page)

        # Record version
        ledger = WikiVersionLedger(db)
        ledger.record_version(
            page=page,
            workspace_id=workspace.id,
            created_by=user.id,
            created_reason="promotion",
        )

    db.refresh(promo)
    return _promo_out(promo)
