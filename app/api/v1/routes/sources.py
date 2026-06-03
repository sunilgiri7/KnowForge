from __future__ import annotations

import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, wiki_store_for_workspace, get_active_workspace_dep
from app.core.errors import KnowForgeError
from app.db.models import ResearchAnalysisJob, ResearchPaper, User, Workspace
from app.db.session import SessionLocal, get_db
from app.llmwiki.ingest import SourceIngestor
from app.llmwiki.temporal import SupersessionDetector, TemporalFactExtractor, WikiVersionLedger
from app.llmwiki.text import slugify
from app.schemas.llmwiki import SourceUploadResponse
from app.services.llm_factory import build_user_llm
from app.services.workspace import get_member, require_role

router = APIRouter(prefix="/sources", tags=["sources"])

_UPLOAD_JOBS: dict[str, dict[str, Any]] = {}
_UPLOAD_JOB_LIMIT = 200
# Keep heavyweight upload pipelines off the request event loop and avoid
# running multiple large PDF/LLM jobs in parallel inside one web process.
_UPLOAD_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowforge-upload")


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
    paper_id: str | None = None,
) -> bool:
    from app.llmwiki.research import ResearchPaperAnalyzer

    db = SessionLocal()
    try:
        if upload_id:
            _set_upload_job(upload_id, phase="research", message="Analyzing research metadata and claims...")
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            return False
        llm = build_user_llm(db, user)
        analyzer = ResearchPaperAnalyzer(db, llm=llm)
        return await analyzer.run_pipeline(
            workspace_id=workspace_id,
            filename=filename,
            text=text,
            slug=slug,
            file_path=file_path,
            force_research=force_research,
            paper_id=paper_id,
        )
    except Exception as e:
        print(f"[Research Ingest BG Error]: {e}")
        if upload_id:
            _set_upload_job(upload_id, research_error=str(e))
        if paper_id:
            _mark_research_job_failed(paper_id, str(e))
        return False
    finally:
        db.close()


def _mark_research_job_failed(paper_id: str, error: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(ResearchAnalysisJob).filter_by(paper_id=paper_id).first()
        if job:
            job.status = "failed"
            job.error_message = error[:1000]
            job.completed_at = datetime.now(UTC)
            db.commit()
    finally:
        db.close()


def _create_pending_research_paper(
    *,
    db: Session,
    workspace_id: str,
    filename: str,
    source_id: str,
    file_path: str | None,
) -> ResearchPaper:
    title = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()
    paper = ResearchPaper(
        workspace_id=workspace_id,
        title=title,
        authors=json.dumps([]),
        slug=slugify(source_id),
        file_path=file_path,
        abstract="Queued for research analysis.",
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)

    job = ResearchAnalysisJob(
        workspace_id=workspace_id,
        paper_id=paper.id,
        status="pending",
    )
    db.add(job)
    db.commit()
    return paper


def _run_upload_worker_sync(**kwargs: Any) -> None:
    asyncio.run(process_upload_bg(**kwargs))


def _schedule_upload_worker(**kwargs: Any) -> None:
    loop = asyncio.get_running_loop()
    loop.run_in_executor(_UPLOAD_EXECUTOR, partial(_run_upload_worker_sync, **kwargs))


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
    research_paper_id: str | None = None,
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
                source_path = str(store.source_dir(source_id) / filename)
                research_ok = await run_research_pipeline_bg(
                    workspace_id=workspace.id,
                    filename=filename,
                    text=text,
                    slug=page.meta.slug,
                    file_path=source_path,
                    user_id=user.id,
                    force_research=force_research,
                    upload_id=upload_id,
                    paper_id=research_paper_id,
                )
                if not research_ok:
                    raise RuntimeError("Research analysis failed. Check the paper job for details.")
        elif force_research:
            source_path = str(store.source_dir(source_id) / filename)
            _set_upload_job(upload_id, status="processing", phase="research", message="Analyzing research metadata and claims...")
            research_ok = await run_research_pipeline_bg(
                workspace_id=workspace.id,
                filename=filename,
                text=text,
                slug=slugify(source_id),
                file_path=source_path,
                user_id=user.id,
                force_research=force_research,
                upload_id=upload_id,
                paper_id=research_paper_id,
            )
            if not research_ok:
                raise RuntimeError("Research analysis failed. Check the paper job for details.")

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
        if research_paper_id:
            _mark_research_job_failed(research_paper_id, str(exc))
    finally:
        db.close()


@router.post("/upload", response_model=SourceUploadResponse)
async def upload_pdf(
    file: Annotated[UploadFile, File(...)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    compile_wiki: bool | None = None,
    force_research: bool = False,
) -> SourceUploadResponse:
    require_role(get_member(db, workspace_id=workspace.id, user_id=user.id), "editor")
    if not file.filename:
        raise KnowForgeError("Uploaded file must have a filename.", code="missing_filename")
    if not file.filename.lower().endswith(".pdf"):
        raise KnowForgeError("Only PDF uploads are supported by this endpoint.", code="unsupported_file")

    # Normal Wiki uploads compile a wiki page. Research-tab uploads should not
    # also compile Wiki by default; that doubles the work for large papers and
    # is the main reason Research processing can starve the web worker.
    if compile_wiki is None:
        compile_wiki = not force_research

    data = await file.read()
    from app.core.config import settings
    if len(data) > settings.max_pdf_upload_bytes:
        size_mb = settings.max_pdf_upload_bytes // (1024 * 1024)
        raise KnowForgeError(f"PDF upload limit is {size_mb} MB.", status_code=413, code="pdf_too_large")

    text = await asyncio.to_thread(SourceIngestor.extract_pdf_text, data)
    if not text.strip():
        raise KnowForgeError("Could not extract text from this PDF.", code="empty_pdf_text")

    store = wiki_store_for_workspace(workspace)
    source_id = store.source_id_for_bytes(file.filename, data)
    store.save_source(source_id, file.filename, data, text)
    research_paper_id = None
    if force_research:
        source_pdf_path = str(store.source_dir(source_id) / file.filename)
        paper = _create_pending_research_paper(
            db=db,
            workspace_id=workspace.id,
            filename=file.filename,
            source_id=source_id,
            file_path=source_pdf_path,
        )
        research_paper_id = paper.id

    upload_id = str(uuid.uuid4())
    initial_status = "processing" if compile_wiki or force_research else "completed"
    initial_message = "PDF saved. Processing has started." if initial_status == "processing" else "PDF ingested."
    _set_upload_job(
        upload_id,
        status=initial_status,
        phase="queued" if initial_status == "processing" else "done",
        filename=file.filename,
        source_id=source_id,
        bytes_received=len(data),
        text_chars=len(text),
        wiki_page_slug=None,
        message=initial_message,
    )

    if compile_wiki or force_research:
        _schedule_upload_worker(
            upload_id=upload_id,
            workspace_id=workspace.id,
            user_id=user.id,
            source_id=source_id,
            filename=file.filename,
            text=text,
            compile_wiki=compile_wiki,
            force_research=force_research,
            research_paper_id=research_paper_id,
        )

    return SourceUploadResponse(
        source_id=source_id,
        filename=file.filename,
        bytes_received=len(data),
        text_chars=len(text),
        wiki_page_slug=None,
        message=initial_message,
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
