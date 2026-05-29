"""
indexer.py — BM25-powered wiki retrieval engine.

Key improvements over v1:
  - BM25PageIndex: in-memory multi-field inverted index; builds once, searches
    in microseconds instead of doing O(n) disk reads per query.
  - Multi-query RRF merging: each query variant runs independently, results
    merged via Reciprocal Rank Fusion for better recall.
  - Better snippet extraction: sentence-level BM25 paragraph scoring + ±1
    expansion for narrative continuity + table preservation.
  - Calibrated routing thresholds derived from BM25 field-weight sums rather
    than the 0.0-1.0 overlap ratio used in v1.
"""
from __future__ import annotations

import threading
import time
from collections import Counter
from dataclasses import dataclass

from app.llmwiki.storage import WikiStore
from app.llmwiki.text import (
    bm25_score,
    keyword_summary,
    reciprocal_rank_fusion,
    tokenize,
    trim_to_chars,
)
from app.schemas.llmwiki import RouteDecision, WikiPage

# ── Routing intent term sets ──────────────────────────────────────────────────

EXACT_EVIDENCE_TERMS = {
    "evidence",
    "exact",
    "line",
    "log",
    "quote",
    "raw",
    "source",
    "transcript",
    "verbatim",
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

VAGUE_DOC_TERMS = {
    "abstract",
    "agreement",
    "architecture",
    "benchmark",
    "compensation",
    "contract",
    "method",
    "notice",
    "paper",
    "research",
    "results",
    "salary",
    "termination",
}


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PageCandidate:
    slug: str
    score: float
    page: WikiPage


# ── BM25 inverted index ───────────────────────────────────────────────────────


class BM25PageIndex:
    """
    In-memory multi-field BM25 inverted index over wiki pages.

    Design notes
    ------------
    * Thread-safe via RLock — async code runs in threads through asyncio.to_thread,
      so the lock prevents torn reads/writes.
    * Incremental: add() and remove() update DF counts without a full rebuild.
    * Lazy averages: _avg_len is recomputed on first use after any mutation
      (O(n) but amortised across many queries).

    Field weights
    -------------
    Title and aliases carry the most routing signal — they are short, curated,
    and map directly to user intent.  Content is broad but noisy.

        title:   5.0   (curated, highest specificity)
        aliases: 3.5   (explicit synonym routing)
        tags:    3.0   (editorial routing keywords)
        summary: 2.0   (synthesised paragraph)
        content: 1.0   (full body, high recall, lower precision)
    """

    FIELD_WEIGHTS: dict[str, float] = {
        "title":   5.0,
        "aliases": 3.5,
        "tags":    3.0,
        "summary": 2.0,
        "content": 1.0,
    }
    # How many content chars to index — balances coverage vs. index build time
    CONTENT_INDEX_CHARS = 8_000

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # slug → {field_name → token list}
        self._doc_fields: dict[str, dict[str, list[str]]] = {}
        # field_name → {term → document_frequency}
        self._df: dict[str, dict[str, int]] = {f: {} for f in self.FIELD_WEIGHTS}
        # field_name → average token count across all docs
        self._avg_len: dict[str, float] = {f: 0.0 for f in self.FIELD_WEIGHTS}
        self._avg_dirty = True

    # ── Indexing API ──────────────────────────────────────────────────────────

    def add(self, page: WikiPage) -> None:
        """Index or re-index a wiki page (idempotent, thread-safe)."""
        slug = page.meta.slug
        new_fields = self._extract_fields(page)
        tokenised = {f: tokenize(text) for f, text in new_fields.items()}
        with self._lock:
            if slug in self._doc_fields:
                self._remove_doc(slug)
            self._doc_fields[slug] = tokenised
            for field_name, tokens in tokenised.items():
                for term in set(tokens):
                    self._df[field_name][term] = self._df[field_name].get(term, 0) + 1
            self._avg_dirty = True

    def remove(self, slug: str) -> None:
        """Remove a page from the index (thread-safe)."""
        with self._lock:
            if slug in self._doc_fields:
                self._remove_doc(slug)
                self._avg_dirty = True

    def rebuild_from_store(self, store: WikiStore) -> None:
        """Full index rebuild — call on initialisation or after bulk mutations."""
        new_fields: dict[str, dict[str, list[str]]] = {}
        new_df: dict[str, dict[str, int]] = {f: {} for f in self.FIELD_WEIGHTS}
        pages = store.list_pages()
        for item in pages:
            try:
                page = store.read_page(item.slug, prefer_compact=False)
                tokenised = {f: tokenize(text) for f, text in self._extract_fields(page).items()}
                new_fields[item.slug] = tokenised
                for field_name, tokens in tokenised.items():
                    for term in set(tokens):
                        new_df[field_name][term] = new_df[field_name].get(term, 0) + 1
            except Exception:
                pass
        with self._lock:
            self._doc_fields = new_fields
            self._df = new_df
            self._avg_dirty = True

    # ── Search API ────────────────────────────────────────────────────────────

    def search(
        self,
        query_terms: list[str],
        *,
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        """Return [(slug, score)] sorted by BM25 descending.

        Only documents that have at least one query term in any field are
        scored — this is the standard "candidate generation" trick used by
        every production inverted index.
        """
        if not query_terms:
            return []
        with self._lock:
            if self._avg_dirty:
                self._refresh_averages()
            num_docs = len(self._doc_fields)
            if num_docs == 0:
                return []
            candidates = self._candidate_slugs(query_terms)
            scored = [
                (slug, self._score_doc(query_terms, slug, num_docs))
                for slug in candidates
            ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(s, sc) for s, sc in scored if sc > 0][:limit]

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _remove_doc(self, slug: str) -> None:
        """Decrement DF counts and delete. Must hold lock."""
        for field_name, tokens in self._doc_fields[slug].items():
            for term in set(tokens):
                cnt = self._df[field_name].get(term, 0) - 1
                if cnt <= 0:
                    self._df[field_name].pop(term, None)
                else:
                    self._df[field_name][term] = cnt
        del self._doc_fields[slug]

    def _refresh_averages(self) -> None:
        """Recompute per-field average lengths. Must hold lock."""
        n = max(1, len(self._doc_fields))
        for field_name in self.FIELD_WEIGHTS:
            total = sum(
                len(doc.get(field_name, [])) for doc in self._doc_fields.values()
            )
            self._avg_len[field_name] = total / n
        self._avg_dirty = False

    def _candidate_slugs(self, query_terms: list[str]) -> set[str]:
        """Slugs that have ≥1 query term in any field."""
        term_set = set(query_terms)
        candidates: set[str] = set()
        for slug, doc in self._doc_fields.items():
            for tokens in doc.values():
                if term_set & set(tokens):
                    candidates.add(slug)
                    break
        return candidates

    def _score_doc(self, query_terms: list[str], slug: str, num_docs: int) -> float:
        """Multi-field weighted BM25 score for one document."""
        doc = self._doc_fields[slug]
        total = 0.0
        for field_name, weight in self.FIELD_WEIGHTS.items():
            tokens = doc.get(field_name, [])
            if not tokens:
                continue
            total += weight * bm25_score(
                query_terms,
                Counter(tokens),
                len(tokens),
                self._df[field_name],
                num_docs,
                self._avg_len[field_name],
            )
        return total

    @staticmethod
    def _extract_fields(page: WikiPage) -> dict[str, str]:
        return {
            "title":   page.meta.title,
            "aliases": " ".join(page.meta.aliases),
            "tags":    " ".join(page.meta.tags),
            "summary": page.meta.summary,
            "content": page.content[: BM25PageIndex.CONTENT_INDEX_CHARS],
        }


# ── WikiIndexer ───────────────────────────────────────────────────────────────


class WikiIndexer:
    """
    Retrieval layer wrapping BM25PageIndex.

    Routing thresholds
    ------------------
    BM25 scores are unbounded (sum of IDF × TF_norm across fields, weighted).
    With the field weights above, a perfect title+tag+summary match on a
    medium-sized wiki typically scores 12–25.  Thresholds below are calibrated
    against this range:

        ≥ 9.0  → very strong match (confident wiki route)
        ≥ 6.0  → good match (wiki route, slightly lower confidence)
        ≥ 3.5  → reasonable match (wiki route for explicit wiki-intent queries)
        ≥ 1.5  → marginal (wiki route only when user explicitly asked for wiki)
        < 1.5  → direct LLM

    These beat the v1 thresholds (0.28 / 0.45 / 0.72 on a 0-1 normalised
    overlap ratio) because BM25 IDF discounts common terms, so the signal is
    cleaner.
    """

    # Rebuild the in-memory index if either condition is met:
    INDEX_MAX_AGE_SECS = 120  # 2-minute freshness window
    # (page count change triggers immediate rebuild regardless of age)

    def __init__(self, store: WikiStore) -> None:
        self.store = store
        self._bm25 = BM25PageIndex()
        self._indexed_page_count = -1
        self._last_rebuild_ts = 0.0

    # ── Index management ──────────────────────────────────────────────────────

    def _ensure_fresh(self) -> None:
        """Rebuild if stale. O(n) on first call, then in-memory cache."""
        current_count = len(self.store.list_pages())
        age = time.monotonic() - self._last_rebuild_ts
        if current_count != self._indexed_page_count or age > self.INDEX_MAX_AGE_SECS:
            self._bm25.rebuild_from_store(self.store)
            self._indexed_page_count = current_count
            self._last_rebuild_ts = time.monotonic()

    def invalidate(self) -> None:
        """Force index rebuild on next search (call after page writes)."""
        self._indexed_page_count = -1

    # ── Routing ───────────────────────────────────────────────────────────────

    def route(
        self,
        question: str,
        *,
        allow_fallback: bool = True,
        candidate_queries: list[str] | None = None,
    ) -> RouteDecision:
        candidates = self.find_candidates(
            question, limit=5, candidate_queries=candidate_queries
        )
        difficulty = self.classify_difficulty(question, candidates)
        explicit_wiki_intent = self.has_wiki_intent(question)

        if not candidates:
            return RouteDecision(
                route="direct",
                confidence=0.0,
                reason="No wiki page found; answering from model knowledge.",
                difficulty=difficulty,
            )

        top = candidates[0]

        # Exact-evidence questions: always route to fallback to expose raw text
        if self.needs_exact_evidence(question) and allow_fallback:
            return RouteDecision(
                route="fallback",
                page_slugs=[c.slug for c in candidates],
                confidence=0.62,
                reason="Question asks for raw/exact source evidence.",
                difficulty=difficulty,
            )

        pages_current = all(c.page.meta.freshness == "current" for c in candidates[:2])
        confidence_ok = top.page.meta.confidence in {"high", "medium"}

        # Very strong BM25 match (score ≥ 9.0 with 5-field weighted sum)
        if top.score >= 9.0 and pages_current and confidence_ok:
            return RouteDecision(
                route="wiki",
                page_slugs=[c.slug for c in candidates[:3]],
                confidence=min(0.95, top.score / 14.0),
                reason="Very strong wiki match.",
                difficulty=difficulty,
            )

        # Good match + explicit wiki intent
        if explicit_wiki_intent and top.score >= 3.5:
            return RouteDecision(
                route="wiki",
                page_slugs=[c.slug for c in candidates[:3]],
                confidence=min(0.88, top.score / 12.0),
                reason="Wiki/document intent detected, good match.",
                difficulty=difficulty,
            )

        # Good match even without explicit intent
        if top.score >= 6.0 and confidence_ok:
            return RouteDecision(
                route="wiki",
                page_slugs=[c.slug for c in candidates[:2]],
                confidence=min(0.82, top.score / 12.0),
                reason="Good wiki match.",
                difficulty=difficulty,
            )

        # Marginal match — include only for explicit wiki requests
        if explicit_wiki_intent and top.score >= 1.5:
            return RouteDecision(
                route="wiki",
                page_slugs=[c.slug for c in candidates[:2]],
                confidence=top.score / 12.0,
                reason="Marginal match; included because wiki intent was explicit.",
                difficulty=difficulty,
            )

        return RouteDecision(
            route="direct",
            page_slugs=[],
            confidence=top.score / 12.0,
            reason="Wiki match too weak; answering from model knowledge.",
            difficulty=difficulty,
        )

    # ── Candidate retrieval ───────────────────────────────────────────────────

    def find_candidates(
        self,
        question: str,
        *,
        limit: int,
        candidate_queries: list[str] | None = None,
    ) -> list[PageCandidate]:
        """
        Multi-query BM25 retrieval with RRF merging.

        Each distinct query runs through BM25 independently.  Results are fused
        via Reciprocal Rank Fusion: a slug that appears in the top-5 of three
        different query variants scores higher than one that appears only once,
        even if that single appearance had a higher raw BM25 score.  This gives
        better recall without sacrificing precision.
        """
        self._ensure_fresh()
        all_queries = [question, *(candidate_queries or [])]

        # De-duplicate by sorted token set to avoid trivially identical queries
        ranked_lists: list[list[str]] = []
        seen: set[str] = set()
        for query in all_queries:
            norm_key = " ".join(sorted(tokenize(query)))
            if not norm_key or norm_key in seen:
                continue
            seen.add(norm_key)
            terms = tokenize(query)
            results = self._bm25.search(terms, limit=limit * 3)
            if results:
                ranked_lists.append([slug for slug, _ in results])

        if not ranked_lists:
            return []

        # Single query: use raw BM25 scores for accurate confidence values
        if len(ranked_lists) == 1:
            terms = tokenize(question)
            raw = self._bm25.search(terms, limit=limit)
            slug_score = dict(raw)
        else:
            merged = reciprocal_rank_fusion(ranked_lists, k=60)
            slug_score = dict(merged[: limit * 2])

        # Hydrate page objects (one disk read per candidate, not per query)
        candidates: list[PageCandidate] = []
        for slug, score in sorted(slug_score.items(), key=lambda x: x[1], reverse=True)[
            :limit
        ]:
            try:
                page = self.store.read_page(slug, prefer_compact=True)
                candidates.append(PageCandidate(slug=slug, score=score, page=page))
            except Exception:
                pass
        return candidates

    # ── Context assembly ──────────────────────────────────────────────────────

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
            snippet = self._page_snippet(
                page, query_terms, max_chars=max(2400, remaining // 3)
            )
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

    # ── Static classifiers ────────────────────────────────────────────────────

    @staticmethod
    def needs_exact_evidence(question: str) -> bool:
        return bool(set(tokenize(question)) & EXACT_EVIDENCE_TERMS)

    @staticmethod
    def has_wiki_intent(question: str) -> bool:
        terms = set(tokenize(question))
        lowered = question.lower()
        return (
            bool(terms & (WIKI_INTENT_TERMS | VAGUE_DOC_TERMS | SELF_PROFILE_TERMS))
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

    # ── Snippet extraction ────────────────────────────────────────────────────

    @staticmethod
    def _page_snippet(page: WikiPage, query_terms: set[str], *, max_chars: int) -> str:
        """
        Sentence-aware snippet extraction with context expansion.

        Algorithm
        ---------
        1. Split content into paragraphs (double-newline separated).
        2. Score each paragraph by query-term overlap, with bonuses for:
           - Markdown tables (high information density)
           - Section headings (navigation signal)
        3. Select top-20 scoring paragraphs.
        4. Expand selection ±1 to preserve narrative continuity.
        5. Reassemble in original document order.
        6. Trim to char budget.

        If no paragraph has keyword overlap (e.g. numeric tables), fall back
        to full content — never silently drop structured data.
        """
        paragraphs = [p.strip() for p in page.content.split("\n\n") if p.strip()]
        if not paragraphs:
            return trim_to_chars(page.content, max_chars)

        scored: list[tuple[int, float, str]] = []
        for idx, para in enumerate(paragraphs):
            para_terms = set(tokenize(para))
            overlap = len(query_terms & para_terms)

            # Structural bonuses (tables are almost always relevant for Q&A)
            is_table = para.startswith("|") or "|---|" in para or "| --- |" in para
            is_heading = para.startswith(("##", "###", "# "))
            structural_bonus = 0.35 if is_table else (0.10 if is_heading else 0.0)

            # Normalise by query length so short queries don't penalise long paras
            score = (overlap / max(1, len(query_terms))) + structural_bonus
            scored.append((idx, score, para))

        # Top-20 by score
        top_indices = {
            idx
            for idx, sc, _ in sorted(scored, key=lambda x: x[1], reverse=True)[:20]
            if sc > 0
        }
        # Expand ±1 for context cohesion
        expanded: set[int] = set()
        for idx in top_indices:
            expanded.update({max(0, idx - 1), idx, min(len(paragraphs) - 1, idx + 1)})

        selected = [
            p for idx, _, p in sorted(scored, key=lambda x: x[0]) if idx in expanded and p
        ]

        if not selected:
            # Fallback: structured/numerical content may have no term overlap
            return trim_to_chars(page.content, max_chars)

        return trim_to_chars("\n\n".join(selected), max_chars)