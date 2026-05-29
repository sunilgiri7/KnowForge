"""
knowledge_graph.py — entity extraction, inter-page linking, and graph expansion.

Compile-time: KnowledgeGraphBuilder populates WikiPageMeta.entities and related_slugs.
Runtime: WikiKnowledgeGraph provides in-memory indexes for multi-hop retrieval.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.llmwiki.storage import WikiStore
from app.llmwiki.text import tokenize
from app.schemas.llmwiki import WikiPage, WikiPageListItem

HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)
PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,4}\b")
ENTITY_NOISE = {
    "summary",
    "profile",
    "overview",
    "introduction",
    "section",
    "details",
    "related",
    "pages",
    "source",
    "evidence",
    "document",
    "page",
    "table",
    "data",
}


def normalize_entity(text: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", " ", text.lower())
    return " ".join(cleaned.split())


def _is_valid_entity(text: str) -> bool:
    norm = normalize_entity(text)
    if len(norm) < 2 or len(norm) > 80:
        return False
    if norm in ENTITY_NOISE:
        return False
    tokens = norm.split()
    if len(tokens) == 1 and len(tokens[0]) < 3:
        return False
    return True


@dataclass
class PageLinkIndex:
    """Normalized lookup keys for cross-page linking."""

    slug: str
    title_norm: str
    slug_norm: str
    alias_norms: set[str] = field(default_factory=set)


class KnowledgeGraphBuilder:
    """Build entities and related_slugs for a single wiki page."""

    @staticmethod
    def extract_entities(
        *,
        title: str,
        tags: list[str],
        content: str,
        chunk_notes: list[dict[str, Any]] | None = None,
        existing_entities: list[str] | None = None,
    ) -> list[str]:
        candidates: list[str] = []
        if existing_entities:
            candidates.extend(existing_entities)

        for note in chunk_notes or []:
            for entity in note.get("key_entities", []):
                text = str(entity).strip()
                if text:
                    candidates.append(text)

        if title.strip():
            candidates.append(title.strip())

        for tag in tags:
            text = str(tag).strip()
            if text:
                candidates.append(text)

        for match in HEADING_RE.findall(content):
            text = match.strip()
            if text and len(text) < 120:
                candidates.append(text)

        for match in PROPER_NOUN_RE.findall(content[:12_000]):
            candidates.append(match.strip())

        freq = Counter()
        ordered: list[str] = []
        for raw in candidates:
            if not _is_valid_entity(raw):
                continue
            norm = normalize_entity(raw)
            freq[norm] += 1
            if norm not in {normalize_entity(x) for x in ordered}:
                ordered.append(raw.strip())

        ordered.sort(key=lambda e: (-freq[normalize_entity(e)], -len(e), e.lower()))
        return ordered[: settings.kg_max_entities_per_page]

    @staticmethod
    def build_page_link_index(
        pages: list[WikiPageListItem],
        *,
        full_pages: dict[str, WikiPage] | None = None,
    ) -> list[PageLinkIndex]:
        indexes: list[PageLinkIndex] = []
        for item in pages:
            aliases: set[str] = set()
            if full_pages and item.slug in full_pages:
                page = full_pages[item.slug]
                aliases.update(page.meta.aliases)
                aliases.update(page.meta.tags)
                aliases.update(page.meta.entities[:8])
            else:
                aliases.update(item.tags)
            indexes.append(
                PageLinkIndex(
                    slug=item.slug,
                    title_norm=normalize_entity(item.title),
                    slug_norm=normalize_entity(item.slug.replace("-", " ")),
                    alias_norms={normalize_entity(a) for a in aliases if normalize_entity(a)},
                )
            )
        return indexes

    @classmethod
    def resolve_related_slugs(
        cls,
        *,
        slug: str,
        entities: list[str],
        link_index: list[PageLinkIndex],
    ) -> list[str]:
        self_slug = slug
        related: list[str] = []
        seen: set[str] = {self_slug}

        for entity in entities:
            norm = normalize_entity(entity)
            if not norm:
                continue
            for entry in link_index:
                if entry.slug == self_slug:
                    continue
                if (
                    norm == entry.title_norm
                    or norm == entry.slug_norm
                    or norm in entry.alias_norms
                    or entry.title_norm in norm
                    or (len(norm) >= 4 and entry.title_norm.startswith(norm))
                    or (len(entry.title_norm) >= 4 and norm.startswith(entry.title_norm))
                ):
                    if entry.slug not in seen:
                        seen.add(entry.slug)
                        related.append(entry.slug)

        return related[: settings.kg_max_related_per_page]

    @classmethod
    def build_for_page(
        cls,
        *,
        page: WikiPage,
        all_pages: list[WikiPageListItem],
        chunk_notes: list[dict[str, Any]] | None = None,
        full_pages: dict[str, WikiPage] | None = None,
    ) -> tuple[list[str], list[str]]:
        entities = cls.extract_entities(
            title=page.meta.title,
            tags=page.meta.tags,
            content=page.content,
            chunk_notes=chunk_notes,
            existing_entities=page.meta.entities or None,
        )
        link_index = cls.build_page_link_index(all_pages, full_pages=full_pages)
        related = cls.resolve_related_slugs(
            slug=page.meta.slug,
            entities=entities,
            link_index=link_index,
        )
        return entities, related

    @classmethod
    def append_related_section(cls, page: WikiPage, slug_to_title: dict[str, str]) -> str:
        if not page.meta.related_slugs:
            return page.content
        if "## related pages" in page.content.lower():
            return page.content
        lines = ["## Related pages", ""]
        for rel_slug in page.meta.related_slugs:
            title = slug_to_title.get(rel_slug, rel_slug.replace("-", " ").title())
            lines.append(f"- [{title}]({rel_slug})")
        return page.content.rstrip() + "\n\n" + "\n".join(lines) + "\n"


def rebuild_all_relations(store: WikiStore) -> None:
    """Recompute entities (if missing) and related_slugs for every page in the store."""
    items = store.list_pages()
    if not items:
        return

    full_pages: dict[str, WikiPage] = {}
    for item in items:
        try:
            full_pages[item.slug] = store.read_page(item.slug, prefer_compact=False)
        except Exception:
            continue

    slug_to_title = {item.slug: item.title for item in items}
    link_index = KnowledgeGraphBuilder.build_page_link_index(items, full_pages=full_pages)

    for item in items:
        page = full_pages.get(item.slug)
        if not page:
            continue
        if not page.meta.entities:
            page.meta.entities = KnowledgeGraphBuilder.extract_entities(
                title=page.meta.title,
                tags=page.meta.tags,
                content=page.content,
            )
        page.meta.related_slugs = KnowledgeGraphBuilder.resolve_related_slugs(
            slug=page.meta.slug,
            entities=page.meta.entities,
            link_index=link_index,
        )
        page.content = KnowledgeGraphBuilder.append_related_section(page, slug_to_title)
        store.upsert_page(page, skip_relink=True)


class WikiKnowledgeGraph:
    """In-memory entity and adjacency indexes rebuilt from wiki pages."""

    INDEX_MAX_AGE_SECS = 120

    def __init__(self, store: WikiStore) -> None:
        self.store = store
        self._entity_to_slugs: dict[str, set[str]] = {}
        self._related: dict[str, set[str]] = {}
        self._page_count = -1
        self._mutation_revision = -1
        self._last_rebuild_ts = 0.0

    def invalidate(self) -> None:
        self._page_count = -1
        self._mutation_revision = -1

    def _ensure_fresh(self) -> None:
        current = len(self.store.list_pages())
        revision = self.store.mutation_revision
        age = time.monotonic() - self._last_rebuild_ts
        if (
            current != self._page_count
            or revision != self._mutation_revision
            or age > self.INDEX_MAX_AGE_SECS
        ):
            self._rebuild()
            self._page_count = current
            self._mutation_revision = revision
            self._last_rebuild_ts = time.monotonic()

    def _rebuild(self) -> None:
        entity_map: dict[str, set[str]] = {}
        related_map: dict[str, set[str]] = {}
        needs_backfill = False

        for item in self.store.list_pages():
            try:
                page = self.store.read_page(item.slug, prefer_compact=False)
            except Exception:
                continue
            if not page.meta.entities:
                needs_backfill = True
            for entity in page.meta.entities:
                norm = normalize_entity(entity)
                if norm:
                    entity_map.setdefault(norm, set()).add(item.slug)
            if page.meta.related_slugs:
                related_map[item.slug] = set(page.meta.related_slugs)

        if needs_backfill:
            rebuild_all_relations(self.store)
            entity_map.clear()
            related_map.clear()
            for item in self.store.list_pages():
                try:
                    page = self.store.read_page(item.slug, prefer_compact=False)
                except Exception:
                    continue
                for entity in page.meta.entities:
                    norm = normalize_entity(entity)
                    if norm:
                        entity_map.setdefault(norm, set()).add(item.slug)
                if page.meta.related_slugs:
                    related_map[item.slug] = set(page.meta.related_slugs)

        self._entity_to_slugs = entity_map
        self._related = related_map

    def slugs_for_query_terms(self, terms: list[str]) -> set[str]:
        self._ensure_fresh()
        slugs: set[str] = set()
        for term in terms:
            norm = normalize_entity(term)
            if not norm:
                continue
            for entity_norm, page_slugs in self._entity_to_slugs.items():
                if norm in entity_norm or entity_norm in norm:
                    slugs.update(page_slugs)
        return slugs

    def expand(
        self,
        seed_slugs: list[str],
        question: str,
        *,
        max_hops: int | None = None,
        max_pages: int | None = None,
    ) -> list[str]:
        self._ensure_fresh()
        hops = max_hops if max_hops is not None else settings.kg_max_hops
        cap = max_pages if max_pages is not None else settings.kg_max_pages_in_context

        ordered: list[str] = []
        seen: set[str] = set()

        def add_slug(slug: str) -> None:
            if slug and slug not in seen and len(ordered) < cap:
                seen.add(slug)
                ordered.append(slug)

        for slug in seed_slugs:
            add_slug(slug)

        query_terms = tokenize(question)
        for slug in self.slugs_for_query_terms(query_terms):
            add_slug(slug)

        frontier = list(ordered)
        for _ in range(hops):
            if len(ordered) >= cap:
                break
            next_frontier: list[str] = []
            for slug in frontier:
                for related in self._related.get(slug, set()):
                    if related not in seen:
                        add_slug(related)
                        next_frontier.append(related)
            frontier = next_frontier
            if not frontier:
                break

        return ordered
