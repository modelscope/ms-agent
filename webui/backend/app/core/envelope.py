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


_CHANGE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Successful writes under these prefixes must NOT broadcast: the presence poll
# would feed back into itself (every browser would refresh on every heartbeat),
# the chat stream/control own their own SSE, and recovery runs before the app is
# even usable. Everything else that mutates state notifies the open pages.
_NO_BROADCAST_PREFIXES = ("/api/presence", "/api/chat", "/api/recovery", "/api/events")


def _broadcast_change(request: Request, status: int) -> None:
    """Announce a successful management write so every open page can refresh.
    Carries the path and method; the frontend maps them to the lists to reload."""
    if request.method not in _CHANGE_METHODS or not (200 <= status < 300):
        return
    path = request.url.path
    if any(path.startswith(p) for p in _NO_BROADCAST_PREFIXES):
        return
    # Imported lazily so this core module stays free of app-package import order
    # concerns; publishing never blocks or raises.
    from app.core.events import event_bus
    event_bus.publish({"path": path, "method": request.method})


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
            _broadcast_change(request, status)
            return success_response(data, status_code=status)

        return custom


async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    message = detail if isinstance(detail, str) else "The request could not be processed."
    return error_response(exc.status_code, message, data=None)


def _field_label(loc: tuple[Any, ...]) -> str:
    """Turn a pydantic error location into a readable field name.

    Drops the request-part prefixes (``body``/``query``/``path``) and list
    indices, then title-cases the last snake_case segment: ``("body",
    "display_name")`` -> ``"Display name"``.
    """
    parts = [
        p for p in loc
        if p not in ("body", "query", "path") and not isinstance(p, int)
    ]
    if not parts:
        return "Value"
    words = str(parts[-1]).replace("_", " ").strip()
    return (words[:1].upper() + words[1:]) if words else "Value"


def _friendly_validation_message(err: dict[str, Any]) -> str:
    """Map a raw pydantic error into a business-facing English sentence.

    Pydantic's own ``msg`` (e.g. "String should have at most 80 characters")
    reads like a developer/library message. We rephrase it around the field and
    the constraint so it makes sense to an end user.
    """
    etype = err.get("type", "")
    ctx = err.get("ctx") or {}
    field = _field_label(tuple(err.get("loc", ())))
    if etype == "missing":
        return f"{field} is required."
    if etype == "string_too_short":
        n = ctx.get("min_length")
        return (f"{field} must be at least {n} characters."
                if n is not None else f"{field} is too short.")
    if etype == "string_too_long":
        n = ctx.get("max_length")
        return (f"{field} must be at most {n} characters."
                if n is not None else f"{field} is too long.")
    if etype == "too_short":
        n = ctx.get("min_length")
        return (f"{field} needs at least {n} items."
                if n is not None else f"{field} has too few items.")
    if etype == "too_long":
        n = ctx.get("max_length")
        return (f"{field} allows at most {n} items."
                if n is not None else f"{field} has too many items.")
    if etype == "string_pattern_mismatch":
        return f"{field} has an invalid format."
    if etype == "greater_than":
        return f"{field} must be greater than {ctx.get('gt')}."
    if etype == "greater_than_equal":
        return f"{field} must be at least {ctx.get('ge')}."
    if etype == "less_than":
        return f"{field} must be less than {ctx.get('lt')}."
    if etype == "less_than_equal":
        return f"{field} must be at most {ctx.get('le')}."
    if etype in ("int_parsing", "int_type", "float_parsing", "float_type",
                 "decimal_parsing"):
        return f"{field} must be a number."
    if etype in ("bool_parsing", "bool_type"):
        return f"{field} must be true or false."
    if etype == "string_type":
        return f"{field} must be text."
    if etype == "json_invalid":
        return "The request body is not valid JSON."
    if etype == "value_error":
        # Custom validator messages are already business-facing; pydantic just
        # prefixes them with "Value error, ".
        msg = str(err.get("msg", ""))
        cleaned = msg[len("Value error, "):] if msg.startswith(
            "Value error, ") else msg
        return cleaned or f"{field} is invalid."
    return f"{field} is invalid."


async def _validation_exception_handler(
        request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    message = "Please check your input and try again."
    if errors:
        message = _friendly_validation_message(errors[0])
    # Keep the raw error list in `data` for debugging / field-level UIs.
    return error_response(422, message, data=errors)


async def _unhandled_exception_handler(
        request: Request, exc: Exception) -> JSONResponse:
    return error_response(
        500, "Something went wrong on our side. Please try again.", data=None)


def register_exception_handlers(app: FastAPI) -> None:
    """Install envelope-shaped handlers for HTTP, validation, and crash errors."""
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError,
                              _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
