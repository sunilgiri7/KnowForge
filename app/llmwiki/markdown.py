from __future__ import annotations

import json
from datetime import UTC, datetime

from app.schemas.llmwiki import WikiPage, WikiPageMeta

FRONTMATTER = "---"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_frontmatter(markdown: str) -> tuple[dict[str, object], str]:
    if not markdown.startswith(FRONTMATTER):
        return {}, markdown
    parts = markdown.split(FRONTMATTER, 2)
    if len(parts) < 3:
        return {}, markdown
    raw_meta = parts[1].strip()
    body = parts[2].lstrip()
    meta: dict[str, object] = {}
    for line in raw_meta.splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip()
        if value.startswith(("[", "{", '"')):
            try:
                meta[key.strip()] = json.loads(value)
                continue
            except json.JSONDecodeError:
                pass
        meta[key.strip()] = value
    return meta, body


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
    meta = WikiPageMeta.model_validate(raw_meta)
    return WikiPage(meta=meta, content=content)
