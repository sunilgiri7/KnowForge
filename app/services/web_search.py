from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


from app.core.config import settings
from app.llmwiki.text import tokenize, trim_to_chars


class WebSearchMode(StrEnum):
    AUTO = "auto"
    FORCE = "force"
    DISABLED = "disabled"


@dataclass(frozen=True)
class WebSearchResult:
    id: str
    title: str
    url: str
    content: str
    score: float = 0.0
    published_date: str | None = None

    @property
    def domain(self) -> str:
        return normalize_domain(self.url)


@dataclass(frozen=True)
class WebSearchBundle:
    query: str
    results: list[WebSearchResult]
    provider: str
    reason: str

    @property
    def available(self) -> bool:
        return bool(self.results)

    def context_block(self) -> str:
        if not self.results:
            return ""

        blocks: list[str] = []
        remaining = max(1600, int(getattr(settings, "web_search_context_chars", 7000)))
        per_source_budget = max(900, min(2400, remaining // max(1, len(self.results))))

        for result in self.results:
            if remaining <= 500:
                break

            date = f"; published: {result.published_date}" if result.published_date else ""
            excerpt = trim_to_chars(result.content, min(per_source_budget, max(500, remaining - 250)))

            block = (
                f"[web:{result.id}] {result.title}\n"
                f"URL: {result.url}\n"
                f"Source: {result.domain}{date}\n"
                f"EvidenceScore: {result.score:.4f}\n"
                f"Excerpt: {excerpt}"
            )
            blocks.append(block)
            remaining -= len(block)

        return (
            "## Web Search Context\n\n"
            "These are external web evidence sources. Use them only when they directly answer the user's question. "
            "Every public/current factual claim must cite [web:n]. "
            "Do not infer missing facts from weak evidence. "
            "If the provided web evidence does not directly answer part of the question, say that part could not be verified.\n\n"
            + "\n\n---\n\n".join(blocks)
        )


class WebSearchProvider:
    provider_name = "web"

    @property
    def available(self) -> bool:
        return False

    async def search(self, query: str) -> WebSearchBundle:
        return WebSearchBundle(query=query, results=[], provider=self.provider_name, reason="unavailable")


@dataclass(frozen=True)
class SearchPlan:
    original_query: str
    search_queries: list[str]
    required_concepts: list[str]
    topic: str = "general"
    time_range: str | None = None
    include_domains: list[str] | None = None
    exclude_domains: list[str] | None = None
    search_depth: str = "advanced"


@dataclass(frozen=True)
class Candidate:
    title: str
    url: str
    snippet: str
    score: float = 0.0
    published_date: str | None = None
    query: str = ""

    @property
    def domain(self) -> str:
        return normalize_domain(self.url)


@dataclass(frozen=True)
class EvidenceCandidate:
    title: str
    url: str
    content: str
    tavily_score: float
    evidence_score: float
    published_date: str | None
    direct_answer: bool
    reason: str

    @property
    def domain(self) -> str:
        return normalize_domain(self.url)


class TavilyWebSearchProvider(WebSearchProvider):
    provider_name = "tavily"

    def __init__(self, llm: object | None = None):
        self.llm = llm

    @property
    def available(self) -> bool:
        return bool(getattr(settings, "tavily_api_key", None))

    async def search(self, query: str) -> WebSearchBundle:
        question = clean_text(query)

        if not question:
            return WebSearchBundle(
                query="",
                results=[],
                provider=self.provider_name,
                reason="Empty query.",
            )

        if not self.available:
            return WebSearchBundle(
                query=question,
                results=[],
                provider=self.provider_name,
                reason="Tavily API key is not configured.",
            )

        try:
            plan = await self._build_plan(question)
            candidates = await self._search_many(plan)
            candidates = dedupe_candidates(candidates)
            candidates = filter_search_candidates(candidates)

            if not candidates:
                return WebSearchBundle(
                    query=" | ".join(plan.search_queries),
                    results=[],
                    provider=self.provider_name,
                    reason="Search returned no usable candidates after quality filtering.",
                )

            candidates = rank_candidates(question, plan.required_concepts, candidates)

            extracted = await self._extract_top(question, candidates)
            evidence = await self._judge_evidence(question, plan.required_concepts, candidates, extracted)
            direct_evidence = [item for item in evidence if item.direct_answer]
            fallback_evidence = [
                item for item in evidence
                if item.evidence_score >= 0.42 and generic_relevance_score(
                    question,
                    plan.required_concepts,
                    item.title,
                    item.url,
                    item.content,
                    item.tavily_score,
                ) >= 0.42
            ]
            accepted = direct_evidence or fallback_evidence
            accepted = sorted(accepted, key=lambda item: item.evidence_score, reverse=True)

            max_results = max(1, int(getattr(settings, "web_search_max_results", 5)))
            final = [
                WebSearchResult(
                    id=str(idx),
                    title=item.title,
                    url=item.url,
                    content=trim_to_chars(item.content, max(2200, int(getattr(settings, "web_search_context_chars", 7000)) // 2)),
                    score=item.evidence_score,
                    published_date=item.published_date,
                )
                for idx, item in enumerate(accepted[:max_results], start=1)
            ]

            if not final:
                ranked = rank_candidates(question, plan.required_concepts, candidates)
                final = [
                    WebSearchResult(
                        id=str(idx),
                        title=item.title,
                        url=item.url,
                        content=trim_to_chars(extracted.get(item.url) or item.snippet, 2200),
                        score=generic_relevance_score(question, plan.required_concepts, item.title, item.url, extracted.get(item.url) or item.snippet, item.score),
                        published_date=item.published_date,
                    )
                    for idx, item in enumerate(ranked[:max_results], start=1)
                ]

            if not final:
                return WebSearchBundle(
                    query=" | ".join(plan.search_queries),
                    results=[],
                    provider=self.provider_name,
                    reason="Search returned no usable web evidence after ranking and extraction.",
                )

            return WebSearchBundle(
                query=" | ".join(plan.search_queries),
                results=final,
                provider=self.provider_name,
                reason=(
                    f"Evidence search completed. queries={len(plan.search_queries)}, "
                    f"candidates={len(candidates)}, accepted_sources={len(final)}, "
                    f"topic={plan.topic}, time_range={plan.time_range or 'none'}."
                ),
            )

        except Exception as exc:
            return WebSearchBundle(
                query=question,
                results=[],
                provider=self.provider_name,
                reason=f"Tavily evidence search failed: {exc}",
            )

    async def _build_plan(self, question: str) -> SearchPlan:
        llm_plan = await self._llm_search_plan(question)
        if llm_plan:
            return llm_plan
        return fallback_search_plan(question)

    async def _llm_search_plan(self, question: str) -> SearchPlan | None:
        if not self.llm or not getattr(self.llm, "available", False):
            return None

        prompt = f"""
You are a web search planner for a production chatbot.

Create a general web retrieval plan. Do not answer the question.

Return strict JSON:
{{
  "search_queries": ["short web query 1", "short web query 2", "short web query 3"],
  "required_concepts": ["concept/entity that must appear in relevant evidence"],
  "topic": "general|news|finance",
  "time_range": "day|week|month|year|null",
  "include_domains": [],
  "exclude_domains": []
}}

Rules:
- Queries must be concise, under 400 characters.
- Do not create one-off special-case logic.
- Include all entities, dates, constraints, and requested facts.
- If the user asks multiple things in one message, create separate queries for each part.
  Example: "who is the current PM of Nepal, tell me about him" needs both identity/current-office queries and biography/profile/background queries.
- If the user asks "tell me about him/her/them", include profile, biography, background, career, and official profile queries for the identified role/entity.
- If the user asks latest/current/live/recent/today, choose an appropriate time_range.
- If the user names a specific year, fiscal year, policy, budget, report, law, or government announcement, usually use time_range=null so authoritative older/official pages are not filtered out.
- Prefer official/primary sources when the question asks for factual status, rules, prices, docs, releases, or statistics.
- required_concepts should include every requested answer dimension, not guessed answers.

User question:
{question}
""".strip()

        try:
            payload = await self.llm.generate_json(prompt)
            queries = payload.get("search_queries") or []
            concepts = payload.get("required_concepts") or []

            queries = [trim_query(str(q)) for q in queries if clean_text(str(q))]
            concepts = [clean_text(str(c)).lower() for c in concepts if clean_text(str(c))]

            if not queries:
                return None

            topic = str(payload.get("topic") or "general").lower().strip()
            if topic not in {"general", "news", "finance"}:
                topic = "general"

            time_range = payload.get("time_range")
            if time_range in {"null", "none", ""}:
                time_range = None
            if time_range not in {None, "day", "week", "month", "year"}:
                time_range = None
            time_range = normalize_time_range_for_query(question, time_range)

            include_domains = normalize_domains(payload.get("include_domains") or [])
            exclude_domains = normalize_domains(payload.get("exclude_domains") or [])

            return SearchPlan(
                original_query=question,
                search_queries=expand_supporting_queries(question, dedupe_preserve_order([question, *queries]))[:10],
                required_concepts=dedupe_preserve_order(concepts)[:12],
                topic=topic,
                time_range=time_range,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
                search_depth=valid_search_depth(),
            )
        except Exception:
            return None

    async def _search_many(self, plan: SearchPlan) -> list[Candidate]:
        tasks = [self._search_once_candidates(q, plan) for q in plan.search_queries]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        candidates: list[Candidate] = []
        errors: list[str] = []

        for response in responses:
            if isinstance(response, Exception):
                errors.append(str(response))
                continue
            candidates.extend(response)

        if not candidates and errors:
            raise RuntimeError("; ".join(errors[:2]))

        return candidates

    async def _search_once_candidates(self, query: str, plan: SearchPlan) -> list[Candidate]:
        max_results = min(20, max(8, int(getattr(settings, "web_search_max_results", 5)) * 4))

        payload: dict[str, object] = {
            "query": trim_query(query),
            "search_depth": plan.search_depth,
            "topic": plan.topic,
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "auto_parameters": True,
        }

        if plan.search_depth in {"advanced", "fast"}:
            payload["chunks_per_source"] = 3

        if plan.time_range:
            payload["time_range"] = plan.time_range

        if plan.include_domains:
            payload["include_domains"] = plan.include_domains

        if plan.exclude_domains:
            payload["exclude_domains"] = plan.exclude_domains

        data = await self._post_json(tavily_search_url(), payload)
        raw_results = data.get("results") if isinstance(data, dict) else []

        candidates: list[Candidate] = []
        for item in raw_results or []:
            if not isinstance(item, dict):
                continue

            title = clean_text(item.get("title"))
            url = clean_text(item.get("url"))
            snippet = clean_text(item.get("content") or item.get("raw_content"))
            score = safe_float(item.get("score"), 0.0)
            published_date = clean_text(item.get("published_date")) or None

            if not title or not url or not snippet:
                continue

            candidates.append(
                Candidate(
                    title=title,
                    url=url,
                    snippet=snippet,
                    score=score,
                    published_date=published_date,
                    query=query,
                )
            )

        return candidates

    async def _extract_top(self, question: str, candidates: list[Candidate]) -> dict[str, str]:
        top_n = min(10, max(5, int(getattr(settings, "web_search_max_results", 5)) * 2))
        urls = [c.url for c in candidates[:top_n]]

        if not urls:
            return {}

        payload: dict[str, object] = {
            "urls": urls,
            "query": trim_query(question),
            "chunks_per_source": 5,
            "extract_depth": "advanced",
            "format": "markdown",
            "include_images": False,
        }

        try:
            data = await self._post_json(tavily_extract_url(), payload)
        except Exception:
            return {}

        extracted: dict[str, str] = {}
        raw_results = data.get("results") if isinstance(data, dict) else []

        for item in raw_results or []:
            if not isinstance(item, dict):
                continue

            url = clean_text(item.get("url"))
            content = clean_text(item.get("raw_content") or item.get("content"))

            if url and content:
                extracted[url] = content

        return extracted

    async def _judge_evidence(
        self,
        question: str,
        required_concepts: list[str],
        candidates: list[Candidate],
        extracted_by_url: dict[str, str],
    ) -> list[EvidenceCandidate]:
        evidence: list[EvidenceCandidate] = []

        for item in candidates:
            content = extracted_by_url.get(item.url) or item.snippet
            if not content or len(content) < 100:
                continue

            score, direct, reason = await self._judge_one_source(
                question=question,
                required_concepts=required_concepts,
                title=item.title,
                url=item.url,
                content=content,
                tavily_score=item.score,
            )

            evidence.append(
                EvidenceCandidate(
                    title=item.title,
                    url=item.url,
                    content=content,
                    tavily_score=item.score,
                    evidence_score=score,
                    published_date=item.published_date,
                    direct_answer=direct,
                    reason=reason,
                )
            )

        return evidence

    async def _judge_one_source(
        self,
        *,
        question: str,
        required_concepts: list[str],
        title: str,
        url: str,
        content: str,
        tavily_score: float,
    ) -> tuple[float, bool, str]:
        if self.llm and getattr(self.llm, "available", False):
            judged = await self._llm_judge_source(question, title, url, content)
            if judged is not None:
                return judged

        return heuristic_source_judge(
            question=question,
            required_concepts=required_concepts,
            title=title,
            url=url,
            content=content,
            tavily_score=tavily_score,
        )

    async def _llm_judge_source(
        self,
        question: str,
        title: str,
        url: str,
        content: str,
    ) -> tuple[float, bool, str] | None:
        prompt = f"""
You are a strict evidence judge.

Decide whether this source directly helps answer the user's exact question.

Return strict JSON:
{{
  "direct_answer": true,
  "score": 0.0,
  "reason": "short reason"
}}

Rules:
- direct_answer=true if the source contains information that directly supports at least one requested answer part.
- For key-points, highlights, summary, budget, fiscal, policy, law, or government-announcement questions, accept official reports/speeches/releases/articles that contain the underlying measures or announcements even if the page does not literally say "key points".
- Do not accept a source only because it is related to the broad topic.
- Do not infer missing winner/number/person/date from surrounding text.
- If the source lacks the exact fact requested and no requested answer part is supported, direct_answer=false.
- score must be 0 to 1.

Question:
{question}

Source title:
{title}

Source URL:
{url}

Source content:
{trim_to_chars(content, 5000)}
""".strip()

        try:
            payload = await self.llm.generate_json(prompt)
            direct = bool(payload.get("direct_answer"))
            score = max(0.0, min(1.0, safe_float(payload.get("score"), 0.0)))
            reason = clean_text(payload.get("reason")) or "LLM evidence judge."
            return score, direct, reason
        except Exception:
            return None

    async def _post_json(self, url: str, payload: dict[str, object]) -> dict:
        api_key = str(getattr(settings, "tavily_api_key", "") or "")
        timeout = float(getattr(settings, "web_search_timeout_seconds", 20.0))

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required for Tavily web search. Install project requirements.") from exc

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)

            if response.status_code in {401, 403}:
                legacy_payload = dict(payload)
                legacy_payload["api_key"] = api_key
                response = await client.post(url, json=legacy_payload)

            response.raise_for_status()
            data = response.json()

        return data if isinstance(data, dict) else {}

    async def _search_once(self, query: str, depth: str) -> tuple[list[WebSearchResult], str | None]:
        plan = fallback_search_plan(query)
        plan = SearchPlan(
            original_query=query,
            search_queries=[query],
            required_concepts=plan.required_concepts,
            topic=plan.topic,
            time_range=plan.time_range,
            include_domains=plan.include_domains,
            exclude_domains=plan.exclude_domains,
            search_depth=depth or valid_search_depth(),
        )

        try:
            candidates = await self._search_once_candidates(query, plan)
        except Exception as exc:
            return [], f"Tavily search failed: {exc}"

        results = [
            WebSearchResult(
                id=str(idx),
                title=item.title,
                url=item.url,
                content=item.snippet,
                score=item.score,
                published_date=item.published_date,
            )
            for idx, item in enumerate(candidates, start=1)
        ]

        return results, None


def normalize_web_search_mode(value: str | WebSearchMode | None) -> WebSearchMode:
    try:
        return WebSearchMode(value or WebSearchMode.AUTO)
    except ValueError:
        return WebSearchMode.AUTO


def should_search_web(question: str, *, mode: WebSearchMode, has_local_context: bool) -> tuple[bool, str]:
    if mode == WebSearchMode.DISABLED:
        return False, "Web search disabled for this request."

    q = clean_text(question).lower()
    if not q:
        return False, "Empty question."

    if mode == WebSearchMode.FORCE:
        return True, "User enabled web search."

    if has_local_context:
        return False, "Local wiki context is available; skipping automatic web search."

    if looks_like_web_needed(q):
        return True, "Question appears to require public/current/external information."

    return False, "No clear web need detected."


def should_bypass_wiki_for_web(question: str, *, mode: WebSearchMode) -> tuple[bool, str]:
    if mode == WebSearchMode.DISABLED:
        return False, ""

    q = clean_text(question).lower()
    if not q:
        return False, ""

    if looks_private_or_workspace_question(q):
        return False, "Question appears to ask about workspace/private context."

    if mode == WebSearchMode.FORCE:
        return True, "User forced web search for this request."

    if looks_like_web_needed(q):
        return True, "Question appears public/current/external; using web evidence only."

    return False, ""


def build_web_search_query(question: str) -> str:
    return trim_query(question)


def rank_web_results(query: str, results: list[WebSearchResult]) -> list[WebSearchResult]:
    required = extract_required_concepts(query)
    ranked = sorted(
        results,
        key=lambda item: generic_relevance_score(query, required, item.title, item.url, item.content, item.score),
        reverse=True,
    )

    reranked: list[WebSearchResult] = []
    for idx, item in enumerate(ranked, start=1):
        reranked.append(
            WebSearchResult(
                id=str(idx),
                title=item.title,
                url=item.url,
                content=item.content,
                score=item.score,
                published_date=item.published_date,
            )
        )

    return reranked


def expand_supporting_queries(question: str, queries: list[str]) -> list[str]:
    q = trim_query(question)
    lowered = q.lower()
    expanded = list(queries)

    asks_profile = bool(re.search(r"\b(tell me about|about him|about her|about them|profile|biography|background|bio|career)\b", lowered))
    if asks_profile:
        expanded.extend([
            f"{q} biography profile background",
            f"{q} official profile",
            f"{q} career background",
        ])

    role_patterns = [
        (r"current\s+(?:pm|prime minister)\s+of\s+([a-z][a-z\s]+)", "current Prime Minister of {entity}"),
        (r"current\s+president\s+of\s+([a-z][a-z\s]+)", "current President of {entity}"),
        (r"current\s+ceo\s+of\s+([a-z0-9&.\-\s]+)", "current CEO of {entity}"),
    ]
    for pattern, template in role_patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        entity = clean_text(re.split(r"\b(tell me about|about him|about her|about them|profile|biography|background|bio|career)\b", match.group(1), flags=re.I)[0]).title()
        if not entity:
            continue
        role_query = template.format(entity=entity)
        expanded.extend([
            role_query,
            f"{role_query} official",
            f"{role_query} biography profile background",
            f"{role_query} career",
        ])
        break

    if asks_for_budget_or_policy(lowered):
        expanded = [q, *expand_budget_policy_queries(q), *expanded]

    return [item for item in dedupe_preserve_order(expanded) if item][:10]


def fallback_search_plan(question: str) -> SearchPlan:
    q = trim_query(question)
    concepts = extract_required_concepts(q)
    freshness = normalize_time_range_for_query(q, infer_generic_freshness(q))

    search_queries = expand_supporting_queries(
        q,
        dedupe_preserve_order(
            [
                q,
                f"{q} official source",
                f"{q} latest update" if freshness else "",
                f"{q} results statistics" if asks_for_numbers_or_results(q) else "",
                f"{q} reliable sources",
            ]
        ),
    )

    return SearchPlan(
        original_query=q,
        search_queries=[item for item in search_queries if item][:8],
        required_concepts=concepts,
        topic=infer_generic_topic(q),
        time_range=freshness,
        include_domains=[],
        exclude_domains=[],
        search_depth=valid_search_depth(),
    )


def asks_for_budget_or_policy(q: str) -> bool:
    return bool(re.search(
        r"\b("
        r"budget|budgets|fiscal|finance bill|appropriation|tax|taxes|"
        r"government announcement|government announced|announced by government|"
        r"ministry of finance|treasury|policy|policies|white paper|economic survey|"
        r"budget speech|budget statement|budget highlights|key points"
        r")\b",
        q,
        flags=re.IGNORECASE,
    ))


def expand_budget_policy_queries(question: str) -> list[str]:
    q = trim_query(question)
    lowered = q.lower()
    queries = [
        f"{q} official",
        f"{q} highlights",
        f"{q} key points",
        f"{q} budget speech",
        f"{q} budget statement",
        f"{q} ministry of finance",
    ]

    for noisy_word in ("vasan", "bhashan"):
        if noisy_word in lowered:
            queries.extend([
                q.replace(noisy_word, "speech"),
                q.replace(noisy_word, "statement"),
                q.replace(noisy_word, "highlights"),
            ])

    year_match = re.search(r"\b(20\d{2})\b", q)
    country_match = re.search(
        r"\b(?:by|of|in|for)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})\b",
        question,
    )
    country = clean_text(country_match.group(1)) if country_match else ""

    if year_match:
        year = int(year_match.group(1))
        fiscal_variants = [
            f"FY {year}",
            f"FY {year}/{str(year + 1)[-2:]}",
            f"fiscal year {year}",
            f"fiscal year {year}/{str(year + 1)[-2:]}",
        ]
        for variant in fiscal_variants:
            queries.append(f"{q} {variant}")
            if country:
                queries.append(f"{country} budget {variant} highlights official")

    return [trim_query(item) for item in dedupe_preserve_order(queries) if trim_query(item)]


def heuristic_source_judge(
    *,
    question: str,
    required_concepts: list[str],
    title: str,
    url: str,
    content: str,
    tavily_score: float,
) -> tuple[float, bool, str]:
    score = generic_relevance_score(question, required_concepts, title, url, content, tavily_score)
    coverage = concept_coverage(required_concepts, f"{title}\n{url}\n{content}")

    direct = score >= 0.55 and coverage >= 0.55

    if len(required_concepts) <= 2:
        direct = score >= 0.50 and coverage >= 0.50

    if asks_for_budget_or_policy(question):
        direct = score >= 0.48 and coverage >= 0.35

    reason = f"heuristic score={score:.2f}, concept_coverage={coverage:.2f}"
    return score, direct, reason


def generic_relevance_score(
    question: str,
    required_concepts: list[str],
    title: str,
    url: str,
    content: str,
    base_score: float,
) -> float:
    text = normalize_for_match(f"{title}\n{url}\n{content}")
    q_terms = meaningful_terms(question)

    if not q_terms:
        return safe_float(base_score)

    text_terms = set(tokenize(text))
    overlap = len(q_terms & text_terms) / max(1, len(q_terms))

    title_text = normalize_for_match(title)
    title_overlap = len(q_terms & set(tokenize(title_text))) / max(1, len(q_terms))

    coverage = concept_coverage(required_concepts, text)
    authority = authority_score(normalize_domain(url))
    content_bonus = min(len(content) / 6000, 0.12)

    score = (
        safe_float(base_score) * 0.35
        + overlap * 0.20
        + title_overlap * 0.15
        + coverage * 0.20
        + authority * 0.07
        + content_bonus
    )

    if is_bad_url_or_domain(url):
        score -= 0.35

    return max(0.0, min(1.0, score))


def concept_coverage(required_concepts: list[str], text: str) -> float:
    if not required_concepts:
        return 1.0

    normalized_text = normalize_for_match(text)
    hits = 0

    for concept in required_concepts:
        c = normalize_for_match(concept)
        if not c:
            continue

        if c in normalized_text:
            hits += 1
            continue

        concept_terms = meaningful_terms(c)
        if concept_terms and len(concept_terms & set(tokenize(normalized_text))) / max(1, len(concept_terms)) >= 0.67:
            hits += 1

    return hits / max(1, len(required_concepts))


def extract_required_concepts(question: str) -> list[str]:
    q = clean_text(question)

    quoted = re.findall(r'"([^"]{2,80})"', q)
    capitalized_phrases = re.findall(r"\b[A-Z][A-Za-z0-9&'.-]*(?:\s+[A-Z][A-Za-z0-9&'.-]*){0,5}", q)
    number_phrases = re.findall(r"\b(?:19|20)\d{2}\b|\b\d+(?:\.\d+)?%?\b", q)

    terms = list(meaningful_terms(q))
    long_terms = [t for t in terms if len(t) >= 4]

    concepts = quoted + capitalized_phrases + number_phrases + long_terms[:10]
    if re.search(r"\b(tell me about|about him|about her|about them|profile|biography|background|bio|career)\b", q, re.I):
        concepts.extend(["profile", "biography", "background", "career"])
    concepts = [clean_text(c).lower() for c in concepts if clean_text(c)]

    return dedupe_preserve_order(concepts)[:16]


def meaningful_terms(text: str) -> set[str]:
    stop = {
        "the", "a", "an", "and", "or", "but", "if", "then", "else", "for", "to", "of", "in", "on", "at",
        "by", "with", "from", "about", "tell", "give", "show", "explain", "me", "my", "our", "your",
        "is", "are", "was", "were", "be", "been", "being", "who", "what", "when", "where", "why",
        "how", "which", "also", "as", "it", "this", "that", "these", "those", "can", "could", "would",
        "should", "please", "need", "want",
    }

    return {
        t
        for t in tokenize(text.lower())
        if len(t) > 2 and t not in stop
    }


def looks_like_web_needed(q: str) -> bool:
    current_patterns = (
        r"\bcurrent\b",
        r"\blatest\b",
        r"\brecent\b",
        r"\btoday\b",
        r"\bnow\b",
        r"\blive\b",
        r"\bnews\b",
        r"\bprice\b",
        r"\bpricing\b",
        r"\bscore\b",
        r"\bstats?\b",
        r"\bstatistics\b",
        r"\bruns?\b",
        r"\bwickets?\b",
        r"\bipl\b",
        r"\bcricket\b",
        r"\bmatch\b",
        r"\bfinals?\b",
        r"\bplayers?\b",
        r"\bwinner\b",
        r"\bresult\b",
        r"\b20\d{2}\b",
        r"\bversion\b",
        r"\brelease\b",
        r"\bdeadline\b",
        r"\bbudget\b",
        r"\bbudgets\b",
        r"\bfiscal\b",
        r"\bfinance bill\b",
        r"\bappropriation\b",
        r"\btax\b",
        r"\bgovernment\b",
        r"\bannounced\b",
        r"\bannouncement\b",
        r"\bministry\b",
        r"\bpolicy\b",
        r"\blaw\b",
        r"\brule\b",
        r"\bregulation\b",
        r"\bschedule\b",
        r"\bcompare\b",
        r"\bbest\b",
        r"\btop\b",
        r"\breview\b",
        r"\bsource\b",
        r"\bcite\b",
        r"\bverify\b",
        r"\bonline\b",
        r"\bweb\b",
        r"\binternet\b",
    )

    if any(re.search(pattern, q, flags=re.IGNORECASE) for pattern in current_patterns):
        return True

    unstable_public_patterns = (
        r"\bceo\b",
        r"\bpresident\b",
        r"\bprime minister\b",
        r"\bminister\b",
        r"\bhead coach\b",
        r"\bcaptain\b",
        r"\bstandings?\b",
        r"\brankings?\b",
    )

    return any(re.search(pattern, q, flags=re.IGNORECASE) for pattern in unstable_public_patterns)


def looks_private_or_workspace_question(q: str) -> bool:
    private_patterns = (
        r"\bmy\b",
        r"\bour\b",
        r"\buploaded\b",
        r"\bwiki\b",
        r"\bdocument\b",
        r"\bdocuments\b",
        r"\bpdf\b",
        r"\bcontract\b",
        r"\bagreement\b",
        r"\bworkspace\b",
        r"\binternal\b",
        r"\bcompany docs\b",
    )

    return any(re.search(pattern, q, flags=re.IGNORECASE) for pattern in private_patterns)


def infer_generic_freshness(q: str) -> str | None:
    q = q.lower()

    if re.search(r"\b(today|now|live|breaking)\b", q):
        return "day"

    if re.search(r"\b(current|latest|recent|recently|news|this week)\b", q):
        return "week"

    if re.search(r"\b(this month|price|pricing|release|version|deadline|schedule)\b", q):
        return "month"

    if re.search(r"\b(this year|benchmark|leaderboard)\b", q):
        return "year"

    return None


def normalize_time_range_for_query(q: str, time_range: str | None) -> str | None:
    lowered = q.lower()
    has_explicit_year = bool(re.search(r"\b(?:19|20)\d{2}\b", lowered))
    has_strong_recency = bool(re.search(r"\b(today|now|live|breaking|current|latest|recent|recently|this week|this month|this year)\b", lowered))

    if has_explicit_year and not has_strong_recency:
        return None

    if asks_for_budget_or_policy(lowered) and has_explicit_year:
        return None

    return time_range


def infer_generic_topic(q: str) -> str:
    q = q.lower()

    if re.search(r"\b(stock|stocks|share price|market cap|earnings|revenue|crypto|bitcoin|ethereum|finance|budget|fiscal|tax|treasury)\b", q):
        return "finance"

    if re.search(r"\b(news|breaking|today|latest|election|court|government|war|conflict|match|score|winner|result)\b", q):
        return "news"

    return "general"


def asks_for_numbers_or_results(q: str) -> bool:
    return bool(re.search(r"\b(score|scores|stats|statistics|number|count|winner|result|ranking|top|highest|lowest)\b", q, re.I))


def valid_search_depth() -> str:
    value = str(getattr(settings, "tavily_search_depth", "advanced") or "advanced").strip()
    return value if value in {"advanced", "basic", "fast", "ultra-fast"} else "advanced"


def filter_search_candidates(candidates: list[Candidate]) -> list[Candidate]:
    filtered: list[Candidate] = []

    for item in candidates:
        if not item.url or not item.title or not item.snippet:
            continue

        if len(item.snippet) < 80:
            continue

        if is_bad_url_or_domain(item.url):
            continue

        filtered.append(item)

    return filtered


def rank_candidates(question: str, required_concepts: list[str], candidates: list[Candidate]) -> list[Candidate]:
    ranked = sorted(
        candidates,
        key=lambda c: generic_relevance_score(question, required_concepts, c.title, c.url, c.snippet, c.score),
        reverse=True,
    )

    return enforce_domain_diversity(ranked, max_per_domain=2)


def dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    best: dict[str, Candidate] = {}

    for item in candidates:
        key = normalize_url_for_dedupe(item.url)
        if not key:
            continue

        current = best.get(key)
        if not current:
            best[key] = item
            continue

        current_score = current.score + min(len(current.snippet) / 3000, 0.2)
        item_score = item.score + min(len(item.snippet) / 3000, 0.2)

        if item_score > current_score:
            best[key] = item

    return list(best.values())


def enforce_domain_diversity(candidates: list[Candidate], *, max_per_domain: int) -> list[Candidate]:
    counts: dict[str, int] = {}
    primary: list[Candidate] = []
    overflow: list[Candidate] = []

    for item in candidates:
        domain = item.domain
        count = counts.get(domain, 0)

        if count < max_per_domain:
            primary.append(item)
            counts[domain] = count + 1
        else:
            overflow.append(item)

    return primary + overflow


def authority_score(domain: str) -> float:
    domain = normalize_domain(domain)

    if not domain:
        return 0.0

    if domain.endswith(".gov") or domain.endswith(".edu"):
        return 1.0

    strong_parts = (
        "official",
        "docs.",
        "developer.",
        "developers.",
        "support.",
        "help.",
        "api.",
        "github.com",
        "who.int",
        "nih.gov",
        "sec.gov",
        "federalreserve.gov",
        "worldbank.org",
        "oecd.org",
        "reuters.com",
        "apnews.com",
        "bbc.com",
        "nature.com",
        "science.org",
        "arxiv.org",
        "openreview.net",
    )

    if any(part in domain for part in strong_parts):
        return 0.8

    if domain.endswith(".org") or domain.endswith(".int"):
        return 0.45

    return 0.2


def is_bad_url_or_domain(url: str) -> bool:
    domain = normalize_domain(url)
    path = urlparse(url).path.lower()

    blocked_parts = (
        "pinterest.",
        "quora.",
        "blogspot.",
        "answers.",
        "fandom.",
        "slideshare.",
    )

    asset_suffixes = (
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
        ".css", ".js", ".zip", ".tar", ".gz", ".mp4", ".mp3",
    )

    if any(part in domain for part in blocked_parts):
        return True

    if path.endswith(asset_suffixes):
        return True

    return False


def tavily_search_url() -> str:
    return str(getattr(settings, "tavily_search_url", "https://api.tavily.com/search"))


def tavily_extract_url() -> str:
    explicit = getattr(settings, "tavily_extract_url", None)
    if explicit:
        return str(explicit)

    search_url = tavily_search_url().rstrip("/")
    if search_url.endswith("/search"):
        return search_url[: -len("/search")] + "/extract"

    return "https://api.tavily.com/extract"


def normalize_domain(url_or_domain: str) -> str:
    raw = str(url_or_domain or "").strip()
    if not raw:
        return ""

    if "://" not in raw:
        raw = "https://" + raw

    try:
        domain = urlparse(raw).netloc.lower()
    except Exception:
        return ""

    if domain.startswith("www."):
        domain = domain[4:]

    return domain


def normalize_url_for_dedupe(url: str) -> str:
    try:
        parsed = urlparse(url)
    except Exception:
        return clean_text(url).lower()

    query_items = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if not k.lower().startswith("utm_")
    ]

    clean_query_string = urlencode(query_items)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]

    normalized = urlunparse(
        (
            parsed.scheme or "https",
            domain,
            parsed.path.rstrip("/"),
            "",
            clean_query_string,
            "",
        )
    )

    return normalized.lower()


def normalize_domains(items: list[object]) -> list[str]:
    domains = []

    for item in items:
        domain = normalize_domain(str(item))
        if domain:
            domains.append(domain)

    return dedupe_preserve_order(domains)


def normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def clean_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def trim_query(value: str, max_chars: int = 390) -> str:
    text = clean_text(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].strip()


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []

    for item in items:
        text = clean_text(item)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        output.append(text)

    return output


def _looks_like_primary_or_reputable(domain: str) -> bool:
    return authority_score(domain) >= 0.45
