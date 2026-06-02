import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import KnowForgeError
from app.db.models import User
from app.db.session import get_db
from app.llm.providers.anthropic_client import AnthropicClient
from app.llm.providers.bedrock_client import BedrockClient
from app.llm.providers.gemini_client import GeminiClient
from app.llm.providers.openai_client import OpenAIClient
from app.llm.providers.openrouter_client import OpenRouterChatMessage
from app.llm.providers.registry import build_chat_model
from app.schemas.llmwiki import LlmKeyStatus, LlmKeyUpsertRequest
from app.services.llm_keys import (
    decode_bedrock_model_field,
    delete_user_llm_key,
    encode_bedrock_credentials,
    encode_bedrock_model_field,
    get_user_llm_key,
    set_active_llm_provider,
    set_user_llm_model,
    upsert_user_llm_key,
)

router = APIRouter(prefix="/llm", tags=["llm"])

SUPPORTED_PROVIDERS = ["openrouter", "openai", "anthropic", "gemini", "bedrock"]


@router.get("/keys", response_model=list[LlmKeyStatus])
async def list_keys(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[LlmKeyStatus]:
    items: list[LlmKeyStatus] = []
    for provider in SUPPORTED_PROVIDERS:
        record = get_user_llm_key(db, user=user, provider=provider)
        # For bedrock, extract a human-readable model from the stored model field
        display_model = ""
        if record and record.model:
            if provider == "bedrock":
                _, model_id = decode_bedrock_model_field(record.model)
                display_model = model_id
            else:
                display_model = record.model
        items.append(
            LlmKeyStatus(
                provider=provider,  # type: ignore[arg-type]
                connected=bool(record),
                model=display_model,
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
    model = (payload.model or "").strip()

    # Validate key via a tiny test call before storing
    try:
        if provider == "openrouter":
            api_key = payload.api_key.strip()
            client = build_chat_model(provider, api_key=api_key)
            text = await client.chat_completions(
                messages=[OpenRouterChatMessage(role="user", content="ping")],
                max_tokens=5,
                temperature=0.0,
                timeout_seconds=20,
            )
        elif provider == "openai":
            api_key = payload.api_key.strip()
            client = OpenAIClient(api_key=api_key)
            text = await client.chat_completions(
                model=model or "gpt-4o-mini",
                messages=[{"role": "user", "content": "ping"}],
                temperature=0.0,
                max_tokens=5,
                timeout_seconds=20,
            )
        elif provider == "anthropic":
            api_key = payload.api_key.strip()
            client = AnthropicClient(api_key=api_key)
            text = await client.messages_create(
                model=model or "claude-3-5-sonnet-latest",
                messages=[{"role": "user", "content": "ping"}],
                temperature=0.0,
                max_tokens=8,
                timeout_seconds=20,
            )
        elif provider == "gemini":
            api_key = payload.api_key.strip()
            client = GeminiClient(api_key=api_key)
            text = await client.generate_content(
                model=model or "gemini-2.0-flash",
                text="ping",
                temperature=0.0,
                max_output_tokens=8,
                timeout_seconds=20,
            )
        elif provider == "bedrock":
            access_key_id = payload.api_key.strip()
            secret_access_key = (payload.aws_secret_access_key or "").strip()
            aws_region = (payload.aws_region or "ap-south-1").strip() or "ap-south-1"

            if not secret_access_key:
                raise KnowForgeError(
                    "AWS Secret Access Key is required for Bedrock.",
                    code="llm_key_validation_failed",
                    status_code=400,
                )

            bedrock_client = BedrockClient(
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
                region=aws_region,
            )
            # Validate credentials first, then invoke the selected model so an
            # invalid model id or missing Bedrock model access is caught at connect time.
            await asyncio.to_thread(bedrock_client.validate_credentials)
            bedrock_model = model or "meta.llama3-70b-instruct-v1:0"
            text = await bedrock_client.converse(
                model_id=bedrock_model,
                messages=[{"role": "user", "content": "ping"}],
                temperature=0.0,
                max_tokens=8,
                timeout_seconds=20,
            )
        else:
            raise KnowForgeError("Unsupported provider.", code="llm_provider_unsupported")

        if not text and provider != "bedrock":
            raise KnowForgeError(
                "Provider returned an empty response.", code="llm_key_validation_failed"
            )
    except KnowForgeError:
        raise
    except Exception as exc:
        # BedrockClient already returns clean messages; other providers may not
        err_msg = str(exc)
        raise KnowForgeError(
            err_msg,
            status_code=400,
            code="llm_key_validation_failed",
        ) from exc

    # Persist credentials
    if provider == "bedrock":
        access_key_id = payload.api_key.strip()
        secret_access_key = (payload.aws_secret_access_key or "").strip()
        aws_region = (payload.aws_region or "ap-south-1").strip() or "ap-south-1"
        # Pick the correct inference profile prefix for the region
        rprefix = "us" if aws_region.startswith("us-") or aws_region.startswith("ca-") else \
                  "eu" if aws_region.startswith("eu-") else \
                  "ap" if aws_region.startswith("ap-") else "us"
        bedrock_model = model or f"{rprefix}.anthropic.claude-3-5-haiku-20241022-v1:0"

        # Store combined credentials: ACCESS_KEY_ID<|>SECRET_ACCESS_KEY
        combined_key = encode_bedrock_credentials(access_key_id, secret_access_key)
        upsert_user_llm_key(db, user=user, provider=provider, api_key=combined_key)
        # Store region + model in the model column
        model_field = encode_bedrock_model_field(aws_region, bedrock_model)
        set_user_llm_model(db, user=user, provider=provider, model=model_field)
        set_active_llm_provider(db, user=user, provider=provider)
        db.commit()
        return LlmKeyStatus(
            provider=provider,  # type: ignore[arg-type]
            connected=True,
            model=bedrock_model,
            active=True,
        )

    # Standard providers
    api_key = payload.api_key.strip()
    upsert_user_llm_key(db, user=user, provider=provider, api_key=api_key)
    if model:
        set_user_llm_model(db, user=user, provider=provider, model=model)
    set_active_llm_provider(db, user=user, provider=provider)
    db.commit()
    return LlmKeyStatus(provider=provider, connected=True, model=model, active=True)  # type: ignore[arg-type]


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

    if provider == "bedrock":
        # model field for bedrock stores region+model; patch only the model part
        record = get_user_llm_key(db, user=user, provider=provider)
        if not record:
            raise KnowForgeError("Connect an API key first.", status_code=400, code="llm_key_missing")
        existing_region, _ = decode_bedrock_model_field(record.model or "")
        new_model_field = encode_bedrock_model_field(existing_region or "us-east-1", model)
        ok = set_user_llm_model(db, user=user, provider=provider, model=new_model_field)
        if not ok:
            raise KnowForgeError("Connect an API key first.", status_code=400, code="llm_key_missing")
        db.commit()
        return LlmKeyStatus(
            provider=provider,  # type: ignore[arg-type]
            connected=True,
            model=model,
            active=(user.llm_active_provider == provider),
        )

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
    if provider not in set(SUPPORTED_PROVIDERS):
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
