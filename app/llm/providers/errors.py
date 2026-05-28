from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import KnowForgeError


@dataclass(frozen=True)
class ProviderErrorInfo:
    code: str
    message: str
    status_code: int = 400


def normalize_provider_error(exc: Exception) -> KnowForgeError:
    msg = str(exc) or exc.__class__.__name__
    lowered = msg.lower()
    if "401" in lowered or "unauthorized" in lowered or "invalid api key" in lowered:
        info = ProviderErrorInfo("llm_key_invalid", "API key invalid or revoked.", 401)
    elif "403" in lowered or "forbidden" in lowered:
        info = ProviderErrorInfo("llm_key_forbidden", "Provider rejected this request.", 403)
    elif "429" in lowered or "rate limit" in lowered or "too many requests" in lowered:
        info = ProviderErrorInfo("llm_rate_limited", "Rate limit reached. Please try again shortly.", 429)
    elif "timeout" in lowered or "timed out" in lowered:
        info = ProviderErrorInfo("llm_timeout", "Provider timed out. Please try again.", 504)
    elif "not found" in lowered and "model" in lowered:
        info = ProviderErrorInfo("llm_model_unavailable", "Model unavailable. Choose another model.", 400)
    else:
        info = ProviderErrorInfo("llm_provider_error", "LLM provider error. Please try again.", 502)
    return KnowForgeError(info.message, status_code=info.status_code, code=info.code)

