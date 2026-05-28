from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any


class AnthropicClient:
    def __init__(self, *, api_key: str, base_url: str = "https://api.anthropic.com"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def messages_create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 1024,
        timeout_seconds: float = 45,
        anthropic_version: str = "2023-06-01",
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        url = f"{self.base_url}/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": anthropic_version,
            "content-type": "application/json",
        }
        body = json.dumps(payload).encode("utf-8")

        def _do() -> str:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                    raw = resp.read().decode("utf-8", errors="ignore")
            except urllib.error.HTTPError as e:
                err = ""
                try:
                    err = e.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
                raise RuntimeError(f"Anthropic HTTP {e.code}: {err or e.reason}") from e
            data = json.loads(raw)
            # Claude response: content is list of blocks; text blocks have {type:"text", text:"..."}
            content = data.get("content") or []
            parts = [block.get("text", "") for block in content if isinstance(block, dict)]
            return "\n".join(part for part in parts if part).strip()

        return await asyncio.to_thread(_do)

