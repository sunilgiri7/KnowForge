"""
routes/versions.py — Wiki version history, diff, and semantic diff API.
"""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_active_workspace_dep, get_current_user, wiki_store_for_workspace
from app.core.errors import KnowForgeError
from app.db.models import User, Workspace
from app.db.session import get_db
from app.llmwiki.groq import GroqClient
from app.llmwiki.temporal import WikiVersionLedger, compute_semantic_diff
from app.schemas.workspace import WikiDiffHunk, WikiSemanticDiff, WikiVersionDetail, WikiVersionListItem

router = APIRouter(prefix="/wiki", tags=["wiki-versions"])


@router.get("/pages/{slug:path}/versions", response_model=list[WikiVersionListItem])
def list_page_versions(
    slug: str,
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WikiVersionListItem]:
    ledger = WikiVersionLedger(db)
    _, versions = ledger.get_versions(workspace_id=workspace.id, slug=slug)
    return [
        WikiVersionListItem(
            id=v.id,
            version_number=v.version_number,
            content_hash=v.content_hash,
            summary=v.summary,
            created_reason=v.created_reason,
            created_by_name=v.creator.name if v.creator else None,
            created_at=v.created_at,
        )
        for v in reversed(versions)
    ]


@router.get("/pages/{slug:path}/versions/{version_number:int}", response_model=WikiVersionDetail)
def get_page_version(
    slug: str,
    version_number: int,
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> WikiVersionDetail:
    ledger = WikiVersionLedger(db)
    v = ledger.get_version_by_number(
        workspace_id=workspace.id, slug=slug, version_number=version_number
    )
    if not v:
        raise KnowForgeError("Version not found.", status_code=404, code="version_not_found")
    return WikiVersionDetail(
        id=v.id,
        version_number=v.version_number,
        content_hash=v.content_hash,
        summary=v.summary,
        created_reason=v.created_reason,
        created_by_name=v.creator.name if v.creator else None,
        created_at=v.created_at,
        content=v.content,
        tags=json.loads(v.tags_json or "[]"),
        entities=json.loads(v.entities_json or "[]"),
        source_ids=json.loads(v.source_ids_json or "[]"),
    )


@router.get("/pages/{slug:path}/diff", response_model=WikiSemanticDiff)
async def get_page_diff(
    slug: str,
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
    from_version: int = Query(..., alias="from"),
    to_version: int = Query(..., alias="to"),
) -> WikiSemanticDiff:
    ledger = WikiVersionLedger(db)
    v_from = ledger.get_version_by_number(
        workspace_id=workspace.id, slug=slug, version_number=from_version
    )
    v_to = ledger.get_version_by_number(
        workspace_id=workspace.id, slug=slug, version_number=to_version
    )
    if not v_from or not v_to:
        raise KnowForgeError("One or both versions not found.", status_code=404, code="version_not_found")

    llm = GroqClient()
    diff_data = await compute_semantic_diff(
        old_content=v_from.content,
        new_content=v_to.content,
        from_version=from_version,
        to_version=to_version,
        llm=llm,
    )
    return WikiSemanticDiff(
        from_version=diff_data["from_version"],
        to_version=diff_data["to_version"],
        line_hunks=[WikiDiffHunk(**h) for h in diff_data["line_hunks"]],
        semantic_summary=diff_data["semantic_summary"],
        changed_facts=diff_data["changed_facts"],
        risk_level=diff_data["risk_level"],  # type: ignore[arg-type]
    )
