"""
vector_store.py — Pinecone vector index client for KnowForge hybrid retrieval.

Architecture
------------
Each wiki workspace maps to ONE Pinecone index. Within that index, vectors
are namespaced by workspace_id so a single Pinecone project can serve all
workspaces without index proliferation.

Vector record format (metadata)
--------------------------------
  id:          "{workspace_id}::{slug}::{chunk_idx}"
  values:      384-dim float32 embedding (all-MiniLM-L6-v2)
  metadata:
    slug:       wiki page slug
    title:      page title
    chunk_idx:  chunk index within the page (0 = summary block)
    chunk_text: the raw text that was embedded (used for snippet preview)
    workspace:  workspace_id (also encoded in namespace)

Why one index, namespaced?
--------------------------
Pinecone serverless charges per index. Using namespaces means all workspaces
share a single index's quota while keeping data logically isolated.
Namespaced queries are strictly scoped — workspace A never sees workspace B.

Graceful-off design
-------------------
If PINECONE_API_KEY is not set, every method is a safe no-op that returns
empty results. BM25 continues working — this class just adds the semantic
layer on top.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from app.core.config import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# How many characters of page content form one chunk for embedding.
# Smaller chunks = more precise semantic matches, more vectors.
# 512 chars ≈ 128 tokens ≈ 1 paragraph — good balance.
CHUNK_CHARS = 512
CHUNK_OVERLAP = 80     # chars shared between adjacent chunks
MAX_CHUNKS_PER_PAGE = 40  # guard against gigantic pages


# ── Pinecone client singleton ─────────────────────────────────────────────────


_pc_client: Any = None


def _get_pinecone() -> Any:
    """Return a Pinecone client, or None if the key is not configured."""
    global _pc_client
    if _pc_client is not None:
        return _pc_client
    api_key = settings.pinecone_api_key
    if not api_key:
        return None
    try:
        from pinecone import Pinecone
        _pc_client = Pinecone(api_key=api_key)
        logger.info("Pinecone client initialised.")
    except Exception as exc:
        logger.warning("Could not initialise Pinecone: %s", exc)
        _pc_client = None
    return _pc_client


def _get_index() -> Any:
    """Return the Pinecone index object (or None if unavailable)."""
    pc = _get_pinecone()
    if pc is None:
        return None
    try:
        return pc.Index(settings.pinecone_index_name)
    except Exception as exc:
        logger.warning("Could not connect to Pinecone index '%s': %s",
                       settings.pinecone_index_name, exc)
        return None


@property
def _available() -> bool:
    return bool(settings.pinecone_api_key)


# ── Text chunking ─────────────────────────────────────────────────────────────


def chunk_text(text: str) -> list[str]:
    """
    Split text into overlapping character-level chunks.

    Splits are always at newline boundaries to avoid cutting mid-sentence,
    which would degrade embedding quality.
    """
    if not text.strip():
        return []

    chunks: list[str] = []
    lines = text.splitlines(keepends=True)
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line)
        if current_len + line_len > CHUNK_CHARS and current:
            chunk = "".join(current).strip()
            if chunk:
                chunks.append(chunk)
            if len(chunks) >= MAX_CHUNKS_PER_PAGE:
                break
            # Carry over tail for overlap
            tail = "".join(current)[-CHUNK_OVERLAP:]
            current = [tail, line]
            current_len = len(tail) + line_len
        else:
            current.append(line)
            current_len += line_len

    if current and len(chunks) < MAX_CHUNKS_PER_PAGE:
        chunk = "".join(current).strip()
        if chunk:
            chunks.append(chunk)

    return chunks


# ── VectorStore class ─────────────────────────────────────────────────────────


class VectorStore:
    """
    Pinecone-backed semantic vector store for wiki pages.

    All operations are async and gracefully degrade to no-ops if Pinecone
    is not configured.
    """

    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id
        # Pinecone namespace — workspace-scoped isolation within one index
        self._namespace = f"ws-{workspace_id}"

    @property
    def available(self) -> bool:
        return bool(settings.pinecone_api_key)

    # ── Write operations ──────────────────────────────────────────────────────

    async def upsert_page(
        self,
        slug: str,
        title: str,
        summary: str,
        content: str,
    ) -> None:
        """
        Embed and upsert all chunks of a wiki page into Pinecone.

        Called from WikiStore.upsert_page() after every page write.
        """
        if not self.available:
            return

        from app.llmwiki.embedder import embed_texts

        # Build text blocks to embed:
        # Block 0: title + summary (high-signal, always present)
        # Blocks 1..N: content chunks
        header = f"{title}\n{summary}"
        content_chunks = chunk_text(content)
        all_texts = [header] + content_chunks

        vectors = await embed_texts(all_texts)
        if vectors is None:
            logger.warning("Skipping Pinecone upsert for %s — embedding failed.", slug)
            return

        records = []
        for chunk_idx, (text, vector) in enumerate(zip(all_texts, vectors)):
            record_id = f"{self.workspace_id}::{slug}::{chunk_idx}"
            records.append({
                "id": record_id,
                "values": vector,
                "metadata": {
                    "slug": slug,
                    "title": title,
                    "chunk_idx": chunk_idx,
                    "chunk_text": text[:400],  # store preview for debugging
                    "workspace": self.workspace_id,
                },
            })

        await asyncio.to_thread(self._upsert_sync, records)

    def _upsert_sync(self, records: list[dict]) -> None:
        index = _get_index()
        if index is None:
            return
        # Pinecone recommends batches of ≤100 vectors
        batch_size = 100
        for i in range(0, len(records), batch_size):
            batch = records[i: i + batch_size]
            try:
                index.upsert(vectors=batch, namespace=self._namespace)
            except Exception as exc:
                logger.warning("Pinecone upsert batch failed: %s", exc)

    async def delete_page(self, slug: str, num_chunks: int = MAX_CHUNKS_PER_PAGE) -> None:
        """Delete all vectors for a page (called on delete_page / rename)."""
        if not self.available:
            return
        ids = [
            f"{self.workspace_id}::{slug}::{i}"
            for i in range(num_chunks + 1)  # +1 for the header block
        ]
        await asyncio.to_thread(self._delete_sync, ids)

    def _delete_sync(self, ids: list[str]) -> None:
        index = _get_index()
        if index is None:
            return
        try:
            index.delete(ids=ids, namespace=self._namespace)
        except Exception as exc:
            logger.warning("Pinecone delete failed: %s", exc)

    # ── Read operations ───────────────────────────────────────────────────────

    async def query(
        self,
        query_text: str,
        *,
        top_k: int = 10,
    ) -> list[tuple[str, float]]:
        """
        Semantic search: embed query and retrieve top-k matching wiki slugs.

        Returns [(slug, score)] sorted by score descending.
        Score is Pinecone's cosine similarity (0–1).
        """
        if not self.available:
            return []

        from app.llmwiki.embedder import embed_query

        vector = await embed_query(query_text)
        if vector is None:
            return []

        return await asyncio.to_thread(self._query_sync, vector, top_k)

    def _query_sync(
        self, vector: list[float], top_k: int
    ) -> list[tuple[str, float]]:
        index = _get_index()
        if index is None:
            return []
        try:
            response = index.query(
                vector=vector,
                top_k=top_k,
                namespace=self._namespace,
                include_metadata=True,
            )
            # Aggregate scores per slug — take max score across all chunks
            slug_scores: dict[str, float] = {}
            for match in response.matches:
                slug = match.metadata.get("slug", "")
                score = float(match.score or 0.0)
                if slug:
                    slug_scores[slug] = max(slug_scores.get(slug, 0.0), score)
            return sorted(slug_scores.items(), key=lambda x: x[1], reverse=True)
        except Exception as exc:
            logger.warning("Pinecone query failed: %s", exc)
            return []
