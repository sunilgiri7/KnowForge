"""
chat.py — main chat service orchestrating the retrieval-augmented generation flow.

Changes over v1:
  - _rerank_candidates(): new method — LLM re-ranks BM25 candidates, rebuilds
    context in re-ranked slug order so the most relevant page comes first.
  - _generate_answer(): CoT scaffolding injected for hard questions; context
    trimming is tighter to stay within Groq rate limits.
  - _verify(): uses the improved VERIFIER_PROMPT which distinguishes
    fully/partially/unsupported and returns grounding_level.
  - answer() assembles the full AgentTrace including rerank and verifier.
  - _citations() unchanged — already correct.
  - _clean_answer_text() unchanged.
  - _local_answer() unchanged.
"""
from __future__ import annotations

import re

from app.core.config import settings
from app.llmwiki.compaction import ConversationCompactor
from app.llmwiki.groq import GroqClient
from app.llmwiki.harness import AIHarness, HarnessPlan
from app.llmwiki.indexer import WikiIndexer
from app.llmwiki.prompts import (
    ANSWER_PROMPT,
    DIRECT_CHAT_PROMPT,
    RERANK_PROMPT,
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

        # Handle brief social replies locally
        if self._is_gratitude(request.question):
            trace = [AgentTrace(
                agent="smalltalk",
                action="gratitude_reply",
                confidence=1.0,
                notes="Handled locally",
            )]
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
        used_pages = state.get("used_pages", []) or plan.used_pages
        fallback_ids = state.get("fallback_ids", [])

        if decision.route == "fallback" and fallback_ids:
            trace.append(AgentTrace(
                agent="fallback_retriever",
                action="loaded_raw_sources",
                confidence=0.55,
                notes=", ".join(fallback_ids[:5]),
            ))

        if state.get("reranked", False):
            trace.append(AgentTrace(
                agent="reranker",
                action="reranked_candidates",
                confidence=0.78,
                notes=f"Re-ranked {len(decision.page_slugs)} candidates for {decision.difficulty} question.",
            ))

        answer = self._clean_answer_text(state.get("answer", ""))
        used_local_fallback = bool(state.get("used_local_fallback"))

        if decision.route == "direct":
            trace.append(AgentTrace(
                agent="direct_assistant",
                action="answered_without_wiki_context" if self.llm.available else "llm_unavailable",
                confidence=0.9 if self.llm.available else 0.0,
                notes="Answered directly.",
            ))
        elif used_local_fallback:
            trace.append(AgentTrace(
                agent="local_fallback",
                action="served_high_confidence_wiki_excerpt",
                confidence=max(0.0, min(1.0, decision.confidence)),
                notes="LLM unavailable; served deterministic wiki excerpts.",
            ))

        trace.append(AgentTrace(
            agent="verifier",
            action="supported" if state.get("verified", False) else "needs_more_evidence",
            confidence=float(state.get("verifier_confidence", 0.5)),
            notes=str(state.get("verifier_note", "")),
        ))

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

    # ── Re-ranking ────────────────────────────────────────────────────────────

    async def _rerank_candidates(
        self,
        question: str,
        plan: HarnessPlan,
    ) -> HarnessPlan:
        """
        LLM re-ranking of BM25 candidate pages.

        Sends the question and a summary of each candidate page to the LLM and
        asks it to return slugs in relevance order.  The plan's context is then
        rebuilt using the re-ranked slug order so the highest-relevance page
        occupies the most characters within the char budget.

        Degrades gracefully: if the LLM is unavailable or returns garbage, the
        original plan is returned unchanged.
        """
        if not self.llm.available or not plan.decision.page_slugs:
            return plan

        # Build candidate descriptions for the re-ranking prompt
        candidate_lines: list[str] = []
        for slug in plan.decision.page_slugs:
            try:
                page = self.store.read_page(slug, prefer_compact=True)
                candidate_lines.append(
                    f"slug: {slug}\n"
                    f"title: {page.meta.title}\n"
                    f"summary: {page.meta.summary[:300]}\n"
                    f"tags: {', '.join(page.meta.tags[:6])}"
                )
            except Exception:
                candidate_lines.append(f"slug: {slug}\n(page not found)")

        candidates_text = "\n\n---\n\n".join(candidate_lines)

        try:
            payload = await self.llm.generate_json(
                safe_format(
                    RERANK_PROMPT,
                    question=question,
                    candidates=candidates_text,
                )
            )
            ranked_slugs: list[str] = [
                str(s).strip()
                for s in payload.get("ranked_slugs", [])
                if str(s).strip()
            ]
            # Only accept slugs that were in the original candidate list
            valid_reranked = [s for s in ranked_slugs if s in plan.decision.page_slugs]
            # Append any original slugs not returned by re-ranker (safety net)
            for slug in plan.decision.page_slugs:
                if slug not in valid_reranked:
                    valid_reranked.append(slug)

            if not valid_reranked or valid_reranked == plan.decision.page_slugs:
                return plan  # Re-ranker agreed with BM25 order — no-op

            # Rebuild decision with re-ranked slug order
            from app.schemas.llmwiki import RouteDecision
            new_decision = RouteDecision(
                route=plan.decision.route,
                page_slugs=valid_reranked,
                confidence=plan.decision.confidence,
                reason=plan.decision.reason + " [re-ranked]",
                difficulty=plan.decision.difficulty,
            )

            # Rebuild context with the new slug order
            from app.core.config import settings
            char_budget = min(settings.wiki_context_char_budget, 16_000)
            context, used_pages = self.indexer.build_context(
                valid_reranked,
                question,
                char_budget=char_budget,
            )

            # Return an updated plan (dataclass — rebuild)
            from app.llmwiki.harness import HarnessPlan
            return HarnessPlan(
                question=plan.question,
                retrieval_question=plan.retrieval_question,
                decision=new_decision,
                context=context,
                used_pages=used_pages,
                candidate_queries=plan.candidate_queries,
                traces=plan.traces,
            )
        except Exception:
            return plan

    # ── Answer generation ─────────────────────────────────────────────────────

    async def _generate_answer(
        self,
        question: str,
        history: str,
        context: str,
        *,
        route_confidence: float,
    ) -> tuple[str, bool]:
        """
        Generate the final wiki-grounded answer.

        Token budget
        ------------
        Groq free tier: ~6000 TPM.  We reserve:
          - 700 chars for prompt template overhead
          - min(900, groq_max_completion_tokens) for output
          - The rest for context (capped at chat_prompt_token_budget)

        For hard questions the ANSWER_PROMPT already includes CoT scaffolding
        ("Evidence from wiki → Analysis → Confidence note"), so we don't need
        to modify the prompt here — just pass it through.
        """
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
                        max_completion_tokens=min(
                            settings.chat_max_completion_tokens,
                            settings.groq_max_completion_tokens,
                        ),
                    ),
                    False,
                )
            except Exception:
                pass
        return self._local_answer(question, context, route_confidence=route_confidence), True

    async def _generate_direct_answer(
        self,
        question: str,
        history: str,
    ) -> tuple[str, bool, str | None]:
        prompt = safe_format(DIRECT_CHAT_PROMPT, question=question, history=history or "None")
        if not self.llm.available:
            return (
                "I could not reach the language model right now. "
                "Please configure your LLM provider and try again.",
                False,
                "LLM API key is missing.",
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
                f"LLM request failed: {exc.__class__.__name__}",
            )

    # ── Verification ──────────────────────────────────────────────────────────

    async def _verify(self, question: str, context: str, answer: str) -> tuple[bool, str, float]:
        """
        Grounding verification using improved VERIFIER_PROMPT.

        The updated prompt returns grounding_level in addition to supported/confidence,
        allowing partial-support detection.  We map:
          fully_supported    → supported=True, confidence as-is
          partially_supported → supported=True (acceptable), confidence × 0.8
          unsupported         → supported=False
        """
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
                supported = bool(payload.get("supported"))
                issues = "; ".join(payload.get("issues", [])) or str(payload.get("missing_topic", ""))
                raw_conf = float(payload.get("confidence", 0.5))
                grounding = payload.get("grounding_level", "")
                # Penalise partial support in confidence score
                confidence = raw_conf * 0.8 if grounding == "partially_supported" else raw_conf
                return supported, issues, confidence
            except Exception:
                pass
        # Heuristic fallback: check for inline citations
        has_citation = bool(re.search(r"\[(wiki|source):[^\]]+\]", answer))
        return has_citation, "Local citation check.", 0.6 if has_citation else 0.3

    # ── Fallback helpers ──────────────────────────────────────────────────────

    def _raw_fallback_context(self, question: str) -> tuple[str, list[str]]:
        """Compact excerpt from raw sources for fallback route."""
        query_terms = set(tokenize(question))
        scored: list[tuple[int, str, str]] = []
        for source_id, text in self.store.iter_sources():
            score = len(query_terms & set(tokenize(text[:8000])))
            if score:
                scored.append((score, source_id, text))
        blocks: list[str] = []
        ids: list[str] = []
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

    # ── Static utilities ──────────────────────────────────────────────────────

    @staticmethod
    def _is_gratitude(question: str) -> bool:
        if not question:
            return False
        q = " ".join(question.lower().split())
        patterns = ("thank", "thanks", "thank you", "thx", "ty", "appreciate", "good")
        return any(p in q for p in patterns) and len(q.split()) <= 6

    @staticmethod
    def _local_answer(question: str, context: str, *, route_confidence: float) -> str:
        """Paragraph-based fallback when the LLM is unavailable."""
        generic_unavailable = (
            "The AI model is temporarily unavailable. "
            "Please try again in a moment."
        )
        if not context.strip():
            return generic_unavailable
        query_terms = set(tokenize(question))
        paragraphs = [
            p.strip()
            for p in re.split(r"\n{2,}", context)
            if len(p.strip()) > 80
            and not p.strip().startswith(("---", "[wiki:", "[source:"))
        ]
        if not paragraphs:
            return generic_unavailable
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
        return "\n".join(cleaned_lines).strip()

    @staticmethod
    def _citations(
        answer: str, used_pages: list[str], fallback_ids: list[str]
    ) -> list[Citation]:
        citations: list[Citation] = []
        for slug in sorted(
            set(re.findall(r"\[wiki:([^\]]+)\]", answer)) | set(used_pages)
        ):
            citations.append(Citation(
                label=f"wiki:{slug}",
                source_id=slug,
                wiki_slug=slug,
                source_type="wiki",
            ))
        source_ids = set(re.findall(r"\[source:([^\]]+)\]", answer)) | set(fallback_ids)
        for source_id in sorted(source_ids):
            citations.append(Citation(
                label=f"source:{source_id}",
                source_id=source_id,
                source_type="source",
            ))
        return citations