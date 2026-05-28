from __future__ import annotations

from typing import Literal

from app.llm.providers.openrouter_provider import build_openrouter_chat

LlmProvider = Literal["openrouter"]


def build_chat_model(
    provider: LlmProvider,
    *,
    api_key: str,
):
    if provider == "openrouter":
        return build_openrouter_chat(api_key=api_key)
    raise ValueError(f"Unsupported provider: {provider}")

