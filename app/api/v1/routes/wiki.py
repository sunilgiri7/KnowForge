from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, wiki_store_for_user
from app.db.models import User
from app.llmwiki.compaction import WikiCompactor
from app.llmwiki.text import slugify
from app.schemas.llmwiki import WikiPage, WikiPageListItem, WikiPageUpsert

router = APIRouter(prefix="/wiki", tags=["wiki"])


@router.get("/index", response_model=dict[str, str])
async def read_index(user: Annotated[User, Depends(get_current_user)]) -> dict[str, str]:
    store = wiki_store_for_user(user)
    return {"index": store.read_index()}


@router.get("/pages", response_model=list[WikiPageListItem])
async def list_pages(user: Annotated[User, Depends(get_current_user)]) -> list[WikiPageListItem]:
    return wiki_store_for_user(user).list_pages()


@router.get("/pages/{slug:path}", response_model=WikiPage)
async def read_page(slug: str, user: Annotated[User, Depends(get_current_user)]) -> WikiPage:
    return wiki_store_for_user(user).read_page(slug)


@router.put("/pages/{slug:path}", response_model=WikiPage)
async def upsert_page(
    slug: str,
    payload: WikiPageUpsert,
    user: Annotated[User, Depends(get_current_user)],
) -> WikiPage:
    store = wiki_store_for_user(user)
    page = store.make_page(
        title=payload.title,
        slug=payload.slug or slugify(slug),
        summary=payload.summary,
        tags=payload.tags,
        source_ids=payload.source_ids,
        content=payload.content,
        confidence="high",
    )
    return store.upsert_page(page)


@router.post("/compact", response_model=dict[str, int])
async def compact_pages(user: Annotated[User, Depends(get_current_user)]) -> dict[str, int]:
    store = wiki_store_for_user(user)
    compactor = WikiCompactor(store)
    count = 0
    for item in store.list_pages():
        page = store.read_page(item.slug)
        if await compactor.compact_if_needed(page):
            count += 1
    return {"compacted": count}
