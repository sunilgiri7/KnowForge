from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import KnowForgeError
from app.db.models import User
from app.db.session import get_db
from app.llm.providers.anthropic_client import AnthropicClient
from app.llm.providers.gemini_client import GeminiClient
from app.llm.providers.openai_client import OpenAIClient
from app.llm.providers.openrouter_client import OpenRouterChatMessage
from app.llm.providers.registry import build_chat_model
from app.schemas.llmwiki import LlmKeyStatus, LlmKeyUpsertRequest
from app.services.llm_keys import (
    delete_user_llm_key,
    get_user_llm_key,
    set_active_llm_provider,
    set_user_llm_model,
    upsert_user_llm_key,
)

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/keys", response_model=list[LlmKeyStatus])
async def list_keys(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[LlmKeyStatus]:
    supported = ["openrouter", "openai", "anthropic", "gemini"]
    items: list[LlmKeyStatus] = []
    for provider in supported:
        record = get_user_llm_key(db, user=user, provider=provider)
        items.append(
            LlmKeyStatus(
                provider=provider,  # type: ignore[arg-type]
                connected=bool(record),
                model=(record.model if record else ""),
                active=(user.llm_active_provider == provider),
            )
        )
    return items


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
        if provider == "openrouter":
            client = build_chat_model(provider, api_key=api_key)
            text = await client.chat_completions(
                messages=[OpenRouterChatMessage(role="user", content="ping")],
                max_tokens=5,
                temperature=0.0,
                timeout_seconds=20,
            )
        elif provider == "openai":
            client = OpenAIClient(api_key=api_key)
            text = await client.chat_completions(
                model=model or "gpt-4o-mini",
                messages=[{"role": "user", "content": "ping"}],
                temperature=0.0,
                max_tokens=5,
                timeout_seconds=20,
            )
        elif provider == "anthropic":
            client = AnthropicClient(api_key=api_key)
            text = await client.messages_create(
                model=model or "claude-3-5-sonnet-latest",
                messages=[{"role": "user", "content": "ping"}],
                temperature=0.0,
                max_tokens=8,
                timeout_seconds=20,
            )
        elif provider == "gemini":
            client = GeminiClient(api_key=api_key)
            text = await client.generate_content(
                model=model or "gemini-2.0-flash",
                text="ping",
                temperature=0.0,
                max_output_tokens=8,
                timeout_seconds=20,
            )
        else:
            raise KnowForgeError("Unsupported provider.", code="llm_provider_unsupported")
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
    set_active_llm_provider(db, user=user, provider=provider)
    db.commit()
    return LlmKeyStatus(provider=provider, connected=True, model=model, active=True)


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
    return LlmKeyStatus(provider=provider, connected=True, model=model, active=(user.llm_active_provider == provider))  # type: ignore[arg-type]


@router.patch("/active-provider", response_model=dict[str, str])
async def set_active_provider(
    payload: dict[str, str],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    provider = (payload.get("provider") or "").strip()
    if provider not in {"openrouter", "openai", "anthropic", "gemini"}:
        raise KnowForgeError("Unsupported provider.", code="llm_provider_unsupported")
    record = get_user_llm_key(db, user=user, provider=provider)
    if not record:
        raise KnowForgeError("Connect an API key first.", status_code=400, code="llm_key_missing")
    set_active_llm_provider(db, user=user, provider=provider)
    db.commit()
    return {"provider": provider}


@router.delete("/keys/{provider}", response_model=dict[str, bool])
async def delete_key(
    provider: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, bool]:
    deleted = delete_user_llm_key(db, user=user, provider=provider)
    db.commit()
    return {"deleted": bool(deleted)}

