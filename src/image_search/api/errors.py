"""Consistent public errors and server-generated request IDs."""

import json
import logging
from uuid import uuid4

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError


def install_errors(app):
    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        if request.url.path.startswith("/v1/") and response.headers.get(
            "content-type", ""
        ).startswith("application/json"):
            raw = b"".join([chunk async for chunk in response.body_iterator])
            body = json.loads(raw)
            if isinstance(body, dict):
                body["request_id"] = request.state.request_id
            replacement = JSONResponse(body, status_code=response.status_code)
            replacement.raw_headers.extend(
                [
                    (k, v)
                    for k, v in response.raw_headers
                    if k not in (b"content-length", b"content-type")
                ]
            )
            response = replacement
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/v1/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def error_response(request, status, code, message, details=None, headers=None):
        return JSONResponse(
            status_code=status,
            headers=headers,
            content={
                "request_id": getattr(request.state, "request_id", str(uuid4())),
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": status in (429, 503, 504),
                    "details": details or [],
                },
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        detail = (
            error.detail
            if isinstance(error.detail, dict)
            else {"code": "REQUEST_FAILED", "message": str(error.detail)}
        )
        headers = dict(error.headers or {})
        if error.status_code == 429:
            headers["Retry-After"] = "60"
        response = error_response(
            request, error.status_code, detail["code"], detail["message"], headers=headers
        )
        if request.url.path == "/v1/auth/refresh" and error.status_code == 401:
            from image_search.api.v1.auth import clear_cookie

            clear_cookie(response, request.app.state.auth)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return error_response(
            request,
            422,
            "INVALID_REQUEST",
            "Dữ liệu nhập chưa hợp lệ.",
            [{"field": ".".join(map(str, e["loc"])), "reason": e["type"]} for e in error.errors()],
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        logging.getLogger(__name__).warning("Database error: %s", type(error).__name__)
        return error_response(request, 503, "DEPENDENCY_UNAVAILABLE", "Dịch vụ chưa sẵn sàng.")

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        logging.getLogger(__name__).error("Unhandled error: %s", type(error).__name__)
        response = error_response(
            request, 500, "INTERNAL_ERROR", "Có lỗi xảy ra. Vui lòng thử lại."
        )
        response.headers["X-Request-ID"] = request.state.request_id
        return response
