from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import get_current_user, wiki_store_for_user
from app.core.errors import KnowForgeError
from app.db.models import User
from app.llmwiki.ingest import SourceIngestor
from app.schemas.llmwiki import SourceUploadResponse

router = APIRouter(prefix="/sources", tags=["sources"])


@router.post("/upload", response_model=SourceUploadResponse)
async def upload_pdf(
    file: Annotated[UploadFile, File(...)],
    user: Annotated[User, Depends(get_current_user)],
    compile_wiki: bool = True,
) -> SourceUploadResponse:
    if not file.filename:
        raise KnowForgeError("Uploaded file must have a filename.", code="missing_filename")
    data = await file.read()
    return await SourceIngestor(wiki_store_for_user(user)).ingest_pdf(
        filename=file.filename,
        data=data,
        compile_wiki=compile_wiki,
    )
