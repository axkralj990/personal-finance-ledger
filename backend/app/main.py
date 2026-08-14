import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from backend.app.api import api_router
from backend.app.config import Settings, get_settings
from backend.app.database import Database
from backend.app.imports.lifecycle import UniversalImportService
from backend.app.imports.openai_mapping import OpenAIMappingBoundary
from backend.app.portfolio.market_data import MarketDataClient
from backend.app.problems import install_problem_handlers
from backend.app.sources.seed import seed_accounts
from backend.app.tagging.model_versions import reconcile_model_artifacts


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or get_settings()
    database = Database(configured.resolved_database_url)
    try:
        database.migrate()
        configured.data_dir.mkdir(parents=True, exist_ok=True)
        with database.session() as session:
            reconcile_model_artifacts(session, configured.data_dir)
            seed_accounts(session)
            UniversalImportService.recover_staging(session)
    except Exception:
        database.dispose()
        raise

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        database.dispose()

    application = FastAPI(title="Personal Finance API", version="1.0.0", lifespan=lifespan)
    application.state.settings = configured
    application.state.database = database
    application.state.market_data_client_factory = MarketDataClient
    application.state.openai_mapping_boundary_factory = OpenAIMappingBoundary
    application.state.portfolio_signing_key = secrets.token_bytes(32)
    write_lock = asyncio.Lock()
    application.state.sqlite_write_lock = write_lock

    @application.middleware("http")
    async def serialize_sqlite_writes(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        external_mapping_call = request.method == "POST" and request.url.path.endswith(
            "/mapping-suggestion"
        )
        serialized_method = request.method in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }
        if (
            database.engine.dialect.name != "sqlite"
            or external_mapping_call
            or not serialized_method
        ):
            return await call_next(request)
        async with write_lock:
            return await call_next(request)

    install_problem_handlers(application)
    application.include_router(api_router)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    _install_frontend(application, configured.frontend_dist_path)
    return application


def _install_frontend(application: FastAPI, dist_path: Path) -> None:
    if not dist_path.is_dir() or not (dist_path / "index.html").is_file():
        return
    resolved_dist = dist_path.resolve()

    @application.get("/{frontend_path:path}", include_in_schema=False)
    def frontend(frontend_path: str, request: Request) -> FileResponse:
        if request.url.path.startswith("/api/") or request.url.path == "/health":
            raise StarletteHTTPException(status_code=404)
        candidate = (resolved_dist / frontend_path).resolve()
        if candidate.is_relative_to(resolved_dist) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(resolved_dist / "index.html")
