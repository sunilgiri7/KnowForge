"""
graph.py — LangGraph chat flow with BM25-retrieval-aware routing.

Changes over v1:
  - rerank_node: LLM re-ranks BM25 candidates when route is "wiki" and
    difficulty is "medium" or "hard". Skipped for direct/easy paths to avoid
    unnecessary LLM latency on simple questions.
  - plan → rerank → answer → verify → finalize
  - rerank_node enriches plan.decision.page_slugs in-place; downstream nodes
    (answer, verify) see the re-ranked ordering without any other changes.
  - All nodes still degrade gracefully if the LLM is unavailable.
"""
from __future__ import annotations

from typing import Any, Protocol, TypedDict

from langgraph.graph import END, StateGraph

from app.schemas.llmwiki import ChatRequest
from app.services.web_search import normalize_web_search_mode, should_bypass_wiki_for_web


class ChatFlowService(Protocol):
    harness: Any

    async def _generate_direct_answer(
        self, question: str, history: str
    ) -> tuple[str, bool, str | None]: ...

    async def _generate_answer(
        self,
        question: str,
        history: str,
        context: str,
        *,
        route_confidence: float,
    ) -> tuple[str, bool]: ...

    async def _verify(
        self, question: str, context: str, answer: str
    ) -> tuple[bool, str, float]: ...

    async def _rerank_candidates(
        self,
        question: str,
        plan: Any,
    ) -> Any: ...

    async def _search_web_if_needed(
        self,
        request: ChatRequest,
        *,
        has_local_context: bool,
    ) -> Any: ...

    def _clean_answer_text(self, answer: str) -> str: ...
    def _raw_fallback_context(self, question: str) -> tuple[str, list[str]]: ...
    def _record_gap(self, question: str, decision: Any, fallback_ids: list[str]) -> bool: ...
    def _citations(
        self, answer: str, used_pages: list[str], fallback_ids: list[str]
    ) -> list[Any]: ...


class ChatFlowState(TypedDict, total=False):
    request: ChatRequest
    history: str
    plan: Any
    context: str
    used_pages: list[str]
    fallback_ids: list[str]
    answer: str
    used_local_fallback: bool
    verified: bool
    verifier_note: str
    verifier_confidence: float
    knowledge_gap_created: bool
    reranked: bool
    web_search_bundle: Any
    web_context: str


def build_chat_flow_graph(service: ChatFlowService) -> StateGraph:
    """
    Build the chat flow graph.

    Flow
    ----
    plan ──► web_search ──► rerank ──► answer ──► verify ──► finalize ──► END
                       │                                  ↑
                       └─ (direct/easy: skip rerank) ─────┘

    Nodes
    -----
    plan      — harness.plan() : routing + multi-query expansion + context assembly
    web_search — optional Tavily-backed current/public web context
    rerank    — optional LLM re-ranking of BM25 candidates (wiki/medium+hard only)
    answer    — generate the final answer from context (or direct LLM)
    verify    — LLM grounding check of draft answer against context
    finalize  — record knowledge gaps, build final knowledge_gap_created flag
    """
    graph = StateGraph(ChatFlowState)

    # ── plan node ─────────────────────────────────────────────────────────────
    async def plan_node(state: ChatFlowState) -> ChatFlowState:
        request = state["request"]
        history = state["history"]
        plan = await service.harness.plan(request, history)
        context = plan.context
        fallback_ids: list[str] = []

        # Append raw-source fallback context for fallback routes
        if (
            plan.decision.route == "fallback"
            and plan.decision.page_slugs
            and request.allow_fallback
        ):
            fallback_context, fallback_ids = service._raw_fallback_context(request.question)
            if fallback_context:
                context = (context + "\n\n---\n\n" if context else "") + fallback_context

        return {
            **state,
            "plan": plan,
            "context": context,
            "used_pages": plan.used_pages,
            "fallback_ids": fallback_ids,
            "reranked": False,
            "web_search_bundle": None,
            "web_context": "",
        }

    # ── web search node ──────────────────────────────────────────────────────
    async def web_search_node(state: ChatFlowState) -> ChatFlowState:
        request = state["request"]
        plan = state["plan"]
        context = state.get("context", "")
        has_local_context = bool((context or "").strip() or plan.used_pages)

        bundle = await service._search_web_if_needed(
            request,
            has_local_context=has_local_context,
        )

        mode = normalize_web_search_mode(request.web_search_mode)
        bypass_wiki, bypass_reason = should_bypass_wiki_for_web(
            request.question,
            mode=mode,
        )

        if not bundle or not getattr(bundle, "available", False):
            if bypass_wiki:
                return {
                    **state,
                    "context": "",
                    "web_search_bundle": bundle,
                    "web_context": "",
                    "used_pages": [],
                    "web_bypassed_wiki": True,
                    "web_bypass_reason": bypass_reason,
                }
            return {
                **state,
                "web_search_bundle": bundle,
                "web_context": "",
            }

        web_context = bundle.context_block()

        if bypass_wiki:
            return {
                **state,
                "context": web_context,
                "web_context": web_context,
                "web_search_bundle": bundle,
                "used_pages": [],
                "web_bypassed_wiki": True,
                "web_bypass_reason": bypass_reason,
            }

        combined = (context + "\n\n---\n\n" if context else "") + web_context

        return {
            **state,
            "context": combined,
            "web_context": web_context,
            "web_search_bundle": bundle,
        }

    # ── rerank node ───────────────────────────────────────────────────────────
    async def rerank_node(state: ChatFlowState) -> ChatFlowState:
        """
        LLM re-ranking of BM25 candidates.

        BM25 maximises recall; re-ranking maximises precision by asking the LLM
        "given these candidate page summaries, which would best answer this
        question?".  The re-ranked order propagates into context assembly so the
        most relevant page is included first (and most completely within budget).

        Only runs for wiki-routed medium/hard questions where the extra LLM call
        is justified.  Skipped for:
          - direct route (no wiki candidates to re-rank)
          - easy questions (BM25 order is sufficient)
          - LLM unavailable (fails gracefully, original order preserved)
        """
        plan = state["plan"]
        request = state["request"]
        decision = plan.decision

        # Guard: only rerank wiki routes with ≥2 candidates and non-easy difficulty
        should_rerank = (
            decision.route == "wiki"
            and len(decision.page_slugs) >= 2
            and decision.difficulty in {"medium", "hard"}
        )
        if not should_rerank:
            return {**state, "reranked": False}

        try:
            updated_plan = await service._rerank_candidates(request.question, plan)
            web_context = state.get("web_context", "")
            combined_context = updated_plan.context
            if web_context:
                combined_context = (combined_context + "\n\n---\n\n" if combined_context else "") + web_context
            return {
                **state,
                "plan": updated_plan,
                "context": combined_context,
                "used_pages": updated_plan.used_pages,
                "reranked": True,
            }
        except Exception:
            # Never block the pipeline on re-ranking failure
            return {**state, "reranked": False}

    # ── answer generation node ───────────────────────────────────────────────
    async def answer_node(state: ChatFlowState) -> ChatFlowState:
        request = state["request"]
        history = state.get("history", "")
        plan = state["plan"]
        context = state.get("context", "")

        web_bundle = state.get("web_search_bundle")
        web_bypassed_wiki = bool(state.get("web_bypassed_wiki"))

        if web_bypassed_wiki and not (web_bundle and getattr(web_bundle, "available", False)):
            return {
                **state,
                "answer": "I could not verify this from the available web sources.",
                "used_local_fallback": False,
                "verified": False,
                "verifier_confidence": 0.1,
                "verifier_note": getattr(web_bundle, "reason", "Web search did not return usable evidence."),
            }

        if web_bypassed_wiki and web_bundle and getattr(web_bundle, "available", False):
            answer, used_local_fallback = await service._generate_web_grounded_answer(
                request.question,
                history,
                web_bundle,
            )

            return {
                **state,
                "answer": answer,
                "used_local_fallback": used_local_fallback,
                "verified": bool(re.search(r"\[web:[^\]]+\]", answer)),
                "verifier_confidence": 0.9 if re.search(r"\[web:[^\]]+\]", answer) else 0.1,
                "verifier_note": "Generated through strict web-only grounded answer path.",
            }

        if plan.decision.route == "direct" and not (context or "").strip():
            answer, _, _ = await service._generate_direct_answer(request.question, history)
            return {
                **state,
                "answer": service._clean_answer_text(answer),
                "used_local_fallback": False,
            }

        answer, used_local_fallback = await service._generate_answer(
            request.question,
            history,
            context,
            route_confidence=plan.decision.confidence,
        )

        return {
            **state,
            "answer": answer,
            "used_local_fallback": used_local_fallback,
        }

    # ── verify node ──────────────────────────────────────────────────────────
    async def verify_node(state: ChatFlowState) -> ChatFlowState:
        if state.get("web_bypassed_wiki") and "verified" in state:
            return state

        request = state["request"]
        context = state.get("context", "")
        answer = state.get("answer", "")

        verified, note, confidence = await service._verify(
            request.question,
            context,
            answer,
        )

        has_web_context = "## Web Search Context" in (context or "")

        # Critical production safety:
        # For web-grounded answers, do not allow unsupported answers to leave the system.
        if has_web_context and not verified:
            safe_answer = "I could not verify this from the available web sources."
            return {
                **state,
                "answer": safe_answer,
                "verified": False,
                "verifier_confidence": confidence,
                "verifier_note": note,
            }

        return {
            **state,
            "verified": verified,
            "verifier_confidence": confidence,
            "verifier_note": note,
        }

    # ── finalize node ─────────────────────────────────────────────────────────
    async def finalize_node(state: ChatFlowState) -> ChatFlowState:
        request = state["request"]
        plan = state["plan"]
        fallback_ids = state.get("fallback_ids", [])
        gap_created = False
        # Record knowledge gaps for unverified answers and fallback routes
        if not state.get("verified", False) or plan.decision.route == "fallback":
            gap_created = service._record_gap(
                request.question, plan.decision, fallback_ids
            )
        return {**state, "knowledge_gap_created": gap_created}

    # ── routing function ──────────────────────────────────────────────────────
    def route_after_plan(state: ChatFlowState) -> str:
        """
        Decide whether to run re-ranking after planning.

        Re-ranking adds one LLM call (~1-2s latency).  It is only worth it for
        wiki routes with multiple candidates on medium/hard questions.
        """
        plan = state.get("plan")
        if plan is None:
            return "answer"
        decision = plan.decision
        if (
            decision.route == "wiki"
            and len(decision.page_slugs) >= 2
            and decision.difficulty in {"medium", "hard"}
        ):
            return "rerank"
        return "answer"

    # ── wire graph ────────────────────────────────────────────────────────────
    graph.add_node("plan", plan_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("rerank", rerank_node)
    graph.add_node("answer", answer_node)
    graph.add_node("verify", verify_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("plan")
    graph.add_conditional_edges(
        "web_search",
        route_after_plan,
        {"rerank": "rerank", "answer": "answer"},
    )
    graph.add_edge("plan", "web_search")
    graph.add_edge("rerank", "answer")
    graph.add_edge("answer", "verify")
    graph.add_edge("verify", "finalize")
    graph.add_edge("finalize", END)
    return graph
