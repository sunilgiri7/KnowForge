from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import KnowForgeError
from app.core.mailer import send_verification_email
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import EmailVerificationCode, User, utc_now
from app.schemas.llmwiki import AuthTokenResponse, UserProfile


def normalize_email(email: str) -> str:
    return email.strip().lower()


def register_user(db: Session, *, name: str, email: str, password: str) -> User:
    clean_email = normalize_email(email)
    existing = db.scalar(select(User).where(User.email == clean_email))
    if existing:
        raise KnowForgeError("An account already exists for this email.", code="email_exists")
    user = User(name=name.strip(), email=clean_email, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    create_and_send_code(db, user)
    db.commit()
    db.refresh(user)
    return user


def create_and_send_code(db: Session, user: User) -> None:
    db.query(EmailVerificationCode).filter(
        EmailVerificationCode.user_id == user.id,
        EmailVerificationCode.consumed_at.is_(None),
    ).update({"consumed_at": utc_now()})
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.verification_code_minutes)
    db.add(EmailVerificationCode(user_id=user.id, code=code, expires_at=expires_at))
    send_verification_email(user.email, code)


def verify_email(db: Session, *, email: str, code: str) -> User:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if not user:
        raise KnowForgeError("Account not found.", status_code=404, code="user_not_found")
    if user.is_verified:
        return user
    verification = db.scalar(
        select(EmailVerificationCode)
        .where(
            EmailVerificationCode.user_id == user.id,
            EmailVerificationCode.code == code.strip(),
            EmailVerificationCode.consumed_at.is_(None),
        )
        .order_by(EmailVerificationCode.created_at.desc())
    )
    if not verification:
        raise KnowForgeError("Invalid verification code.", code="invalid_verification_code")
    expires_at = verification.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        raise KnowForgeError("Verification code has expired.", code="verification_code_expired")
    verification.consumed_at = utc_now()
    user.is_verified = True
    db.commit()
    db.refresh(user)
    return user


def resend_code(db: Session, *, email: str) -> None:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if not user:
        raise KnowForgeError("Account not found.", status_code=404, code="user_not_found")
    if user.is_verified:
        raise KnowForgeError("This account is already verified.", code="already_verified")
    create_and_send_code(db, user)
    db.commit()


def login_user(db: Session, *, email: str, password: str) -> AuthTokenResponse:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if not user or not verify_password(password, user.password_hash):
        raise KnowForgeError("Invalid email or password.", status_code=401, code="invalid_login")
    if not user.is_verified:
        raise KnowForgeError(
            "Please verify your email before logging in.",
            status_code=403,
            code="email_unverified",
        )
    return AuthTokenResponse(access_token=create_access_token(user.id), user=profile_for_user(user))


def profile_for_user(user: User) -> UserProfile:
    return UserProfile(id=user.id, name=user.name, email=user.email, is_verified=user.is_verified)
