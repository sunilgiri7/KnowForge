from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.db.models import User, UserLlmKey

# Delimiter used to join/split the AWS Bedrock combined credentials stored
# in encrypted_key: "ACCESS_KEY_ID<|>SECRET_ACCESS_KEY"
_BEDROCK_KEY_SEP = "<|>"
# Delimiter used in the model field for bedrock: "region<|>model_id"
_BEDROCK_MODEL_SEP = "<|>"


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


# ── Bedrock-specific helpers ──────────────────────────────────────────────────


def encode_bedrock_credentials(access_key_id: str, secret_access_key: str) -> str:
    """Encode both AWS keys as a single string for encrypted storage."""
    return f"{access_key_id}{_BEDROCK_KEY_SEP}{secret_access_key}"


def decode_bedrock_credentials(combined: str) -> tuple[str, str]:
    """Decode combined credential string → (access_key_id, secret_access_key)."""
    parts = combined.split(_BEDROCK_KEY_SEP, 1)
    if len(parts) != 2:
        raise ValueError("Invalid Bedrock credential format in storage.")
    return parts[0], parts[1]


def encode_bedrock_model_field(region: str, model_id: str) -> str:
    """Encode region + model_id into the model column."""
    return f"{region}{_BEDROCK_MODEL_SEP}{model_id}"


def decode_bedrock_model_field(value: str) -> tuple[str, str]:
    """Decode model column → (region, model_id) for Bedrock."""
    parts = value.split(_BEDROCK_MODEL_SEP, 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    # Legacy: just model ID, use default region
    return "us-east-1", value


def get_bedrock_credentials(db: Session, *, user: User) -> tuple[str, str, str, str] | None:
    """
    Returns (access_key_id, secret_access_key, region, model_id) or None.
    """
    record = get_user_llm_key(db, user=user, provider="bedrock")
    if not record:
        return None
    combined = decrypt_secret(record.encrypted_key, secret=settings.llm_key_encryption_secret)
    if not combined:
        return None
    access_key_id, secret_access_key = decode_bedrock_credentials(combined)
    region, model_id = decode_bedrock_model_field(record.model or "")
    if not region:
        region = "us-east-1"
    if not model_id:
        model_id = "meta.llama3-70b-instruct-v1:0"
    return access_key_id, secret_access_key, region, model_id


# ── Generic CRUD helpers ──────────────────────────────────────────────────────


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


def set_active_llm_provider(db: Session, *, user: User, provider: str) -> None:
    user.llm_active_provider = provider
    db.add(user)


def delete_user_llm_key(db: Session, *, user: User, provider: str) -> bool:
    record = get_user_llm_key(db, user=user, provider=provider)
    if not record:
        return False
    db.delete(record)
    return True
