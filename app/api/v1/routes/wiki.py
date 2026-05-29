from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, wiki_store_for_workspace, get_active_workspace_dep
from app.db.models import User, Workspace
from app.db.session import get_db
from app.llmwiki.compaction import WikiCompactor
from app.llmwiki.contradictions import ContradictionStore
from app.llmwiki.temporal import WikiVersionLedger
from app.llmwiki.text import slugify
from app.schemas.llmwiki import WikiPage, WikiPageListItem, WikiPageRename, WikiPageUpsert
from app.services.workspace import get_member, require_role

router = APIRouter(prefix="/wiki", tags=["wiki"])


@router.get("/index", response_model=dict[str, str])
async def read_index(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    require_role(get_member(db, workspace_id=workspace.id, user_id=user.id), "viewer")
    store = wiki_store_for_workspace(workspace)
    return {"index": store.read_index()}


@router.get("/pages", response_model=list[WikiPageListItem])
async def list_pages(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WikiPageListItem]:
    require_role(get_member(db, workspace_id=workspace.id, user_id=user.id), "viewer")
    store = wiki_store_for_workspace(workspace)
    pages = store.list_pages()
    conflict_counts = ContradictionStore(store).open_count_by_slug()
    return [
        page.model_copy(
            update={"open_conflict_count": conflict_counts.get(page.slug, 0)}
        )
        for page in pages
    ]


@router.get("/pages/{slug:path}", response_model=WikiPage)
async def read_page(
    slug: str,
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WikiPage:
    require_role(get_member(db, workspace_id=workspace.id, user_id=user.id), "viewer")
    return wiki_store_for_workspace(workspace).read_page(slug)


@router.put("/pages/{slug:path}", response_model=WikiPage)
async def upsert_page(
    slug: str,
    payload: WikiPageUpsert,
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WikiPage:
    require_role(get_member(db, workspace_id=workspace.id, user_id=user.id), "editor")
    store = wiki_store_for_workspace(workspace)
    page = store.make_page(
        title=payload.title,
        slug=payload.slug or slugify(slug),
        summary=payload.summary,
        tags=payload.tags,
        source_ids=payload.source_ids,
        entities=payload.entities,
        related_slugs=payload.related_slugs,
        content=payload.content,
        confidence="high",
    )
    saved = store.upsert_page(page)
    WikiVersionLedger(db).record_version(
        page=saved,
        workspace_id=workspace.id,
        created_by=user.id,
        created_reason="manual_edit",
    )
    return saved


@router.patch("/pages/{slug:path}", response_model=WikiPage)
async def rename_page(
    slug: str,
    payload: WikiPageRename,
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WikiPage:
    require_role(get_member(db, workspace_id=workspace.id, user_id=user.id), "editor")
    page = wiki_store_for_workspace(workspace).rename_page(slug, payload.title)
    WikiVersionLedger(db).record_version(
        page=page,
        workspace_id=workspace.id,
        created_by=user.id,
        created_reason="rename",
    )
    return page


@router.delete("/pages/{slug:path}", response_model=dict[str, bool])
async def delete_page(
    slug: str,
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, bool]:
    require_role(get_member(db, workspace_id=workspace.id, user_id=user.id), "editor")
    wiki_store_for_workspace(workspace).delete_page(slug)
    return {"deleted": True}


@router.post("/compact", response_model=dict[str, int])
async def compact_pages(
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int]:
    require_role(get_member(db, workspace_id=workspace.id, user_id=user.id), "editor")
    store = wiki_store_for_workspace(workspace)
    compactor = WikiCompactor(store)
    count = 0
    for item in store.list_pages():
        page = store.read_page(item.slug)
        if await compactor.compact_if_needed(page):
            count += 1
    return {"compacted": count}
