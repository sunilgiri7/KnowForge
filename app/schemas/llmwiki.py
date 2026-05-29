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
    entities: list[str] = Field(default_factory=list)
    related_slugs: list[str] = Field(default_factory=list)
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
    entities: list[str] = Field(default_factory=list)
    related_slugs: list[str] = Field(default_factory=list)
    content: str


class WikiPageRename(BaseModel):
    title: str = Field(min_length=1, max_length=240)


LlmProvider = Literal["openrouter", "openai", "anthropic", "gemini"]


class LlmKeyUpsertRequest(BaseModel):
    provider: LlmProvider
    api_key: str = Field(min_length=6, max_length=4000)
    model: str | None = Field(default=None, max_length=120)


class LlmKeyStatus(BaseModel):
    provider: LlmProvider
    connected: bool
    model: str = ""
    active: bool = False


class WikiPageListItem(BaseModel):
    title: str
    slug: str
    summary: str
    tags: list[str]
    freshness: str
    confidence: str
    source_ids: list[str]
    entity_count: int = 0
    related_count: int = 0
    open_conflict_count: int = 0


class WikiContradiction(BaseModel):
    id: str
    slug_a: str
    slug_b: str
    title_a: str = ""
    title_b: str = ""
    topic: str
    claim_a: str
    claim_b: str
    severity: Literal["low", "medium", "high"] = "medium"
    status: Literal["open", "dismissed", "resolved"] = "open"
    rationale: str = ""
    detected_at: str


class ContradictionScanResponse(BaseModel):
    scanned_pairs: int
    new_conflicts: int
    open_conflicts: int
    contradictions: list[WikiContradiction] = Field(default_factory=list)


class ContradictionStatusUpdate(BaseModel):
    status: Literal["open", "dismissed", "resolved"]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=20_000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8_000)
    messages: list[ChatMessage] = Field(default_factory=list, max_length=80)
    allow_fallback: bool = True
    session_id: str | None = None
    parent_id: str | None = Field(default=None, max_length=80)
    interaction: Literal["message", "reply", "comment"] = "message"
    context_page_slugs: list[str] = Field(default_factory=list, max_length=8)
    intent: Literal["auto", "wiki", "direct"] = "auto"


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


class ChatSessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=180)


class StoredChatMessage(BaseModel):
    id: str
    role: Literal["user", "assistant", "system"]
    content: str
    parent_id: str | None = None
    interaction: Literal["message", "reply", "comment"] = "message"
    route: str | None = None
    created_at: datetime


class ChatSessionMessages(BaseModel):
    session: ChatSessionItem
    messages: list[StoredChatMessage]
