from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class GeminiClient:
    def __init__(self, *, api_key: str, base_url: str = "https://generativelanguage.googleapis.com"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def generate_content(
        self,
        *,
        model: str,
        text: str,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        timeout_seconds: float = 45,
    ) -> str:
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"temperature": temperature},
        }
        if max_output_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = max_output_tokens

        path = f"/v1beta/models/{model}:generateContent"
        url = f"{self.base_url}{path}?{urllib.parse.urlencode({'key': self.api_key})}"
        headers = {"Content-Type": "application/json"}
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
                raise RuntimeError(f"Gemini HTTP {e.code}: {err or e.reason}") from e
            data = json.loads(raw)
            candidates = data.get("candidates") or []
            if not candidates:
                return ""
            parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
            texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
            return "\n".join(t for t in texts if t).strip()

        return await asyncio.to_thread(_do)

