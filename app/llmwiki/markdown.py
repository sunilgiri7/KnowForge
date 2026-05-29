from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from app.schemas.llmwiki import WikiPage, WikiPageMeta

FRONTMATTER = "---"

LIST_META_KEYS = frozenset({"tags", "source_ids", "aliases", "entities", "related_slugs"})
_JSON_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def coerce_meta_list(value: object) -> list[str]:
    """Normalize frontmatter list fields that may be list, broken JSON string, or scalar."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []
    text = value.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            extracted = [match.strip() for match in _JSON_STRING_RE.findall(text) if match.strip()]
            if extracted:
                return extracted
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return [text]


def _bracket_balance(fragment: str) -> int:
    return fragment.count("[") - fragment.count("]")


def _accumulate_json_value(lines: list[str], start_index: int, initial: str) -> tuple[str, int]:
    """Join continuation lines until JSON brackets/braces are balanced."""
    parts = [initial]
    balance = _bracket_balance(initial)
    if initial.startswith("{") or "{" in initial:
        balance += initial.count("{") - initial.count("}")
    index = start_index
    while index + 1 < len(lines):
        if balance <= 0:
            break
        index += 1
        next_line = lines[index]
        if re.match(r"^[A-Za-z_][\w-]*:\s", next_line) and balance <= 0:
            index -= 1
            break
        parts.append(next_line)
        balance = _bracket_balance("".join(parts))
        if "{" in initial or parts[0].strip().startswith("{"):
            joined = "".join(parts)
            balance += joined.count("{") - joined.count("}")
    return "\n".join(parts), index


def parse_frontmatter(markdown: str) -> tuple[dict[str, object], str]:
    if not markdown.startswith(FRONTMATTER):
        return {}, markdown
    parts = markdown.split(FRONTMATTER, 2)
    if len(parts) < 3:
        return {}, markdown
    raw_meta = parts[1].strip()
    body = parts[2].lstrip()
    meta: dict[str, object] = {}
    lines = raw_meta.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if ":" not in line:
            index += 1
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if value.startswith(("[", "{", '"')):
            needs_more = (
                (value.startswith("[") and _bracket_balance(value) > 0)
                or (value.startswith("{") and value.count("{") > value.count("}"))
            )
            if needs_more:
                value, index = _accumulate_json_value(lines, index, value)
            else:
                try:
                    meta[key] = json.loads(value)
                    index += 1
                    continue
                except json.JSONDecodeError:
                    pass
            try:
                meta[key] = json.loads(value)
                index += 1
                continue
            except json.JSONDecodeError:
                if key in LIST_META_KEYS:
                    meta[key] = coerce_meta_list(value)
                else:
                    meta[key] = value
                index += 1
                continue
        if key in LIST_META_KEYS:
            meta[key] = coerce_meta_list(value)
        else:
            meta[key] = value
        index += 1
    return meta, body


def normalize_meta_dict(raw_meta: dict[str, object]) -> dict[str, object]:
    normalized = dict(raw_meta)
    for key in LIST_META_KEYS:
        if key in normalized:
            normalized[key] = coerce_meta_list(normalized[key])
    return normalized


def render_page(page: WikiPage) -> str:
    meta = page.meta.model_dump()
    lines = [FRONTMATTER]
    for key, value in meta.items():
        if isinstance(value, list):
            rendered = json.dumps(value, ensure_ascii=False)
        elif value is None:
            rendered = ""
        elif isinstance(value, str):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = str(value)
        lines.append(f"{key}: {rendered}")
    lines.extend([FRONTMATTER, "", page.content.strip(), ""])
    return "\n".join(lines)


def page_from_markdown(markdown: str, fallback_slug: str) -> WikiPage:
    raw_meta, content = parse_frontmatter(markdown)
    raw_meta.setdefault("title", fallback_slug.replace("-", " ").title())
    raw_meta.setdefault("slug", fallback_slug)
    raw_meta = normalize_meta_dict(raw_meta)
    meta = WikiPageMeta.model_validate(raw_meta)
    return WikiPage(meta=meta, content=content)
