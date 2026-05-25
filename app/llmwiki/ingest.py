from __future__ import annotations

from io import BytesIO
from typing import Any, TypedDict

from app.core.config import settings
from app.core.errors import KnowForgeError
from app.llmwiki.compaction import WikiCompactor
from app.llmwiki.groq import GroqClient
from app.llmwiki.prompts import COMPILE_PROMPT
from app.llmwiki.storage import WikiStore
from app.llmwiki.text import keyword_summary, slugify, trim_to_chars
from app.schemas.llmwiki import SourceUploadResponse


class CompileState(TypedDict, total=False):
    source_id: str
    filename: str
    raw_text: str
    clean_text: str
    payload: dict[str, Any]
    title: str
    summary: str
    tags: list[str]
    content: str


class SourceIngestor:
    def __init__(self, store: WikiStore, llm: GroqClient | None = None):
        self.store = store
        self.llm = llm or GroqClient()
        self.compactor = WikiCompactor(store, self.llm)

    async def ingest_pdf(
        self,
        *,
        filename: str,
        data: bytes,
        compile_wiki: bool = True,
    ) -> SourceUploadResponse:
        if not filename.lower().endswith(".pdf"):
            raise KnowForgeError(
                "Only PDF uploads are supported by this endpoint.",
                code="unsupported_file",
            )
        if len(data) > settings.max_pdf_upload_bytes:
            raise KnowForgeError("PDF upload limit is 5 MB.", status_code=413, code="pdf_too_large")
        text = self.extract_pdf_text(data)
        if not text.strip():
            raise KnowForgeError("Could not extract text from this PDF.", code="empty_pdf_text")
        source_id = self.store.source_id_for_bytes(filename, data)
        self.store.save_source(source_id, filename, data, text)
        page_slug = None
        if compile_wiki:
            page = await self.compile_source(source_id=source_id, filename=filename, text=text)
            page_slug = page.meta.slug
        return SourceUploadResponse(
            source_id=source_id,
            filename=filename,
            bytes_received=len(data),
            text_chars=len(text),
            wiki_page_slug=page_slug,
            message="PDF ingested and wiki updated." if page_slug else "PDF ingested.",
        )

    @staticmethod
    def extract_pdf_text(data: bytes) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise KnowForgeError(
                "PDF support is not installed.",
                code="pdf_dependency_missing",
            ) from exc
        try:
            reader = PdfReader(BytesIO(data))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise KnowForgeError("Invalid or unreadable PDF.", code="invalid_pdf") from exc

    async def compile_source(self, *, source_id: str, filename: str, text: str):
        state = await self._run_compile_graph(source_id=source_id, filename=filename, text=text)
        title = state["title"]
        summary = state["summary"]
        tags = state["tags"]
        content = state["content"]

        page = self.store.make_page(
            title=title,
            slug=slugify(title),
            summary=trim_to_chars(summary, 500),
            tags=tags,
            source_ids=[source_id],
            content=content,
            confidence="medium",
        )
        saved = self.store.upsert_page(page)
        await self.compactor.compact_if_needed(saved)
        return saved

    async def _run_compile_graph(self, *, source_id: str, filename: str, text: str) -> CompileState:
        from langgraph.graph import END, StateGraph

        graph = StateGraph(CompileState)
        graph.add_node("clean", self._clean_node)
        graph.add_node("llm_compile", self._llm_compile_node)
        graph.add_node("validate", self._validate_node)
        graph.set_entry_point("clean")
        graph.add_edge("clean", "llm_compile")
        graph.add_edge("llm_compile", "validate")
        graph.add_edge("validate", END)
        compiled = graph.compile()
        return await compiled.ainvoke(
            {
                "source_id": source_id,
                "filename": filename,
                "raw_text": text,
            }
        )

    async def _clean_node(self, state: CompileState) -> CompileState:
        state["clean_text"] = self._clean_extracted_text(state["raw_text"])
        return state

    async def _llm_compile_node(self, state: CompileState) -> CompileState:
        clean_text = state["clean_text"]
        if not self.llm.available:
            return state
        try:
            state["payload"] = await self.llm.generate_json(
                COMPILE_PROMPT.format(
                    source_id=state["source_id"],
                    filename=state["filename"],
                    source_text=trim_to_chars(clean_text, settings.wiki_context_char_budget),
                ),
                temperature=0.1,
            )
        except Exception:
            state["payload"] = {}
        return state

    async def _validate_node(self, state: CompileState) -> CompileState:
        payload = state.get("payload") or {}
        title = str(payload.get("title") or "").strip()
        summary = str(payload.get("summary") or "").strip()
        content = str(payload.get("content") or "").strip()
        tags = [str(tag).strip() for tag in payload.get("tags", []) if str(tag).strip()]

        if not title or not summary or len(content) < 400:
            title, summary, tags, content = self._local_compile(
                state["filename"],
                state["source_id"],
                state["clean_text"],
            )

        state["title"] = title
        state["summary"] = " ".join(summary.split())
        state["tags"] = tags[:12]
        state["content"] = content
        return state

    @staticmethod
    def _local_compile(filename: str, source_id: str, text: str) -> tuple[str, str, list[str], str]:
        title = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()
        cleaned = SourceIngestor._clean_extracted_text(text)
        sections = SourceIngestor._split_sections(cleaned)
        summary = SourceIngestor._summary_from_sections(sections, cleaned)
        section_blocks = []
        for section_title, lines in sections:
            if section_title.lower() == "summary":
                continue
            bullets = "\n".join(f"- {line}" for line in lines)
            section_blocks.append(f"## {section_title}\n\n{bullets}")
        compiled_sections = trim_to_chars("\n\n".join(section_blocks), 18_000)
        content = (
            f"# {title}\n\n"
            f"## Summary\n\n{summary}\n\n"
            f"{compiled_sections}\n\n"
            "## Source Evidence\n\n"
            f"- Compiled from [source:{source_id}]."
        )
        tags = SourceIngestor._infer_tags(title, cleaned)
        return title, summary, tags, content

    @staticmethod
    def _clean_extracted_text(text: str) -> str:
        lines = []
        previous_clean = ""
        for raw_line in text.replace("\x00", " ").splitlines():
            stripped = raw_line.strip()
            had_indent = raw_line[:1].isspace()
            had_bullet = stripped.startswith(("\x7f", "•", "-", "*"))
            line = " ".join(stripped.replace("\x7f", "-").replace("•", "-").split()).strip()
            line = line.lstrip("- ").strip() if had_bullet else line
            if not line or line == previous_clean:
                continue
            should_join = lines and SourceIngestor._should_join_with_previous(
                lines[-1],
                line,
                had_indent,
                had_bullet,
            )
            if should_join:
                lines[-1] = f"{lines[-1]} {line}"
                previous_clean = lines[-1]
                continue
            previous_clean = line
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _should_join_with_previous(
        previous: str,
        current: str,
        had_indent: bool,
        had_bullet: bool,
    ) -> bool:
        if had_bullet:
            return False
        if SourceIngestor._is_heading(previous) or SourceIngestor._is_heading(current):
            return False
        if SourceIngestor._looks_like_label(current):
            return False
        if "@" in current or "|" in current:
            return False
        if had_indent:
            return True
        if current[:1].islower():
            return True
        if ":" in previous and not previous.endswith((".", ":", ";", ")", "]")):
            return True
        return not previous.endswith((".", ":", ";", ")", "]")) and len(previous) > 60

    @staticmethod
    def _looks_like_label(line: str) -> bool:
        if ":" not in line:
            return False
        label = line.split(":", 1)[0]
        return 1 <= len(label.split()) <= 5 and len(label) <= 40

    @staticmethod
    def _meaningful_lines(text: str) -> list[str]:
        lines = []
        seen = set()
        for line in text.splitlines():
            normalized = line.casefold()
            if len(line) < 4 or normalized in seen:
                continue
            seen.add(normalized)
            lines.append(line)
        return lines

    @staticmethod
    def _split_sections(text: str) -> list[tuple[str, list[str]]]:
        headings = {
            "SUMMARY",
            "PROFILE",
            "CONTACT",
            "WORK EXPERIENCE",
            "EXPERIENCE",
            "SKILLS",
            "PROJECTS",
            "EDUCATION",
            "CERTIFICATIONS",
            "CERTIFICATION",
            "ACHIEVEMENTS",
        }
        sections: list[tuple[str, list[str]]] = []
        current_title = "Key Facts"
        current_lines: list[str] = []
        for line in SourceIngestor._meaningful_lines(text):
            if SourceIngestor._is_heading(line) and line.strip().upper() in headings:
                if current_lines:
                    sections.append((current_title, current_lines))
                current_title = line.title()
                current_lines = []
                continue
            current_lines.append(line.lstrip("- ").strip())
        if current_lines:
            sections.append((current_title, current_lines))
        return sections or [("Key Facts", SourceIngestor._meaningful_lines(text))]

    @staticmethod
    def _is_heading(line: str) -> bool:
        stripped = line.strip()
        return stripped.isupper() and len(stripped.split()) <= 4

    @staticmethod
    def _infer_tags(title: str, text: str) -> list[str]:
        tags = [slugify(part) for part in title.split()[:4]]
        lowered = text.lower()
        for keyword in ("resume", "ai", "ml", "rag", "fastapi", "langchain", "aws", "python"):
            if keyword in lowered and keyword not in tags:
                tags.append(keyword)
        return tags[:12]

    @staticmethod
    def _summary_from_sections(sections: list[tuple[str, list[str]]], text: str) -> str:
        for title, lines in sections:
            if title.lower() == "summary" and lines:
                return trim_to_chars(" ".join(lines[:4]), 700)
        return SourceIngestor._first_sentences(text, count=4)

    @staticmethod
    def _first_sentences(text: str, *, count: int) -> str:
        summary = keyword_summary(text, max_sentences=count)
        if summary:
            return summary
        lines = SourceIngestor._meaningful_lines(text)
        return "\n".join(lines[:count]) or "Source document imported into KnowForge."
