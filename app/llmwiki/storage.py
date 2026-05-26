from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from threading import RLock

from app.core.config import settings
from app.core.errors import KnowForgeError
from app.llmwiki.markdown import now_iso, page_from_markdown, render_page
from app.llmwiki.text import slugify
from app.schemas.llmwiki import KnowledgeGapEvent, WikiPage, WikiPageListItem, WikiPageMeta


class WikiStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or settings.knowforge_storage_path)
        self.wiki_dir = self.root / "wiki"
        self.raw_dir = self.root / "raw"
        self.compact_dir = self.root / "compact"
        self.events_dir = self.root / "events"
        self.index_path = self.wiki_dir / "index.md"
        self._lock = RLock()
        self.ensure_ready()

    def for_user(self, user_id: str) -> WikiStore:
        return WikiStore(self.root / "users" / user_id)

    def ensure_ready(self) -> None:
        for path in (self.wiki_dir, self.raw_dir, self.compact_dir, self.events_dir):
            path.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._atomic_write(self.index_path, "# KnowForge Wiki Index\n\n")

    def page_path(self, slug: str) -> Path:
        clean_slug = slugify(slug)
        return self.wiki_dir / f"{clean_slug}.md"

    def compact_path(self, slug: str) -> Path:
        clean_slug = slugify(slug)
        return self.compact_dir / f"{clean_slug}.md"

    def source_dir(self, source_id: str) -> Path:
        path = self.raw_dir / source_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def source_id_for_bytes(self, filename: str, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()[:16]
        return f"{slugify(Path(filename).stem)}-{digest}"

    def list_pages(self) -> list[WikiPageListItem]:
        pages = []
        for path in sorted(self.wiki_dir.glob("*.md")):
            if path.name == "index.md":
                continue
            page = self.read_page(path.stem)
            pages.append(
                WikiPageListItem(
                    title=page.meta.title,
                    slug=page.meta.slug,
                    summary=page.meta.summary,
                    tags=page.meta.tags,
                    freshness=page.meta.freshness,
                    confidence=page.meta.confidence,
                    source_ids=page.meta.source_ids,
                )
            )
        return pages

    def read_page(self, slug: str, *, prefer_compact: bool = False) -> WikiPage:
        compact_path = self.compact_path(slug)
        path = compact_path if prefer_compact and compact_path.exists() else self.page_path(slug)
        if not path.exists():
            raise KnowForgeError(
                "Wiki page not found.",
                status_code=404,
                code="wiki_page_not_found",
            )
        return page_from_markdown(path.read_text(encoding="utf-8"), path.stem)

    def upsert_page(self, page: WikiPage) -> WikiPage:
        with self._lock:
            page.meta.slug = slugify(page.meta.slug)
            page.meta.last_compiled_at = page.meta.last_compiled_at or now_iso()
            self._atomic_write(self.page_path(page.meta.slug), render_page(page))
            self.rebuild_index()
            return page

    def save_source(self, source_id: str, filename: str, data: bytes, text: str) -> None:
        directory = self.source_dir(source_id)
        self._atomic_write_bytes(directory / filename, data)
        self._atomic_write(directory / "text.txt", text)
        self._atomic_write(
            directory / "metadata.json",
            json.dumps(
                {"source_id": source_id, "filename": filename, "text_chars": len(text)},
                indent=2,
            ),
        )

    def iter_sources(self) -> list[tuple[str, str]]:
        sources: list[tuple[str, str]] = []
        for path in sorted(self.raw_dir.glob("*/text.txt")):
            sources.append((path.parent.name, path.read_text(encoding="utf-8", errors="ignore")))
        return sources

    def append_gap_event(self, event: KnowledgeGapEvent) -> None:
        path = self.events_dir / "knowledge-gaps.jsonl"
        payload = event.model_dump()
        payload["created_at"] = now_iso()
        with self._lock:
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            self._atomic_write(path, existing + json.dumps(payload, ensure_ascii=False) + "\n")

    def rebuild_index(self) -> str:
        lines = ["# KnowForge Wiki Index", ""]
        for item in self.list_pages():
            aliases = ", ".join(item.tags)
            lines.append(
                "- "
                f"title: {item.title}; slug: {item.slug}; summary: {item.summary}; "
                f"tags: {aliases}; freshness: {item.freshness}; confidence: {item.confidence}; "
                f"sources: {', '.join(item.source_ids)}"
            )
        index = "\n".join(lines).strip() + "\n"
        self._atomic_write(self.index_path, index)
        return index

    def read_index(self) -> str:
        return self.index_path.read_text(encoding="utf-8")

    def make_page(
        self,
        *,
        title: str,
        content: str,
        slug: str | None = None,
        summary: str = "",
        tags: list[str] | None = None,
        source_ids: list[str] | None = None,
        confidence: str = "medium",
    ) -> WikiPage:
        clean_slug = slugify(slug or title)
        meta = WikiPageMeta(
            title=title,
            slug=clean_slug,
            summary=summary,
            tags=tags or [],
            source_ids=source_ids or [],
            confidence=confidence,
            last_compiled_at=now_iso(),
        )
        return WikiPage(meta=meta, content=content)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)

    @staticmethod
    def _atomic_write_bytes(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
