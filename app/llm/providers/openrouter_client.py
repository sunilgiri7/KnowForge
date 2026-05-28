from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.core.config import settings


@dataclass
class OpenRouterChatMessage:
    role: str
    content: str


class OpenRouterClient:
    def __init__(self, *, api_key: str, base_url: str = "https://openrouter.ai/api/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def chat_completions(
        self,
        *,
        model: str | None = None,
        messages: list[OpenRouterChatMessage],
        temperature: float = 0.2,
        max_tokens: int | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or settings.openrouter_default_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # Recommended attribution headers (safe defaults)
            "HTTP-Referer": "http://localhost",
            "X-OpenRouter-Title": settings.app_name,
        }
        if extra_headers:
            headers.update(extra_headers)

        body = json.dumps(payload).encode("utf-8")

        def _do_request() -> str:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout_seconds or 45) as resp:
                    raw = resp.read().decode("utf-8", errors="ignore")
            except urllib.error.HTTPError as e:
                error_body = ""
                try:
                    error_body = e.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
                raise RuntimeError(f"OpenRouter HTTP {e.code}: {error_body or e.reason}") from e
            except Exception as e:
                raise RuntimeError(f"OpenRouter request failed: {e}") from e

            data = json.loads(raw)
            # OpenAI-compatible: choices[0].message.content
            return (
                (data.get("choices") or [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

        return await asyncio.to_thread(_do_request)

