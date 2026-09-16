"""Conversation exports preserve the replay model in safe Markdown and HTML."""
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app.backends.ms_agent.common import find_session
from app.backends.ms_agent.session_export import (
    ExportMetadata,
    render_html,
    render_markdown,
)
from app.core.settings import settings
from app.schemas.session import (
    SessionFile,
    SessionMessage,
    SessionPart,
    SessionStep,
    SessionTask,
)


def _metadata() -> ExportMetadata:
    return ExportMetadata(
        title="Export <test>",
        session_id="abc123",
        project_name="Demo",
        project_id="demo",
        model="provider/model",
        created_at="2026-09-15T10:00:00+00:00",
        updated_at="2026-09-15T10:01:00+00:00",
    )


def _messages() -> list[SessionMessage]:
    return [
        SessionMessage(
            role="user",
            content="Please render **this**.\n<script>alert('x')</script>",
            files=[
                SessionFile(
                    name="notes.txt",
                    path="user_files/notes.txt",
                    size=12,
                    exists=True,
                )
            ],
        ),
        SessionMessage(
            role="assistant",
            content="Final **answer**.",
            parts=[
                SessionPart(kind="thought", text="private thought", duration=2),
                SessionPart(
                    kind="tasks",
                    tasks=[
                        SessionTask(id="1", label="Inspect", status="done"),
                        SessionTask(id="2", label="Finish", status="pending"),
                    ],
                ),
                SessionPart(
                    kind="step",
                    step=SessionStep(
                        kind="terminal",
                        meta={
                            "tool": "shell",
                            "description": "Run command",
                            "arguments": {"command": "echo hi"},
                            "result": "</script><script>alert('tool')</script>",
                            "duration_ms": 1250,
                        },
                    ),
                ),
                SessionPart(
                    kind="step",
                    step=SessionStep(
                        kind="tool_call",
                        meta={
                            "tool": "shell_executor---shell_executor",
                            "status": "error",
                            "result": (
                                'Tool "shell_executor---shell_executor" is not '
                                "available. Use the exact tool name from the tool list."
                            ),
                            "error": (
                                'Tool "shell_executor---shell_executor" is not '
                                "available. Use the exact tool name from the tool list."
                            ),
                            "duration_ms": 0,
                        },
                    ),
                ),
                SessionPart(kind="text", text="Final **answer**."),
                SessionPart(kind="error", text="Recoverable failure"),
                SessionPart(kind="interrupted"),
            ],
            changed_files=["report.md"],
            duration_ms=2400,
        ),
    ]


def test_markdown_full_preserves_rich_transcript():
    output = render_markdown(_metadata(), _messages(), "full")

    assert output.startswith("# Export <test>\n")
    assert "## User" in output and "## Assistant" in output
    assert "user_files/notes.txt" in output
    assert "### Thought · 2s" in output
    assert "- [x] Inspect" in output
    assert "Tool · shell · Run command" in output
    assert '"command": "echo hi"' in output
    assert "Recoverable failure" in output
    assert "Interrupted" in output
    assert "report.md" in output
    assert "Turn duration: 2.4s" in output


def test_detail_levels_remove_private_and_operational_content():
    compact = render_markdown(_metadata(), _messages(), "compact")
    conversation_only = render_markdown(_metadata(), _messages(), "user-only")

    assert "private thought" not in compact
    assert '"command": "echo hi"' not in compact
    assert "Tool · shell · Run command" in compact
    assert "Final **answer**." in compact

    assert "private thought" not in conversation_only
    assert "Tool ·" not in conversation_only
    assert "Attachments" not in conversation_only
    assert "Changed files" not in conversation_only
    assert "Please render **this**." in conversation_only
    assert "Final **answer**." in conversation_only


def test_compact_error_step_stacks_error_below_header():
    output = render_html(_metadata(), _messages(), "compact")
    soup = BeautifulSoup(output, "html.parser")
    card = soup.select_one(".step.compact.error")

    assert card is not None
    direct_children = [child for child in card.children if getattr(child, "name", None)]
    assert [child.get("class") for child in direct_children] == [
        ["step-compact-header"],
        ["step-error"],
    ]
    assert card.select_one(".status-mark svg.status-glyph") is not None
    assert card.select_one(".step-kind").get_text(strip=True) == "Tool"
    assert card.select_one(".step-title").get_text(strip=True) == (
        "shell_executor---shell_executor"
    )
    assert card.select_one(".duration").get_text(strip=True) == "0.0s"
    assert "Use the exact tool name" in card.select_one(".step-error").get_text()
    assert ".step-compact-header {" in output
    assert ".step-error {" in output and "overflow-wrap: anywhere;" in output
    # The flex error layout must be scoped to the standalone turn error so it
    # never turns a tool error card into a side-by-side row (which pulled the
    # duration out of the shared right-aligned column).
    assert '.error[data-kind="error"] { display: flex' in output
    assert "\n.error { display: flex" not in output


def test_duplicate_error_result_is_rendered_once():
    html_output = render_html(_metadata(), _messages(), "full")
    markdown_output = render_markdown(_metadata(), _messages(), "full")
    soup = BeautifulSoup(html_output, "html.parser")
    error_card = soup.select_one(".step.error")

    assert [heading.get_text(strip=True) for heading in error_card.select("h4")] == [
        "Error"
    ]
    assert markdown_output.count("Use the exact tool name from the tool list.") == 1


def test_html_covers_all_step_families_and_mcp_source():
    kinds = [
        "terminal",
        "file_read",
        "file_write",
        "file_edit",
        "memory",
        "search",
        "browser",
        "skill_list",
        "skill_load",
        "authorization",
        "tool_call",
        "future_kind",
    ]
    parts = []
    for kind in kinds:
        source = "mcp" if kind == "tool_call" else "native"
        parts.append(
            SessionPart(
                kind="step",
                step=SessionStep(
                    kind=kind,
                    meta={
                        "tool": f"provider---{kind}_with_a_very_long_tool_name",
                        "source": source,
                        "arguments": {"path": "deep/path/value", "query": "x" * 240},
                        "result": {"ok": True, "content": "结果" * 300},
                        "duration_ms": 42,
                    },
                ),
            )
        )
    message = SessionMessage(role="assistant", content="Done", parts=parts)
    output = render_html(_metadata(), [message], "full")
    soup = BeautifulSoup(output, "html.parser")
    cards = soup.select(".step[data-kind='tool']")

    assert len(cards) == len(kinds)
    assert {card["data-step-kind"] for card in cards} == set(kinds)
    assert soup.select_one(".step[data-source='mcp'] .step-kind").get_text(
        strip=True
    ) == "MCP"
    assert all(card.select_one(".step-title") for card in cards)
    assert all(card.select_one(".step-body pre") for card in cards)
    assert "provider---future_kind_with_a_very_long_tool_name" in output


def test_html_is_self_contained_rendered_and_escapes_transcript_markup():
    output = render_html(_metadata(), _messages(), "full")

    assert output.startswith("<!doctype html>")
    assert "<style>" in output
    assert '<html lang="en">' in output
    assert 'class="hero-kicker"' in output
    assert output.count('class="hero-stat"') == 3
    assert 'class="archive-details"' in output
    assert "data-filter=\"tool\"" in output
    assert "data-filter=\"file\"" in output
    assert 'data-details="open"' in output
    assert "<strong>this</strong>" in output
    assert "<strong>answer</strong>" in output
    assert "<details class=\"thought\"" in output
    assert "<details class=\"step done\"" in output
    assert "<link" not in output
    assert "<script src=" not in output
    # There is one trusted inline behavior script; transcript scripts stay text.
    assert output.count("<script>") == 1
    assert "<script>alert('x')</script>" not in output
    assert "&lt;script&gt;alert('x')&lt;/script&gt;" in output
    assert "&lt;/script&gt;&lt;script&gt;alert(&#x27;tool&#x27;)&lt;/script&gt;" in output


def test_export_api_returns_raw_downloads_and_validates_options(monkeypatch):
    monkeypatch.setattr(settings, "ms_agent_llm_model", "")
    from app.main import create_app

    with TestClient(create_app()) as client:
        created = client.post("/api/sessions", json={"title": "导出 / 测试"})
        assert created.status_code == 201
        session_id = created.json()["data"]["id"]
        found = find_session(session_id)
        assert found is not None
        _project, session, manager = found
        log = manager.get_session_log(session)
        log.append({"role": "user", "content": "Hello"})
        log.append({"role": "assistant", "content": "World **bold**"})

        markdown = client.get(
            f"/api/sessions/{session_id}/export",
            params={"format": "markdown", "detail": "full"},
        )
        assert markdown.status_code == 200
        assert markdown.headers["content-type"].startswith("text/markdown")
        assert markdown.headers["content-disposition"].startswith("attachment;")
        assert "filename*=UTF-8''" in markdown.headers["content-disposition"]
        assert markdown.headers["cache-control"] == "no-store"
        assert markdown.text.startswith("# 导出 / 测试")
        assert "## User\n\nHello" in markdown.text
        assert "## Assistant\n\nWorld **bold**" in markdown.text
        assert not markdown.text.startswith('{"code"')

        exported_html = client.get(
            f"/api/sessions/{session_id}/export",
            params={"format": "html", "detail": "compact"},
        )
        assert exported_html.status_code == 200
        assert exported_html.headers["content-type"].startswith("text/html")
        assert exported_html.text.startswith("<!doctype html>")
        assert "<strong>bold</strong>" in exported_html.text

        invalid = client.get(
            f"/api/sessions/{session_id}/export",
            params={"format": "pdf"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == 422
