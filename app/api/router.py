from fastapi import APIRouter

from app.api.routes.automation import router as automation_router
from app.api.routes.artifacts import router as artifacts_router
from app.api.routes.publishers import router as publishers_router
from app.api.routes.seo_assets import router as seo_assets_router
from app.api.routes.tasks import router as tasks_router
from app.api.routes.topic_manager import router as topic_manager_router
from app.api.routes.topics import router as topics_router

api_router = APIRouter()
api_router.include_router(topic_manager_router, tags=["topic-manager"])
api_router.include_router(automation_router, prefix="/automation", tags=["automation"])
api_router.include_router(topics_router, prefix="/topics", tags=["topics"])
api_router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
api_router.include_router(artifacts_router, prefix="/artifacts", tags=["artifacts"])
api_router.include_router(seo_assets_router, prefix="/seo-assets", tags=["seo-assets"])
api_router.include_router(publishers_router, prefix="/publisher", tags=["publisher"])
