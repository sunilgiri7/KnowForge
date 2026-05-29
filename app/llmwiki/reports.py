"""
reports.py — Grounded report generation pipeline.

Flow:
1. Load a ReportTemplate (column definitions, scope slugs).
2. For each page in scope, call LLM to extract the column values.
3. Assemble ExtractedRow objects.
4. Export as XLSX, DOCX, or PDF.
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ReportJob, ReportTemplate
from app.llmwiki.groq import GroqClient
from app.llmwiki.storage import WikiStore
from app.llmwiki.text import safe_format, trim_to_chars
from app.schemas.workspace import ExtractedCell, ExtractedRow, ReportColumnDef


# ---------------------------------------------------------------------------
# LLM Extraction Prompt
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """\
You are a structured data extractor. Given a wiki page and a list of extraction columns,
return a JSON object with one key per column (using the column key as the JSON key).

Each value should be an object with:
  - value: the extracted value as a string (or "" if not found)
  - confidence: float 0.0–1.0 (1.0 = explicit statement, 0.5 = inferred, 0.0 = not found)
  - quote: the exact sentence from the page that supports this value (or null)

Return ONLY the JSON. Do NOT invent information not present in the page.

Columns to extract:
{columns_spec}

Wiki page title: {title}
Wiki page content:
{content}
"""

KNOWLEDGE_EXTRACTION_PROMPT = """\
You are an intelligent knowledge base assistant. Answer the following questions/extraction columns using your own internal knowledge. Do NOT look up or expect any wiki documents.
Return a JSON object with one key per column (using the column key as the JSON key).

Each value should be an object with:
  - value: your answer as a string (or "" if you do not know)
  - confidence: float 0.0–1.0 (1.0 = highly certain, 0.5 = uncertain, 0.0 = completely unknown)
  - quote: null (since you are answering from your own knowledge)

Columns to answer:
{columns_spec}
"""


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class ReportExtractor:
    def __init__(self, store: WikiStore, llm: GroqClient | None = None):
        self.store = store
        self.llm = llm or GroqClient()

    async def extract_page(
        self,
        *,
        slug: str,
        columns: list[ReportColumnDef],
    ) -> ExtractedRow | None:
        try:
            page = self.store.read_page(slug)
        except Exception:
            return None

        columns_spec = "\n".join(
            f"- key={col.key}: {col.label}. Instruction: {col.instruction}"
            for col in columns
        )

        cells: dict[str, ExtractedCell] = {}

        if self.llm.available:
            try:
                raw = await self.llm.generate_json(
                    safe_format(
                        EXTRACTION_PROMPT,
                        columns_spec=columns_spec,
                        title=page.meta.title,
                        content=trim_to_chars(page.content, 8000),
                    ),
                    temperature=0.05,
                )
                for col in columns:
                    cell_raw = raw.get(col.key, {})
                    if isinstance(cell_raw, dict):
                        cells[col.key] = ExtractedCell(
                            value=str(cell_raw.get("value", "")),
                            confidence=float(cell_raw.get("confidence", 0.0)),
                            source_slug=slug,
                            quote=str(cell_raw.get("quote", "")) or None,
                        )
                    else:
                        cells[col.key] = ExtractedCell(value=str(cell_raw), source_slug=slug)
            except Exception:
                for col in columns:
                    cells[col.key] = ExtractedCell(value="", confidence=0.0, source_slug=slug)
        else:
            for col in columns:
                cells[col.key] = ExtractedCell(value="", confidence=0.0, source_slug=slug)

        return ExtractedRow(page_slug=slug, page_title=page.meta.title, cells=cells)

    async def extract_without_context(
        self,
        *,
        columns: list[ReportColumnDef],
    ) -> ExtractedRow:
        columns_spec = "\n".join(
            f"- key={col.key}: {col.label}. Instruction: {col.instruction}"
            for col in columns
        )

        cells: dict[str, ExtractedCell] = {}

        if self.llm.available:
            try:
                raw = await self.llm.generate_json(
                    safe_format(
                        KNOWLEDGE_EXTRACTION_PROMPT,
                        columns_spec=columns_spec,
                    ),
                    temperature=0.3,
                )
                for col in columns:
                    cell_raw = raw.get(col.key, {})
                    if isinstance(cell_raw, dict):
                        cells[col.key] = ExtractedCell(
                            value=str(cell_raw.get("value", "")),
                            confidence=float(cell_raw.get("confidence", 0.0)),
                            source_slug="llm_knowledge",
                            quote=None,
                        )
                    else:
                        cells[col.key] = ExtractedCell(value=str(cell_raw), source_slug="llm_knowledge")
            except Exception:
                for col in columns:
                    cells[col.key] = ExtractedCell(value="", confidence=0.0, source_slug="llm_knowledge")
        else:
            for col in columns:
                cells[col.key] = ExtractedCell(value="", confidence=0.0, source_slug="llm_knowledge")

        return ExtractedRow(page_slug="llm_knowledge", page_title="LLM Internal Knowledge", cells=cells)


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------


def export_xlsx(rows: list[ExtractedRow], columns: list[ReportColumnDef]) -> bytes:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Report"

    # Header row
    headers = ["Page", "Title"] + [col.label for col in columns]
    header_fill = PatternFill("solid", fgColor="1E293B")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(wrap_text=True, vertical="center")

    # Data rows
    for row_idx, row in enumerate(rows, start=2):
        ws.cell(row=row_idx, column=1, value=row.page_slug)
        ws.cell(row=row_idx, column=2, value=row.page_title)
        for col_idx, col in enumerate(columns, start=3):
            cell_data = row.cells.get(col.key)
            val = cell_data.value if cell_data else ""
            ws.cell(row=row_idx, column=col_idx, value=val)

        # Zebra stripe
        if row_idx % 2 == 0:
            fill = PatternFill("solid", fgColor="F8FAFC")
            for col_idx in range(1, len(headers) + 1):
                ws.cell(row=row_idx, column=col_idx).fill = fill

    # Auto-width
    for col_cells in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col_cells), default=10)
        ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 50)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_docx(
    rows: list[ExtractedRow],
    columns: list[ReportColumnDef],
    template_name: str = "Report",
) -> bytes:
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # Title
    title_para = doc.add_heading(template_name, level=1)
    title_para.alignment = WD_ALIGN_PARAGRAPH.LEFT

    doc.add_paragraph(f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    doc.add_paragraph("")

    # Table
    table = doc.add_table(rows=1, cols=len(columns) + 2)
    table.style = "Table Grid"

    # Header
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = "Page Slug"
    hdr_cells[1].text = "Title"
    for i, col in enumerate(columns):
        hdr_cells[i + 2].text = col.label
    for cell in hdr_cells:
        for para in cell.paragraphs:
            for run in para.runs:
                run.bold = True
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    # Data
    for row in rows:
        row_cells = table.add_row().cells
        row_cells[0].text = row.page_slug
        row_cells[1].text = row.page_title
        for i, col in enumerate(columns):
            cell_data = row.cells.get(col.key)
            row_cells[i + 2].text = cell_data.value if cell_data else ""

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def export_pdf(
    rows: list[ExtractedRow],
    columns: list[ReportColumnDef],
    template_name: str = "Report",
) -> bytes:
    import weasyprint

    col_headers = "".join(f"<th>{col.label}</th>" for col in columns)
    data_rows_html = ""
    for row in rows:
        cells_html = "".join(
            f"<td>{row.cells.get(col.key, ExtractedCell(value='')).value}</td>"
            for col in columns
        )
        data_rows_html += f"<tr><td>{row.page_slug}</td><td>{row.page_title}</td>{cells_html}</tr>"

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 11px; color: #1e293b; margin: 20px; }}
  h1 {{ color: #6366f1; font-size: 20px; margin-bottom: 4px; }}
  p.meta {{ color: #64748b; font-size: 10px; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ background: #1e293b; color: #fff; padding: 6px 8px; text-align: left; font-size: 10px; }}
  td {{ border: 1px solid #e2e8f0; padding: 5px 8px; vertical-align: top; }}
  tr:nth-child(even) td {{ background: #f8fafc; }}
</style>
</head>
<body>
<h1>{template_name}</h1>
<p class="meta">Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}</p>
<table>
  <thead><tr><th>Page</th><th>Title</th>{col_headers}</tr></thead>
  <tbody>{data_rows_html}</tbody>
</table>
</body>
</html>"""

    return weasyprint.HTML(string=html).write_pdf()


# ---------------------------------------------------------------------------
# Job Runner
# ---------------------------------------------------------------------------


class ReportRunner:
    def __init__(self, db: Session, store: WikiStore, llm: GroqClient | None = None):
        self.db = db
        self.store = store
        self.llm = llm or GroqClient()

    async def run(self, job: ReportJob) -> ReportJob:
        job.status = "processing"
        self.db.commit()

        try:
            template = self.db.get(ReportTemplate, job.template_id)
            if not template:
                raise ValueError(f"Template {job.template_id} not found")

            columns = [ReportColumnDef(**c) for c in json.loads(template.columns_json)]
            scope_slugs = json.loads(template.scope_slugs_json or "[]")

            extractor = ReportExtractor(self.store, self.llm)
            rows: list[ExtractedRow] = []
            if scope_slugs:
                for slug in scope_slugs:
                    row = await extractor.extract_page(slug=slug, columns=columns)
                    if row:
                        rows.append(row)
            else:
                row = await extractor.extract_without_context(columns=columns)
                rows.append(row)

            job.results_json = json.dumps([r.model_dump() for r in rows])

            # Export
            fmt = job.export_format
            export_name = f"report_{job.id[:8]}.{fmt}"
            export_dir = self.store.root / "reports"
            export_dir.mkdir(parents=True, exist_ok=True)
            export_path = export_dir / export_name

            if fmt == "xlsx":
                export_path.write_bytes(export_xlsx(rows, columns))
            elif fmt == "docx":
                export_path.write_bytes(export_docx(rows, columns, template.name))
            elif fmt == "pdf":
                export_path.write_bytes(export_pdf(rows, columns, template.name))

            job.file_path = str(export_path)
            job.status = "done"
            job.completed_at = datetime.now(UTC)

        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(UTC)

        self.db.commit()
        return job

    def create_job(
        self,
        *,
        workspace_id: str,
        template_id: str,
        export_format: str,
        created_by: str | None = None,
    ) -> ReportJob:
        job = ReportJob(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            template_id=template_id,
            export_format=export_format,
            created_by=created_by,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job
