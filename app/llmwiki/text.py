"""
text.py — string utilities, BM25 scoring, and Reciprocal Rank Fusion.

Additions over v1:
  - bm25_score(): Okapi BM25 for a single document field
  - reciprocal_rank_fusion(): rank-based merging for multi-query retrieval
"""
from __future__ import annotations

import re
from collections import Counter
from math import log

TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,}")
STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "because",
    "between",
    "can",
    "could",
    "does",
    "for",
    "from",
    "give",
    "have",
    "how",
    "into",
    "need",
    "not",
    "our",
    "should",
    "that",
    "the",
    "their",
    "then",
    "there",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
    "you",
}

# ── BM25 parameters ───────────────────────────────────────────────────────────
# k1 controls term-frequency saturation: higher → slower saturation (more
#   weight to high-TF terms).  Standard range: 1.2–2.0.
# b  controls length normalisation: 1.0 = full, 0.0 = none.  0.75 is the
#   standard default from the Okapi BM25 paper.
BM25_K1: float = 1.5
BM25_B: float = 0.75


# ── Core text utilities (unchanged) ──────────────────────────────────────────


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text) if token.lower() not in STOPWORDS]


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def trim_to_chars(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit("\n", 1)[0].strip()
    return cut or text[:limit].strip()


def keyword_summary(text: str, *, max_sentences: int = 8) -> str:
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    words = tokenize(text)
    scores = Counter(words)
    ranked: list[tuple[int, float, str]] = []
    for index, sentence in enumerate(sentences):
        sentence_words = tokenize(sentence)
        if not sentence_words:
            continue
        score = sum(scores[word] for word in sentence_words) / len(sentence_words)
        ranked.append((index, score, sentence.strip()))
    chosen = sorted(sorted(ranked, key=lambda item: item[1], reverse=True)[:max_sentences])
    return "\n".join(sentence for _, _, sentence in chosen)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


def safe_format(template: str, **kwargs: object) -> str:
    """Format a prompt template safely.

    Unlike str.format(), this replaces {key} placeholders using simultaneous
    regex substitution so that:
      - { and } inside values never cause KeyError/ValueError
      - Values containing other {placeholder} patterns are treated as literals
      - Works when PDF text, wiki content, or code is embedded in kwargs
    """
    if not kwargs:
        return template
    str_kwargs = {k: str(v) for k, v in kwargs.items()}
    key_pattern = re.compile(
        r"\{(" + "|".join(re.escape(k) for k in str_kwargs) + r")\}"
    )
    return key_pattern.sub(lambda m: str_kwargs[m.group(1)], template)


def count_approx_tokens(text: str) -> int:
    """Rough estimate: 1 token ≈ 4 characters (Llama/GPT heuristic)."""
    return max(1, len(text) // 4)


def trim_context_to_token_budget(
    context: str,
    *,
    token_budget: int,
    reserve_for_prompt: int = 1500,
    reserve_for_output: int = 1024,
) -> str:
    """Trim context so the total prompt stays within token_budget.

    Leaves headroom for the prompt template and expected output tokens.
    """
    available = token_budget - reserve_for_prompt - reserve_for_output
    char_limit = max(2000, available * 4)
    return trim_to_chars(context, char_limit)


# ── BM25 scoring ──────────────────────────────────────────────────────────────


def bm25_score(
    query_terms: list[str],
    doc_term_counts: Counter,
    doc_length: int,
    df: dict[str, int],
    num_docs: int,
    avg_doc_len: float,
    *,
    k1: float = BM25_K1,
    b: float = BM25_B,
) -> float:
    """Okapi BM25 score for a single document field.

    Uses Robertson IDF — always non-negative even for very common terms.

    Args:
        query_terms:      Tokenised query (after stopword removal).
        doc_term_counts:  Counter of {term: frequency} for the document field.
        doc_length:       Total token count for this field in this document.
        df:               {term: document_frequency} across the whole corpus.
        num_docs:         Total number of indexed documents.
        avg_doc_len:      Corpus-average token count for this field.
        k1:               TF saturation (default 1.5).
        b:                Length normalisation (default 0.75).

    Returns:
        Non-negative float; higher = more relevant.
    """
    if num_docs == 0 or avg_doc_len == 0:
        return 0.0
    score = 0.0
    for term in set(query_terms):
        tf = doc_term_counts.get(term, 0)
        if tf == 0:
            continue
        n_docs_with_term = df.get(term, 0)
        if n_docs_with_term == 0:
            continue
        # Robertson IDF  — log((N - df + 0.5) / (df + 0.5) + 1)
        idf = log((num_docs - n_docs_with_term + 0.5) / (n_docs_with_term + 0.5) + 1)
        # Length-normalised TF
        tf_norm = (tf * (k1 + 1)) / (
            tf + k1 * (1.0 - b + b * doc_length / avg_doc_len)
        )
        score += idf * tf_norm
    return score


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    *,
    k: int = 60,
) -> list[tuple[str, float]]:
    """Fuse multiple ranked result lists without needing normalised scores.

    RRF score for document d: Σ_r 1 / (k + rank_r(d))

    k=60 is from Cormack et al. 2009.  Higher k → less sensitivity to top ranks.

    Args:
        ranked_lists:  Each inner list is a slug list ordered best-first.
        k:             Rank constant (default 60).

    Returns:
        List of (slug, rrf_score) sorted descending.
    """
    fusion: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, slug in enumerate(ranked, start=1):
            fusion[slug] = fusion.get(slug, 0.0) + 1.0 / (k + rank)
    return sorted(fusion.items(), key=lambda x: x[1], reverse=True)