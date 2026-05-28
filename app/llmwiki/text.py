import re
from collections import Counter

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


# ── Prompt safe-formatting ────────────────────────────────────────────────────

def safe_format(template: str, **kwargs: object) -> str:
    """Format a prompt template safely.

    Unlike str.format(), this replaces {key} placeholders using simultaneous
    regex substitution so that:
      - { and } characters inside values never cause KeyError/ValueError
      - Values containing other {placeholder} patterns are treated as literals
      - Works correctly even when PDF text, wiki content, or code is embedded

    All values are converted to str before substitution.
    """
    if not kwargs:
        return template
    str_kwargs = {k: str(v) for k, v in kwargs.items()}
    # Build pattern that matches only the known keys in this template
    key_pattern = re.compile(
        r"\{(" + "|".join(re.escape(k) for k in str_kwargs) + r")\}"
    )
    return key_pattern.sub(lambda m: str_kwargs[m.group(1)], template)


# ── Context token budget helpers ─────────────────────────────────────────────

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

    Leaves headroom for the prompt template and expected output to prevent
    Groq rate-limit (429) errors on high-token requests.
    """
    available = token_budget - reserve_for_prompt - reserve_for_output
    char_limit = max(2000, available * 4)
    return trim_to_chars(context, char_limit)