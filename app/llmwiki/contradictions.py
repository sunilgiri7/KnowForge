"""
contradictions.py — detect and persist factual conflicts across related wiki pages.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Protocol

from app.core.config import settings
from app.llmwiki.groq import GroqClient
from app.llmwiki.markdown import now_iso
from app.llmwiki.prompts import CONTRADICTION_PROMPT
from app.llmwiki.storage import WikiStore
from app.llmwiki.text import safe_format, trim_to_chars
from app.schemas.llmwiki import WikiContradiction, WikiPage


class ContradictionLLM(Protocol):
    @property
    def available(self) -> bool: ...

    async def generate_json(self, prompt: str, *, temperature: float = 0.1) -> dict[str, Any]: ...


def pair_key(slug_a: str, slug_b: str) -> str:
    a, b = sorted([slug_a, slug_b])
    return f"{a}|{b}"


def page_fingerprint(page: WikiPage) -> str:
    payload = "|".join(
        [
            page.meta.title,
            page.meta.summary,
            " ".join(page.meta.entities),
            page.content[:12_000],
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


class ContradictionStore:
    def __init__(self, wiki_store: WikiStore):
        self.wiki_store = wiki_store
        self.path = wiki_store.events_dir / "contradictions.json"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "items": [], "pair_fingerprints": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"version": 1, "items": [], "pair_fingerprints": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.wiki_store._atomic_write(
            self.path,
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        )

    def list_all(self) -> list[WikiContradiction]:
        raw_items = self._load().get("items", [])
        return [WikiContradiction.model_validate(item) for item in raw_items]

    def list_open(self) -> list[WikiContradiction]:
        return [item for item in self.list_all() if item.status == "open"]

    def open_count_for_slug(self, slug: str) -> int:
        return sum(
            1
            for item in self.list_open()
            if item.slug_a == slug or item.slug_b == slug
        )

    def open_count_by_slug(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.list_open():
            counts[item.slug_a] = counts.get(item.slug_a, 0) + 1
            counts[item.slug_b] = counts.get(item.slug_b, 0) + 1
        return counts

    def update_status(self, contradiction_id: str, status: str) -> WikiContradiction | None:
        data = self._load()
        updated: WikiContradiction | None = None
        for item in data.get("items", []):
            if item.get("id") == contradiction_id:
                item["status"] = status
                updated = WikiContradiction.model_validate(item)
                break
        if updated:
            self._save(data)
        return updated

    def replace_pair_results(
        self,
        slug_a: str,
        slug_b: str,
        *,
        fingerprint_a: str,
        fingerprint_b: str,
        contradictions: list[WikiContradiction],
    ) -> None:
        data = self._load()
        key = pair_key(slug_a, slug_b)
        kept = [
            item
            for item in data.get("items", [])
            if pair_key(item.get("slug_a", ""), item.get("slug_b", "")) != key
        ]
        kept.extend(contradiction.model_dump() for contradiction in contradictions)
        data["items"] = kept
        fingerprints = data.setdefault("pair_fingerprints", {})
        fingerprints[key] = {"hash_a": fingerprint_a, "hash_b": fingerprint_b}
        self._save(data)

    def pair_is_fresh(self, slug_a: str, slug_b: str, fp_a: str, fp_b: str) -> bool:
        data = self._load()
        stored = data.get("pair_fingerprints", {}).get(pair_key(slug_a, slug_b))
        if not stored:
            return False
        a, b = sorted([slug_a, slug_b])
        if a == slug_a:
            return stored.get("hash_a") == fp_a and stored.get("hash_b") == fp_b
        return stored.get("hash_a") == fp_b and stored.get("hash_b") == fp_a


class ContradictionScanner:
    def __init__(self, store: WikiStore, llm: ContradictionLLM | None = None):
        self.store = store
        self.llm = llm or GroqClient()
        self.records = ContradictionStore(store)

    def candidate_pairs(self, *, focus_slugs: set[str] | None = None) -> list[tuple[str, str]]:
        pages = self.store.list_pages()
        slug_set = {page.slug for page in pages}
        seen: set[str] = set()
        pairs: list[tuple[str, str]] = []

        for item in pages:
            if focus_slugs and item.slug not in focus_slugs:
                continue
            page = self.store.read_page(item.slug, prefer_compact=True)
            neighbors = set(page.meta.related_slugs)
            for entity in page.meta.entities[:12]:
                entity_norm = entity.lower().strip()
                if len(entity_norm) < 4:
                    continue
                for other in pages:
                    if other.slug == item.slug:
                        continue
                    title_norm = other.title.lower()
                    if entity_norm in title_norm or title_norm in entity_norm:
                        neighbors.add(other.slug)

            for other_slug in neighbors:
                if other_slug not in slug_set or other_slug == item.slug:
                    continue
                key = pair_key(item.slug, other_slug)
                if key in seen:
                    continue
                seen.add(key)
                pairs.append((item.slug, other_slug))
                if len(pairs) >= settings.contradiction_max_pairs_per_scan:
                    return pairs
        return pairs

    async def scan(
        self,
        *,
        focus_slugs: set[str] | None = None,
        max_pairs: int | None = None,
    ) -> tuple[int, int]:
        if not self.llm.available:
            return 0, len(self.records.list_open())

        cap = max_pairs or settings.contradiction_max_pairs_per_scan
        pairs = self.candidate_pairs(focus_slugs=focus_slugs)[:cap]
        new_count = 0
        for slug_a, slug_b in pairs:
            added = await self._scan_pair(slug_a, slug_b)
            new_count += added
        return len(pairs), new_count

    async def _scan_pair(self, slug_a: str, slug_b: str) -> int:
        page_a = self.store.read_page(slug_a, prefer_compact=True)
        page_b = self.store.read_page(slug_b, prefer_compact=True)
        fp_a = page_fingerprint(page_a)
        fp_b = page_fingerprint(page_b)
        if self.records.pair_is_fresh(slug_a, slug_b, fp_a, fp_b):
            return 0

        excerpt_a = trim_to_chars(page_a.content, settings.contradiction_excerpt_chars)
        excerpt_b = trim_to_chars(page_b.content, settings.contradiction_excerpt_chars)
        try:
            payload = await self.llm.generate_json(
                safe_format(
                    CONTRADICTION_PROMPT,
                    title_a=page_a.meta.title,
                    slug_a=page_a.meta.slug,
                    excerpt_a=excerpt_a,
                    title_b=page_b.meta.title,
                    slug_b=page_b.meta.slug,
                    excerpt_b=excerpt_b,
                ),
                temperature=0.05,
            )
        except Exception:
            return 0

        detected: list[WikiContradiction] = []
        for raw in payload.get("contradictions", []):
            topic = str(raw.get("topic", "")).strip()
            claim_a = str(raw.get("claim_a", "")).strip()
            claim_b = str(raw.get("claim_b", "")).strip()
            if not topic or not claim_a or not claim_b:
                continue
            severity = str(raw.get("severity", "medium")).lower()
            if severity not in {"low", "medium", "high"}:
                severity = "medium"
            detected.append(
                WikiContradiction(
                    id=str(uuid.uuid4()),
                    slug_a=slug_a,
                    slug_b=slug_b,
                    title_a=page_a.meta.title,
                    title_b=page_b.meta.title,
                    topic=topic,
                    claim_a=claim_a,
                    claim_b=claim_b,
                    severity=severity,  # type: ignore[arg-type]
                    rationale=str(raw.get("rationale", "")).strip(),
                    detected_at=now_iso(),
                )
            )

        self.records.replace_pair_results(
            slug_a,
            slug_b,
            fingerprint_a=fp_a,
            fingerprint_b=fp_b,
            contradictions=detected,
        )
        return len(detected)

    def context_warnings_for_slugs(self, slugs: list[str]) -> str:
        if not slugs:
            return ""
        slug_set = set(slugs)
        warnings: list[str] = []
        for item in self.records.list_open():
            if item.slug_a not in slug_set and item.slug_b not in slug_set:
                continue
            warnings.append(
                f"- [{item.severity}] {item.topic}: "
                f'"{item.title_a}" says "{item.claim_a}" but '
                f'"{item.title_b}" says "{item.claim_b}".'
            )
            if len(warnings) >= 5:
                break
        if not warnings:
            return ""
        return (
            "OPEN WIKI CONFLICTS (flag to the user; do not invent a resolution):\n"
            + "\n".join(warnings)
        )
