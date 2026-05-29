"""
temporal.py — Temporal fact extraction and version supersession detection.

At ingest time:
1. Compare new page against existing pages (title similarity, entity overlap, source filename).
2. If likely a newer version → create WikiSupersessionLink, mark old page as 'superseded'.
3. Extract temporal facts (dates, rates, roles, deadlines) from compiled content.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import WikiFactEvent, WikiPageRecord, WikiPageVersion, WikiSupersessionLink
from app.llmwiki.groq import GroqClient
from app.llmwiki.text import safe_format, slugify
from app.schemas.llmwiki import WikiPage


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

TEMPORAL_FACT_PROMPT = """\
You are a temporal fact extractor. Given a knowledge-base wiki page, extract ALL time-sensitive facts.

Return JSON with a single key "facts": a list of objects. Each object must have:
  - fact_type: one of [effective_date, deadline, price_rate, assignment, policy_period, publication_date, other]
  - subject: the entity the fact is about (person, team, policy, product, etc.)
  - predicate: the relationship or attribute (e.g., "joined", "cost", "expires", "reports to")
  - object_val: the value or description (text, number, date string, name, etc.)
  - effective_date: ISO 8601 date string (or null if not specified)
  - expiration_date: ISO 8601 date string (or null if not specified)
  - source_quote: the exact sentence or phrase from the page that supports this fact
  - confidence: float 0.0–1.0

Only extract facts that are temporal or factual. Do NOT invent information not present in the text.
Return at most 20 facts.

Wiki page title: {title}
Wiki page content (excerpt):
{content}
"""

SEMANTIC_DIFF_PROMPT = """\
You are a knowledge change analyst. Given two versions of a wiki page, summarize what changed.

Return JSON with:
  - semantic_summary: a plain-English 2–4 sentence summary of what changed and why it matters
  - changed_facts: list of strings, each describing one specific change (e.g., "Price changed from $100 to $120")
  - risk_level: "low", "medium", or "high" (based on significance of the changes)

Be specific about numbers, dates, names, and decisions that changed.
Do NOT mention formatting changes or minor rewordings unless they change meaning.

OLD VERSION:
{old_content}

NEW VERSION:
{new_content}
"""


# ---------------------------------------------------------------------------
# Version Ledger
# ---------------------------------------------------------------------------


def compute_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]


class WikiVersionLedger:
    """
    Writes immutable version rows to Postgres for every wiki page write.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_or_create_page_record(
        self,
        *,
        workspace_id: str,
        slug: str,
        title: str,
    ) -> WikiPageRecord:
        record = (
            self.db.query(WikiPageRecord)
            .filter_by(workspace_id=workspace_id, slug=slug)
            .first()
        )
        if not record:
            record = WikiPageRecord(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                slug=slug,
                title=title,
            )
            self.db.add(record)
            self.db.flush()
        else:
            record.title = title
        return record

    def record_version(
        self,
        *,
        page: WikiPage,
        workspace_id: str,
        created_by: str | None = None,
        created_reason: str = "compilation",
    ) -> WikiPageVersion:
        content_hash = compute_content_hash(page.content)
        record = self.get_or_create_page_record(
            workspace_id=workspace_id,
            slug=page.meta.slug,
            title=page.meta.title,
        )

        # If content is identical to last version, don't create duplicate
        if record.versions:
            last = record.versions[-1]
            if last.content_hash == content_hash:
                return last

        next_number = (record.versions[-1].version_number + 1) if record.versions else 1
        version = WikiPageVersion(
            id=str(uuid.uuid4()),
            page_record_id=record.id,
            version_number=next_number,
            content_hash=content_hash,
            content=page.content,
            summary=page.meta.summary,
            tags_json=json.dumps(page.meta.tags),
            entities_json=json.dumps(page.meta.entities),
            source_ids_json=json.dumps(page.meta.source_ids),
            created_by=created_by,
            created_reason=created_reason,
        )
        self.db.add(version)
        record.current_version_id = version.id
        self.db.commit()
        return version

    def get_versions(
        self, *, workspace_id: str, slug: str
    ) -> tuple[WikiPageRecord | None, list[WikiPageVersion]]:
        record = (
            self.db.query(WikiPageRecord)
            .filter_by(workspace_id=workspace_id, slug=slug)
            .first()
        )
        if not record:
            return None, []
        return record, list(record.versions)

    def get_version_by_number(
        self, *, workspace_id: str, slug: str, version_number: int
    ) -> WikiPageVersion | None:
        record = (
            self.db.query(WikiPageRecord)
            .filter_by(workspace_id=workspace_id, slug=slug)
            .first()
        )
        if not record:
            return None
        for v in record.versions:
            if v.version_number == version_number:
                return v
        return None


# ---------------------------------------------------------------------------
# Supersession Detection
# ---------------------------------------------------------------------------


def _title_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _entity_overlap(entities_a: list[str], entities_b: list[str]) -> float:
    if not entities_a or not entities_b:
        return 0.0
    set_a = {e.lower() for e in entities_a}
    set_b = {e.lower() for e in entities_b}
    overlap = len(set_a & set_b)
    return overlap / max(len(set_a), len(set_b))


class SupersessionDetector:
    """
    During ingest, detect if the new page is a newer version of an existing page.
    Scoring: title similarity + entity overlap + content similarity.
    """

    THRESHOLD = 0.65  # combined score to declare supersession

    def __init__(self, db: Session):
        self.db = db

    def find_superseded_page(
        self,
        *,
        new_page: WikiPage,
        workspace_id: str,
        existing_pages: list[WikiPage],
    ) -> str | None:
        """Return the slug of the best supersession candidate, or None."""
        new_title = new_page.meta.title.lower()
        new_entities = new_page.meta.entities
        new_content = new_page.content[:4000]

        best_score = 0.0
        best_slug: str | None = None

        for old_page in existing_pages:
            if old_page.meta.slug == new_page.meta.slug:
                continue
            if old_page.meta.freshness == "superseded":
                continue

            title_sim = _title_similarity(new_title, old_page.meta.title)
            entity_sim = _entity_overlap(new_entities, old_page.meta.entities)
            content_sim = difflib.SequenceMatcher(
                None, old_page.content[:4000], new_content
            ).ratio()

            # Weighted average: title matters most
            combined = 0.5 * title_sim + 0.3 * entity_sim + 0.2 * content_sim

            if combined > best_score and combined >= self.THRESHOLD:
                best_score = combined
                best_slug = old_page.meta.slug

        return best_slug

    def record_supersession(
        self,
        *,
        workspace_id: str,
        old_slug: str,
        new_slug: str,
        similarity: float,
    ) -> WikiSupersessionLink:
        link = WikiSupersessionLink(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            old_slug=old_slug,
            new_slug=new_slug,
            link_type="supersedes",
            detected_similarity=round(similarity, 3),
        )
        self.db.add(link)
        self.db.commit()
        return link


# ---------------------------------------------------------------------------
# Temporal Fact Extractor
# ---------------------------------------------------------------------------


_DATE_PATTERN = re.compile(
    r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)


def _parse_date_str(raw: str | None) -> datetime | None:
    if not raw:
        return None
    from datetime import datetime as dt
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return dt.strptime(raw.strip(), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


class TemporalFactExtractor:
    """
    Calls Groq LLM to extract temporal facts from compiled wiki content.
    Falls back to regex extraction if LLM is unavailable.
    """

    def __init__(self, db: Session, llm: GroqClient | None = None):
        self.db = db
        self.llm = llm or GroqClient()

    async def extract_and_store(
        self,
        *,
        page: WikiPage,
        workspace_id: str,
    ) -> list[WikiFactEvent]:
        # Remove old facts for this page before re-extracting
        self.db.query(WikiFactEvent).filter_by(
            workspace_id=workspace_id, page_slug=page.meta.slug
        ).delete()
        self.db.flush()

        facts: list[dict[str, Any]] = []
        if self.llm.available:
            try:
                result = await self.llm.generate_json(
                    safe_format(
                        TEMPORAL_FACT_PROMPT,
                        title=page.meta.title,
                        content=page.content[:8000],
                    ),
                    temperature=0.05,
                )
                facts = result.get("facts", [])
            except Exception:
                facts = []

        if not facts:
            facts = self._regex_fallback(page)

        rows: list[WikiFactEvent] = []
        for raw in facts[:20]:
            event = WikiFactEvent(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                page_slug=page.meta.slug,
                fact_type=str(raw.get("fact_type", "other")),
                subject=str(raw.get("subject", ""))[:255],
                predicate=str(raw.get("predicate", ""))[:255],
                object_val=str(raw.get("object_val", "")),
                effective_date=_parse_date_str(raw.get("effective_date")),
                expiration_date=_parse_date_str(raw.get("expiration_date")),
                source_quote=str(raw.get("source_quote", ""))[:2000],
                confidence=float(raw.get("confidence", 0.8)),
            )
            self.db.add(event)
            rows.append(event)

        self.db.commit()
        return rows

    @staticmethod
    def _regex_fallback(page: WikiPage) -> list[dict[str, Any]]:
        """Best-effort regex fallback when LLM is unavailable."""
        results: list[dict[str, Any]] = []
        for line in page.content.splitlines():
            if not line.strip():
                continue
            for m in _DATE_PATTERN.finditer(line):
                results.append({
                    "fact_type": "publication_date",
                    "subject": page.meta.title,
                    "predicate": "contains date",
                    "object_val": m.group(0),
                    "effective_date": m.group(0),
                    "expiration_date": None,
                    "source_quote": line.strip()[:300],
                    "confidence": 0.5,
                })
                if len(results) >= 10:
                    return results
        return results


# ---------------------------------------------------------------------------
# Semantic Diff
# ---------------------------------------------------------------------------


def compute_line_diff(old_content: str, new_content: str) -> list[dict[str, Any]]:
    """
    Returns a list of diff hunks using difflib.unified_diff.
    Each hunk: {kind: equal|insert|delete|replace, old_lines: [...], new_lines: [...]}
    """
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    hunks: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        hunks.append({
            "kind": tag,
            "old_lines": old_lines[i1:i2],
            "new_lines": new_lines[j1:j2],
        })
    return hunks


async def compute_semantic_diff(
    *,
    old_content: str,
    new_content: str,
    from_version: int,
    to_version: int,
    llm: GroqClient | None = None,
) -> dict[str, Any]:
    """Combines line diff + LLM semantic diff into a unified response."""
    line_hunks = compute_line_diff(old_content, new_content)

    semantic_summary = ""
    changed_facts: list[str] = []
    risk_level = "low"

    if llm and llm.available:
        try:
            result = await llm.generate_json(
                safe_format(
                    SEMANTIC_DIFF_PROMPT,
                    old_content=old_content[:5000],
                    new_content=new_content[:5000],
                ),
                temperature=0.05,
            )
            semantic_summary = str(result.get("semantic_summary", ""))
            changed_facts = [str(f) for f in result.get("changed_facts", [])]
            risk_level = str(result.get("risk_level", "low"))
            if risk_level not in ("low", "medium", "high"):
                risk_level = "low"
        except Exception:
            pass

    return {
        "from_version": from_version,
        "to_version": to_version,
        "line_hunks": line_hunks,
        "semantic_summary": semantic_summary,
        "changed_facts": changed_facts,
        "risk_level": risk_level,
    }
