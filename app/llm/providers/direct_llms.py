from __future__ import annotations

from typing import Any

from app.llm.providers.anthropic_client import AnthropicClient
from app.llm.providers.bedrock_client import BedrockClient
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

    async def generate_json(
        self,
        prompt: str,
        *,
        temperature: float = 0.1,
        max_completion_tokens: int | None = None,
    ) -> dict[str, Any]:
        text = await self.generate_text(prompt, temperature=temperature, max_completion_tokens=max_completion_tokens)
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

    async def generate_json(
        self,
        prompt: str,
        *,
        temperature: float = 0.1,
        max_completion_tokens: int | None = None,
    ) -> dict[str, Any]:
        text = await self.generate_text(prompt, temperature=temperature, max_completion_tokens=max_completion_tokens)
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

    async def generate_json(
        self,
        prompt: str,
        *,
        temperature: float = 0.1,
        max_completion_tokens: int | None = None,
    ) -> dict[str, Any]:
        text = await self.generate_text(prompt, temperature=temperature, max_completion_tokens=max_completion_tokens)
        return GroqClient._parse_json(text)


class BedrockLlm:
    """AWS Bedrock LLM wrapper using the Converse API."""

    # Inference profile IDs are required for on-demand throughput.
    # Prefix matches the region: us. / eu. / ap.
    DEFAULT_MODEL  = "meta.llama3-70b-instruct-v1:0"
    DEFAULT_REGION = "us-east-1"

    def __init__(
        self,
        *,
        access_key_id: str,
        secret_access_key: str,
        region: str = "us-east-1",
        model: str | None = None,
    ):
        self.client = BedrockClient(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region=region or self.DEFAULT_REGION,
        )
        self.model = model or self.DEFAULT_MODEL

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
        try:
            return await self.client.converse(
                model_id=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_completion_tokens or 1024,
            )
        except RuntimeError as exc:
            message = str(exc).lower()
            should_retry_default = (
                self.model != self.DEFAULT_MODEL
                and (
                    "model identifier is invalid" in message
                    or "model" in message and "not found" in message
                    or "requires an inference profile" in message
                )
            )
            if not should_retry_default:
                raise
            print(f"[Bedrock] Model '{self.model}' failed; retrying default '{self.DEFAULT_MODEL}'.")
            return await self.client.converse(
                model_id=self.DEFAULT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_completion_tokens or 1024,
            )

    async def generate_json(
        self,
        prompt: str,
        *,
        temperature: float = 0.1,
        max_completion_tokens: int | None = None,
    ) -> dict[str, Any]:
        text = await self.generate_text(prompt, temperature=temperature, max_completion_tokens=max_completion_tokens)
        return GroqClient._parse_json(text)
