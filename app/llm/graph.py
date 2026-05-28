from __future__ import annotations

from typing import Any, Protocol, TypedDict

from langgraph.graph import END, StateGraph

from app.schemas.llmwiki import ChatRequest


class ChatFlowService(Protocol):
    harness: Any

    async def _generate_direct_answer(self, question: str, history: str) -> tuple[str, bool, str | None]: ...
    async def _generate_answer(
        self,
        question: str,
        history: str,
        context: str,
        *,
        route_confidence: float,
    ) -> tuple[str, bool]: ...
    async def _verify(self, question: str, context: str, answer: str) -> tuple[bool, str, float]: ...

    def _clean_answer_text(self, answer: str) -> str: ...
    def _raw_fallback_context(self, question: str) -> tuple[str, list[str]]: ...
    def _record_gap(self, question: str, decision: Any, fallback_ids: list[str]) -> bool: ...
    def _citations(self, answer: str, used_pages: list[str], fallback_ids: list[str]) -> list[Any]: ...


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


def build_chat_flow_graph(service: ChatFlowService) -> StateGraph:
    graph = StateGraph(ChatFlowState)

    async def plan_node(state: ChatFlowState) -> ChatFlowState:
        request = state["request"]
        history = state["history"]
        plan = await service.harness.plan(request, history)
        context = plan.context
        fallback_ids: list[str] = []
        if plan.decision.route == "fallback" and plan.decision.page_slugs and request.allow_fallback:
            fallback_context, fallback_ids = service._raw_fallback_context(request.question)
            if fallback_context:
                context = (context + "\n\n---\n\n" if context else "") + fallback_context
        return {
            **state,
            "plan": plan,
            "context": context,
            "used_pages": plan.used_pages,
            "fallback_ids": fallback_ids,
        }

    async def answer_node(state: ChatFlowState) -> ChatFlowState:
        request = state["request"]
        history = state["history"]
        plan = state["plan"]
        context = state.get("context", "")
        if plan.decision.route == "direct" or not (context or "").strip():
            answer, _, _ = await service._generate_direct_answer(request.question, history)
            return {**state, "answer": service._clean_answer_text(answer), "used_local_fallback": False}
        answer, used_local_fallback = await service._generate_answer(
            request.question,
            history,
            context,
            route_confidence=plan.decision.confidence,
        )
        return {
            **state,
            "answer": service._clean_answer_text(answer),
            "used_local_fallback": used_local_fallback,
        }

    async def verify_node(state: ChatFlowState) -> ChatFlowState:
        request = state["request"]
        context = state.get("context", "")
        answer = state.get("answer", "")
        verified, note, conf = await service._verify(request.question, context, answer)
        return {
            **state,
            "verified": verified,
            "verifier_note": note,
            "verifier_confidence": conf,
        }

    async def finalize_node(state: ChatFlowState) -> ChatFlowState:
        request = state["request"]
        plan = state["plan"]
        fallback_ids = state.get("fallback_ids", [])
        gap_created = False
        if not state.get("verified", False) or plan.decision.route == "fallback":
            gap_created = service._record_gap(request.question, plan.decision, fallback_ids)
        return {**state, "knowledge_gap_created": gap_created}

    def route_from_plan(state: ChatFlowState) -> str:
        # We always proceed to answer; route logic is inside answer_node.
        return "answer"

    graph.add_node("plan", plan_node)
    graph.add_node("answer", answer_node)
    graph.add_node("verify", verify_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("plan")
    graph.add_conditional_edges("plan", route_from_plan, {"answer": "answer"})
    graph.add_edge("answer", "verify")
    graph.add_edge("verify", "finalize")
    graph.add_edge("finalize", END)
    return graph

