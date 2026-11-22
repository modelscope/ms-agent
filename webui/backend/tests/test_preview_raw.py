"""Raw byte serving behind the document previews.

A previewed HTML file runs in an iframe on its own raw URL, so the browser —
not us — resolves its `./style.css`. That only works while the file's path is
the URL TAIL, which is what these tests pin down, together with the sandbox the
same route has to send for HTML.
"""
from app.backends.ms_agent import skills, workspace
from app.backends.ms_agent.bootstrap import bootstrap
from app.backends.ms_agent.projects import create_project
from app.core.filetypes import raw_headers
from app.schemas.project import ProjectCreate


def _new_project(name: str) -> str:
    bootstrap()
    return create_project(ProjectCreate(name=name)).id


def test_html_is_sandboxed_and_other_types_are_not():
    html = raw_headers("text/html")
    assert html["X-Content-Type-Options"] == "nosniff"
    assert html["Content-Security-Policy"].startswith("sandbox ")
    # Scripts have to survive: a preview without them is not the page.
    assert "allow-scripts" in html["Content-Security-Policy"]
    # Never `allow-same-origin` — that would hand the document our session.
    assert "allow-same-origin" not in html["Content-Security-Policy"]

    png = raw_headers("image/png")
    assert png["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" not in png
    assert "Content-Security-Policy" not in raw_headers(None)


def test_raw_route_puts_the_file_path_in_the_url_tail():
    from fastapi.testclient import TestClient

    from app.main import create_app

    pid = _new_project("ws-raw-url")
    workspace.save_upload(pid, "docs/page.html",
                          b"<link href='./style.css'>")
    workspace.save_upload(pid, "docs/style.css", b"body{color:red}")

    with TestClient(create_app()) as client:
        page = client.get(f"/api/projects/{pid}/workspace/raw/docs/page.html")
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert page.headers["content-security-policy"].startswith("sandbox ")

        # What the browser requests for `./style.css` while showing that page:
        # the last URL segment is replaced, nothing else.
        sibling = page.request.url.join("./style.css")
        assert client.get(str(sibling)).content == b"body{color:red}"


def test_raw_route_refuses_to_leave_the_workspace():
    from fastapi.testclient import TestClient

    from app.main import create_app

    pid = _new_project("ws-raw-escape")
    with TestClient(create_app()) as client:
        # Already-decoded traversal is normalised away by the client/router, so
        # send it encoded — the form that actually reaches the adapter.
        res = client.get(
            f"/api/projects/{pid}/workspace/raw/%2E%2E/%2E%2E/etc/hosts")
        assert res.status_code in (400, 404)


def test_skill_raw_rejects_traversal_and_unknown_skills():
    import pytest

    from app.backends.errors import BadRequest, NotFound

    with pytest.raises(BadRequest):
        skills.raw_skill_file("src::global::whatever", "../../etc/hosts")
    with pytest.raises(NotFound):
        skills.raw_skill_file("no-such-skill", "SKILL.md")
