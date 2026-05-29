from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy.orm import Session

from app.db.models import User
from app.llm.providers.direct_llms import AnthropicLlm, GeminiLlm, OpenAILlm
from app.llm.providers.openrouter_llm import OpenRouterLlm
from app.services.llm_keys import get_user_llm_key, get_user_llm_key_plaintext


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

    async def generate_json(self, prompt: str, *, temperature: float = 0.1) -> dict: ...


def build_user_llm(db: Session, user: User) -> JsonLlm | None:
    provider = (user.llm_active_provider or "openrouter").strip()
    record = get_user_llm_key(db, user=user, provider=provider)
    if not record:
        return None
    api_key = get_user_llm_key_plaintext(db, user=user, provider=provider)
    if not api_key:
        return None
    if provider == "openrouter":
        return OpenRouterLlm(api_key=api_key, model=(record.model or None))
    if provider == "openai":
        return OpenAILlm(api_key=api_key, model=(record.model or "gpt-4o-mini"))
    if provider == "anthropic":
        return AnthropicLlm(api_key=api_key, model=(record.model or "claude-3-5-sonnet-latest"))
    if provider == "gemini":
        return GeminiLlm(api_key=api_key, model=(record.model or "gemini-2.0-flash"))
    return None
