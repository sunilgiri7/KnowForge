"""
indexer.py — Hybrid BM25 + Semantic vector retrieval engine.

Key capabilities:
  - BM25PageIndex: in-memory multi-field inverted index; builds once, searches
    in microseconds instead of doing O(n) disk reads per query.
  - Semantic vector search via Pinecone (all-MiniLM-L6-v2 embeddings, 384-dim).
  - Hybrid RRF fusion: BM25 ranked list + vector ranked list merged via
    Reciprocal Rank Fusion with configurable weight split.
  - Multi-query expansion: original + rewrite + step-back + keyword variants
    all passed to BM25; merged via RRF for better recall.
  - Better snippet extraction: sentence-level paragraph scoring + ±1
    expansion for narrative continuity + table preservation.
  - Calibrated routing thresholds derived from BM25 field-weight sums.
"""
from __future__ import annotations

import asyncio
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass

from app.core.config import settings
from app.llmwiki.knowledge_graph import WikiKnowledgeGraph
from app.llmwiki.storage import WikiStore
from app.llmwiki.text import (
    bm25_score,
    reciprocal_rank_fusion,
    tokenize,
    trim_to_chars,
)
from app.schemas.llmwiki import RouteDecision, WikiPage

# ── Routing intent term sets ──────────────────────────────────────────────────

_SLUG_TOKEN_RE = re.compile(r"\b[a-z0-9]+(?:-[a-z0-9]+)+\b", re.IGNORECASE)

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
    # Contract / agreement types
    "abstract", "agreement", "architecture", "benchmark", "contract",
    "method", "notice", "paper", "policy", "provision", "research",
    "results", "section", "termination",
    # Financial / HR (the most common query category)
    "allowance", "benefits", "bonus", "breakdown", "compensation",
    "component", "ctc", "deduction", "earnings", "gross", "incentive",
    "netpay", "package", "pay", "payslip", "salary", "structure", "tax",
    # Personal document terms
    "certification", "clause", "details", "education", "employment",
    "joining", "leave", "offer", "probation", "qualification",
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
        "title":    5.0,
        "slug":     4.5,
        "aliases":  3.5,
        "tags":     3.0,
        "entities": 1.2,
        "summary":  2.0,
        "content":  1.0,
    }

    # How many content chars to index.
    # Must be large enough to cover salary tables, clause lists, etc.
    # that appear deep in compiled employment/contract wiki pages.
    CONTENT_INDEX_CHARS = 24_000

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
        slug_text = page.meta.slug.replace("-", " ")
        return {
            "title":    page.meta.title,
            "slug":     f"{page.meta.slug} {slug_text}",
            "aliases":  " ".join(page.meta.aliases),
            "tags":     " ".join(page.meta.tags),
            "entities": " ".join(page.meta.entities),
            "summary":  page.meta.summary,
            "content":  page.content[: BM25PageIndex.CONTENT_INDEX_CHARS],
        }


# ── WikiIndexer ───────────────────────────────────────────────────────────────


class WikiIndexer:
    """
    Hybrid retrieval layer: BM25 (lexical) + Pinecone (semantic).

    Routing thresholds
    ------------------
    BM25 scores are unbounded (sum of IDF x TF_norm across fields, weighted).
    With the field weights above, a perfect title+tag+summary match on a
    medium-sized wiki typically scores 12-25.  Thresholds below are calibrated
    against this range:

        >= 9.0  -> very strong match (confident wiki route)
        >= 6.0  -> good match (wiki route, slightly lower confidence)
        >= 3.5  -> reasonable match (wiki route for explicit wiki-intent queries)
        >= 1.5  -> marginal (wiki route only when user explicitly asked for wiki)
        <  1.5  -> direct LLM

    Hybrid fusion
    -------------
    When Pinecone is configured, vector search results are RRF-merged with BM25
    results using the hybrid_vector_weight setting (default 0.5):
      - BM25 ranked list -> RRF score weighted by (1 - hybrid_vector_weight)
      - Vector ranked list -> RRF score weighted by hybrid_vector_weight
    This combination captures both keyword precision and semantic similarity.
    """

    # Rebuild the in-memory index if either condition is met:
    INDEX_MAX_AGE_SECS = 120  # 2-minute freshness window
    # (page count change triggers immediate rebuild regardless of age)

    def __init__(self, store: WikiStore) -> None:
        self.store = store
        self._bm25 = BM25PageIndex()
        self._graph = WikiKnowledgeGraph(store)
        self._indexed_page_count = -1
        self._indexed_mutation_revision = -1
        self._last_rebuild_ts = 0.0
        # Lazy VectorStore — only initialised if Pinecone key is configured
        self._vector_store = None
        if settings.pinecone_api_key:
            try:
                from app.llmwiki.vector_store import VectorStore
                self._vector_store = VectorStore(store._workspace_id)
            except Exception:
                pass

    # ── Index management ──────────────────────────────────────────────────────

    def _ensure_fresh(self) -> None:
        """Rebuild if stale. O(n) on first call, then in-memory cache."""
        current_count = len(self.store.list_pages())
        revision = self.store.mutation_revision
        age = time.monotonic() - self._last_rebuild_ts
        if (
            current_count != self._indexed_page_count
            or revision != self._indexed_mutation_revision
            or age > self.INDEX_MAX_AGE_SECS
        ):
            self._bm25.rebuild_from_store(self.store)
            self._indexed_page_count = current_count
            self._indexed_mutation_revision = revision
            self._last_rebuild_ts = time.monotonic()

    def invalidate(self) -> None:
        """Force index rebuild on next search (call after page writes)."""
        self._indexed_page_count = -1
        self._indexed_mutation_revision = -1
        self._graph.invalidate()

    def resolve_slug_mentions(self, question: str) -> list[str]:
        """
        Match wiki pages explicitly referenced in the user question.

        Three layers:
        1. Exact slug match ("employment-agreement-sunil-giri" in question)
        2. Hyphenated token regex match
        3. Title-word overlap — if ≥2 significant words from a page title
           appear in the question, treat it as an explicit reference.
        4. Entity name match — if a named entity stored in page metadata
           (e.g. "Sunil Giri", "AcoBloom International") appears verbatim
           in the question, route to that page.
        """
        self._ensure_fresh()
        pages = self.store.list_pages()
        if not pages:
            return []

        known = {item.slug for item in pages}
        found: list[str] = []
        seen: set[str] = set()
        lowered = question.lower()
        q_tokens = set(tokenize(question))

        # Layer 1: exact slug substring
        for slug in sorted(known, key=len, reverse=True):
            if slug in lowered and slug not in seen:
                seen.add(slug)
                found.append(slug)

        # Layer 2: hyphenated-token pattern
        for match in _SLUG_TOKEN_RE.findall(question):
            candidate = match.lower()
            if candidate in known and candidate not in seen:
                seen.add(candidate)
                found.append(candidate)

        # Layer 3: title-word overlap (≥2 significant title tokens in question)
        for item in pages:
            if item.slug in seen:
                continue
            title_tokens = set(tokenize(item.title))
            # Require at least 2 meaningful overlapping words
            overlap = title_tokens & q_tokens
            if len(overlap) >= 2:
                seen.add(item.slug)
                found.append(item.slug)

        # Layer 4: entity name match (person names, org names, etc.)
        for item in pages:
            if item.slug in seen:
                continue
            for entity in item.tags[:20]:          # tags store key entities/topics
                entity_clean = entity.strip().lower()
                if len(entity_clean) >= 4 and entity_clean in lowered:
                    seen.add(item.slug)
                    found.append(item.slug)
                    break

        return found

    def expand_with_graph(
        self,
        seed_slugs: list[str],
        question: str,
        *,
        max_extra: int = 4,
        max_hops: int | None = None,
    ) -> list[str]:
        """Return seed slugs plus graph-expanded pages (seeds first, deduped)."""
        cap = min(settings.kg_max_pages_in_context, len(seed_slugs) + max(0, max_extra))
        hops = max_hops if max_hops is not None else settings.kg_max_hops
        return self._graph.expand(
            seed_slugs,
            question,
            max_hops=hops,
            max_pages=cap,
        )

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
        Hybrid retrieval: BM25 (lexical) + Pinecone vector (semantic), fused via RRF.

        Step 1 — BM25 retrieval:
          Each distinct query variant runs through BM25 independently.
          Results fused via RRF across all variants.

        Step 2 — Vector retrieval (when Pinecone is configured):
          The original question is embedded and queried against Pinecone.
          Returns top-k slugs sorted by cosine similarity.

        Step 3 — Hybrid RRF fusion:
          BM25 slug list and vector slug list are merged via weighted RRF:
            RRF_hybrid(slug) = w_bm25 * RRF_bm25(slug) + w_vec * RRF_vec(slug)
          w_bm25 = 1 - hybrid_vector_weight
          w_vec  = hybrid_vector_weight

        This approach is used in production by Cohere, Weaviate, Elastic and
        Pinecone's own hybrid search documentation.
        """
        self._ensure_fresh()
        all_queries = [question, *(candidate_queries or [])]

        # ── Step 1: BM25 retrieval ────────────────────────────────────────────
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
            bm25_slug_scores: dict[str, float] = {}
        elif len(ranked_lists) == 1:
            terms = tokenize(question)
            raw = self._bm25.search(terms, limit=limit)
            bm25_slug_scores = dict(raw)
        else:
            merged = reciprocal_rank_fusion(ranked_lists, k=60)
            bm25_slug_scores = dict(merged[: limit * 2])

        # ── Step 2: Vector retrieval (async in sync context via asyncio) ──────
        vector_slug_scores: dict[str, float] = {}
        if self._vector_store and self._vector_store.available:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We are inside an async context — schedule and await
                    import concurrent.futures
                    future = asyncio.run_coroutine_threadsafe(
                        self._vector_store.query(question, top_k=limit * 2),
                        loop,
                    )
                    vector_results = future.result(timeout=5)
                else:
                    vector_results = loop.run_until_complete(
                        self._vector_store.query(question, top_k=limit * 2)
                    )
                vector_slug_scores = dict(vector_results)
            except Exception:
                vector_slug_scores = {}

        # ── Step 3: Weighted RRF fusion ───────────────────────────────────────
        w_vec = settings.hybrid_vector_weight
        w_bm25 = 1.0 - w_vec
        k = 60  # RRF rank constant

        all_slugs = set(bm25_slug_scores) | set(vector_slug_scores)

        if not all_slugs:
            return []

        # Sort each list independently for rank-based scoring
        bm25_ranked = sorted(bm25_slug_scores, key=lambda s: bm25_slug_scores[s], reverse=True)
        vec_ranked   = sorted(vector_slug_scores, key=lambda s: vector_slug_scores[s], reverse=True)

        bm25_rank = {slug: rank for rank, slug in enumerate(bm25_ranked, start=1)}
        vec_rank  = {slug: rank for rank, slug in enumerate(vec_ranked, start=1)}

        hybrid_scores: dict[str, float] = {}
        for slug in all_slugs:
            rrf_bm25 = w_bm25 / (k + bm25_rank[slug]) if slug in bm25_rank else 0.0
            rrf_vec  = w_vec  / (k + vec_rank[slug])  if slug in vec_rank  else 0.0
            hybrid_scores[slug] = rrf_bm25 + rrf_vec

        # ── Hydrate page objects ──────────────────────────────────────────────
        candidates: list[PageCandidate] = []
        for slug, score in sorted(hybrid_scores.items(), key=lambda x: x[1], reverse=True)[:limit]:
            try:
                page = self.store.read_page(slug, prefer_compact=True)
                # Use BM25 raw score for routing confidence (more calibrated than RRF float)
                raw_bm25 = bm25_slug_scores.get(slug, 0.0)
                candidates.append(PageCandidate(slug=slug, score=raw_bm25, page=page))
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
            # Give each page the full remaining budget divided by pages left.
            # Previously //3 was too aggressive — a long employment agreement
            # needs >4000 chars to include both the compensation clause AND the
            # Addendum IV salary breakdown table.
            pages_left = max(1, len(slugs) - len(used))
            per_page_budget = max(4000, remaining // pages_left)
            snippet = self._page_snippet(
                page, query_terms, max_chars=min(per_page_budget, remaining - 800)
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
        Sentence-aware snippet extraction with budget-aware selection and pruning.
        """
        paragraphs = [p.strip() for p in page.content.split("\n\n") if p.strip()]
        if not paragraphs:
            return trim_to_chars(page.content, max_chars)

        _STOP_WORDS = {
            "a", "about", "above", "after", "again", "against", "all", "am", "an",
            "and", "any", "are", "as", "at", "be", "because", "been", "before", "being",
            "below", "between", "both", "but", "by", "can", "did", "do", "does", "doing",
            "don", "down", "during", "each", "few", "for", "from", "further", "had",
            "has", "have", "having", "he", "her", "here", "hers", "herself", "him",
            "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself",
            "me", "more", "most", "my", "myself", "no", "nor", "not", "of", "off", "on",
            "once", "only", "or", "other", "our", "ours", "ourselves", "out", "over",
            "own", "same", "she", "should", "so", "some", "such", "than", "that", "the",
            "their", "theirs", "them", "themselves", "then", "there", "these", "they",
            "this", "those", "through", "to", "too", "under", "until", "up", "very",
            "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom",
            "why", "with", "you", "your", "yours", "yourself", "yourselves"
        }

        def count_financial_numbers(text: str) -> int:
            tokens = re.findall(r"\b\d[\d,.]*\b", text)
            count = 0
            for t in tokens:
                if t.count(".") > 1:
                    continue  # section numbers like 2.1.1
                clean = t.replace(",", "").replace(".", "")
                if clean.isdigit():
                    val = int(clean)
                    # Financial/salary values are typically between 100 and 2,000,000
                    if 100 <= val <= 2000000:
                        count += 1
            return count

        _HEADING_RE = re.compile(r"^#{1,4}\s+(.+)$")
        _CURRENCY_CHAR_RE = re.compile(r"[₹$€£,]")

        meaningful_query_terms = query_terms - _STOP_WORDS

        # Classify query type using meaningful query terms
        _FINANCIAL_TERMS = {
            "salary", "structure", "pay", "netpay", "compensation", "allowance",
            "deduction", "benefits", "ctc", "gross", "basic", "hra", "package",
            "earnings", "breakdown", "component", "incentive", "tax", "amount",
        }
        _EDUCATION_TERMS = {
            "qualifications", "certification", "education", "degree", "diploma",
            "gpa", "marks", "percentage", "university", "college", "school",
        }
        is_financial_query = bool(meaningful_query_terms & _FINANCIAL_TERMS)
        is_education_query = bool(meaningful_query_terms & _EDUCATION_TERMS)

        _SALARY_COMPONENTS = {
            "basic", "hra", "conveyance", "allowance", "allowances", "ctc", "net pay", "netpay",
            "gross salary", "gross", "deduction", "deductions", "provident", "pf", "bonus",
            "gratuity", "medical insurance", "inr", "rupees", "particulars"
        }
        _EDUCATION_COMPONENTS = {
            "btech", "degree", "diploma", "gpa", "marks", "percentage", "university", "college",
            "school", "passing year", "year of passing", "specialization"
        }

        # Track the nearest preceding heading's tokens for each paragraph
        current_heading_tokens: set[str] = set()
        para_heading_tokens: list[set[str]] = []
        for para in paragraphs:
            m = _HEADING_RE.match(para)
            if m:
                current_heading_tokens = (set(tokenize(m.group(1))) - _STOP_WORDS)
            para_heading_tokens.append(current_heading_tokens.copy())

        scored: list[tuple[int, float, str]] = []
        for idx, para in enumerate(paragraphs):
            para_terms = set(tokenize(para))
            meaningful_para_terms = para_terms - _STOP_WORDS
            overlap = len(meaningful_query_terms & meaningful_para_terms)

            is_table = para.startswith("|") or "|---|" in para or "| --- |" in para
            is_heading = para.startswith(("##", "###", "# "))

            # Heading contains query terms?
            ancestor_overlap = len(meaningful_query_terms & para_heading_tokens[idx])
            heading_context_bonus = 0.50 if ancestor_overlap > 0 else 0.0

            # Table bonus
            table_bonus = 0.40 if is_table else 0.0

            # Number density bonus (crucial for numerical queries)
            num_count = count_financial_numbers(para)
            currency_count = len(_CURRENCY_CHAR_RE.findall(para))
            number_density = min(num_count * 0.08 + currency_count * 0.10, 0.70)
            if is_financial_query:
                number_density *= 2.0

            # Keyword overlap score
            kw_score = overlap / max(1, len(meaningful_query_terms))

            # Heading bonus
            heading_bonus = 0.15 if is_heading else 0.0

            # Addendum / Appendix bonus
            is_addendum = any(kw in para.lower() for kw in ("addendum", "appendix", "schedule", "annex"))
            addendum_bonus = 0.35 if is_addendum else 0.0

            # Component matching bonus (boosts exact domain tables/breakdowns)
            component_bonus = 0.0
            lower_para = para.lower()
            if is_financial_query:
                matching_components = [c for c in _SALARY_COMPONENTS if c in lower_para]
                component_bonus = min(len(matching_components) * 0.20, 1.0)
            elif is_education_query:
                matching_components = [c for c in _EDUCATION_COMPONENTS if c in lower_para]
                component_bonus = min(len(matching_components) * 0.20, 1.0)

            score = kw_score + table_bonus + number_density + heading_context_bonus + heading_bonus + addendum_bonus + component_bonus
            scored.append((idx, score, para))

        # Sort paragraphs by score descending to prioritize high-value content
        sorted_by_score = sorted(scored, key=lambda x: x[1], reverse=True)

        selected_indices = set()
        seed_count = 0
        max_seeds = 5  # limit seeds to avoid noise flooding when budget is large
        
        # We greedily add the highest scoring paragraphs and their ±2/±1 context
        # as long as the total length stays under max_chars.
        for idx, score, para in sorted_by_score:
            if score <= 0.05:
                continue
            if seed_count >= max_seeds:
                break
            
            # Context expansion: try to add the paragraph and its neighbors
            # We use max(0, idx - 2) to capture introductory paragraphs/subheadings
            # preceding tables or sections (e.g. Basic and HRA headers for salary tables).
            neighbors = {max(0, idx - 2), max(0, idx - 1), idx, min(len(paragraphs) - 1, idx + 1)}
            new_indices = selected_indices | neighbors
            
            # Calculate total character length if we include this neighborhood
            total_len = sum(len(paragraphs[i]) + 2 for i in new_indices)
            
            if total_len <= max_chars:
                selected_indices = new_indices
                seed_count += 1
            else:
                # If neighborhood doesn't fit, try to add just this paragraph
                new_indices_solo = selected_indices | {idx}
                total_len_solo = sum(len(paragraphs[i]) + 2 for i in new_indices_solo)
                if total_len_solo <= max_chars:
                    selected_indices = new_indices_solo
                    seed_count += 1
                # If even the paragraph alone doesn't fit, keep searching for smaller high-scoring paras

        # Fallback: if nothing got selected (e.g. extremely low scores), fill budget from the beginning
        if not selected_indices:
            current_len = 0
            for idx, para in enumerate(paragraphs):
                if current_len + len(para) + 2 <= max_chars:
                    selected_indices.add(idx)
                    current_len += len(para) + 2
                else:
                    break

        if not selected_indices:
            return trim_to_chars(page.content, max_chars)

        # Assemble selected paragraphs in original document order to preserve coherence
        selected_paragraphs = [paragraphs[i] for i in sorted(selected_indices)]
        return "\n\n".join(selected_paragraphs)