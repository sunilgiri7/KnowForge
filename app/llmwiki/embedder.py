"""
embedder.py — Local sentence embedding for hybrid retrieval.

Uses the `all-MiniLM-L6-v2` model from sentence-transformers:
  - 384-dimensional dense vectors
  - ~80ms per batch of 64 passages on CPU
  - No external API calls — fully local, free, fast
  - Downloads once to ~/.cache/huggingface/ and is cached forever

Design decisions
----------------
* Singleton loader: the model is expensive to load (~30MB), so we load it
  once on first use and reuse it for the lifetime of the process.
* Async-safe: embedding is CPU-bound, so we wrap it in asyncio.to_thread()
  so the FastAPI event loop never blocks.
* Graceful-off: if torch/sentence-transformers are unavailable (shouldn't
  happen after install), returns None so callers can skip vector search.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_MODEL_NAME = "all-MiniLM-L6-v2"
_model: Any = None
_model_lock = threading.Lock()


def _load_model() -> Any:
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:  # double-check after acquiring lock
            return _model
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading embedding model %s …", _MODEL_NAME)
            _model = SentenceTransformer(_MODEL_NAME)
            logger.info("Embedding model loaded.")
        except Exception as exc:
            logger.warning("Could not load embedding model: %s", exc)
            _model = None
    return _model


def _embed_sync(texts: list[str]) -> list[list[float]] | None:
    model = _load_model()
    if model is None:
        return None
    try:
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]
    except Exception as exc:
        logger.warning("Embedding failed: %s", exc)
        return None


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Embed a list of texts, returns None if the model is unavailable."""
    if not texts:
        return None
    return await asyncio.to_thread(_embed_sync, texts)


async def embed_query(query: str) -> list[float] | None:
    """Embed a single query string."""
    result = await embed_texts([query])
    if result is None:
        return None
    return result[0]


EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 output dimension
