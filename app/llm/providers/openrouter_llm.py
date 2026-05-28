from __future__ import annotations

from typing import Any

from app.llm.providers.openrouter_client import OpenRouterChatMessage, OpenRouterClient
from app.llmwiki.groq import GroqClient


class OpenRouterLlm:
    def __init__(self, *, api_key: str, model: str | None = None):
        self.client = OpenRouterClient(api_key=api_key)
        self.model = model

    @property
    def available(self) -> bool:
        return True

    async def generate_text(
        self,
        prompt: str,
        *,
        temperature: float = 0.2,
        max_completion_tokens: int | None = None,
    ) -> str:
        return await self.client.chat_completions(
            model=self.model,
            messages=[OpenRouterChatMessage(role="user", content=prompt)],
            temperature=temperature,
            max_tokens=max_completion_tokens,
        )

    async def generate_json(self, prompt: str, *, temperature: float = 0.1) -> dict[str, Any]:
        text = await self.generate_text(prompt, temperature=temperature)
        return GroqClient._parse_json(text)

