"""Exercise optional authentication through the real app, routes and storage."""
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.core.auth import COOKIE_NAME, SESSION_SECONDS
from app.core.settings import Settings, settings
from app.main import create_app

PASSWORD = "test-only-webui-password"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "ms_agent_webui_auth_enabled", True)
    monkeypatch.setattr(settings, "ms_agent_webui_username", "admin")
    monkeypatch.setattr(settings, "ms_agent_webui_password", SecretStr(PASSWORD))
    with TestClient(create_app()) as client:
        yield client


def login(client, **kwargs):
    return client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}, **kwargs)


def test_disabled_by_default_preserves_existing_api(monkeypatch):
    monkeypatch.setattr(settings, "ms_agent_webui_auth_enabled", False)
    with TestClient(create_app()) as client:
        assert client.get("/api/projects").status_code == 200
        assert client.get("/api/auth/status").json()["data"] == {
            "enabled": False, "authenticated": True, "username": None,
        }
        assert login(client).status_code == 400


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/projects"), ("POST", "/api/mcps"),
    ("GET", "/api/events"), ("POST", "/api/chat"),
    ("GET", "/api/projects/_default/workspace/files"),
    ("POST", "/api/recovery/default-project"),
    ("GET", "/docs"), ("GET", "/openapi.json"),
])
def test_anonymous_requests_are_rejected_before_dispatch(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.headers["x-ms-agent-auth-required"] == "1"
    assert response.headers["cache-control"] == "no-store"


def test_login_cookie_protects_real_crud_and_logout(client):
    assert client.get("/api/health").status_code == 200
    assert not client.get("/api/auth/status").json()["data"]["authenticated"]
    response = login(client)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert f"Max-Age={SESSION_SECONDS}" in cookie
    assert "Secure" not in cookie  # local HTTP works
    assert client.get("/api/auth/status").json()["data"]["username"] == "admin"
    project = client.post("/api/projects", json={"name": "auth-check", "memory_enabled": False})
    assert project.status_code == 201
    pid = project.json()["data"]["id"]
    session = client.post("/api/sessions", json={"project_id": pid, "title": "auth-check"})
    assert session.status_code == 201
    response = client.post("/api/chat/attach", json={"session_id": session.json()["data"]["id"]})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert '"done"' in response.text
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert COOKIE_NAME not in client.cookies
    assert client.get("/api/projects").status_code == 401


def test_wrong_credentials_and_guessing_limit(client):
    for i in range(10):
        response = client.post("/api/auth/login", json={
            "username": "wrong" if i % 2 else "admin", "password": "wrong",
        })
        assert response.status_code == 401
        assert "set-cookie" not in response.headers
    response = login(client)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


def test_forged_expired_and_old_credentials_do_not_authenticate(client, monkeypatch):
    assert login(client).status_code == 200
    token = client.cookies[COOKIE_NAME]
    client.cookies.clear()
    forged = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert client.get("/api/projects", headers={"Cookie": f"{COOKIE_NAME}={forged}"}).status_code == 401
    with patch("app.core.auth.time.time", return_value=time.time() + SESSION_SECONDS + 1):
        assert client.get("/api/projects", headers={"Cookie": f"{COOKIE_NAME}={token}"}).status_code == 401
    # A normal restart retains the seven-day login; a password change revokes it.
    with TestClient(create_app()) as restarted:
        assert restarted.get("/api/projects", headers={"Cookie": f"{COOKIE_NAME}={token}"}).status_code == 200
    monkeypatch.setattr(settings, "ms_agent_webui_password", SecretStr("changed-password"))
    with TestClient(create_app()) as changed:
        assert changed.get("/api/projects", headers={"Cookie": f"{COOKIE_NAME}={token}"}).status_code == 401


def test_browser_origins_and_tls_cookie(client):
    assert login(client, headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert login(client, headers={"Origin": "null"}).status_code == 403
    assert login(client, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    # A sibling subdomain is a different origin, and the cookie is SameSite=lax.
    assert login(client, headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
    assert login(client, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert login(client, headers={"Sec-Fetch-Site": "none"}).status_code == 200
    assert login(client, headers={"Origin": "http://localhost:5173"}).status_code == 200
    assert client.post("/api/auth/logout", headers={"Origin": "https://untrusted.example"}).status_code == 403
    # TLS can terminate at the public proxy while the backend uses loopback HTTP.
    response = login(client, headers={"Origin": "https://testserver"})
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


def test_cors_preflight_and_recovery_do_not_bypass_auth(client):
    response = client.options("/api/projects", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
    })
    assert response.status_code == 200
    assert client.post("/api/projects", json={"name": "denied"}).status_code == 401
    client.app.state.recovery.required = True
    assert client.get("/api/recovery").status_code == 401
    assert login(client).status_code == 200
    assert client.get("/api/recovery").status_code == 200
    assert client.get("/api/projects").status_code == 503


def test_enabled_configuration_fails_closed_without_password():
    with pytest.raises(ValidationError, match="MS_AGENT_WEBUI_PASSWORD"):
        Settings(_env_file=None, ms_agent_webui_auth_enabled=True, ms_agent_webui_password="")
    with pytest.raises(ValidationError, match="MS_AGENT_CORS_ORIGINS") as error:
        Settings(_env_file=None, ms_agent_webui_auth_enabled=True,
                 ms_agent_webui_password=PASSWORD, ms_agent_cors_origins="*")
    assert PASSWORD not in str(error.value)
