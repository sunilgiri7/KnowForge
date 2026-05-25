from fastapi import APIRouter

from app.llmwiki.chat import ChatService
from app.llmwiki.storage import WikiStore
from app.schemas.llmwiki import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return await ChatService(WikiStore()).answer(request)
