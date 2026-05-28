from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.db.models import User, UserLlmKey


def _utc_now() -> datetime:
    return datetime.now(UTC)


def get_user_llm_key(db: Session, *, user: User, provider: str) -> UserLlmKey | None:
    return db.scalar(
        select(UserLlmKey).where(UserLlmKey.user_id == user.id, UserLlmKey.provider == provider)
    )


def get_user_llm_key_plaintext(db: Session, *, user: User, provider: str) -> str | None:
    record = get_user_llm_key(db, user=user, provider=provider)
    if not record:
        return None
    return decrypt_secret(record.encrypted_key, secret=settings.llm_key_encryption_secret)


def get_user_llm_model(db: Session, *, user: User, provider: str) -> str | None:
    record = get_user_llm_key(db, user=user, provider=provider)
    if not record:
        return None
    return (record.model or "").strip() or None


def upsert_user_llm_key(db: Session, *, user: User, provider: str, api_key: str) -> None:
    encrypted = encrypt_secret(api_key, secret=settings.llm_key_encryption_secret)
    record = get_user_llm_key(db, user=user, provider=provider)
    if record:
        record.encrypted_key = encrypted
        record.updated_at = _utc_now()
        return
    db.add(
        UserLlmKey(
            user_id=user.id,
            provider=provider,
            encrypted_key=encrypted,
            model="",
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
    )


def set_user_llm_model(db: Session, *, user: User, provider: str, model: str) -> bool:
    record = get_user_llm_key(db, user=user, provider=provider)
    if not record:
        return False
    record.model = (model or "").strip()
    record.updated_at = _utc_now()
    return True


def delete_user_llm_key(db: Session, *, user: User, provider: str) -> bool:
    record = get_user_llm_key(db, user=user, provider=provider)
    if not record:
        return False
    db.delete(record)
    return True

