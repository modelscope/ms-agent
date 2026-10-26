"""Optional single-user authentication shared by every HTTP entry point."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import deque
from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.envelope import error_response
from app.core.settings import Settings

COOKIE_NAME = "ms_agent_webui_session"
SESSION_SECONDS = 7 * 24 * 60 * 60
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_PUBLIC_ROUTES = {
    ("GET", "/api/health"),
    ("GET", "/api/auth/status"),
    ("POST", "/api/auth/login"),
}


class WebUIAuth:
    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.ms_agent_webui_auth_enabled
        self.username = settings.ms_agent_webui_username
        self._password = settings.ms_agent_webui_password.get_secret_value()
        # A stable, purpose-specific key keeps sessions valid across restarts.
        # Changing either configured credential invalidates existing sessions.
        self._key = hashlib.scrypt(
            self._password.encode(),
            salt=b"ms-agent-webui-session-v1\0" + self.username.encode(),
            n=16384, r=8, p=1,
        ) if self.enabled else b""
        self._failed_logins: deque[float] = deque(maxlen=10)

    def check_credentials(self, username: str, password: str) -> bool:
        user_ok = hmac.compare_digest(username.encode(), self.username.encode())
        password_ok = hmac.compare_digest(password.encode(), self._password.encode())
        return user_ok and password_ok

    def login_retry_after(self) -> int:
        """Bound password guessing for this single-user server, including proxies.

        Called by the async login handler without intervening awaits, so attempts
        are serialized on the API event loop. Existing sessions remain usable.
        """
        now = time.monotonic()
        while self._failed_logins and now - self._failed_logins[0] >= 60:
            self._failed_logins.popleft()
        if len(self._failed_logins) == self._failed_logins.maxlen:
            return max(1, int(60 - (now - self._failed_logins[0])) + 1)
        return 0

    def record_failed_login(self) -> None:
        self._failed_logins.append(time.monotonic())

    def issue_session(self) -> str:
        payload = f"{int(time.time()) + SESSION_SECONDS}.{secrets.token_hex(16)}"
        signature = hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def authenticated(self, request: Request) -> bool:
        if not self.enabled:
            return True
        token = request.cookies.get(COOKIE_NAME, "")
        if len(token) > 200 or not token.isascii():
            return False
        try:
            expires, nonce, signature = token.split(".")
            if not nonce or int(expires) <= time.time():
                return False
        except (ValueError, TypeError):
            return False
        expected = hmac.new(
            self._key, f"{expires}.{nonce}".encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)


def trusted_origin(request: Request, allowed_origins: list[str]) -> bool:
    """Cookies authenticate users; this separate check prevents cross-site writes.

    The proxy preserves the browser's Host. Compare it to Origin (including the
    port) rather than the internal loopback API address. Explicit CORS origins
    also support the documented development setup.
    """
    origin = request.headers.get("origin")
    if origin is None:
        return request.headers.get("sec-fetch-site") != "cross-site"
    if origin in allowed_origins:
        return True
    try:
        url = urlsplit(origin)
        return (
            url.scheme in {"http", "https"}
            and not url.username and not url.password
            and not url.path and not url.query and not url.fragment
            and url.netloc.lower() == request.headers.get("host", "").lower()
        )
    except ValueError:
        return False


class AuthMiddleware:
    """Check before dispatch, without reading or buffering uploads/SSE bodies."""

    def __init__(self, app: ASGIApp, auth: WebUIAuth, allowed_origins: list[str]) -> None:
        self.app = app
        self.auth = auth
        self.allowed_origins = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.auth.enabled:
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        if request.method in _WRITE_METHODS and not trusted_origin(request, self.allowed_origins):
            await error_response(403, "Request origin is not allowed.")(scope, receive, send)
            return
        if ((request.method, scope["path"]) not in _PUBLIC_ROUTES
                and not self.auth.authenticated(request)):
            response = error_response(401, "Sign in to continue.")
            response.headers["X-MS-Agent-Auth-Required"] = "1"
            response.headers["Cache-Control"] = "no-store"
            await response(scope, receive, send)
            return

        async def send_private(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_private)
