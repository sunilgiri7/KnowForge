from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from app.core.config import settings


class GroqClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_completion_tokens: int | None = None,
    ):
        self.api_key = api_key if api_key is not None else settings.groq_api_key
        self.model = model or settings.groq_model
        self.max_completion_tokens = max_completion_tokens or settings.groq_max_completion_tokens

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    async def generate_text(self, prompt: str, *, temperature: float = 0.2) -> str:
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not configured.")
        return await asyncio.wait_for(
            asyncio.to_thread(self._generate_text_sync, prompt, temperature),
            timeout=settings.groq_timeout_seconds,
        )

    async def generate_json(self, prompt: str, *, temperature: float = 0.1) -> dict[str, Any]:
        text = await self.generate_text(prompt, temperature=temperature)
        return self._parse_json(text)

    def _generate_text_sync(self, prompt: str, temperature: float) -> str:
        from groq import Groq

        client = Groq(api_key=self.api_key)
        completion = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_completion_tokens=self.max_completion_tokens,
            top_p=1,
            stream=True,
            stop=None,
        )
        chunks: list[str] = []
        for chunk in completion:
            chunks.append(chunk.choices[0].delta.content or "")
        return "".join(chunks)

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))