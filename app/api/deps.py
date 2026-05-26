from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import KnowForgeError
from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db
from app.llmwiki.storage import WikiStore

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if not credentials:
        raise KnowForgeError("Login is required.", status_code=401, code="auth_required")
    user_id = decode_access_token(credentials.credentials)
    user = db.get(User, user_id)
    if not user:
        raise KnowForgeError("User account was not found.", status_code=401, code="invalid_token")
    if not user.is_verified:
        raise KnowForgeError(
            "Email verification is required.",
            status_code=403,
            code="email_unverified",
        )
    return user


def wiki_store_for_user(user: User) -> WikiStore:
    return WikiStore().for_user(user.id)
