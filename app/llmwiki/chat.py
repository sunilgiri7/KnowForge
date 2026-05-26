from __future__ import annotations

import re

from app.core.config import settings
from app.llmwiki.compaction import ConversationCompactor
from app.llmwiki.groq import GroqClient
from app.llmwiki.indexer import WikiIndexer
from app.llmwiki.prompts import (
    ANSWER_PROMPT,
    DIRECT_CHAT_PROMPT,
    PLANNER_PROMPT,
    QUERY_REWRITE_PROMPT,
    VERIFIER_PROMPT,
)
from app.llmwiki.storage import WikiStore
from app.llmwiki.text import keyword_summary, tokenize, trim_to_chars
from app.schemas.llmwiki import (
    AgentTrace,
    ChatRequest,
    ChatResponse,
    Citation,
    KnowledgeGapEvent,
    RouteDecision,
)


class ChatService:
    def __init__(self, store: WikiStore, llm: GroqClient | None = None):
        self.store = store
        self.llm = llm or GroqClient()
        self.indexer = WikiIndexer(store)
        self.history_compactor = ConversationCompactor(self.llm)

    async def answer(self, request: ChatRequest) -> ChatResponse:
        history = await self.history_compactor.compact(
            [message.model_dump() for message in request.messages],
            char_budget=settings.chat_history_char_budget,
            keep_last=settings.chat_history_keep_last,
        )
        retrieval_question = request.question
        route_hint = False
        candidate_queries = [request.question]
        if self._is_self_profile_question(request.question):
            route_hint = True
            profile_query = self._profile_query(request)
            retrieval_question = profile_query
            candidate_queries.append(profile_query)
        if not request.context_page_slugs and request.intent == "auto":
            rewritten_question, rewrite_hint = await self._rewrite_for_retrieval(
                request.question,
                self._history_with_user_context(history, request.user_context),
            )
            if rewritten_question != request.question:
                candidate_queries.append(rewritten_question)
            if not self._is_self_profile_question(request.question):
                retrieval_question = rewritten_question
            route_hint = route_hint or rewrite_hint
        if request.context_page_slugs:
            decision = RouteDecision(
                route="wiki",
                page_slugs=request.context_page_slugs,
                confidence=1.0,
                reason="User selected explicit wiki page context.",
                difficulty=self.indexer.classify_difficulty(request.question, []),
            )
        elif request.intent == "direct":
            decision = RouteDecision(
                route="direct",
                page_slugs=[],
                confidence=1.0,
                reason="User requested direct assistant mode.",
                difficulty="easy",
            )
        else:
            decision = self.indexer.route(
                retrieval_question,
                allow_fallback=request.allow_fallback,
                candidate_queries=candidate_queries,
            )
            if route_hint and decision.route == "direct":
                candidates = self.indexer.find_candidates(
                    retrieval_question,
                    limit=3,
                    candidate_queries=candidate_queries,
                )
                if candidates:
                    decision = RouteDecision(
                        route="wiki",
                        page_slugs=[candidate.slug for candidate in candidates],
                        confidence=max(0.35, candidates[0].score),
                        reason="Query rewrite indicated likely wiki context.",
                        difficulty=self.indexer.classify_difficulty(retrieval_question, candidates),
                    )
        trace = [
            AgentTrace(
                agent="router",
                action=decision.route,
                confidence=decision.confidence,
                notes=decision.reason,
            )
        ]
        if request.context_page_slugs or request.intent == "wiki":
            context, used_pages = self.indexer.build_exact_page_context(
                decision.page_slugs,
                char_budget=settings.wiki_context_char_budget,
            )
        else:
            context, used_pages = self.indexer.build_context(
                decision.page_slugs,
                retrieval_question,
                char_budget=settings.wiki_context_char_budget,
            )
        fallback_context, fallback_ids = ("", [])
        if decision.route == "fallback" and decision.page_slugs and request.allow_fallback:
            fallback_context, fallback_ids = self._raw_fallback_context(request.question)
            if fallback_context:
                context = (context + "\n\n---\n\n" if context else "") + fallback_context
                trace.append(
                    AgentTrace(
                        agent="fallback_retriever",
                        action="loaded_raw_sources",
                        confidence=0.55,
                        notes=", ".join(fallback_ids[:5]),
                    )
                )

        if decision.route == "direct" or not context.strip():
            answer, llm_answered, llm_error = await self._generate_direct_answer(
                request.question,
                history,
            )
            trace.append(
                AgentTrace(
                    agent="direct_assistant",
                    action="answered_without_wiki_context" if llm_answered else "llm_unavailable",
                    confidence=0.9 if llm_answered else 0.0,
                    notes=llm_error or "No wiki/source context was available; used direct LLM.",
                )
            )
            return ChatResponse(
                session_id=request.session_id,
                answer=answer,
                route="direct",
                difficulty=decision.difficulty,
                citations=[],
                used_pages=[],
                knowledge_gap_created=False,
                agent_trace=trace,
            )

        if decision.difficulty == "hard":
            plan_notes = await self._plan_hard_question(retrieval_question, context)
            trace.append(
                AgentTrace(
                    agent="planner",
                    action="decomposed_question",
                    confidence=0.72,
                    notes=plan_notes,
                )
            )

        answer = await self._generate_answer(request.question, history, context)
        verified, verifier_note, verifier_confidence = await self._verify(
            request.question,
            context,
            answer,
        )
        trace.append(
            AgentTrace(
                agent="verifier",
                action="supported" if verified else "needs_more_evidence",
                confidence=verifier_confidence,
                notes=verifier_note,
            )
        )
        gap_created = False
        if not verified or decision.route == "fallback":
            gap_created = self._record_gap(request.question, decision, fallback_ids)

        citations = self._citations(answer, used_pages, fallback_ids)
        return ChatResponse(
            session_id=request.session_id,
            answer=answer,
            route=decision.route,
            difficulty=decision.difficulty,
            citations=citations,
            used_pages=used_pages,
            knowledge_gap_created=gap_created,
            agent_trace=trace,
        )

    async def _generate_answer(self, question: str, history: str, context: str) -> str:
        prompt = ANSWER_PROMPT.format(question=question, history=history or "None", context=context)
        if self.llm.available:
            try:
                return await self.llm.generate_text(prompt, temperature=0.2)
            except Exception:
                pass
        return self._local_answer(question, context)

    async def _rewrite_for_retrieval(self, question: str, history: str) -> tuple[str, bool]:
        if not self.llm.available or not history.strip():
            return question, False
        try:
            payload = await self.llm.generate_json(
                QUERY_REWRITE_PROMPT.format(question=question, history=history),
                temperature=0.05,
            )
            rewritten = str(payload.get("rewritten_question") or question).strip()
            should_use_wiki = bool(payload.get("should_use_wiki"))
            return rewritten or question, should_use_wiki
        except Exception:
            return question, False

    @staticmethod
    def _is_self_profile_question(question: str) -> bool:
        lowered = question.lower()
        compact = " ".join(lowered.split())
        patterns = (
            "about me",
            "know about me",
            "who am i",
            "my profile",
            "my background",
            "my experience",
            "my skills",
            "my resume",
            "tell me about myself",
        )
        return any(pattern in compact for pattern in patterns)

    @staticmethod
    def _history_with_user_context(history: str, user_context: str | None) -> str:
        if not user_context:
            return history
        return f"{user_context}\n\n{history}" if history else user_context

    @staticmethod
    def _profile_query(request: ChatRequest) -> str:
        parts = [
            request.question,
            "user profile resume background experience skills projects education contact",
        ]
        if request.user_context:
            parts.append(request.user_context)
        return " ".join(parts)

    async def _generate_direct_answer(
        self,
        question: str,
        history: str,
    ) -> tuple[str, bool, str | None]:
        prompt = DIRECT_CHAT_PROMPT.format(question=question, history=history or "None")
        if not self.llm.available:
            return (
                "I could not reach the language model right now. "
                "Please configure Groq and try again.",
                False,
                "Groq API key is missing.",
            )
        try:
            return await self.llm.generate_text(prompt, temperature=0.35), True, None
        except Exception as exc:
            return (
                "I could not reach the language model right now. Please try again in a moment.",
                False,
                f"Groq request failed: {exc.__class__.__name__}",
            )

    async def _plan_hard_question(self, question: str, context: str) -> str:
        if self.llm.available:
            try:
                payload = await self.llm.generate_json(
                    PLANNER_PROMPT.format(
                        question=question,
                        context=trim_to_chars(context, settings.wiki_context_char_budget),
                    )
                )
                return "; ".join(payload.get("subquestions", [])) or str(payload.get("notes", ""))
            except Exception:
                pass
        return "Use routed wiki pages, check citations, then verify support before final answer."

    async def _verify(self, question: str, context: str, answer: str) -> tuple[bool, str, float]:
        if self.llm.available:
            try:
                payload = await self.llm.generate_json(
                    VERIFIER_PROMPT.format(
                        question=question,
                        context=trim_to_chars(context, settings.wiki_context_char_budget),
                        answer=trim_to_chars(answer, 5000),
                    )
                )
                return (
                    bool(payload.get("supported")),
                    "; ".join(payload.get("issues", [])) or str(payload.get("missing_topic", "")),
                    float(payload.get("confidence", 0.5)),
                )
            except Exception:
                pass
        has_citation = bool(re.search(r"\[(wiki|source):[^\]]+\]", answer))
        return has_citation, "Local citation check.", 0.6 if has_citation else 0.3

    def _raw_fallback_context(self, question: str) -> tuple[str, list[str]]:
        query_terms = set(tokenize(question))
        scored: list[tuple[int, str, str]] = []
        for source_id, text in self.store.iter_sources():
            score = len(query_terms & set(tokenize(text[:8000])))
            if score:
                scored.append((score, source_id, text))
        blocks = []
        ids = []
        remaining = max(3000, settings.wiki_context_char_budget // 2)
        for _, source_id, text in sorted(scored, reverse=True)[:3]:
            summary = trim_to_chars(keyword_summary(text, max_sentences=8), remaining // 2)
            block = f"[source:{source_id}]\n{summary}"
            blocks.append(block)
            ids.append(source_id)
            remaining -= len(block)
            if remaining <= 1000:
                break
        return "\n\n---\n\n".join(blocks), ids

    def _record_gap(self, question: str, decision: RouteDecision, fallback_ids: list[str]) -> bool:
        event = KnowledgeGapEvent(
            question=question,
            route=decision.route if decision.route != "clarify" else "clarify",
            missing_topic=decision.reason,
            fallback_source_ids=fallback_ids,
            suggested_page_slug=decision.page_slugs[0] if decision.page_slugs else None,
            priority="high" if decision.difficulty == "hard" else "medium",
        )
        self.store.append_gap_event(event)
        return True

    @staticmethod
    def _local_answer(question: str, context: str) -> str:
        summary = keyword_summary(context, max_sentences=8)
        if not summary:
            return "I could not find enough supported context in the KnowForge wiki to answer that."
        return (
            f"Based on the current KnowForge wiki context, the relevant information is:\n\n"
            f"{summary}\n\n"
            "This answer is generated from available wiki/source excerpts only; "
            "add more source material if you need a more complete answer."
        )

    @staticmethod
    def _citations(answer: str, used_pages: list[str], fallback_ids: list[str]) -> list[Citation]:
        citations: list[Citation] = []
        for slug in sorted(set(re.findall(r"\[wiki:([^\]]+)\]", answer)) | set(used_pages)):
            citations.append(
                Citation(
                    label=f"wiki:{slug}",
                    source_id=slug,
                    wiki_slug=slug,
                    source_type="wiki",
                )
            )
        source_ids = set(re.findall(r"\[source:([^\]]+)\]", answer)) | set(fallback_ids)
        for source_id in sorted(source_ids):
            citations.append(
                Citation(
                    label=f"source:{source_id}",
                    source_id=source_id,
                    source_type="source",
                )
            )
        return citations
