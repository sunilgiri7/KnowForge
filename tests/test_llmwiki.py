import pytest

from app.core.config import settings
from app.core.errors import KnowForgeError
from app.llmwiki.chat import ChatService
from app.llmwiki.groq import GroqClient
from app.llmwiki.indexer import WikiIndexer
from app.llmwiki.ingest import SourceIngestor
from app.llmwiki.storage import WikiStore
from app.schemas.llmwiki import ChatRequest


class FakeLLM:
    available = True

    def __init__(self, answer: str = "LLM answer"):
        self.answer = answer
        self.prompts: list[str] = []

    async def generate_text(self, prompt: str, *, temperature: float = 0.2) -> str:
        self.prompts.append(prompt)
        return self.answer

    async def generate_json(self, prompt: str, *, temperature: float = 0.1) -> dict:
        self.prompts.append(prompt)
        return {"supported": True, "confidence": 0.9, "issues": []}


def test_wiki_page_round_trip_and_index(tmp_path) -> None:
    store = WikiStore(tmp_path)
    page = store.make_page(
        title="Service Deployments",
        summary="How platform services are deployed.",
        tags=["deployments", "platform"],
        source_ids=["source-1"],
        content="# Service Deployments\n\nUse the release checklist. [source:source-1]",
        confidence="high",
    )

    store.upsert_page(page)

    loaded = store.read_page("service-deployments")
    assert loaded.meta.title == "Service Deployments"
    assert "release checklist" in loaded.content
    assert "service-deployments" in store.read_index()


def test_router_prefers_current_wiki_page(tmp_path) -> None:
    store = WikiStore(tmp_path)
    store.upsert_page(
        store.make_page(
            title="Incident Review Process",
            summary="How incident reviews are handled.",
            tags=["incident", "review"],
            content=(
                "# Incident Review Process\n\n"
                "Incident reviews require timeline, impact, root cause, and actions."
            ),
            confidence="high",
        )
    )

    decision = WikiIndexer(store).route("How do we handle incident review root cause actions?")

    assert decision.route == "wiki"
    assert decision.page_slugs == ["incident-review-process"]


def test_router_uses_direct_llm_for_unrelated_question(tmp_path) -> None:
    store = WikiStore(tmp_path)
    store.upsert_page(
        store.make_page(
            title="Sunil Resume",
            summary="AI engineer resume.",
            tags=["resume", "profile"],
            content="# Sunil Resume\n\nPython, FastAPI, and AI engineering experience.",
            confidence="high",
        )
    )

    decision = WikiIndexer(store).route("What is a multi agent AI system?")

    assert decision.route == "direct"
    assert decision.page_slugs == []


def test_router_uses_wiki_when_user_asks_for_document_context(tmp_path) -> None:
    store = WikiStore(tmp_path)
    store.upsert_page(
        store.make_page(
            title="Sunil Resume",
            summary="AI engineer resume.",
            tags=["resume", "profile"],
            content="# Sunil Resume\n\nPython, FastAPI, and AI engineering experience.",
            confidence="high",
        )
    )

    decision = WikiIndexer(store).route("What skills are listed in the uploaded resume?")

    assert decision.route == "wiki"
    assert decision.page_slugs == ["sunil-resume"]


@pytest.mark.asyncio
async def test_chat_uses_wiki_context_without_groq(tmp_path) -> None:
    store = WikiStore(tmp_path)
    store.upsert_page(
        store.make_page(
            title="API Key Setup",
            summary="Users add Groq keys from settings.",
            tags=["api", "groq", "settings"],
            content=(
                "# API Key Setup\n\n"
                "Users save the Groq API key in settings. [wiki:api-key-setup]"
            ),
            confidence="high",
        )
    )

    response = await ChatService(store, llm=GroqClient(api_key="")).answer(
        ChatRequest(question="Where do users save Groq API keys?")
    )

    assert response.route == "wiki"
    assert "Groq API key" in response.answer
    assert response.citations


@pytest.mark.asyncio
async def test_chat_falls_back_to_direct_answer_without_context(tmp_path) -> None:
    store = WikiStore(tmp_path)
    llm = FakeLLM("Hello from the LLM.")

    response = await ChatService(store, llm=llm).answer(ChatRequest(question="Hii"))

    assert response.route == "direct"
    assert response.answer == "Hello from the LLM."
    assert response.knowledge_gap_created is False
    assert "Hii" in llm.prompts[0]


@pytest.mark.asyncio
async def test_chat_direct_answer_reports_llm_unavailable_without_fake_answer(tmp_path) -> None:
    store = WikiStore(tmp_path)

    response = await ChatService(store, llm=GroqClient(api_key="")).answer(
        ChatRequest(question="what is multi agent AI system")
    )

    assert "language model" in response.answer
    assert "multi-agent AI system" not in response.answer
    assert "GROQ_API_KEY" not in response.answer


@pytest.mark.asyncio
async def test_pdf_upload_limit_is_enforced(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_pdf_upload_bytes", 10)
    store = WikiStore(tmp_path)

    with pytest.raises(KnowForgeError) as exc:
        await SourceIngestor(store).ingest_pdf(filename="large.pdf", data=b"x" * 11)

    assert exc.value.code == "pdf_too_large"


def test_local_compile_keeps_rich_resume_context_and_joins_wrapped_lines() -> None:
    text = """
Sunil Giri
 sunilgiri.dev@gmail.com | Noida, India
SUMMARY
Backend-heavy AI/ML Engineer with 2+ years of experience delivering production-grade AI systems,
real-time IoT pipelines, and LLM-powered
applications.
WORK EXPERIENCE
\x7f Built high-throughput WebSocket layer serving multi-sensor data across any timestamp range;
 raw, aggregated and non-aggregated payloads efficiently at scale.
SKILLS
Python, FastAPI, LangChain, AWS
"""

    _, summary, tags, content = SourceIngestor._local_compile("SUNIL.pdf", "source-1", text)

    assert "LLM-powered applications" in summary
    assert "raw, aggregated and non-aggregated payloads efficiently at scale" in content
    assert "fastapi" in tags
