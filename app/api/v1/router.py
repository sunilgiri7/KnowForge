from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.chat import router as chat_router
from app.api.v1.routes.contradictions import router as contradictions_router
from app.api.v1.routes.llm_keys import router as llm_keys_router
from app.api.v1.routes.promotions import router as promotions_router
from app.api.v1.routes.reports import router as reports_router
from app.api.v1.routes.sources import router as sources_router
from app.api.v1.routes.versions import router as versions_router
from app.api.v1.routes.wiki import router as wiki_router
from app.api.v1.routes.workspaces import router as workspaces_router
from app.api.v1.routes.research import router as research_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(chat_router)
api_router.include_router(llm_keys_router)
api_router.include_router(sources_router)
api_router.include_router(wiki_router)
api_router.include_router(versions_router)
api_router.include_router(contradictions_router)
api_router.include_router(workspaces_router)
api_router.include_router(promotions_router)
api_router.include_router(reports_router)
api_router.include_router(research_router)
