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

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "knowforge"
    db_user: str = "knowforge"
    db_password: str = "knowforge"
    database_url: str | None = None

    jwt_secret_key: str = "change-this-local-secret"
    jwt_algorithm: str = "HS256"
    jwt_access_token_minutes: int = 60 * 24

    verification_code_minutes: int = 15
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "noreply@knowforge.local"
    smtp_use_tls: bool = True

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
