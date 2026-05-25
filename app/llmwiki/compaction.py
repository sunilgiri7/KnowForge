from app.core.config import settings
from app.llmwiki.groq import GroqClient
from app.llmwiki.markdown import render_page
from app.llmwiki.prompts import COMPACT_PROMPT
from app.llmwiki.storage import WikiStore
from app.llmwiki.text import keyword_summary, trim_to_chars
from app.schemas.llmwiki import WikiPage


class WikiCompactor:
    def __init__(self, store: WikiStore, llm: GroqClient | None = None):
        self.store = store
        self.llm = llm or GroqClient()

    async def compact_if_needed(self, page: WikiPage) -> bool:
        raw = render_page(page)
        if len(raw) <= settings.wiki_page_soft_char_limit:
            return False
        compact = await self.compact_page(page)
        compact.meta.summary = compact.meta.summary or page.meta.summary
        self.store._atomic_write(self.store.compact_path(page.meta.slug), render_page(compact))
        return True

    async def compact_page(self, page: WikiPage) -> WikiPage:
        raw = render_page(page)
        if self.llm.available:
            try:
                content = await self.llm.generate_text(
                    COMPACT_PROMPT.format(
                        page=trim_to_chars(raw, settings.wiki_context_char_budget)
                    ),
                    temperature=0.1,
                )
            except Exception:
                content = keyword_summary(page.content, max_sentences=16)
        else:
            content = keyword_summary(page.content, max_sentences=16)
        page.meta.confidence = "medium" if page.meta.confidence == "low" else page.meta.confidence
        return WikiPage(meta=page.meta, content=content)


class ConversationCompactor:
    def __init__(self, llm: GroqClient | None = None):
        self.llm = llm or GroqClient()

    async def compact(
        self,
        messages: list[dict[str, str]],
        *,
        char_budget: int,
        keep_last: int,
    ) -> str:
        if not messages:
            return ""
        tail = messages[-keep_last:]
        older = messages[:-keep_last]
        tail_text = "\n".join(f"{message['role']}: {message['content']}" for message in tail)
        if not older:
            return trim_to_chars(tail_text, char_budget)
        older_text = "\n".join(f"{message['role']}: {message['content']}" for message in older)
        if self.llm.available and len(older_text) > char_budget // 2:
            try:
                summary = await self.llm.generate_text(
                    "Summarize this prior chat for a knowledge-base QA agent. "
                    "Keep user goals, constraints, unresolved asks, and decisions only.\n\n"
                    + trim_to_chars(older_text, char_budget),
                    temperature=0.1,
                )
            except Exception:
                summary = keyword_summary(older_text, max_sentences=8)
        else:
            summary = keyword_summary(older_text, max_sentences=8)
        return trim_to_chars(
            f"Prior summary:\n{summary}\n\nRecent messages:\n{tail_text}",
            char_budget,
        )
