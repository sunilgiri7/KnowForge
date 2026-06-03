from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy.orm import Session

from app.db.models import User
from app.llm.providers.direct_llms import AnthropicLlm, BedrockLlm, GeminiLlm, OpenAILlm
from app.llm.providers.openrouter_llm import OpenRouterLlm
from app.llmwiki.groq import GroqClient
from app.services.llm_keys import (
    get_bedrock_credentials,
    get_user_llm_key,
    get_user_llm_key_plaintext,
)


@runtime_checkable
class JsonLlm(Protocol):
    @property
    def available(self) -> bool: ...

    async def generate_text(
        self,
        prompt: str,
        *,
        temperature: float = 0.2,
        max_completion_tokens: int | None = None,
    ) -> str: ...

    async def generate_json(
        self,
        prompt: str,
        *,
        temperature: float = 0.1,
        max_completion_tokens: int | None = None,
    ) -> dict: ...


class PreferredLlmWithFallback:
    """Try the user connected LLM first, then fall back to the system Groq LLM."""

    def __init__(self, primary: JsonLlm | None, fallback: JsonLlm | None = None):
        self.primary = primary
        self.fallback = fallback or GroqClient()

    @property
    def available(self) -> bool:
        return bool(
            (self.primary and self.primary.available)
            or (self.fallback and self.fallback.available)
        )

    async def generate_text(
        self,
        prompt: str,
        *,
        temperature: float = 0.2,
        max_completion_tokens: int | None = None,
    ) -> str:
        if self.primary and self.primary.available:
            try:
                return await self.primary.generate_text(
                    prompt,
                    temperature=temperature,
                    max_completion_tokens=max_completion_tokens,
                )
            except Exception as exc:
                print(f"[LLM] User provider failed, falling back to system Groq: {exc}")
        if self.fallback and self.fallback.available:
            return await self.fallback.generate_text(
                prompt,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
            )
        raise RuntimeError("No user or system LLM provider is configured.")

    async def generate_json(
        self,
        prompt: str,
        *,
        temperature: float = 0.1,
        max_completion_tokens: int | None = None,
    ) -> dict:
        if self.primary and self.primary.available:
            try:
                return await self.primary.generate_json(
                    prompt,
                    temperature=temperature,
                    max_completion_tokens=max_completion_tokens,
                )
            except Exception as exc:
                print(f"[LLM] User provider JSON call failed, falling back to system Groq: {exc}")
        if self.fallback and self.fallback.available:
            return await self.fallback.generate_json(
                prompt,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
            )
        raise RuntimeError("No user or system LLM provider is configured.")


def build_user_llm(db: Session, user: User) -> JsonLlm | None:
    provider = (user.llm_active_provider or "openrouter").strip()
    primary: JsonLlm | None = None

    if provider == "bedrock":
        creds = get_bedrock_credentials(db, user=user)
        if creds:
            access_key_id, secret_access_key, region, model_id = creds
            primary = BedrockLlm(
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
                region=region,
                model=model_id,
            )
        return PreferredLlmWithFallback(primary)

    record = get_user_llm_key(db, user=user, provider=provider)
    if not record:
        return PreferredLlmWithFallback(None)
    api_key = get_user_llm_key_plaintext(db, user=user, provider=provider)
    if not api_key:
        return PreferredLlmWithFallback(None)

    if provider == "openrouter":
        primary = OpenRouterLlm(api_key=api_key, model=(record.model or None))
    elif provider == "openai":
        primary = OpenAILlm(api_key=api_key, model=(record.model or "gpt-4o-mini"))
    elif provider == "anthropic":
        primary = AnthropicLlm(api_key=api_key, model=(record.model or "claude-3-5-sonnet-latest"))
    elif provider == "gemini":
        primary = GeminiLlm(api_key=api_key, model=(record.model or "gemini-2.0-flash"))

    return PreferredLlmWithFallback(primary)
