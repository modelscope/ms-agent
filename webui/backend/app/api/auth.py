from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.auth import COOKIE_NAME, SESSION_SECONDS, WebUIAuth
from app.core.envelope import error_response, success_response

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=4096)


@router.get("/status")
async def status(request: Request):
    auth: WebUIAuth = request.app.state.auth
    authenticated = auth.authenticated(request)
    return success_response({
        "enabled": auth.enabled,
        "authenticated": authenticated,
        "username": auth.username if auth.enabled and authenticated else None,
    })


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    auth: WebUIAuth = request.app.state.auth
    if not auth.enabled:
        return error_response(400, "Authentication is not enabled.")
    retry_after = auth.login_retry_after()
    if retry_after:
        response = error_response(429, "Too many sign-in attempts. Try again in one minute.")
        response.headers["Retry-After"] = str(retry_after)
        return response
    if not auth.check_credentials(body.username, body.password):
        auth.record_failed_login()
        return error_response(401, "Incorrect username or password.")
    response = success_response(None)
    # Origin retains the public HTTPS scheme even behind a TLS-terminating proxy.
    secure = request.url.scheme == "https" or request.headers.get("origin", "").startswith("https://")
    response.set_cookie(
        COOKIE_NAME, auth.issue_session(), max_age=SESSION_SECONDS,
        httponly=True, secure=secure, samesite="lax", path="/",
    )
    return response


@router.post("/logout")
async def logout():
    response = success_response(None)
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
    return response
