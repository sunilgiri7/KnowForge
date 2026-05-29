"""
routes/reports.py — Report template CRUD + generate + download.

Fixes:
  - Added GET /reports (list all jobs for workspace)
  - BackgroundTask uses its own independent DB session (not the request session)
  - GroqClient uses user's stored LLM key via db lookup
  - Proper error propagation to job.error_message
"""
from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_active_workspace_dep, get_current_user, wiki_store_for_workspace
from app.core.errors import KnowForgeError
from app.db.models import ReportJob, ReportTemplate, User, Workspace
from app.db.session import SessionLocal, get_db
from app.llmwiki.groq import GroqClient
from app.llmwiki.reports import ReportRunner
from app.schemas.workspace import (
    ExtractedRow,
    ReportGenerateRequest,
    ReportJobOut,
    ReportTemplateCreate,
    ReportTemplateOut,
)
from app.services.llm_keys import get_user_llm_key_plaintext, get_user_llm_model
from app.services.workspace import get_member, require_role

router = APIRouter(prefix="/reports", tags=["reports"])

CONTENT_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


def _template_out(t: ReportTemplate) -> ReportTemplateOut:
    from app.schemas.workspace import ReportColumnDef, ReportSectionDef
    return ReportTemplateOut(
        id=t.id,
        name=t.name,
        description=t.description,
        columns=[ReportColumnDef(**c) for c in json.loads(t.columns_json or "[]")],
        sections=[ReportSectionDef(**s) for s in json.loads(t.sections_json or "[]")],
        scope_slugs=json.loads(t.scope_slugs_json or "[]"),
        created_at=t.created_at,
    )


def _job_out(j: ReportJob, template_name: str | None = None) -> ReportJobOut:
    results = None
    if j.results_json:
        try:
            results = [ExtractedRow(**r) for r in json.loads(j.results_json)]
        except Exception:
            results = None
    return ReportJobOut(
        id=j.id,
        template_id=j.template_id,
        template_name=template_name,
        status=j.status,  # type: ignore[arg-type]
        export_format=j.export_format,  # type: ignore[arg-type]
        results=results,
        error_message=j.error_message,
        file_path=j.file_path,
        created_at=j.created_at,
        completed_at=j.completed_at,
    )


def _get_user_llm_client(db: Session, user_id: str) -> GroqClient:
    """Get a GroqClient using the user's stored API key (any provider)."""
    from app.db.models import User
    user = db.get(User, user_id)
    if not user:
        return GroqClient()
    provider = user.llm_active_provider or "groq"
    api_key = get_user_llm_key_plaintext(db, user=user, provider=provider)
    model = get_user_llm_model(db, user=user, provider=provider)
    if api_key:
        return GroqClient(api_key=api_key, model=model or None)
    return GroqClient()


async def _run_job_in_background(
    job_id: str,
    workspace_id: str,
    user_id: str,
) -> None:
    """
    Background task: creates its own independent DB session so it doesn't
    share the request's session (which is closed after response is sent).
    """
    db = SessionLocal()
    try:
        job = db.get(ReportJob, job_id)
        if not job:
            return
        workspace = db.get(Workspace, workspace_id)
        if not workspace:
            return

        from app.api.deps import wiki_store_for_workspace as _store_for_ws
        store = _store_for_ws(workspace)
        llm = _get_user_llm_client(db, user_id)
        runner = ReportRunner(db, store, llm)
        await runner.run(job)
    except Exception as exc:
        # Last-ditch: mark the job as failed
        try:
            job = db.get(ReportJob, job_id)
            if job and job.status not in ("done", "failed"):
                from datetime import UTC, datetime
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@router.post("/templates", response_model=ReportTemplateOut, status_code=201)
def create_template(
    payload: ReportTemplateCreate,
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> ReportTemplateOut:
    member = get_member(db, workspace_id=workspace.id, user_id=user.id)
    require_role(member, "editor")

    template = ReportTemplate(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name=payload.name,
        description=payload.description,
        columns_json=json.dumps([c.model_dump() for c in payload.columns]),
        sections_json=json.dumps([s.model_dump() for s in payload.sections]),
        scope_slugs_json=json.dumps(payload.scope_slugs),
        created_by=user.id,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return _template_out(template)


@router.get("/templates", response_model=list[ReportTemplateOut])
def list_templates(
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ReportTemplateOut]:
    member = get_member(db, workspace_id=workspace.id, user_id=user.id)
    require_role(member, "viewer")
    templates = (
        db.query(ReportTemplate)
        .filter_by(workspace_id=workspace.id)
        .order_by(ReportTemplate.created_at.desc())
        .all()
    )
    return [_template_out(t) for t in templates]


@router.delete("/templates/{template_id}", response_model=dict)
def delete_template(
    template_id: str,
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    member = get_member(db, workspace_id=workspace.id, user_id=user.id)
    require_role(member, "editor")
    template = db.get(ReportTemplate, template_id)
    if not template or template.workspace_id != workspace.id:
        raise KnowForgeError("Template not found.", status_code=404, code="template_not_found")
    db.delete(template)
    db.commit()
    return {"deleted": True}


@router.put("/templates/{template_id}", response_model=ReportTemplateOut)
def update_template(
    template_id: str,
    payload: ReportTemplateCreate,
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> ReportTemplateOut:
    member = get_member(db, workspace_id=workspace.id, user_id=user.id)
    require_role(member, "editor")
    template = db.get(ReportTemplate, template_id)
    if not template or template.workspace_id != workspace.id:
        raise KnowForgeError("Template not found.", status_code=404, code="template_not_found")
    
    template.name = payload.name
    template.description = payload.description
    template.columns_json = json.dumps([c.model_dump() for c in payload.columns])
    template.sections_json = json.dumps([s.model_dump() for s in payload.sections])
    template.scope_slugs_json = json.dumps(payload.scope_slugs)
    db.commit()
    db.refresh(template)
    return _template_out(template)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ReportJobOut])
def list_jobs(
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ReportJobOut]:
    """List all report jobs for the active workspace (newest first)."""
    member = get_member(db, workspace_id=workspace.id, user_id=user.id)
    require_role(member, "viewer")
    jobs = (
        db.query(ReportJob)
        .filter_by(workspace_id=workspace.id)
        .order_by(ReportJob.created_at.desc())
        .limit(50)
        .all()
    )
    results = []
    for j in jobs:
        template_name = None
        if j.template:
            template_name = j.template.name
        results.append(_job_out(j, template_name))
    return results


@router.post("/generate", response_model=ReportJobOut, status_code=202)
async def generate_report(
    payload: ReportGenerateRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> ReportJobOut:
    member = get_member(db, workspace_id=workspace.id, user_id=user.id)
    require_role(member, "editor")

    template = db.get(ReportTemplate, payload.template_id)
    if not template or template.workspace_id != workspace.id:
        raise KnowForgeError("Template not found.", status_code=404, code="template_not_found")

    # Override scope slugs for this run if provided
    if payload.scope_slugs:
        template_scope = json.dumps(payload.scope_slugs)
    else:
        template_scope = template.scope_slugs_json

    # Create the job record
    job = ReportJob(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        template_id=payload.template_id,
        export_format=payload.export_format,
        created_by=user.id,
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Schedule background processing with its OWN db session
    background_tasks.add_task(
        _run_job_in_background,
        job.id,
        workspace.id,
        user.id,
    )

    return _job_out(job, template.name)


@router.get("/{job_id}", response_model=ReportJobOut)
def get_job(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> ReportJobOut:
    member = get_member(db, workspace_id=workspace.id, user_id=user.id)
    require_role(member, "viewer")
    job = db.get(ReportJob, job_id)
    if not job or job.workspace_id != workspace.id:
        raise KnowForgeError("Job not found.", status_code=404, code="job_not_found")
    template_name = job.template.name if job.template else None
    return _job_out(job, template_name)


@router.get("/{job_id}/download")
def download_report(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_active_workspace_dep)],
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    member = get_member(db, workspace_id=workspace.id, user_id=user.id)
    require_role(member, "viewer")
    job = db.get(ReportJob, job_id)
    if not job or job.workspace_id != workspace.id:
        raise KnowForgeError("Job not found.", status_code=404, code="job_not_found")
    if job.status != "done" or not job.file_path:
        raise KnowForgeError("Report is not ready yet.", status_code=409, code="report_not_ready")

    import os
    if not os.path.exists(job.file_path):
        raise KnowForgeError("Report file not found on disk.", status_code=404, code="file_missing")

    fmt = job.export_format
    return FileResponse(
        path=job.file_path,
        media_type=CONTENT_TYPES.get(fmt, "application/octet-stream"),
        filename=f"report_{job_id[:8]}.{fmt}",
    )
