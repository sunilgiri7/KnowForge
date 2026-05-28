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

SELF_PROFILE_TERMS = {
    "about",
    "background",
    "bio",
    "experience",
    "me",
    "my",
    "myself",
    "profile",
    "resume",
    "skills",
}


@dataclass(frozen=True)
class PageCandidate:
    slug: str
    score: float
    page: WikiPage


class WikiIndexer:
    def __init__(self, store: WikiStore):
        self.store = store

    def route(
        self,
        question: str,
        *,
        allow_fallback: bool = True,
        candidate_queries: list[str] | None = None,
    ) -> RouteDecision:
        candidates = self.find_candidates(question, limit=4, candidate_queries=candidate_queries)
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
        if top.score >= 0.45 and pages_are_current and confidence_is_ok:
            return RouteDecision(
                route="wiki",
                page_slugs=[candidate.slug for candidate in candidates[:3]],
                confidence=min(0.95, top.score),
                reason="Strong wiki match found.",
                difficulty=difficulty,
            )
        if explicit_wiki_intent and top.score >= 0.20:
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

    def find_candidates(
        self,
        question: str,
        *,
        limit: int,
        candidate_queries: list[str] | None = None,
    ) -> list[PageCandidate]:
        queries = [question, *(candidate_queries or [])]
        query_terms = set()
        for query in queries:
            query_terms.update(tokenize(query))
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
            title_terms = set(tokenize(page.meta.title))
            summary_terms = set(tokenize(page.meta.summary))
            tag_terms = set(tokenize(" ".join(page.meta.tags)))
            title_bonus = 0.20 if query_terms & title_terms else 0
            tag_bonus = 0.12 if query_terms & tag_terms else 0
            summary_bonus = min(0.20, len(query_terms & summary_terms) * 0.04)
            score = min(
                1.0,
                overlap / max(4, min(12, len(query_terms)))
                + title_bonus
                + tag_bonus
                + summary_bonus,
            )
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
            snippet = self._page_snippet(page, query_terms, max_chars=max(6000, remaining // 2))
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
        vague_doc_terms = {
            "agreement",
            "contract",
            "salary",
            "compensation",
            "notice",
            "termination",
            "paper",
            "research",
            "abstract",
            "method",
            "architecture",
            "benchmark",
            "results",
            "resume",
            "experience",
            "skills",
        }
        return (
            bool(terms & (WIKI_INTENT_TERMS | vague_doc_terms | SELF_PROFILE_TERMS))
            or "according to" in lowered
            or "do you know about me" in lowered
            or "know about me" in lowered
        )

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
        # Expanded from top-10 to top-15 for better coverage of long docs
        selected_indices = {index for index, score, _ in ranked[:15] if score > 0}
        expanded_indices = set(selected_indices)
        for index in selected_indices:
            expanded_indices.update({index - 1, index, index + 1})
        selected = [
            paragraph
            for index, _, paragraph in sorted(scored, key=lambda item: item[0])
            if index in expanded_indices and paragraph
        ]
        if not selected:
            # No keyword overlap — return the full page content trimmed to budget
            # (better than a 6-sentence summary that may miss structured data)
            return trim_to_chars(page.content, max_chars)
        ordered = "\n\n".join(selected)
        return trim_to_chars(ordered, max_chars)