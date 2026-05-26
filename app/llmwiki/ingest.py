from __future__ import annotations

from io import BytesIO
from typing import Any, TypedDict

from app.core.config import settings
from app.core.errors import KnowForgeError
from app.llmwiki.compaction import WikiCompactor
from app.llmwiki.groq import GroqClient
from app.llmwiki.prompts import CHUNK_NOTES_PROMPT, COMPILE_PROMPT, SYNTHESIZE_WIKI_PROMPT
from app.llmwiki.storage import WikiStore
from app.llmwiki.text import keyword_summary, slugify, trim_to_chars
from app.schemas.llmwiki import SourceUploadResponse


class CompileState(TypedDict, total=False):
    source_id: str
    filename: str
    raw_text: str
    clean_text: str
    payload: dict[str, Any]
    chunk_notes: list[dict[str, Any]]
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
            size_mb = settings.max_pdf_upload_bytes // (1024 * 1024)
            raise KnowForgeError(
                f"PDF upload limit is {size_mb} MB.",
                status_code=413,
                code="pdf_too_large",
            )
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
            pages = []
            total_chars = 0
            for index, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                if not page_text.strip():
                    continue
                block = f"\n\n--- Page {index} ---\n\n{page_text}"
                pages.append(block)
                total_chars += len(block)
                if total_chars >= settings.pdf_extract_char_limit:
                    pages.append(
                        "\n\n[Extraction stopped: PDF text exceeded configured character limit.]"
                    )
                    break
            return "\n".join(pages)
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
        graph.add_node("chunk_notes", self._chunk_notes_node)
        graph.add_node("llm_compile", self._llm_compile_node)
        graph.add_node("validate", self._validate_node)
        graph.set_entry_point("clean")
        graph.add_edge("clean", "chunk_notes")
        graph.add_edge("chunk_notes", "llm_compile")
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

    async def _chunk_notes_node(self, state: CompileState) -> CompileState:
        clean_text = state["clean_text"]
        if not self.llm.available:
            state["chunk_notes"] = []
            return state
        notes: list[dict[str, Any]] = []
        chunks = self._chunk_document(clean_text)
        for index, chunk in enumerate(chunks, start=1):
            try:
                notes.append(
                    await self.llm.generate_json(
                        CHUNK_NOTES_PROMPT.format(
                            source_id=state["source_id"],
                            filename=state["filename"],
                            chunk_number=index,
                            chunk_text=chunk,
                        ),
                        temperature=0.05,
                    )
                )
            except Exception:
                notes.append(
                    {
                        "heading": f"Chunk {index}",
                        "document_type": "other",
                        "key_entities": [],
                        "facts": self._meaningful_lines(chunk)[:40],
                        "sections_seen": [],
                        "open_questions": ["LLM chunk extraction failed; local notes used."],
                    }
                )
        state["chunk_notes"] = notes
        return state

    async def _llm_compile_node(self, state: CompileState) -> CompileState:
        clean_text = state["clean_text"]
        if not self.llm.available:
            return state
        try:
            if state.get("chunk_notes"):
                state["payload"] = await self.llm.generate_json(
                    SYNTHESIZE_WIKI_PROMPT.format(
                        source_id=state["source_id"],
                        filename=state["filename"],
                        chunk_notes=state["chunk_notes"],
                        source_excerpt=self._representative_excerpt(clean_text),
                    ),
                    temperature=0.08,
                )
            else:
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

        if (
            not title
            or not summary
            or len(content) < 400
            or self._looks_like_weak_summary(summary)
        ):
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
    def _looks_like_weak_summary(summary: str) -> bool:
        words = [word for word in summary.replace(":", " ").split() if word.strip()]
        if len(words) < 8:
            return True
        generic = {"company", "for", "to", "in", "of", "the"}
        return len(set(word.lower().strip(".,") for word in words) - generic) < 4

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
        compiled_sections = trim_to_chars(
            "\n\n".join(section_blocks),
            max(18_000, settings.wiki_page_soft_char_limit - 5_000),
        )
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
            if stripped.startswith("--- Page ") and stripped.endswith("---"):
                if lines and lines[-1] != stripped:
                    lines.append(stripped)
                previous_clean = stripped
                continue
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
            "ABSTRACT",
            "INTRODUCTION",
            "BACKGROUND",
            "METHODOLOGY",
            "METHOD",
            "METHODS",
            "RESULTS",
            "DISCUSSION",
            "CONCLUSION",
            "LIMITATIONS",
            "REFERENCES",
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
            "EMPLOYMENT",
            "DUTIES",
            "COMPENSATION",
            "TERMINATION",
            "GOVERNING LAW",
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
        if stripped.startswith("--- Page ") and stripped.endswith("---"):
            return True
        if stripped.isupper() and len(stripped.split()) <= 6:
            return True
        if stripped[:2].isdigit() and len(stripped.split()) <= 8:
            return True
        return False

    @staticmethod
    def _infer_tags(title: str, text: str) -> list[str]:
        tags = [slugify(part) for part in title.split()[:4]]
        lowered = text.lower()
        for keyword in ("resume", "ai", "ml", "rag", "fastapi", "langchain", "aws", "python"):
            if keyword in lowered and keyword not in tags:
                tags.append(keyword)
        document_keywords = (
            "agreement",
            "employment",
            "termination",
            "compensation",
            "research",
            "paper",
        )
        for keyword in document_keywords:
            if keyword in lowered and keyword not in tags:
                tags.append(keyword)
        return tags[:12]

    @staticmethod
    def _chunk_document(text: str) -> list[str]:
        lines = text.splitlines()
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        limit = settings.wiki_compile_chunk_chars
        for line in lines:
            line_len = len(line) + 1
            boundary = SourceIngestor._is_heading(line) or line.startswith("--- Page ")
            if current and current_len + line_len > limit and boundary:
                chunks.append("\n".join(current).strip())
                current = []
                current_len = 0
            current.append(line)
            current_len += line_len
            if current_len >= limit * 1.25:
                chunks.append("\n".join(current).strip())
                current = []
                current_len = 0
        if current:
            chunks.append("\n".join(current).strip())
        if len(chunks) > settings.wiki_compile_max_chunks:
            head = chunks[: settings.wiki_compile_max_chunks // 2]
            tail = chunks[-(settings.wiki_compile_max_chunks - len(head)) :]
            chunks = head + tail
        return [chunk for chunk in chunks if chunk.strip()]

    @staticmethod
    def _representative_excerpt(text: str) -> str:
        chunks = SourceIngestor._chunk_document(text)
        if not chunks:
            return trim_to_chars(text, settings.wiki_context_char_budget)
        first = chunks[:2]
        last = chunks[-1:] if len(chunks) > 2 else []
        middle = [chunks[len(chunks) // 2]] if len(chunks) > 4 else []
        excerpt = "\n\n---\n\n".join(first + middle + last)
        return trim_to_chars(excerpt, settings.wiki_context_char_budget)

    @staticmethod
    def _summary_from_sections(sections: list[tuple[str, list[str]]], text: str) -> str:
        document_summary = SourceIngestor._document_specific_summary(text)
        if document_summary:
            return document_summary
        for title, lines in sections:
            if title.lower() == "summary" and lines:
                meaningful = [line for line in lines if SourceIngestor._is_summary_line(line)]
                if meaningful:
                    return trim_to_chars(" ".join(meaningful[:4]), 700)
        return SourceIngestor._first_sentences(text, count=4)

    @staticmethod
    def _first_sentences(text: str, *, count: int) -> str:
        cleaned = "\n".join(
            line
            for line in SourceIngestor._meaningful_lines(text)
            if SourceIngestor._is_summary_line(line)
        )
        summary = keyword_summary(cleaned, max_sentences=count)
        if summary:
            return summary
        lines = [
            line
            for line in SourceIngestor._meaningful_lines(text)
            if SourceIngestor._is_summary_line(line)
        ]
        return "\n".join(lines[:count]) or "Source document imported into KnowForge."

    @staticmethod
    def _is_summary_line(line: str) -> bool:
        stripped = line.strip()
        if len(stripped) < 30:
            return False
        if stripped.endswith(":"):
            return False
        if stripped.startswith(("Figure ", "Table ", "CIN:", "GSTIN:", "Tel:", "Sign")):
            return False
        return bool(any(char.isalpha() for char in stripped))

    @staticmethod
    def _document_specific_summary(text: str) -> str:
        lines = SourceIngestor._meaningful_lines(text)
        lowered = text.lower()
        if "employment agreement" in lowered:
            facts = SourceIngestor._find_lines(
                lines,
                [
                    "This Employment Agreement",
                    "effective from",
                    "gross annual payment",
                    "Senior Associate",
                    "90 days written notice",
                    "probation",
                    "Governing Law",
                ],
            )
            if facts:
                return trim_to_chars(" ".join(facts[:5]), 900)
        if "abstract" in lowered and ("arxiv" in lowered or "technical report" in lowered):
            facts = SourceIngestor._find_lines(
                lines,
                [
                    "Technical Report",
                    "We present",
                    "Abstract",
                    "parameters",
                    "training",
                    "outperforms",
                    "Conclusion",
                ],
            )
            if facts:
                return trim_to_chars(" ".join(facts[:6]), 900)
        return ""

    @staticmethod
    def _find_lines(lines: list[str], needles: list[str]) -> list[str]:
        found = []
        lowered_needles = [needle.lower() for needle in needles]
        for line in lines:
            lowered = line.lower()
            if (
                any(needle in lowered for needle in lowered_needles)
                and SourceIngestor._is_summary_line(line)
            ):
                found.append(line)
        return found
