from __future__ import annotations

import re

from app.core.config import settings
from app.llmwiki.compaction import ConversationCompactor
from app.llmwiki.groq import GroqClient
from app.llmwiki.harness import AIHarness
from app.llmwiki.indexer import WikiIndexer
from app.llmwiki.prompts import (
    ANSWER_PROMPT,
    DIRECT_CHAT_PROMPT,
    PLANNER_PROMPT,
    VERIFIER_PROMPT,
)
from app.llmwiki.storage import WikiStore
from app.llmwiki.text import keyword_summary, safe_format, tokenize, trim_context_to_token_budget, trim_to_chars
from app.llm.graph import build_chat_flow_graph
from app.schemas.llmwiki import (
    AgentTrace,
    ChatRequest,
    ChatResponse,
    Citation,
    KnowledgeGapEvent,
    RouteDecision,
)


class ChatService:
    def __init__(self, store: WikiStore, llm: object | None = None):
        self.store = store
        self.llm = llm or GroqClient()
        self.indexer = WikiIndexer(store)
        self.harness = AIHarness(store, self.indexer, self.llm)
        self.history_compactor = ConversationCompactor(self.llm)

    FALLBACK_MATCH_MIN_OVERLAP = 4
    FALLBACK_MATCH_MIN_RATIO = 0.14
    DIRECT_COMPLETION_CAP = 700

    async def answer(self, request: ChatRequest) -> ChatResponse:
        history = await self.history_compactor.compact(
            [message.model_dump() for message in request.messages],
            char_budget=settings.chat_history_char_budget,
            keep_last=settings.chat_history_keep_last,
        )
        # Handle brief social replies locally (e.g., "thanks", "thank you")
        if self._is_gratitude(request.question):
            trace = [
                AgentTrace(
                    agent="smalltalk",
                    action="gratitude_reply",
                    confidence=1.0,
                    notes="Handled locally",
                )
            ]
            return ChatResponse(
                session_id=request.session_id,
                answer="You're welcome! Happy to help — let me know if you need anything else.",
                route="direct",
                difficulty="easy",
                citations=[],
                used_pages=[],
                knowledge_gap_created=False,
                agent_trace=trace,
            )
        flow = build_chat_flow_graph(self).compile()
        state = await flow.ainvoke({"request": request, "history": history})
        plan = state["plan"]
        decision = plan.decision
        trace = plan.traces
        context = state.get("context", "")
        used_pages = state.get("used_pages", []) or plan.used_pages
        fallback_ids = state.get("fallback_ids", [])

        if decision.difficulty == "hard" and context.strip():
            plan_notes = await self._plan_hard_question(plan.retrieval_question, context)
            trace.append(
                AgentTrace(
                    agent="planner",
                    action="decomposed_question",
                    confidence=0.72,
                    notes=plan_notes,
                )
            )
        if decision.route == "fallback" and fallback_ids:
            trace.append(
                AgentTrace(
                    agent="fallback_retriever",
                    action="loaded_raw_sources",
                    confidence=0.55,
                    notes=", ".join(fallback_ids[:5]),
                )
            )

        answer = self._clean_answer_text(state.get("answer", ""))
        used_local_fallback = bool(state.get("used_local_fallback"))
        if decision.route == "direct":
            # direct path trace
            trace.append(
                AgentTrace(
                    agent="direct_assistant",
                    action="answered_without_wiki_context" if self.llm.available else "llm_unavailable",
                    confidence=0.9 if self.llm.available else 0.0,
                    notes="Answered directly.",
                )
            )
        elif used_local_fallback:
            trace.append(
                AgentTrace(
                    agent="local_fallback",
                    action="served_high_confidence_wiki_excerpt",
                    confidence=max(0.0, min(1.0, decision.confidence)),
                    notes="LLM unavailable; served deterministic wiki excerpts.",
                )
            )
        trace.append(
            AgentTrace(
                agent="verifier",
                action="supported" if state.get("verified", False) else "needs_more_evidence",
                confidence=float(state.get("verifier_confidence", 0.5)),
                notes=str(state.get("verifier_note", "")),
            )
        )

        citations = self._citations(answer, used_pages, fallback_ids)
        return ChatResponse(
            session_id=request.session_id,
            answer=answer,
            route=decision.route,
            difficulty=decision.difficulty,
            citations=citations,
            used_pages=used_pages,
            knowledge_gap_created=bool(state.get("knowledge_gap_created", False)),
            agent_trace=trace,
        )

    async def _generate_answer(
        self,
        question: str,
        history: str,
        context: str,
        *,
        route_confidence: float,
    ) -> tuple[str, bool]:
        # Cap context to ~8000 tokens to stay within Groq's rate limits.
        # Total request: 8000 (context) + 2048 (output) + ~600 (prompt+history) ≈ 10,648 tokens.
        # This is safe for Groq paid tier; free-tier users will be rate limited per-minute.
        safe_context = trim_context_to_token_budget(
            context,
            token_budget=settings.chat_prompt_token_budget,
            reserve_for_prompt=700,
            reserve_for_output=min(settings.chat_max_completion_tokens, settings.groq_max_completion_tokens),
        )
        prompt = safe_format(
            ANSWER_PROMPT,
            question=question,
            history=history or "None",
            context=safe_context,
        )
        if self.llm.available:
            try:
                return (
                    await self.llm.generate_text(
                        prompt,
                        temperature=0.2,
                        max_completion_tokens=min(settings.chat_max_completion_tokens, settings.groq_max_completion_tokens),
                    ),
                    False,
                )
            except Exception:
                pass
        return self._local_answer(question, context, route_confidence=route_confidence), True

    @staticmethod
    def _is_gratitude(question: str) -> bool:
        if not question:
            return False
        q = " ".join(question.lower().split())
        # common short gratitude phrases
        patterns = (
            "thank",
            "thanks",
            "thank you",
            "thx",
            "ty",
            "appreciate",
            "good"
        )
        # Only treat as gratitude when the message is short (avoids false positives)
        return any(p in q for p in patterns) and len(q.split()) <= 6

    async def _generate_direct_answer(
        self,
        question: str,
        history: str,
    ) -> tuple[str, bool, str | None]:
        prompt = safe_format(DIRECT_CHAT_PROMPT, question=question, history=history or "None")
        if not self.llm.available:
            return (
                "I could not reach the language model right now. "
                "Please configure Groq and try again.",
                False,
                "Groq API key is missing.",
            )
        try:
            text = await self.llm.generate_text(
                prompt,
                temperature=0.35,
                max_completion_tokens=min(self.DIRECT_COMPLETION_CAP, settings.groq_max_completion_tokens),
            )
            return self._clean_answer_text(text), True, None
        except Exception as exc:
            return (
                "We currently have insufficient tokens. Please try again shortly.",
                False,
                f"Groq request failed: {exc.__class__.__name__}",
            )

    async def _plan_hard_question(self, question: str, context: str) -> str:
        if self.llm.available:
            try:
                payload = await self.llm.generate_json(
                    safe_format(
                        PLANNER_PROMPT,
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
                    safe_format(
                        VERIFIER_PROMPT,
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
        """Return a compact, token-budget-safe excerpt from raw sources.

        Deliberately kept small — the wiki page should be the primary source.
        This is only used for the fallback route when no wiki page exists yet.
        """
        query_terms = set(tokenize(question))
        scored: list[tuple[int, str, str]] = []
        for source_id, text in self.store.iter_sources():
            score = len(query_terms & set(tokenize(text[:8000])))
            if score:
                scored.append((score, source_id, text))
        blocks = []
        ids = []
        # Conservative budget: at most 4000 chars total for fallback context
        remaining = 4000
        for _, source_id, text in sorted(scored, reverse=True)[:2]:
            summary = trim_to_chars(keyword_summary(text, max_sentences=10), remaining // 2)
            block = f"[source:{source_id}]\n{summary}"
            blocks.append(block)
            ids.append(source_id)
            remaining -= len(block)
            if remaining <= 500:
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
    def _local_answer(question: str, context: str, *, route_confidence: float) -> str:
        """Fallback answer used when the LLM is unavailable or errored.

        Instead of running keyword_summary (which produces fragment garbage like
        'Company:', 'of the Company.'), this extracts whole paragraphs that
        overlap with the question terms and presents them as direct excerpts.
        """
        generic_unavailable = (
            "The AI model is temporarily unavailable. "
            "Please try again in a moment."
        )
        if not context.strip():
            return generic_unavailable
        query_terms = set(tokenize(question))
        # Split into substantial paragraphs
        paragraphs = [
            p.strip()
            for p in re.split(r"\n{2,}", context)
            if len(p.strip()) > 80
            and not p.strip().startswith(("---", "[wiki:", "[source:"))
        ]
        if not paragraphs:
            return generic_unavailable
        # Score each paragraph by keyword overlap with the question
        scored: list[tuple[int, int, str]] = [
            (len(query_terms & set(tokenize(p))), idx, p)
            for idx, p in enumerate(paragraphs)
        ]
        top = sorted(scored, key=lambda x: (-x[0], x[1]))[:3]
        relevant = [p for score, _, p in top if score > 0]
        best_overlap = top[0][0] if top else 0
        normalized = best_overlap / max(1, len(query_terms))
        confidence_gate_passed = (
            best_overlap >= ChatService.FALLBACK_MATCH_MIN_OVERLAP
            and normalized >= ChatService.FALLBACK_MATCH_MIN_RATIO
            and route_confidence >= 0.45
        )
        if relevant and confidence_gate_passed:
            return (
                "**Note: AI model temporarily unavailable. Showing relevant wiki excerpts:**\n\n"
                + "\n\n".join(relevant[:3])
            )
        return generic_unavailable

    @staticmethod
    def _clean_answer_text(answer: str) -> str:
        text = (answer or "").replace("\r\n", "\n").strip()
        if not text:
            return text
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        lines = [line.rstrip() for line in text.split("\n")]
        cleaned_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped in {"| --- |", "|---|", "---"}:
                continue
            cleaned_lines.append(line)
        text = "\n".join(cleaned_lines).strip()
        return text

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