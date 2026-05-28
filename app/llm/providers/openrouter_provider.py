from __future__ import annotations

from app.llm.providers.openrouter_client import OpenRouterClient


def build_openrouter_chat(*, api_key: str) -> OpenRouterClient:
    return OpenRouterClient(api_key=api_key)

