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
