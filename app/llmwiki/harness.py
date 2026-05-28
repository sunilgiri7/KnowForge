from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import settings
from app.llmwiki.groq import GroqClient
from app.llmwiki.indexer import PageCandidate, WikiIndexer
from app.llmwiki.prompts import QUERY_REWRITE_PROMPT
from app.llmwiki.storage import WikiStore
from app.llmwiki.text import safe_format, tokenize
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
    """Deterministic control layer around the LLM.

    The harness keeps routing and retrieval predictable: selected pages are always
    used, vague memory questions search the user's wiki, and weak matches stay direct.
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
        # Keep route-specific budgets conservative for free-tier model context windows.
        if request.context_page_slugs or request.intent == "wiki":
            return min(settings.wiki_context_char_budget, 16_000)
        if decision.route == "fallback":
            return min(settings.wiki_context_char_budget, 7_000)
        return min(settings.chat_context_char_budget, settings.wiki_context_char_budget)

    async def plan(self, request: ChatRequest, history: str) -> HarnessPlan:
        traces = [
            AgentTrace(
                agent="harness",
                action="start",
                confidence=1.0,
                notes="Prepared request, memory, routing, and retrieval controls.",
            )
        ]
        if "Selected thread context for this reply/comment:" in history:
            traces.append(
                AgentTrace(
                    agent="thread_harness",
                    action=request.interaction,
                    confidence=0.86,
                    notes="Anchored this turn to the selected parent message thread.",
                )
            )
        candidate_queries = [request.question]
        retrieval_question = request.question

        if request.context_page_slugs:
            decision = RouteDecision(
                route="wiki",
                page_slugs=request.context_page_slugs,
                confidence=1.0,
                reason="Explicit wiki page context was selected.",
                difficulty=self.indexer.classify_difficulty(request.question, []),
            )
            context, used_pages = self.indexer.build_exact_page_context(
                decision.page_slugs,
                char_budget=settings.wiki_context_char_budget,
            )
            traces.append(self._trace_decision(decision))
            return HarnessPlan(
                question=request.question,
                retrieval_question=retrieval_question,
                decision=decision,
                context=context,
                used_pages=used_pages,
                candidate_queries=candidate_queries,
                traces=traces,
            )

        if request.intent == "direct":
            decision = RouteDecision(
                route="direct",
                page_slugs=[],
                confidence=1.0,
                reason="Direct assistant mode was requested.",
                difficulty="easy",
            )
            traces.append(self._trace_decision(decision))
            return HarnessPlan(
                question=request.question,
                retrieval_question=retrieval_question,
                decision=decision,
                context="",
                used_pages=[],
                candidate_queries=candidate_queries,
                traces=traces,
            )

        rewrite, rewrite_hint = await self._rewrite_for_retrieval(request.question, history)
        if rewrite != request.question:
            candidate_queries.append(rewrite)
            retrieval_question = rewrite
            traces.append(
                AgentTrace(
                    agent="query_understanding",
                    action="rewrote_query",
                    confidence=0.72,
                    notes=rewrite,
                )
            )

        memory_hint = self._looks_like_memory_question(request.question)
        if memory_hint:
            memory_queries = self._memory_queries()
            if memory_queries:
                candidate_queries.extend(memory_queries)
                retrieval_question = " ".join([retrieval_question, *memory_queries[:4]])
                traces.append(
                    AgentTrace(
                        agent="memory_router",
                        action="expanded_from_wiki_memory",
                        confidence=0.74,
                        notes=(
                            "Used uploaded wiki titles, summaries, tags, and aliases "
                            "for ambiguous personal/document context."
                        ),
                    )
                )

        decision = self.indexer.route(
            retrieval_question,
            allow_fallback=request.allow_fallback,
            candidate_queries=candidate_queries,
        )

        if (memory_hint or rewrite_hint or request.intent == "wiki") and decision.route == "direct":
            candidates = self.indexer.find_candidates(
                retrieval_question,
                limit=4,
                candidate_queries=candidate_queries,
            )
            if candidates:
                decision = self._wiki_decision_from_candidates(
                    retrieval_question,
                    candidates,
                    "Harness found likely uploaded wiki memory for an ambiguous question.",
                )

        if request.intent == "wiki" and decision.route == "direct":
            candidates = self.indexer.find_candidates(
                retrieval_question,
                limit=4,
                candidate_queries=candidate_queries,
            )
            decision = self._wiki_decision_from_candidates(
                retrieval_question,
                candidates,
                "Wiki mode was requested.",
            )

        traces.append(self._trace_decision(decision))
        context_budget = self._context_char_budget_for_route(request, decision)
        if decision.route == "wiki" or request.intent == "wiki":
            if memory_hint or request.intent == "wiki":
                context, used_pages = self.indexer.build_exact_page_context(
                    decision.page_slugs,
                    char_budget=context_budget,
                )
            else:
                context, used_pages = self.indexer.build_context(
                    decision.page_slugs,
                    retrieval_question,
                    char_budget=context_budget,
                )
        elif decision.route == "fallback":
            context, used_pages = self.indexer.build_context(
                decision.page_slugs,
                retrieval_question,
                char_budget=context_budget,
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

    async def _rewrite_for_retrieval(self, question: str, history: str) -> tuple[str, bool]:
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

    def _memory_queries(self) -> list[str]:
        queries: list[str] = []
        for item in self.store.list_pages()[:8]:
            parts = [
                item.title,
                item.summary,
                " ".join(item.tags),
                " ".join(item.source_ids),
            ]
            query = " ".join(part for part in parts if part).strip()
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
                "who iam",
                "my profile",
                "my background",
                "my resume",
                "my experience",
                "my skills",
            )
        ):
            return True
        terms = set(tokenize(question))
        first_person_terms = {"i", "iam", "me", "my", "myself", "mine"}
        memory_terms = {
            "about",
            "background",
            "bio",
            "details",
            "experience",
            "identity",
            "know",
            "profile",
            "resume",
            "skills",
            "tell",
            "who",
        }
        return bool((terms & first_person_terms) and (terms & memory_terms))

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
                reason="No usable wiki page was found for requested wiki context.",
                difficulty="easy",
            )
        return RouteDecision(
            route="wiki",
            page_slugs=[candidate.slug for candidate in candidates[:4]],
            confidence=max(0.35, candidates[0].score),
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