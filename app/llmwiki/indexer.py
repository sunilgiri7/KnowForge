from dataclasses import dataclass

from app.llmwiki.storage import WikiStore
from app.llmwiki.text import keyword_summary, tokenize, trim_to_chars
from app.schemas.llmwiki import RouteDecision, WikiPage

EXACT_EVIDENCE_TERMS = {
    "quote",
    "exact",
    "log",
    "transcript",
    "raw",
    "verbatim",
    "line",
    "source",
    "evidence",
}

WIKI_INTENT_TERMS = {
    "according",
    "citation",
    "document",
    "documents",
    "file",
    "files",
    "pdf",
    "resume",
    "source",
    "sources",
    "uploaded",
    "wiki",
}


@dataclass(frozen=True)
class PageCandidate:
    slug: str
    score: float
    page: WikiPage


class WikiIndexer:
    def __init__(self, store: WikiStore):
        self.store = store

    def route(self, question: str, *, allow_fallback: bool = True) -> RouteDecision:
        candidates = self.find_candidates(question, limit=4)
        difficulty = self.classify_difficulty(question, candidates)
        explicit_wiki_intent = self.has_wiki_intent(question)
        if self.needs_exact_evidence(question) and candidates and allow_fallback:
            return RouteDecision(
                route="fallback",
                page_slugs=[candidate.slug for candidate in candidates],
                confidence=0.62,
                reason="Question asks for raw or exact source evidence.",
                difficulty=difficulty,
            )
        if not candidates:
            return RouteDecision(
                route="direct",
                confidence=0.0,
                reason="No strong wiki match; answer with the direct LLM.",
                difficulty=difficulty,
            )
        top = candidates[0]
        pages_are_current = all(item.page.meta.freshness == "current" for item in candidates[:2])
        confidence_is_ok = top.page.meta.confidence in {"high", "medium"}
        if top.score >= 0.65 and pages_are_current and confidence_is_ok:
            return RouteDecision(
                route="wiki",
                page_slugs=[candidate.slug for candidate in candidates[:3]],
                confidence=min(0.95, top.score),
                reason="Strong wiki match found.",
                difficulty=difficulty,
            )
        if explicit_wiki_intent and top.score >= 0.35:
            return RouteDecision(
                route="wiki",
                page_slugs=[candidate.slug for candidate in candidates[:2]],
                confidence=top.score,
                reason="Question explicitly asks for wiki/source context.",
                difficulty=difficulty,
            )
        return RouteDecision(
            route="direct",
            page_slugs=[],
            confidence=top.score,
            reason="Wiki match is weak; answer with the direct LLM.",
            difficulty=difficulty,
        )

    def find_candidates(self, question: str, *, limit: int) -> list[PageCandidate]:
        query_terms = set(tokenize(question))
        if not query_terms:
            return []
        candidates: list[PageCandidate] = []
        for item in self.store.list_pages():
            page = self.store.read_page(item.slug, prefer_compact=True)
            haystack = " ".join(
                [
                    page.meta.title,
                    page.meta.summary,
                    " ".join(page.meta.tags),
                    " ".join(page.meta.aliases),
                    page.content[:3000],
                ]
            )
            page_terms = set(tokenize(haystack))
            if not page_terms:
                continue
            overlap = len(query_terms & page_terms)
            title_bonus = 0.15 if query_terms & set(tokenize(page.meta.title)) else 0
            score = min(1.0, overlap / max(3, len(query_terms)) + title_bonus)
            if score > 0:
                candidates.append(PageCandidate(slug=item.slug, score=score, page=page))
        return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)[:limit]

    def build_context(
        self,
        slugs: list[str],
        question: str,
        *,
        char_budget: int,
    ) -> tuple[str, list[str]]:
        query_terms = set(tokenize(question))
        blocks: list[str] = []
        used: list[str] = []
        remaining = char_budget
        for slug in slugs:
            page = self.store.read_page(slug, prefer_compact=True)
            snippet = self._page_snippet(page, query_terms, max_chars=max(1200, remaining // 2))
            block = (
                f"[wiki:{page.meta.slug}] {page.meta.title}\n"
                f"Summary: {page.meta.summary}\n{snippet}"
            )
            if len(block) > remaining:
                block = trim_to_chars(block, remaining)
            if block.strip():
                blocks.append(block)
                used.append(page.meta.slug)
                remaining -= len(block)
            if remaining <= 800:
                break
        return "\n\n---\n\n".join(blocks), used

    def build_exact_page_context(
        self,
        slugs: list[str],
        *,
        char_budget: int,
    ) -> tuple[str, list[str]]:
        blocks: list[str] = []
        used: list[str] = []
        remaining = char_budget
        for slug in slugs:
            page = self.store.read_page(slug, prefer_compact=False)
            block = (
                f"[wiki:{page.meta.slug}] {page.meta.title}\n"
                f"Summary: {page.meta.summary}\n"
                f"Tags: {', '.join(page.meta.tags)}\n"
                f"Sources: {', '.join(page.meta.source_ids)}\n\n"
                f"{page.content}"
            )
            if len(block) > remaining:
                block = trim_to_chars(block, remaining)
            if block.strip():
                blocks.append(block)
                used.append(page.meta.slug)
                remaining -= len(block)
            if remaining <= 800:
                break
        return "\n\n---\n\n".join(blocks), used

    @staticmethod
    def needs_exact_evidence(question: str) -> bool:
        return bool(set(tokenize(question)) & EXACT_EVIDENCE_TERMS)

    @staticmethod
    def has_wiki_intent(question: str) -> bool:
        terms = set(tokenize(question))
        lowered = question.lower()
        return bool(terms & WIKI_INTENT_TERMS) or "according to" in lowered

    @staticmethod
    def classify_difficulty(question: str, candidates: list[PageCandidate]) -> str:
        terms = set(tokenize(question))
        hard_terms = {
            "analyze",
            "architecture",
            "compare",
            "debug",
            "decision",
            "design",
            "explain",
            "impact",
            "migrate",
            "plan",
            "reason",
            "root",
            "tradeoff",
            "why",
        }
        if len(question) > 700 or len(candidates) >= 3 or terms & hard_terms:
            return "hard"
        if len(question) > 220 or len(candidates) == 2:
            return "medium"
        return "easy"

    @staticmethod
    def _page_snippet(page: WikiPage, query_terms: set[str], *, max_chars: int) -> str:
        paragraphs = [part.strip() for part in page.content.split("\n\n") if part.strip()]
        scored: list[tuple[int, int, str]] = []
        for index, paragraph in enumerate(paragraphs):
            score = len(query_terms & set(tokenize(paragraph)))
            scored.append((index, score, paragraph))
        ranked = sorted(scored, key=lambda item: item[1], reverse=True)
        selected = [paragraph for _, score, paragraph in ranked[:8] if score > 0]
        if not selected:
            selected = [keyword_summary(page.content, max_sentences=6)]
        ordered = "\n\n".join(selected)
        return trim_to_chars(ordered, max_chars)
