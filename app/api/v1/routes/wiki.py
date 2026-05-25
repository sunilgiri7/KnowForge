from fastapi import APIRouter

from app.llmwiki.compaction import WikiCompactor
from app.llmwiki.storage import WikiStore
from app.llmwiki.text import slugify
from app.schemas.llmwiki import WikiPage, WikiPageListItem, WikiPageUpsert

router = APIRouter(prefix="/wiki", tags=["wiki"])


@router.get("/index", response_model=dict[str, str])
async def read_index() -> dict[str, str]:
    store = WikiStore()
    return {"index": store.read_index()}


@router.get("/pages", response_model=list[WikiPageListItem])
async def list_pages() -> list[WikiPageListItem]:
    return WikiStore().list_pages()


@router.get("/pages/{slug:path}", response_model=WikiPage)
async def read_page(slug: str) -> WikiPage:
    return WikiStore().read_page(slug)


@router.put("/pages/{slug:path}", response_model=WikiPage)
async def upsert_page(slug: str, payload: WikiPageUpsert) -> WikiPage:
    store = WikiStore()
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
async def compact_pages() -> dict[str, int]:
    store = WikiStore()
    compactor = WikiCompactor(store)
    count = 0
    for item in store.list_pages():
        page = store.read_page(item.slug)
        if await compactor.compact_if_needed(page):
            count += 1
    return {"compacted": count}
