from __future__ import annotations

from typing import Any

from app.llm.providers.anthropic_client import AnthropicClient
from app.llm.providers.gemini_client import GeminiClient
from app.llm.providers.openai_client import OpenAIClient
from app.llmwiki.groq import GroqClient


class OpenAILlm:
    def __init__(self, *, api_key: str, model: str):
        self.client = OpenAIClient(api_key=api_key)
        self.model = model

    @property
    def available(self) -> bool:
        return True

    async def generate_text(self, prompt: str, *, temperature: float = 0.2, max_completion_tokens: int | None = None) -> str:
        return await self.client.chat_completions(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_completion_tokens,
        )

    async def generate_json(self, prompt: str, *, temperature: float = 0.1) -> dict[str, Any]:
        text = await self.generate_text(prompt, temperature=temperature)
        return GroqClient._parse_json(text)


class AnthropicLlm:
    def __init__(self, *, api_key: str, model: str):
        self.client = AnthropicClient(api_key=api_key)
        self.model = model

    @property
    def available(self) -> bool:
        return True

    async def generate_text(self, prompt: str, *, temperature: float = 0.2, max_completion_tokens: int | None = None) -> str:
        return await self.client.messages_create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_completion_tokens or 900,
        )

    async def generate_json(self, prompt: str, *, temperature: float = 0.1) -> dict[str, Any]:
        text = await self.generate_text(prompt, temperature=temperature)
        return GroqClient._parse_json(text)


class GeminiLlm:
    def __init__(self, *, api_key: str, model: str):
        self.client = GeminiClient(api_key=api_key)
        self.model = model

    @property
    def available(self) -> bool:
        return True

    async def generate_text(self, prompt: str, *, temperature: float = 0.2, max_completion_tokens: int | None = None) -> str:
        return await self.client.generate_content(
            model=self.model,
            text=prompt,
            temperature=temperature,
            max_output_tokens=max_completion_tokens,
        )

    async def generate_json(self, prompt: str, *, temperature: float = 0.1) -> dict[str, Any]:
        text = await self.generate_text(prompt, temperature=temperature)
        return GroqClient._parse_json(text)

