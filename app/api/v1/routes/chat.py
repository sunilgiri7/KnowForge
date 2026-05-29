from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, wiki_store_for_workspace, get_active_workspace_dep
from app.db.models import User, Workspace
from app.db.session import get_db
from app.llmwiki.chat import ChatService
from app.schemas.llmwiki import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatSessionItem,
    ChatSessionMessages,
    ChatSessionUpdate,
)
from app.services.chat_sessions import (
    add_message,
    compact_session_if_needed,
    delete_session,
    get_or_create_session,
    get_session_messages,
    history_for_session,
    list_user_sessions,
    rename_session_title,
    session_item,
    thread_context_for_parent,
)
from app.services.llm_factory import build_user_llm

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatResponse:
    session = get_or_create_session(db, user, request.session_id, request.question, workspace.id)
    request.session_id = session.id
    if request.parent_id and request.interaction == "message":
        request.interaction = "reply"
    thread_context = thread_context_for_parent(db, user, session, request.parent_id)
    request.messages = history_for_session(db, session)
    if thread_context:
        request.messages.append(ChatMessage(role="system", content=thread_context))
    user_message = add_message(
        db,
        user=user,
        session=session,
        role="user",
        content=request.question,
        parent_id=request.parent_id,
        interaction=request.interaction,
    )
    user_llm = build_user_llm(db, user)
    if request.generate_report:
        from app.llmwiki.reports import generate_report_from_chat
        response = await generate_report_from_chat(db, user, workspace, request)
    else:
        response = await ChatService(wiki_store_for_workspace(workspace), llm=user_llm).answer(request)
    add_message(
        db,
        user=user,
        session=session,
        role="assistant",
        content=response.answer,
        parent_id=user_message.id if request.interaction in {"reply", "comment"} else None,
        interaction=request.interaction,
        route=response.route,
    )
    compact_session_if_needed(db, session)
    db.commit()
    response.session_id = session.id
    return response


@router.get("/sessions", response_model=list[ChatSessionItem])
async def sessions(
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ChatSessionItem]:
    return list_user_sessions(db, user, workspace.id)


@router.get("/sessions/{session_id}", response_model=ChatSessionMessages)
async def session_messages(
    session_id: str,
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatSessionMessages:
    return get_session_messages(db, user, session_id, workspace.id)


@router.patch("/sessions/{session_id}", response_model=ChatSessionItem)
async def update_session(
    session_id: str,
    request: ChatSessionUpdate,
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatSessionItem:
    session = rename_session_title(db, user, session_id, request.title, workspace.id)
    return session_item(session)


@router.delete("/sessions/{session_id}", response_model=dict[str, bool])
async def delete_session_route(
    session_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, bool]:
    delete_session(db, user, session_id)
    return {"deleted": True}
