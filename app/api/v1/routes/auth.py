from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.llmwiki import (
    AuthMessageResponse,
    AuthTokenResponse,
    ResendCodeRequest,
    UserLoginRequest,
    UserProfile,
    UserRegisterRequest,
    VerifyEmailRequest,
)
from app.services.auth import login_user, profile_for_user, register_user, resend_code, verify_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthMessageResponse)
async def register(payload: UserRegisterRequest, db: Annotated[Session, Depends(get_db)]):
    register_user(db, name=payload.name, email=payload.email, password=payload.password)
    return AuthMessageResponse(
        message="Account created. Check your email for the verification code."
    )


@router.post("/verify-email", response_model=AuthMessageResponse)
async def verify(payload: VerifyEmailRequest, db: Annotated[Session, Depends(get_db)]):
    verify_email(db, email=payload.email, code=payload.code)
    return AuthMessageResponse(message="Email verified. You can now log in.")


@router.post("/resend-code", response_model=AuthMessageResponse)
async def resend(payload: ResendCodeRequest, db: Annotated[Session, Depends(get_db)]):
    resend_code(db, email=payload.email)
    return AuthMessageResponse(message="A fresh verification code has been sent.")


@router.post("/login", response_model=AuthTokenResponse)
async def login(payload: UserLoginRequest, db: Annotated[Session, Depends(get_db)]):
    return login_user(db, email=payload.email, password=payload.password)


@router.get("/me", response_model=UserProfile)
async def me(user: Annotated[User, Depends(get_current_user)]):
    return profile_for_user(user)
