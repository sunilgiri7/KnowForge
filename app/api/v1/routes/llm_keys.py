from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import KnowForgeError
from app.db.models import User
from app.db.session import get_db
from app.llm.providers.openrouter_client import OpenRouterChatMessage
from app.llm.providers.registry import build_chat_model
from app.schemas.llmwiki import LlmKeyStatus, LlmKeyUpsertRequest
from app.services.llm_keys import (
    delete_user_llm_key,
    get_user_llm_key,
    set_user_llm_model,
    upsert_user_llm_key,
)

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/keys", response_model=list[LlmKeyStatus])
async def list_keys(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[LlmKeyStatus]:
    # For now only OpenRouter is supported
    record = get_user_llm_key(db, user=user, provider="openrouter")
    return [
        LlmKeyStatus(provider="openrouter", connected=bool(record), model=(record.model if record else ""))
    ]


@router.put("/keys", response_model=LlmKeyStatus)
async def upsert_key(
    payload: LlmKeyUpsertRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> LlmKeyStatus:
    provider = payload.provider
    api_key = payload.api_key.strip()
    model = (payload.model or "").strip()

    # Validate key via a tiny test call before storing
    try:
        client = build_chat_model(provider, api_key=api_key)
        text = await client.chat_completions(
            messages=[OpenRouterChatMessage(role="user", content="ping")],
            max_tokens=5,
            temperature=0.0,
            timeout_seconds=20,
        )
        if not text:
            raise KnowForgeError("Provider returned an empty response.", code="llm_key_validation_failed")
    except KnowForgeError:
        raise
    except Exception as exc:
        raise KnowForgeError(
            f"Could not validate provider key: {exc}",
            status_code=400,
            code="llm_key_validation_failed",
        ) from exc

    upsert_user_llm_key(db, user=user, provider=provider, api_key=api_key)
    if model:
        set_user_llm_model(db, user=user, provider=provider, model=model)
    db.commit()
    return LlmKeyStatus(provider=provider, connected=True, model=model)


@router.patch("/keys/{provider}/model", response_model=LlmKeyStatus)
async def update_model(
    provider: str,
    payload: dict[str, str],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> LlmKeyStatus:
    model = (payload.get("model") or "").strip()
    if not model:
        raise KnowForgeError("Model is required.", code="llm_model_required")
    ok = set_user_llm_model(db, user=user, provider=provider, model=model)
    if not ok:
        raise KnowForgeError("Connect an API key first.", status_code=400, code="llm_key_missing")
    db.commit()
    return LlmKeyStatus(provider="openrouter", connected=True, model=model)


@router.delete("/keys/{provider}", response_model=dict[str, bool])
async def delete_key(
    provider: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, bool]:
    deleted = delete_user_llm_key(db, user=user, provider=provider)
    db.commit()
    return {"deleted": bool(deleted)}

