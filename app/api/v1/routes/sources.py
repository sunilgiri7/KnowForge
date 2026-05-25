from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.core.errors import KnowForgeError
from app.llmwiki.ingest import SourceIngestor
from app.llmwiki.storage import WikiStore
from app.schemas.llmwiki import SourceUploadResponse

router = APIRouter(prefix="/sources", tags=["sources"])


@router.post("/upload", response_model=SourceUploadResponse)
async def upload_pdf(
    file: Annotated[UploadFile, File(...)],
    compile_wiki: bool = True,
) -> SourceUploadResponse:
    if not file.filename:
        raise KnowForgeError("Uploaded file must have a filename.", code="missing_filename")
    data = await file.read()
    return await SourceIngestor(WikiStore()).ingest_pdf(
        filename=file.filename,
        data=data,
        compile_wiki=compile_wiki,
    )
