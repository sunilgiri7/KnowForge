"""
harness.py — deterministic routing and retrieval control layer.

Key improvements over v1:
  - Multi-query expansion: original + rewrite + step-back + keyword decomposition
    variants are all passed to the BM25 index, merged via RRF for better recall.
  - HyDE (Hypothetical Document Embeddings): generates a short hypothetical wiki
    passage and uses it as an additional retrieval signal. This captures semantic
    intent that keyword overlap misses (e.g. "how do I make X faster" → passage
    about latency optimisation → finds relevant wiki page).
  - Routing confidence is now derived from calibrated BM25 scores (not 0-1 overlap
    ratio), so the harness override conditions are more precise.
  - All expansion steps are optional-LLM-guarded: the system degrades gracefully
    to single-query BM25 if the LLM is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import settings
from app.llmwiki.contradictions import ContradictionScanner
from app.llmwiki.groq import GroqClient
from app.llmwiki.indexer import PageCandidate, WikiIndexer
from app.llmwiki.prompts import (
    HYDE_PROMPT,
    PLANNER_PROMPT,
    QUERY_EXPANSION_PROMPT,
    QUERY_REWRITE_PROMPT,
)
from app.llmwiki.storage import WikiStore
from app.llmwiki.text import safe_format, tokenize, trim_to_chars
from app.schemas.llmwiki import AgentTrace, ChatRequest, RouteDecision


@dataclass
class HarnessPlan:
    question: str
    retrieval_question: str
    decision: RouteDecision
    context: str
    used_pages: list[str]
    candidate_queries: list[str] = field(default_factory=list)
    traces: list[AgentTrace] = field(default_factory=list)


class AIHarness:
    """
    Deterministic control layer around the LLM.

    The harness is the single point of truth for routing decisions.  It ensures:
    - Explicit page selections are always honoured (no re-routing).
    - Memory/profile questions always reach the wiki even if the raw query
      scores poorly (the memory_queries expansion compensates).
    - Confidence values passed to the graph are calibrated and meaningful.
    - Every expansion step is logged in AgentTrace for observability.
    """

    def __init__(
        self,
        store: WikiStore,
        indexer: WikiIndexer,
        llm: GroqClient,
    ) -> None:
        self.store = store
        self.indexer = indexer
        self.llm = llm

    @staticmethod
    def _context_char_budget_for_route(request: ChatRequest, decision: RouteDecision) -> int:
        if request.context_page_slugs or request.intent == "wiki":
            return min(settings.wiki_context_char_budget, 16_000)
        if decision.route == "fallback":
            return min(settings.wiki_context_char_budget, 7_000)
        return min(settings.chat_context_char_budget, settings.wiki_context_char_budget)

    async def plan(self, request: ChatRequest, history: str) -> HarnessPlan:
        traces: list[AgentTrace] = [
            AgentTrace(
                agent="harness",
                action="start",
                confidence=1.0,
                notes="Routing, expansion, and retrieval controls initialised.",
            )
        ]

        if "Selected thread context for this reply/comment:" in history:
            traces.append(AgentTrace(
                agent="thread_harness",
                action=request.interaction,
                confidence=0.86,
                notes="Anchored reply to selected parent message thread.",
            ))

        # ── Fast path: explicit wiki page selection or slug named in question ─
        selected_slugs = list(request.context_page_slugs)
        if not selected_slugs:
            selected_slugs = self.indexer.resolve_slug_mentions(request.question)
        if selected_slugs:
            reason = (
                "Explicit wiki page context selected by user."
                if request.context_page_slugs
                else f"Question names wiki page(s): {', '.join(selected_slugs)}."
            )
            decision = RouteDecision(
                route="wiki",
                page_slugs=selected_slugs[: settings.kg_max_pages_in_context],
                confidence=1.0,
                reason=reason,
                difficulty=self.indexer.classify_difficulty(request.question, []),
            )
            # If the user explicitly selected the page, or the slug is named in the question,
            # but the page is very long, we should use snippet extraction to prevent LLM distraction.
            # Otherwise, use exact page context.
            use_exact = True
            for slug in decision.page_slugs:
                try:
                    p = self.indexer.store.read_page(slug)
                    if len(p.content) > 12000:
                        use_exact = False
                        break
                except Exception:
                    pass

            if use_exact:
                context, used_pages = self.indexer.build_exact_page_context(
                    decision.page_slugs,
                    char_budget=settings.wiki_context_char_budget,
                )
            else:
                context, used_pages = self.indexer.build_context(
                    decision.page_slugs,
                    request.question,
                    char_budget=settings.wiki_context_char_budget,
                )
            traces.append(self._trace_decision(decision))
            if not request.context_page_slugs and selected_slugs:
                traces.append(
                    AgentTrace(
                        agent="wiki_selector",
                        action="resolved_slug_in_question",
                        confidence=1.0,
                        notes=", ".join(selected_slugs),
                    )
                )
            return HarnessPlan(
                question=request.question,
                retrieval_question=request.question,
                decision=decision,
                context=context,
                used_pages=used_pages,
                candidate_queries=[request.question],
                traces=traces,
            )

        # ── Fast path: explicit direct mode ──────────────────────────────────
        if request.intent == "direct":
            decision = RouteDecision(
                route="direct",
                page_slugs=[],
                confidence=1.0,
                reason="Direct assistant mode requested.",
                difficulty="easy",
            )
            traces.append(self._trace_decision(decision))
            return HarnessPlan(
                question=request.question,
                retrieval_question=request.question,
                decision=decision,
                context="",
                used_pages=[],
                candidate_queries=[request.question],
                traces=traces,
            )

        # ── Multi-query expansion ────────────────────────────────────────────
        # We build a set of query variants that cover different facets of the
        # user's intent.  All variants are passed to find_candidates() which
        # runs BM25 per variant and merges via RRF.
        candidate_queries: list[str] = [request.question]
        retrieval_question = request.question
        memory_hint = self._looks_like_memory_question(request.question)

        # 1. Context-aware rewrite: resolve pronouns / anaphora from history
        rewrite, rewrite_hint = await self._rewrite_for_retrieval(request.question, history)
        if rewrite and rewrite != request.question:
            candidate_queries.append(rewrite)
            retrieval_question = rewrite
            traces.append(AgentTrace(
                agent="query_understanding",
                action="rewrote_query",
                confidence=0.72,
                notes=rewrite,
            ))

        # 2. Step-back + keyword expansion (LLM-generated alternative phrasings)
        if self.llm.available:
            expanded = await self._expand_queries(request.question, history)
            new_variants = [q for q in expanded if q not in candidate_queries][:2]
            if new_variants:
                candidate_queries.extend(new_variants)
                traces.append(AgentTrace(
                    agent="query_expansion",
                    action="generated_variants",
                    confidence=0.68,
                    notes="; ".join(new_variants),
                ))

        # 3. HyDE: hypothetical passage for semantic retrieval coverage.
        #    Fire for memory, rewrite-hinted, explicit wiki-mode, OR any
        #    document/financial intent — these queries need the vocabulary
        #    bridge most (e.g. "salary structure" → "compensation breakdown").
        wiki_intent_hint = self.indexer.has_wiki_intent(request.question)
        if (memory_hint or rewrite_hint or wiki_intent_hint or request.intent == "wiki") and self.llm.available:
            hyde = await self._hyde_passage(request.question)
            if hyde:
                candidate_queries.append(hyde)
                traces.append(AgentTrace(
                    agent="hyde",
                    action="generated_hypothetical_passage",
                    confidence=0.60,
                    notes="Hypothetical passage added for semantic retrieval coverage.",
                ))

        # 4. Memory expansion: use wiki page metadata as additional queries
        #    so profile/background questions find the right personal pages
        if memory_hint:
            memory_queries = self._memory_queries()
            if memory_queries:
                candidate_queries.extend(memory_queries)
                retrieval_question = " ".join([retrieval_question, *memory_queries[:4]])
                traces.append(AgentTrace(
                    agent="memory_router",
                    action="expanded_from_wiki_memory",
                    confidence=0.74,
                    notes="Added wiki titles/summaries/tags for personal context queries.",
                ))

        # ── Routing ──────────────────────────────────────────────────────────
        decision = self.indexer.route(
            retrieval_question,
            allow_fallback=request.allow_fallback,
            candidate_queries=candidate_queries,
        )

        # Harness override: memory/wiki intent should always reach the wiki
        # even if the BM25 score is marginal (HyDE+expansion improves recall,
        # but we still fall back to a direct fetch if anything scored at all).
        if (memory_hint or rewrite_hint or request.intent == "wiki") and decision.route == "direct":
            candidates = self.indexer.find_candidates(
                retrieval_question, limit=4, candidate_queries=candidate_queries
            )
            if candidates:
                decision = self._wiki_decision_from_candidates(
                    retrieval_question,
                    candidates,
                    "Harness override: wiki context found via expanded query.",
                )

        # Harness override: any query with explicit wiki/document intent
        # (salary, contract, benefits, pay, etc.) should never go direct when
        # there are wiki pages available — the BM25 threshold is too strict for
        # small corpora where IDF is compressed.
        if decision.route == "direct" and self.indexer.has_wiki_intent(request.question):
            candidates = self.indexer.find_candidates(
                retrieval_question, limit=4, candidate_queries=candidate_queries
            )
            if candidates:
                decision = self._wiki_decision_from_candidates(
                    retrieval_question,
                    candidates,
                    "Harness override: document-intent query rerouted to wiki.",
                )
                traces.append(AgentTrace(
                    agent="wiki_intent_override",
                    action="forced_wiki_route",
                    confidence=decision.confidence,
                    notes="Query contained document/financial intent terms; BM25 score was below threshold but wiki pages exist.",
                ))

        if request.intent == "wiki" and decision.route == "direct":
            candidates = self.indexer.find_candidates(
                retrieval_question, limit=4, candidate_queries=candidate_queries
            )
            decision = self._wiki_decision_from_candidates(
                retrieval_question, candidates, "Wiki mode requested."
            )

        traces.append(self._trace_decision(decision))

        # ── Knowledge graph + planner-driven multi-hop retrieval ─────────────
        if decision.route in ("wiki", "fallback") and decision.page_slugs:
            expanded_slugs, kg_traces = await self._expand_retrieval_slugs(
                decision=decision,
                retrieval_question=retrieval_question,
                candidate_queries=candidate_queries,
            )
            traces.extend(kg_traces)
            if expanded_slugs != decision.page_slugs:
                decision = decision.model_copy(update={"page_slugs": expanded_slugs})

        # ── Context assembly ──────────────────────────────────────────────────
        context_budget = self._context_char_budget_for_route(request, decision)
        if decision.route in ("wiki", "fallback") or request.intent == "wiki":
            # Memory/wiki-mode: always return the full page so the LLM has
            # complete structured data (salary tables, full experience sections)
            use_exact = memory_hint or request.intent == "wiki"
            if use_exact:
                context, used_pages = self.indexer.build_exact_page_context(
                    decision.page_slugs, char_budget=context_budget,
                )
            else:
                context, used_pages = self.indexer.build_context(
                    decision.page_slugs, retrieval_question, char_budget=context_budget,
                )
            conflict_note = ContradictionScanner(self.store).context_warnings_for_slugs(
                used_pages or decision.page_slugs
            )
            if conflict_note:
                context = f"{conflict_note}\n\n{context}"
                traces.append(
                    AgentTrace(
                        agent="contradiction_guard",
                        action="injected_open_conflicts",
                        confidence=0.82,
                        notes="Open cross-page conflicts prepended to wiki context.",
                    )
                )
        else:
            context, used_pages = "", []

        return HarnessPlan(
            question=request.question,
            retrieval_question=retrieval_question,
            decision=decision,
            context=context,
            used_pages=used_pages,
            candidate_queries=candidate_queries,
            traces=traces,
        )

    # ── Query expansion helpers ───────────────────────────────────────────────

    async def _rewrite_for_retrieval(self, question: str, history: str) -> tuple[str, bool]:
        """Resolve pronouns/anaphora using conversation history."""
        if not self.llm.available or not history.strip():
            return question, False
        try:
            payload = await self.llm.generate_json(
                safe_format(QUERY_REWRITE_PROMPT, question=question, history=history),
                temperature=0.05,
            )
            rewritten = str(payload.get("rewritten_question") or question).strip()
            should_use_wiki = bool(payload.get("should_use_wiki"))
            return rewritten or question, should_use_wiki
        except Exception:
            return question, False

    async def _expand_queries(self, question: str, history: str) -> list[str]:
        """
        Generate 2 alternative retrieval queries via step-back prompting.

        Step-back prompting (Zheng et al. 2023): ask the model to produce a
        more general version of the question that a search engine would respond
        to better.  We also ask for a keyword-focused variant which tends to
        pull in structured pages that the conversational phrasing misses.

        Returns at most 2 non-empty, non-duplicate strings.
        """
        try:
            payload = await self.llm.generate_json(
                safe_format(
                    QUERY_EXPANSION_PROMPT,
                    question=question,
                    history=history or "None",
                ),
                temperature=0.15,
            )
            variants = payload.get("variants", [])
            return [
                str(v).strip()
                for v in variants
                if str(v).strip() and str(v).strip() != question
            ]
        except Exception:
            return []

    async def _hyde_passage(self, question: str) -> str:
        """
        HyDE (Hypothetical Document Embeddings, Gao et al. 2022).

        Ask the LLM: "What would a wiki page section that answers this question
        look like?"  Use the generated passage as an additional BM25 query.
        This bridges the vocabulary gap between the user's question and the
        wiki page's terminology.

        Example:
          Q: "What's my notice period if I leave?"
          Hypothetical passage: "Employee must provide 90 days written notice
          before termination. Early departure triggers a notice-period penalty
          clause under Section 7."
          → This surfaces the employment-agreement wiki page via "notice period"
            and "termination" even if the original question used different words.
        """
        try:
            payload = await self.llm.generate_json(
                safe_format(HYDE_PROMPT, question=question),
                temperature=0.25,
            )
            return str(payload.get("passage", "")).strip()
        except Exception:
            return ""

    async def _expand_retrieval_slugs(
        self,
        *,
        decision: RouteDecision,
        retrieval_question: str,
        candidate_queries: list[str],
    ) -> tuple[list[str], list[AgentTrace]]:
        traces: list[AgentTrace] = []
        seed_slugs = list(decision.page_slugs)
        max_hops = settings.kg_max_hops
        if decision.difficulty == "hard" and decision.confidence < 0.75:
            max_hops = settings.kg_max_hops_hard

        expanded = self.indexer.expand_with_graph(
            seed_slugs,
            retrieval_question,
            max_hops=max_hops,
        )
        added = [s for s in expanded if s not in seed_slugs]
        if added:
            traces.append(
                AgentTrace(
                    agent="knowledge_graph",
                    action="expanded_pages",
                    confidence=0.74,
                    notes=f"Graph expansion added: {', '.join(added)}",
                )
            )

        if decision.difficulty == "hard" and self.llm.available:
            planner_context = ""
            if expanded:
                planner_context, _ = self.indexer.build_context(
                    expanded[:2],
                    retrieval_question,
                    char_budget=min(settings.wiki_context_char_budget, 6_000),
                )
            subquestions = await self._planner_subquestions(retrieval_question, planner_context)
            planner_added: list[str] = []
            for subq in subquestions[: settings.kg_planner_subquestions]:
                candidates = self.indexer.find_candidates(
                    subq,
                    limit=2,
                    candidate_queries=candidate_queries,
                )
                for cand in candidates:
                    if cand.slug not in expanded:
                        expanded.append(cand.slug)
                        planner_added.append(cand.slug)
                    if len(expanded) >= settings.kg_max_pages_in_context:
                        break
                if len(expanded) >= settings.kg_max_pages_in_context:
                    break
            if subquestions:
                traces.append(
                    AgentTrace(
                        agent="planner",
                        action="retrieval_subquestions",
                        confidence=0.72,
                        notes="; ".join(subquestions[: settings.kg_planner_subquestions]),
                    )
                )
            if planner_added:
                traces.append(
                    AgentTrace(
                        agent="knowledge_graph",
                        action="planner_expanded_pages",
                        confidence=0.70,
                        notes=f"Planner retrieval added: {', '.join(planner_added)}",
                    )
                )

        return expanded[: settings.kg_max_pages_in_context], traces

    async def _planner_subquestions(self, question: str, context: str) -> list[str]:
        if not self.llm.available:
            return []
        try:
            payload = await self.llm.generate_json(
                safe_format(
                    PLANNER_PROMPT,
                    question=question,
                    context=trim_to_chars(context, settings.wiki_context_char_budget),
                ),
                temperature=0.1,
            )
            raw = payload.get("subquestions", [])
            return [str(item).strip() for item in raw if str(item).strip()]
        except Exception:
            return []

    # ── Memory helpers ────────────────────────────────────────────────────────

    def _memory_queries(self) -> list[str]:
        """Build retrieval queries from wiki page metadata for profile questions."""
        queries: list[str] = []
        for item in self.store.list_pages()[:8]:
            parts = [
                item.title,
                item.summary,
                " ".join(item.tags),
                " ".join(item.source_ids),
            ]
            query = " ".join(p for p in parts if p).strip()
            if query:
                queries.append(query)
        return queries

    @staticmethod
    def _looks_like_memory_question(question: str) -> bool:
        compact = " ".join(question.lower().split())
        if any(
            phrase in compact
            for phrase in (
                "about me",
                "about myself",
                "know me",
                "know about me",
                "know about myself",
                "who am i",
                "who i am",
                "my profile",
                "my background",
                "my resume",
                "my experience",
                "my skills",
            )
        ):
            return True
        terms = set(tokenize(question))
        first_person = {"i", "me", "my", "myself", "mine"}
        memory_terms = {
            "about", "background", "bio", "details", "experience",
            "identity", "know", "profile", "resume", "skills", "tell", "who",
        }
        return bool((terms & first_person) and (terms & memory_terms))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _wiki_decision_from_candidates(
        self,
        question: str,
        candidates: list[PageCandidate],
        reason: str,
    ) -> RouteDecision:
        if not candidates:
            return RouteDecision(
                route="direct",
                page_slugs=[],
                confidence=0.0,
                reason="No usable wiki page found.",
                difficulty="easy",
            )
        top_score = candidates[0].score
        return RouteDecision(
            route="wiki",
            page_slugs=[c.slug for c in candidates[:4]],
            # Calibrate confidence to BM25 score range (max ~25 for perfect match)
            confidence=min(0.87, max(0.30, top_score / 14.0)),
            reason=reason,
            difficulty=self.indexer.classify_difficulty(question, candidates),
        )

    @staticmethod
    def _trace_decision(decision: RouteDecision) -> AgentTrace:
        return AgentTrace(
            agent="router",
            action=decision.route,
            confidence=decision.confidence,
            notes=decision.reason,
        )