from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]

# Load a developer-provided .env file at runtime if present. This ensures credentials
# and runtime secrets from `.env` are used. Do not fall back to `.env.example`.
try:
    from dotenv import load_dotenv

    env_path = BASE_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
except Exception:
    # dotenv not installed or load failed; rely on pydantic env_file fallback
    pass


class Settings(BaseSettings):
    app_name: str = "KnowForge"
    app_env: str = "local"
    app_debug: bool = False
    api_v1_prefix: str = "/api/v1"

    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_timeout_seconds: float = 40.0
    groq_max_completion_tokens: int = 2048
    groq_compile_max_completion_tokens: int = 6000  # higher limit for wiki compilation
    groq_compile_timeout_seconds: float = 120.0    # longer timeout for compilation

    knowforge_storage_path: str = "storage"
    max_pdf_upload_bytes: int = 100 * 1024 * 1024
    pdf_extract_char_limit: int = 1_200_000
    wiki_context_char_budget: int = 40_000
    chat_context_char_budget: int = 12_000
    chat_prompt_token_budget: int = 5_500
    chat_max_completion_tokens: int = 900
    wiki_page_soft_char_limit: int = 120_000
    wiki_compile_chunk_chars: int = 24_000
    wiki_compile_max_chunks: int = 24
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
        # Keep env_file configured but prefer the explicitly loaded .env above.
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()