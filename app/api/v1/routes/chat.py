from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, wiki_store_for_user
from app.db.models import User
from app.db.session import get_db
from app.llmwiki.chat import ChatService
from app.schemas.llmwiki import ChatRequest, ChatResponse, ChatSessionItem, ChatSessionMessages
from app.services.chat_sessions import (
    add_message,
    compact_session_if_needed,
    get_or_create_session,
    get_session_messages,
    history_for_session,
    list_user_sessions,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatResponse:
    session = get_or_create_session(db, user, request.session_id, request.question)
    request.session_id = session.id
    request.user_context = (
        "The user is authenticated and may ask about their own profile, background, or uploaded "
        "wiki documents. Prefer relevant user-specific wiki pages when answering personal questions."
    )
    request.messages = history_for_session(db, session)
    add_message(db, user=user, session=session, role="user", content=request.question)
    response = await ChatService(wiki_store_for_user(user)).answer(request)
    add_message(
        db,
        user=user,
        session=session,
        role="assistant",
        content=response.answer,
        route=response.route,
    )
    compact_session_if_needed(db, session)
    db.commit()
    response.session_id = session.id
    return response


@router.get("/sessions", response_model=list[ChatSessionItem])
async def sessions(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ChatSessionItem]:
    return list_user_sessions(db, user)


@router.get("/sessions/{session_id}", response_model=ChatSessionMessages)
async def session_messages(
    session_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatSessionMessages:
    return get_session_messages(db, user, session_id)
