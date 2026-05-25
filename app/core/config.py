from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "KnowForge"
    app_env: str = "local"
    app_debug: bool = False
    api_v1_prefix: str = "/api/v1"

    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_timeout_seconds: float = 40.0
    groq_max_completion_tokens: int = 2048

    knowforge_storage_path: str = "storage"
    max_pdf_upload_bytes: int = 5 * 1024 * 1024
    wiki_context_char_budget: int = 24_000
    wiki_page_soft_char_limit: int = 50_000
    chat_history_char_budget: int = 6_000
    chat_history_keep_last: int = 6

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
