from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RouteName = Literal["direct", "wiki", "fallback", "clarify", "no_answer"]
DifficultyLevel = Literal["easy", "medium", "hard"]


class Citation(BaseModel):
    label: str
    source_id: str
    source_type: str = "wiki"
    uri: str | None = None
    wiki_slug: str | None = None
    span: str | None = None
    quote: str | None = None


class WikiPageMeta(BaseModel):
    title: str
    slug: str
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    freshness: Literal["current", "stale", "unknown"] = "current"
    confidence: Literal["high", "medium", "low"] = "medium"
    aliases: list[str] = Field(default_factory=list)
    last_compiled_at: str | None = None


class WikiPage(BaseModel):
    meta: WikiPageMeta
    content: str


class WikiPageUpsert(BaseModel):
    title: str
    slug: str | None = None
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    content: str


class WikiPageListItem(BaseModel):
    title: str
    slug: str
    summary: str
    tags: list[str]
    freshness: str
    confidence: str
    source_ids: list[str]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=20_000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8_000)
    messages: list[ChatMessage] = Field(default_factory=list, max_length=80)
    allow_fallback: bool = True
    session_id: str | None = None
    context_page_slugs: list[str] = Field(default_factory=list, max_length=8)
    intent: Literal["auto", "wiki", "direct"] = "auto"
    user_context: str | None = Field(default=None, max_length=1_000)


class AgentTrace(BaseModel):
    agent: str
    action: str
    confidence: float = Field(ge=0, le=1)
    notes: str = ""


class RouteDecision(BaseModel):
    route: RouteName
    page_slugs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    reason: str
    difficulty: DifficultyLevel = "easy"


class ChatResponse(BaseModel):
    session_id: str | None = None
    answer: str
    route: RouteName
    difficulty: DifficultyLevel
    citations: list[Citation] = Field(default_factory=list)
    used_pages: list[str] = Field(default_factory=list)
    knowledge_gap_created: bool = False
    agent_trace: list[AgentTrace] = Field(default_factory=list)


class SourceUploadResponse(BaseModel):
    source_id: str
    filename: str
    bytes_received: int
    text_chars: int
    wiki_page_slug: str | None = None
    message: str


class KnowledgeGapEvent(BaseModel):
    question: str
    route: RouteName
    missing_topic: str
    fallback_source_ids: list[str] = Field(default_factory=list)
    suggested_page_slug: str | None = None
    priority: Literal["low", "medium", "high"] = "medium"


class UserRegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class UserLoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class VerifyEmailRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    code: str = Field(min_length=4, max_length=12)


class ResendCodeRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)


class UserProfile(BaseModel):
    id: str
    name: str
    email: str
    is_verified: bool


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfile


class AuthMessageResponse(BaseModel):
    message: str


class ChatSessionItem(BaseModel):
    id: str
    title: str
    summary: str = ""
    created_at: datetime
    updated_at: datetime


class StoredChatMessage(BaseModel):
    id: str
    role: Literal["user", "assistant", "system"]
    content: str
    parent_id: str | None = None
    route: str | None = None
    created_at: datetime


class ChatSessionMessages(BaseModel):
    session: ChatSessionItem
    messages: list[StoredChatMessage]
