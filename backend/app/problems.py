import logging
import sqlite3
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException


class ProblemBody(BaseModel):
    code: str
    message: str
    field: str | None = None
    row: int | None = None
    recoverable: bool = False
    details: Any | None = None


class Problem(Exception):  # noqa: N818 - API problem is the domain term from RFC 9457.
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        field: str | None = None,
        row: int | None = None,
        recoverable: bool = False,
        details: Any | None = None,
    ) -> None:
        self.status_code = status_code
        self.body = ProblemBody(
            code=code,
            message=message,
            field=field,
            row=row,
            recoverable=recoverable,
            details=details,
        )
        super().__init__(message)


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def handle_problem(_request: Request, exc: Problem) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(exc.body))

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        serializable_errors = jsonable_encoder(
            errors,
            custom_encoder={ValueError: str},
        )
        location = errors[0].get("loc", ()) if errors else ()
        field = ".".join(str(part) for part in location[1:]) or None
        body = ProblemBody(
            code="validation_error",
            message="Request validation failed",
            field=field,
            recoverable=True,
            details=serializable_errors,
        )
        return JSONResponse(status_code=422, content=jsonable_encoder(body))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        body = ProblemBody(
            code="not_found" if exc.status_code == 404 else "http_error",
            message=str(exc.detail),
            recoverable=exc.status_code < 500,
        )
        return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(body))

    @app.exception_handler(OperationalError)
    async def handle_operational_error(request: Request, exc: OperationalError) -> JSONResponse:
        if isinstance(exc.orig, sqlite3.OperationalError) and "locked" in str(exc.orig).casefold():
            body = ProblemBody(
                code="database_busy",
                message="The database is temporarily busy; retry the request",
                recoverable=True,
            )
            return JSONResponse(status_code=503, content=jsonable_encoder(body))
        return await handle_unexpected(request, exc)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger(__name__).exception(
            "Unhandled API error for %s", request.url.path, exc_info=exc
        )
        body = ProblemBody(
            code="internal_error",
            message="An unexpected server error occurred",
            recoverable=True,
        )
        return JSONResponse(status_code=500, content=jsonable_encoder(body))
