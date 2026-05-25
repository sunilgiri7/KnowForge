from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.api.v1.routes.chat import router as chat_router
from app.api.v1.routes.sources import router as sources_router
from app.api.v1.routes.wiki import router as wiki_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(chat_router)
api_router.include_router(sources_router)
api_router.include_router(wiki_router)
