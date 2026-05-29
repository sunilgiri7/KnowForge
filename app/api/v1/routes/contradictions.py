from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, wiki_store_for_user
from app.db.models import User
from app.llmwiki.contradictions import ContradictionScanner, ContradictionStore
from app.llmwiki.groq import GroqClient
from app.schemas.llmwiki import (
    ContradictionScanResponse,
    ContradictionStatusUpdate,
    WikiContradiction,
)

router = APIRouter(prefix="/wiki/contradictions", tags=["contradictions"])


@router.get("", response_model=list[WikiContradiction])
async def list_contradictions(
    user: Annotated[User, Depends(get_current_user)],
    *,
    open_only: bool = True,
) -> list[WikiContradiction]:
    store = ContradictionStore(wiki_store_for_user(user))
    return store.list_open() if open_only else store.list_all()


@router.post("/scan", response_model=ContradictionScanResponse)
async def scan_contradictions(
    user: Annotated[User, Depends(get_current_user)],
) -> ContradictionScanResponse:
    wiki_store = wiki_store_for_user(user)
    scanner = ContradictionScanner(wiki_store, GroqClient())
    scanned_pairs, new_conflicts = await scanner.scan()
    records = ContradictionStore(wiki_store)
    open_items = records.list_open()
    return ContradictionScanResponse(
        scanned_pairs=scanned_pairs,
        new_conflicts=new_conflicts,
        open_conflicts=len(open_items),
        contradictions=open_items,
    )


@router.patch("/{contradiction_id}", response_model=WikiContradiction)
async def update_contradiction_status(
    contradiction_id: str,
    payload: ContradictionStatusUpdate,
    user: Annotated[User, Depends(get_current_user)],
) -> WikiContradiction:
    store = ContradictionStore(wiki_store_for_user(user))
    updated = store.update_status(contradiction_id, payload.status)
    if not updated:
        from app.core.errors import KnowForgeError

        raise KnowForgeError(
            "Contradiction not found.",
            status_code=404,
            code="contradiction_not_found",
        )
    return updated
