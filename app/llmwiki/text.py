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
