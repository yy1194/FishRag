from __future__ import annotations

from fastapi import APIRouter

from fishrag_api.api.routes.agent import router as agent_router
from fishrag_api.api.routes.auth import router as auth_router
from fishrag_api.api.routes.documents import router as documents_router
from fishrag_api.api.routes.health import router as health_router
from fishrag_api.api.routes.memories import router as memories_router
from fishrag_api.api.routes.planning import router as planning_router
from fishrag_api.api.routes.rag import router as rag_router
from fishrag_api.api.routes.sessions import router as sessions_router

api_router = APIRouter()
api_router.include_router(agent_router)
api_router.include_router(auth_router)
api_router.include_router(documents_router)
api_router.include_router(health_router, tags=["health"])
api_router.include_router(memories_router)
api_router.include_router(planning_router)
api_router.include_router(rag_router)
api_router.include_router(sessions_router)
