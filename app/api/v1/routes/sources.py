from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, wiki_store_for_workspace, get_active_workspace_dep
from app.core.errors import KnowForgeError
from app.db.models import User, Workspace
from app.db.session import get_db
from app.llmwiki.ingest import SourceIngestor
from app.llmwiki.temporal import SupersessionDetector, TemporalFactExtractor, WikiVersionLedger
from app.schemas.llmwiki import SourceUploadResponse
from app.services.llm_factory import build_user_llm
from app.services.workspace import get_member, require_role

router = APIRouter(prefix="/sources", tags=["sources"])


async def run_research_pipeline_bg(
    workspace_id: str,
    filename: str,
    text: str,
    slug: str,
    file_path: str | None,
    user_id: str,
    force_research: bool = False
):
    from app.db.session import SessionLocal
    from app.llmwiki.research import ResearchPaperAnalyzer
    from app.db.models import User
    from app.services.llm_factory import build_user_llm

    db = SessionLocal()
    try:
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
            force_research=force_research
        )
    except Exception as e:
        print(f"[Research Ingest BG Error]: {e}")
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
    data = await file.read()
    store = wiki_store_for_workspace(workspace)
    existing_pages = [store.read_page(item.slug) for item in store.list_pages()]
    response = await SourceIngestor(store).ingest_pdf(
        filename=file.filename,
        data=data,
        compile_wiki=compile_wiki,
    )
    if response.wiki_page_slug:
        page = store.read_page(response.wiki_page_slug)
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
        llm = build_user_llm(db, user)
        await TemporalFactExtractor(db, llm=llm).extract_and_store(
            page=page,
            workspace_id=workspace.id,
        )

        # Trigger Research Paper Ingest pipeline (Phase 2)
        import asyncio
        source_path = str(store.page_path(response.wiki_page_slug))
        asyncio.create_task(
            run_research_pipeline_bg(
                workspace_id=workspace.id,
                filename=file.filename,
                text=page.content,
                slug=page.meta.slug,
                file_path=source_path,
                user_id=user.id,
                force_research=force_research
            )
        )

    return response
