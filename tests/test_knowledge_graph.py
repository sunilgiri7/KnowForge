from __future__ import annotations

import tempfile
from pathlib import Path

from app.llmwiki.indexer import BM25PageIndex
from app.llmwiki.knowledge_graph import (
    KnowledgeGraphBuilder,
    WikiKnowledgeGraph,
    normalize_entity,
    rebuild_all_relations,
)
from app.llmwiki.storage import WikiStore
from app.schemas.llmwiki import WikiPage, WikiPageListItem, WikiPageMeta


def test_normalize_entity_strips_punctuation() -> None:
    assert normalize_entity("  Acme Corp.  ") == "acme corp"


def test_extract_entities_dedupes_and_caps() -> None:
    notes = [{"key_entities": ["Acme Corp", "acme corp", "Jane Doe"]}]
    entities = KnowledgeGraphBuilder.extract_entities(
        title="Employment Agreement",
        tags=["hr"],
        content="## Compensation\n\nAcme Corp pays Jane Doe.",
        chunk_notes=notes,
    )
    norms = [normalize_entity(e) for e in entities]
    assert "acme corp" in norms
    assert norms.count("acme corp") == 1


def test_resolve_related_slugs_by_title_match() -> None:
    link_index = KnowledgeGraphBuilder.build_page_link_index(
        [
            WikiPageListItem(
                title="Employment Agreement",
                slug="employment-agreement",
                summary="",
                tags=[],
                freshness="current",
                confidence="medium",
                source_ids=[],
            ),
            WikiPageListItem(
                title="Benefits Policy",
                slug="benefits-policy",
                summary="",
                tags=[],
                freshness="current",
                confidence="medium",
                source_ids=[],
            ),
        ]
    )
    related = KnowledgeGraphBuilder.resolve_related_slugs(
        slug="employment-agreement",
        entities=["Benefits Policy", "unused"],
        link_index=link_index,
    )
    assert related == ["benefits-policy"]


def test_wiki_knowledge_graph_expand_respects_cap() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = WikiStore(Path(tmp) / "user")
        for slug, title, related in (
            ("page-a", "Page A", ["page-b"]),
            ("page-b", "Page B", ["page-c"]),
            ("page-c", "Page C", []),
        ):
            store.upsert_page(
                WikiPage(
                    meta=WikiPageMeta(
                        title=title,
                        slug=slug,
                        entities=[title],
                        related_slugs=related,
                    ),
                    content=f"Body for {title}",
                ),
                skip_relink=True,
            )
        rebuild_all_relations(store)
        graph = WikiKnowledgeGraph(store)
        expanded = graph.expand(["page-a"], "page c linkage", max_hops=2, max_pages=2)
        assert expanded[0] == "page-a"
        assert len(expanded) <= 2


def test_bm25_index_includes_entities_field() -> None:
    page = WikiPage(
        meta=WikiPageMeta(
            title="Salary Guide",
            slug="salary-guide",
            entities=["Net Pay", "CTC"],
        ),
        content="Tables and numbers.",
    )
    fields = BM25PageIndex._extract_fields(page)
    assert "Net Pay" in fields["entities"]
    assert "CTC" in fields["entities"]
    assert "entities" in BM25PageIndex.FIELD_WEIGHTS
