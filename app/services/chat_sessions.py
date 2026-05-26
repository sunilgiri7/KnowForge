from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import KnowForgeError
from app.db.models import ChatMessageRecord, ChatSession, User, utc_now
from app.schemas.llmwiki import ChatMessage, ChatSessionItem, ChatSessionMessages, StoredChatMessage


def get_or_create_session(
    db: Session,
    user: User,
    session_id: str | None,
    question: str,
) -> ChatSession:
    if session_id:
        session = db.scalar(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id)
        )
        if not session:
            raise KnowForgeError(
                "Chat session not found.",
                status_code=404,
                code="session_not_found",
            )
        return session
    title = question.strip().splitlines()[0][:80] or "New chat"
    session = ChatSession(user_id=user.id, title=title)
    db.add(session)
    db.flush()
    return session


def add_message(
    db: Session,
    *,
    user: User,
    session: ChatSession,
    role: str,
    content: str,
    parent_id: str | None = None,
    interaction: str = "message",
    route: str | None = None,
) -> ChatMessageRecord:
    created_at = utc_now()
    record = ChatMessageRecord(
        user_id=user.id,
        session_id=session.id,
        role=role,
        content=content,
        parent_id=parent_id,
        interaction=interaction,
        route=route,
        created_at=created_at,
    )
    db.add(record)
    session.updated_at = created_at
    return record


def history_for_session(db: Session, session: ChatSession, *, limit: int = 80) -> list[ChatMessage]:
    records = db.scalars(
        select(ChatMessageRecord)
        .where(ChatMessageRecord.session_id == session.id)
        .order_by(ChatMessageRecord.created_at.desc())
        .limit(limit)
    ).all()
    ordered = list(reversed(records))
    return [
        ChatMessage(
            role=record.role if record.role in {"user", "assistant", "system"} else "user",
            content=record.content,
        )
        for record in ordered
    ]


def list_user_sessions(db: Session, user: User) -> list[ChatSessionItem]:
    sessions = db.scalars(
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
    ).all()
    return [session_item(session) for session in sessions]


def get_session_messages(db: Session, user: User, session_id: str) -> ChatSessionMessages:
    session = db.scalar(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(ChatSession.id == session_id, ChatSession.user_id == user.id)
    )
    if not session:
        raise KnowForgeError("Chat session not found.", status_code=404, code="session_not_found")
    return ChatSessionMessages(
        session=session_item(session),
        messages=[
            StoredChatMessage(
                id=message.id,
                role=message.role if message.role in {"user", "assistant", "system"} else "user",
                content=message.content,
                parent_id=message.parent_id,
                interaction=(
                    message.interaction
                    if message.interaction in {"message", "reply", "comment"}
                    else "message"
                ),
                route=message.route,
                created_at=message.created_at,
            )
            for message in session.messages
        ],
    )


def thread_context_for_parent(
    db: Session,
    user: User,
    session: ChatSession,
    parent_id: str | None,
    *,
    limit: int = 12,
) -> str:
    if not parent_id:
        return ""
    records = db.scalars(
        select(ChatMessageRecord)
        .where(ChatMessageRecord.session_id == session.id, ChatMessageRecord.user_id == user.id)
        .order_by(ChatMessageRecord.created_at)
    ).all()
    by_id = {record.id: record for record in records}
    parent = by_id.get(parent_id)
    if not parent:
        raise KnowForgeError(
            "The selected message is no longer available.",
            status_code=404,
            code="parent_message_not_found",
        )

    ancestors: list[ChatMessageRecord] = []
    current = parent
    seen: set[str] = set()
    while current and current.id not in seen:
        ancestors.append(current)
        seen.add(current.id)
        current = by_id.get(current.parent_id) if current.parent_id else None
    ancestors = list(reversed(ancestors))[-limit:]

    child_count = sum(1 for record in records if record.parent_id == parent_id)
    lines = [
        "Selected thread context for this reply/comment:",
        *[
            f"{record.role} ({record.interaction}): {record.content[:1200]}"
            for record in ancestors
        ],
    ]
    if child_count:
        lines.append(f"Existing direct replies/comments under selected message: {child_count}")
    return "\n".join(lines)


def compact_session_if_needed(db: Session, session: ChatSession) -> None:
    records = db.scalars(
        select(ChatMessageRecord)
        .where(ChatMessageRecord.session_id == session.id)
        .order_by(ChatMessageRecord.created_at.desc())
        .limit(40)
    ).all()
    if len(records) < 40:
        return
    recent = list(reversed(records[:12]))
    session.summary = "\n".join(f"{record.role}: {record.content[:500]}" for record in recent)


def session_item(session: ChatSession) -> ChatSessionItem:
    return ChatSessionItem(
        id=session.id,
        title=session.title,
        summary=session.summary or "",
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
