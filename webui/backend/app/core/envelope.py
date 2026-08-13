"""Uniform API response envelope for all non-chat (RESTful CRUD) endpoints.

Every successful management response is wrapped as::

    {"code": 0, "message": "success", "data": <payload>}

and every error (HTTPException, validation error, or unhandled crash) as::

    {"code": <http_status>, "message": "<human readable>", "data": null}

HTTP status codes are preserved so REST semantics stay intact; the envelope
adds a stable, structured shape the frontend can rely on. The chat SSE stream
is intentionally excluded — it owns its own wire format.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException


def _envelope(data: Any = None, *, code: int = 0,
              message: str = "success") -> dict[str, Any]:
    return {"code": code, "message": message, "data": data}


def success_response(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(_envelope(data), status_code=status_code)


def error_response(status_code: int, message: str, *,
                   data: Any = None) -> JSONResponse:
    return JSONResponse(
        _envelope(data, code=status_code, message=message),
        status_code=status_code,
    )


class EnvelopeRoute(APIRoute):
    """Wraps a route's serialized success payload into the standard envelope.

    Runs after FastAPI has already validated/serialized the return value
    against `response_model`, so route signatures and validation are untouched.
    Errors raised inside the endpoint bypass this and are handled by the
    registered exception handlers below.
    """

    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def custom(request: Request) -> Response:
            response = await original(request)
            # Skip streaming or bodiless-by-design responses we can't buffer.
            raw = getattr(response, "body", None)
            if raw is None:
                return response
            media = response.headers.get("content-type", "")
            # Only unwrap JSON payloads. A 204 delete has an empty body and no
            # JSON content-type — treat it as `data: null`.
            if raw and "application/json" not in media:
                return response
            data = json.loads(raw) if raw else None
            # Preserve the RESTful status code (e.g. 201 Created). A 204 becomes
            # 200 since the envelope now carries a body.
            status = 200 if response.status_code == 204 else response.status_code
            return success_response(data, status_code=status)

        return custom


async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    message = detail if isinstance(detail, str) else "request failed"
    return error_response(exc.status_code, message, data=None)


async def _validation_exception_handler(
        request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    message = "validation error"
    if errors:
        first = errors[0]
        loc = ".".join(
            str(p) for p in first.get("loc", []) if p not in ("body", "query"))
        msg = first.get("msg", "validation error")
        message = f"{loc}: {msg}" if loc else msg
    # Keep the raw error list in `data` for debugging / field-level UIs.
    return error_response(422, message, data=errors)


async def _unhandled_exception_handler(
        request: Request, exc: Exception) -> JSONResponse:
    return error_response(500, "internal server error", data=None)


def register_exception_handlers(app: FastAPI) -> None:
    """Install envelope-shaped handlers for HTTP, validation, and crash errors."""
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError,
                              _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
