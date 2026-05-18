from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from docforge.errors import DocforgeError
from docforge.logs import get_logger

log = get_logger(__name__)


def _body(code: str, message: str, details: object | None = None) -> dict[str, object]:
    error: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DocforgeError)
    async def domain_error(request: Request, exc: DocforgeError) -> JSONResponse:
        if exc.status_code >= 500:
            log.error("request.failed", path=request.url.path, error=exc.message)
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": [str(p) for p in error["loc"]], "message": error["msg"]} for error in exc.errors()]
        return JSONResponse(
            status_code=422, content=_body("invalid_request", "request validation failed", details)
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        log.exception("request.crashed", path=request.url.path)
        return JSONResponse(
            status_code=500, content=_body("internal_error", "something went wrong on our side")
        )
