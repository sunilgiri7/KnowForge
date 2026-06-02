from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, wiki_store_for_workspace, get_active_workspace_dep
from app.core.errors import KnowForgeError
from app.db.models import User, Workspace
from app.db.session import SessionLocal, get_db
from app.llmwiki.ingest import SourceIngestor
from app.llmwiki.temporal import SupersessionDetector, TemporalFactExtractor, WikiVersionLedger
from app.schemas.llmwiki import SourceUploadResponse
from app.services.llm_factory import build_user_llm
from app.services.workspace import get_member, require_role

router = APIRouter(prefix="/sources", tags=["sources"])

_UPLOAD_JOBS: dict[str, dict[str, Any]] = {}
_UPLOAD_JOB_LIMIT = 200


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _set_upload_job(upload_id: str, **updates: Any) -> None:
    job = _UPLOAD_JOBS.setdefault(upload_id, {"upload_id": upload_id, "created_at": _now_iso()})
    job.update(updates)
    job["updated_at"] = _now_iso()
    while len(_UPLOAD_JOBS) > _UPLOAD_JOB_LIMIT:
        oldest = sorted(_UPLOAD_JOBS.values(), key=lambda item: item.get("updated_at") or item.get("created_at") or "")[0]
        _UPLOAD_JOBS.pop(str(oldest.get("upload_id")), None)


async def run_research_pipeline_bg(
    workspace_id: str,
    filename: str,
    text: str,
    slug: str,
    file_path: str | None,
    user_id: str,
    force_research: bool = False,
    upload_id: str | None = None,
):
    from app.llmwiki.research import ResearchPaperAnalyzer

    db = SessionLocal()
    try:
        if upload_id:
            _set_upload_job(upload_id, phase="research", message="Analyzing research metadata and claims...")
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            return
        llm = build_user_llm(db, user)
        analyzer = ResearchPaperAnalyzer(db, llm=llm)
        await analyzer.run_pipeline(
            workspace_id=workspace_id,
            filename=filename,
            text=text,
            slug=slug,
            file_path=file_path,
            force_research=force_research,
        )
    except Exception as e:
        print(f"[Research Ingest BG Error]: {e}")
        if upload_id:
            _set_upload_job(upload_id, research_error=str(e))
    finally:
        db.close()


async def process_upload_bg(
    *,
    upload_id: str,
    workspace_id: str,
    user_id: str,
    source_id: str,
    filename: str,
    text: str,
    compile_wiki: bool,
    force_research: bool,
) -> None:
    db = SessionLocal()
    try:
        workspace = db.get(Workspace, workspace_id)
        user = db.get(User, user_id)
        if not workspace or not user:
            raise RuntimeError("Workspace or user no longer exists.")

        store = wiki_store_for_workspace(workspace)
        llm = build_user_llm(db, user)
        page_slug = None

        if compile_wiki:
            _set_upload_job(upload_id, status="processing", phase="wiki", message="Building wiki page from PDF...")
            existing_pages = [store.read_page(item.slug) for item in store.list_pages()]
            page = await SourceIngestor(store, llm=llm).compile_source(
                source_id=source_id,
                filename=filename,
                text=text,
            )
            page_slug = page.meta.slug
            _set_upload_job(
                upload_id,
                wiki_page_slug=page_slug,
                phase="versioning",
                message="Saving wiki version and checking freshness...",
            )

            ledger = WikiVersionLedger(db)
            ledger.record_version(
                page=page,
                workspace_id=workspace.id,
                created_by=user.id,
                created_reason="compilation",
            )
            detector = SupersessionDetector(db)
            old_slug = detector.find_superseded_page(
                new_page=page,
                workspace_id=workspace.id,
                existing_pages=existing_pages,
            )
            if old_slug:
                detector.record_supersession(
                    workspace_id=workspace.id,
                    old_slug=old_slug,
                    new_slug=page.meta.slug,
                    similarity=detector.best_score,
                )
                old_page = store.read_page(old_slug)
                old_page.meta.freshness = "superseded"
                store.upsert_page(old_page)
                old_record, _ = ledger.get_versions(workspace_id=workspace.id, slug=old_slug)
                if old_record:
                    old_record.status = "superseded"
            db.commit()

            _set_upload_job(upload_id, phase="facts", message="Extracting temporal facts...")
            await TemporalFactExtractor(db, llm=llm).extract_and_store(
                page=page,
                workspace_id=workspace.id,
            )

            if force_research:
                source_path = str(store.page_path(page_slug))
                await run_research_pipeline_bg(
                    workspace_id=workspace.id,
                    filename=filename,
                    text=page.content,
                    slug=page.meta.slug,
                    file_path=source_path,
                    user_id=user.id,
                    force_research=force_research,
                    upload_id=upload_id,
                )

        _set_upload_job(
            upload_id,
            status="completed",
            phase="done",
            wiki_page_slug=page_slug,
            message="Upload complete.",
            completed_at=_now_iso(),
        )
    except Exception as exc:
        print(f"[Upload BG Error]: {exc}")
        _set_upload_job(
            upload_id,
            status="failed",
            phase="failed",
            error=str(exc),
            message="Upload processing failed.",
            completed_at=_now_iso(),
        )
    finally:
        db.close()


@router.post("/upload", response_model=SourceUploadResponse)
async def upload_pdf(
    file: Annotated[UploadFile, File(...)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    compile_wiki: bool = True,
    force_research: bool = False,
) -> SourceUploadResponse:
    require_role(get_member(db, workspace_id=workspace.id, user_id=user.id), "editor")
    if not file.filename:
        raise KnowForgeError("Uploaded file must have a filename.", code="missing_filename")
    if not file.filename.lower().endswith(".pdf"):
        raise KnowForgeError("Only PDF uploads are supported by this endpoint.", code="unsupported_file")

    data = await file.read()
    from app.core.config import settings
    if len(data) > settings.max_pdf_upload_bytes:
        size_mb = settings.max_pdf_upload_bytes // (1024 * 1024)
        raise KnowForgeError(f"PDF upload limit is {size_mb} MB.", status_code=413, code="pdf_too_large")

    text = SourceIngestor.extract_pdf_text(data)
    if not text.strip():
        raise KnowForgeError("Could not extract text from this PDF.", code="empty_pdf_text")

    store = wiki_store_for_workspace(workspace)
    source_id = store.source_id_for_bytes(file.filename, data)
    store.save_source(source_id, file.filename, data, text)

    upload_id = str(uuid.uuid4())
    initial_status = "processing" if compile_wiki else "completed"
    _set_upload_job(
        upload_id,
        status=initial_status,
        phase="queued" if compile_wiki else "done",
        filename=file.filename,
        source_id=source_id,
        bytes_received=len(data),
        text_chars=len(text),
        wiki_page_slug=None,
        message="PDF saved. Wiki processing has started." if compile_wiki else "PDF ingested.",
    )

    if compile_wiki:
        asyncio.create_task(
            process_upload_bg(
                upload_id=upload_id,
                workspace_id=workspace.id,
                user_id=user.id,
                source_id=source_id,
                filename=file.filename,
                text=text,
                compile_wiki=compile_wiki,
                force_research=force_research,
            )
        )

    return SourceUploadResponse(
        source_id=source_id,
        filename=file.filename,
        bytes_received=len(data),
        text_chars=len(text),
        wiki_page_slug=None,
        message="PDF saved. Wiki processing has started." if compile_wiki else "PDF ingested.",
        status=initial_status,
        upload_id=upload_id,
    )


@router.get("/uploads/{upload_id}")
async def upload_status(
    upload_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    job = _UPLOAD_JOBS.get(upload_id)
    if not job:
        raise KnowForgeError("Upload job not found.", status_code=404, code="upload_job_not_found")
    return job
