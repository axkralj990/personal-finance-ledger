from fastapi import APIRouter

from backend.app.api.accounts import router as accounts_router
from backend.app.api.assets import router as assets_router
from backend.app.api.dashboard import router as dashboard_router
from backend.app.api.imports import router as imports_router
from backend.app.api.portfolio import router as portfolio_router
from backend.app.api.reporting import router as reporting_router
from backend.app.api.tag_rules import router as tag_rules_router
from backend.app.api.tagging_models import router as tagging_models_router
from backend.app.api.taxonomy import router as taxonomy_router
from backend.app.api.transactions import router as transactions_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(assets_router)
api_router.include_router(portfolio_router)
api_router.include_router(dashboard_router)
api_router.include_router(accounts_router)
api_router.include_router(imports_router)
api_router.include_router(taxonomy_router)
api_router.include_router(tag_rules_router)
api_router.include_router(tagging_models_router)
api_router.include_router(transactions_router)
api_router.include_router(reporting_router)

__all__ = ["api_router"]
