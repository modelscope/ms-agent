"""Chat event->ChatChunk mapping + turn termination on TURN_END."""
import asyncio
import json
import os

from app.backends.ms_agent import chat
from app.backends.ms_agent import runtime as rt_mod
from app.schemas.chat import ChatFile, ChatMessage, ChatRequest


def test_compose_prompt_plain_text_when_no_files():
    msg = ChatMessage(role="user", content="hello")
    assert chat._compose_prompt(msg) == "hello"


def test_compose_prompt_appends_attached_files_block():
    msg = ChatMessage(
        role="user",
        content="summarize these",
        files=[
            ChatFile(name="a.pdf", path="user_files/a.pdf"),
            ChatFile(name="b.png", path="user_files/b.png"),
        ],
    )
    prompt = chat._compose_prompt(msg)
    # The user's typed text is preserved and the workspace-relative file paths
    # are listed so the agent can read the real bytes with its file tools.
    assert prompt.startswith("summarize these")
    assert "user_files/a.pdf" in prompt
    assert "user_files/b.png" in prompt


def test_compose_prompt_files_only_turn():
    msg = ChatMessage(role="user",
                      content="",
                      files=[
                          ChatFile(name="a.pdf", path="user_files/a.pdf"),
                      ])
    prompt = chat._compose_prompt(msg)
    assert prompt and "user_files/a.pdf" in prompt


def test_turn_mapper_maps_new_protocol():
    m = chat._TurnMapper()
    assert [c.type for c in m.map({
        "type": "content_delta",
        "text": "hi"
    })] == ["text"]

    # Reasoning streams incrementally: each delta is its own thought frame, and
    # reasoning_ended emits a zero-width finalize frame carrying duration.
    assert m.map({"type": "reasoning_started"}) == []
    delta = m.map({"type": "reasoning_delta", "text": "th"})
    assert [c.type for c in delta] == ["thought"] and delta[0].content == "th"
    ended = m.map({"type": "reasoning_ended"})
    assert [c.type for c in ended] == ["thought"]
    assert ended[0].content == "" and "duration" in ended[0].meta

    # plan -> task frames; status mapped; index-stable ids for in-place upsert.
    tasks = m.map({
        "type":
        "plan_updated",
        "entries": [
            {
                "content": "a",
                "status": "in_progress"
            },
            {
                "content": "b",
                "status": "completed"
            },
        ]
    })
    assert [(c.meta["id"], c.meta["status"])
            for c in tasks] == [("0", "running"), ("1", "done")]

    # A file_system read: started stashes it; completed emits the file_read step.
    # tool_call_started now emits a live "running" card for immediate feedback;
    # the completed event's step replaces it in place (matched by call_id).
    run = m.map({
        "type": "tool_call_started",
        "name": "file_system---read_file",
        "call_id": "c1",
        "arguments": {
            "path": "a.md"
        }
    })
    assert [c.type for c in run] == ["step"]
    assert run[0].meta == {
        "kind": "file_read",
        "path": "a.md",
        "name": "file_system---read_file",
        "tool": "file_system---read_file",
        "arguments": {
            "path": "a.md"
        },
        "group": 1,
        "call_id": "c1",
        "status": "running",
    }
    step = m.map({
        "type": "tool_call_completed",
        "call_id": "c1",
        "name": "file_system---read_file",
        "result": "# Title"
    })
    assert [c.type for c in step] == ["step"]
    assert step[0].meta == {
        "kind": "file_read",
        "path": "a.md",
        "name": "file_system---read_file",
        "tool": "file_system---read_file",
        "arguments": {
            "path": "a.md"
        },
        "result": "# Title",
        # Server-side tool-round grouping: this reply's tool-call set.
        "group": 1,
        "call_id": "c1",
    }

    # A failed completion carries error status on the step (+ full invocation).
    m.map({
        "type": "tool_call_started",
        "name": "sh",
        "call_id": "c2",
        "arguments": {}
    })
    err = m.map({
        "type": "tool_call_completed",
        "call_id": "c2",
        "name": "sh",
        "error": "boom"
    })
    assert err[0].meta == {
        "kind": "tool_call",
        "name": "sh",
        "tool": "sh",
        "arguments": {},
        "status": "error",
        "error": "boom",
        "source": "tool",
        # c1's round fully drained before this started → a NEW round: the
        # SDK emits one reply's whole tool_calls array as consecutive
        # started events, so a started arriving after pending emptied is
        # the next array's first element.
        "group": 2,
        "call_id": "c2",
    }

    # todo_list / task_control calls are the timeline, not step cards — no
    # running card on started either (their _tool_step_meta is None).
    assert m.map({
        "type": "tool_call_started",
        "name": "todo_list---todo_write",
        "call_id": "c3",
        "arguments": {}
    }) == []
    assert m.map({
        "type": "tool_call_completed",
        "call_id": "c3",
        "name": "todo_list---todo_write"
    }) == []

    # A turn/API error -> a structured error frame.
    er = m.map({
        "type": "error",
        "message": "APIError: 401",
        "recoverable": False
    })
    assert [c.type for c in er] == ["error"]
    assert er[0].meta == {"message": "APIError: 401", "recoverable": False}
    # Unhandled events (content_end, ...) yield nothing.
    assert m.map({"type": "content_end"}) == []


def test_turn_mapper_maps_permission_request_to_authorization_step():
    m = chat._TurnMapper("sid-9")
    out = m.map({
        "type": "permission_request",
        "request_id": "req-1",
        "tool_name": "file_system---write_file",
        "tool_args": {
            "path": "a.md",
            "content": "x"
        },
    })
    # Emitted as a standalone authorization step (no task nesting).
    assert [c.type for c in out] == ["step"]
    meta = out[0].meta
    assert meta["kind"] == "authorization" and meta["state"] == "pending"
    assert meta["request_id"] == "req-1" and meta["session_id"] == "sid-9"
    assert meta["tool_name"] == "file_system---write_file"
    assert "a.md" in meta["desc"]


def test_turn_mapper_emits_standalone_step_for_toolcall_without_plan():
    m = chat._TurnMapper()
    m.map({
        "type": "tool_call_started",
        "name": "sh",
        "call_id": "c1",
        "arguments": {
            "a": 1
        }
    })
    out = m.map({"type": "tool_call_completed", "call_id": "c1", "name": "sh"})
    # No plan needed: the tool call is emitted as its own linear step, carrying
    # its full invocation (tool + arguments) and its call_id (so the frontend
    # replaces the live "running" card emitted on start).
    assert [c.type for c in out] == ["step"]
    assert out[0].meta == {
        "kind": "tool_call",
        "name": "sh",
        "tool": "sh",
        "arguments": {
            "a": 1
        },
        "source": "tool",
        "group": 1,
        "call_id": "c1",
    }


def test_running_card_emitted_on_start_and_flush_keeps_call_id():
    """tool_call_started emits a live 'running' card (immediate feedback for slow
    tools like web_search). If the turn is interrupted before completion, flush()
    emits the sealed card with the SAME call_id so the frontend flips the running
    card in place rather than leaving a stuck spinner."""
    m = chat._TurnMapper()
    run = m.map({
        "type": "tool_call_started",
        "name": "web_search---exa_search",
        "call_id": "c1",
        "arguments": {"query": "今天科技新闻"},
    })
    assert [c.type for c in run] == ["step"]
    assert run[0].meta["kind"] == "search"
    assert run[0].meta["status"] == "running"
    assert run[0].meta["call_id"] == "c1"
    assert run[0].meta["query"] == "今天科技新闻"

    flushed = m.flush()
    steps = [c for c in flushed if c.type == "step"]
    assert len(steps) == 1
    assert steps[0].meta["call_id"] == "c1"
    assert steps[0].meta["status"] == "error"


def test_tool_step_meta_maps_full_taxonomy():
    """The `server---tool` taxonomy maps to specialized step kinds (matching on
    the full name, not the short leaf)."""
    meta = chat._tool_step_meta

    # code_executor -> terminal, carrying the command / code body.
    assert meta("code_executor---shell_executor", {"command": "ls -la"}) == {
        "kind": "terminal",
        "name": "code_executor---shell_executor",
        "code": "ls -la"
    }
    assert meta("code_executor---python_executor", {"code": "print(1)"}) == {
        "kind": "terminal",
        "name": "code_executor---python_executor",
        "code": "print(1)"
    }

    # web_search -> search (query); fetch_page -> browser (url).
    assert meta("web_search---tavily_search", {"query": "ai agents"}) == {
        "kind": "search",
        "name": "web_search---tavily_search",
        "query": "ai agents",
        "scope": "web"
    }
    assert meta("web_search---fetch_page", {"url": "http://x"}) == {
        "kind": "browser",
        "name": "web_search---fetch_page",
        "url": "http://x"
    }

    # file_system write vs edit -> DISTINCT kinds (a full-content write and an
    # in-place edit render as different cards).
    assert meta("file_system---write_file", {
        "path": "a.md",
        "content": "x"
    }) == {
        "kind": "file_write",
        "path": "a.md",
        "name": "file_system---write_file"
    }
    assert meta("file_system---edit_file", {
        "path": "a.md",
        "old_string": "x",
        "new_string": "y"
    }) == {
        "kind": "file_edit",
        "path": "a.md",
        "name": "file_system---edit_file"
    }

    # file_system grep/glob -> search over the workspace.
    assert meta("file_system---grep", {"pattern": "TODO"}) == {
        "kind": "search",
        "name": "file_system---grep",
        "query": "TODO",
        "scope": "files"
    }

    # unified_memory -> memory (action); memory_read implies a read.
    assert meta("unified_memory---memory", {
        "action": "add",
        "content": "x"
    }) == {
        "kind": "memory",
        "name": "unified_memory---memory",
        "action": "add"
    }
    assert meta("unified_memory---memory_read", {}) == {
        "kind": "memory",
        "name": "unified_memory---memory_read",
        "action": "read"
    }

    # Unknown / MCP tools -> the generic tool_call card by unified name.
    assert meta("my_mcp---do_thing", {"a": 1}) == {
        "kind": "tool_call",
        "name": "my_mcp---do_thing",
        # Non-builtin `server---tool` → an MCP call (UI: "call MCP").
        "source": "mcp"
    }
    # Plan machinery is still dropped.
    assert meta("todo_list---todo_write", {}) is None


def test_turn_mapper_flags_plan_touched_on_todo_write():
    """A completed todo_write leaves no step card, but flags the mapper so the
    loop's changed-files summary can include the session "plan.md"; a FAILED
    todo_write doesn't count (nothing was written)."""
    m = chat._TurnMapper()
    assert m.plan_touched is False
    m.map({
        "type": "tool_call_started",
        "name": "todo_list---todo_write",
        "call_id": "c1",
        "arguments": {}
    })
    assert m.map({
        "type": "tool_call_completed",
        "call_id": "c1",
        "name": "todo_list---todo_write"
    }) == []
    assert m.plan_touched is True

    failed = chat._TurnMapper()
    failed.map({
        "type": "tool_call_started",
        "name": "todo_list---todo_write",
        "call_id": "c2",
        "arguments": {}
    })
    failed.map({
        "type": "tool_call_completed",
        "call_id": "c2",
        "name": "todo_list---todo_write",
        "error": "boom"
    })
    assert failed.plan_touched is False


def test_changed_files_in_rows_includes_plan_write():
    """The drain-side derivation counts todo_write rows as "plan.md" alongside
    workspace write/edit paths (deduped, first-write order)."""
    from app.backends.ms_agent.sessions import changed_files_in_rows

    rows = [
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "todo_list---todo_write",
                    "arguments": {
                        "todos": []
                    }
                },
                {
                    "id": "c2",
                    "tool_name": "file_system---edit_file",
                    "arguments": {
                        "path": "a.md"
                    }
                },
            ]
        },
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c3",
                    "tool_name": "todo_list---todo_write",  # dup → once
                    "arguments": {
                        "todos": []
                    }
                },
            ]
        },
    ]
    assert changed_files_in_rows(rows) == ["plan.md", "a.md"]


def test_changed_files_excludes_out_of_workspace_and_custom_plan(tmp_path):
    """With a workspace root, a write that resolves OUTSIDE the workspace (the
    model copying its plan into the session dir via ``..``) and a plan file
    under a NON-plan.md name (identified by the todo tool's own render report —
    no filename heuristic) are both kept out of the summary; real in-workspace
    deliverables stay, workspace-relative."""
    from app.backends.ms_agent.sessions import changed_files_in_rows

    ws = str(tmp_path)
    rows = [
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "todo_list---todo_write",
                    "arguments": {
                        "todos": []
                    }
                },
            ]
        },
        # model renders the plan markdown into the workspace under a custom name
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c2",
                    "tool_name": "todo_list---todo_render_md",
                    "arguments": {
                        "path": "roadmap_plan.md"
                    }
                },
            ]
        },
        {
            "role": "tool",
            "tool_call_id": "c2",
            "content": "OK: rendered plan markdown to roadmap_plan.md"
        },
        {
            "role":
            "assistant",
            "tool_calls": [
                # a genuine workspace deliverable
                {
                    "id": "c3",
                    "tool_name": "file_system---write_file",
                    "arguments": {
                        "path": "report.txt"
                    }
                },
                # model copies the plan into the session dir (outside ws via ..)
                {
                    "id": "c4",
                    "tool_name": "file_system---write_file",
                    "arguments": {
                        "path": "../sess/plan_copy.md"
                    }
                },
                # model rewrites the custom-named plan the render produced: matches
                # a reported plan path -> excluded (not a deliverable)
                {
                    "id": "c5",
                    "tool_name": "file_system---edit_file",
                    "arguments": {
                        "path": "roadmap_plan.md"
                    }
                },
            ]
        },
    ]
    got = changed_files_in_rows(rows, ws)
    assert "report.txt" in got
    assert "roadmap_plan.md" not in got  # custom-named plan, by tool report
    assert not any("plan_copy.md" in p for p in got)  # out-of-ws write
    assert not any(".." in p for p in got)  # no escapes leak through
    assert "plan.md" in got  # the reserved plan marker still present


def test_plan_paths_and_latest_rendered_md(tmp_path):
    """plan_paths_in_rows collects plan locations from todo reports (write's
    plan_path + its .md twin, render targets) and loop_end plan_file;
    latest_rendered_plan_md returns the last rendered markdown target."""
    from app.backends.ms_agent.sessions import (
        latest_rendered_plan_md,
        plan_paths_in_rows,
    )

    ws = str(tmp_path)
    rows = [
        {
            "role": "tool",
            "content": '{"status":"ok","plan_path":"plan.json"}'
        },
        {
            "role": "tool",
            "content": "OK: rendered plan markdown to a_plan.md"
        },
        {
            "role": "tool",
            "content": "OK: rendered plan markdown to b_plan.md"
        },
        {
            "_type": "loop_end",
            "plan_file": str(tmp_path / "sess" / "x.md")
        },
    ]
    paths = plan_paths_in_rows(rows, ws)
    assert os.path.join(ws, "plan.json") in paths
    assert os.path.join(ws, "plan.md") in paths  # .json twin
    assert os.path.join(ws, "a_plan.md") in paths
    assert os.path.join(ws, "b_plan.md") in paths
    assert os.path.normpath(str(tmp_path / "sess" / "x.md")) in paths
    assert latest_rendered_plan_md(rows, ws) == os.path.join(ws, "b_plan.md")


def test_mapper_render_md_marks_plan_and_records_report():
    """A live todo_render_md completion flags plan_touched and stashes its
    rendered target (raw), so loop end points plan_file at the fresh markdown
    and keeps that file out of the changed-files summary — regardless of name."""
    m = chat._TurnMapper()
    m.map({
        "type": "tool_call_started",
        "name": "todo_list---todo_render_md",
        "call_id": "c1",
        "arguments": {
            "path": "custom_plan.md"
        }
    })
    out = m.map({
        "type": "tool_call_completed",
        "call_id": "c1",
        "name": "todo_list---todo_render_md",
        "result": "OK: rendered plan markdown to custom_plan.md"
    })
    assert out == []  # plan machinery emits no step card
    assert m.plan_touched is True
    assert m.plan_reports == ["custom_plan.md"]
    assert m.latest_plan_md_report == "custom_plan.md"


def test_tool_step_surfaces_duration_ms():
    """The SDK's per-tool duration_s is surfaced on the step meta as duration_ms
    (live), independent of the tool's card kind."""
    m = chat._TurnMapper()
    m.map({
        "type": "tool_call_started",
        "name": "code_executor---shell_executor",
        "call_id": "c1",
        "arguments": {
            "command": "ls"
        }
    })
    out = m.map({
        "type": "tool_call_completed",
        "call_id": "c1",
        "name": "code_executor---shell_executor",
        "result": "ok",
        "duration_s": 1.18
    })
    assert out[0].meta["kind"] == "terminal"
    assert out[0].meta["duration_ms"] == 1180


def test_reconstruct_preserves_text_tool_text_order():
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {
            "role": "user",
            "content": "hi"
        },
        {
            "role": "assistant",
            "content": "before"
        },
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "file_system---read_file",
                    "arguments": '{"path": "a.md"}'
                },
            ]
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": "file body"
        },
        {
            "role": "assistant",
            "content": "after"
        },
    ]
    msgs = _reconstruct(rows)
    assert [m.role for m in msgs] == ["user", "assistant"]
    parts = msgs[1].parts
    # text "before" -> step (file_read) -> text "after", in stream order.
    assert [p.kind for p in parts] == ["text", "step", "text"]
    assert parts[0].text == "before" and parts[2].text == "after"
    step = parts[1].step
    assert step.kind == "file_read"
    # Full invocation is carried so the detail drawer shows tool + args + result.
    assert step.meta["tool"] == "file_system---read_file"
    assert step.meta["arguments"] == {"path": "a.md"}
    assert step.meta["result"] == "file body"
    # content stays the joined answer text for fallback consumers.
    assert msgs[1].content == "before\n\nafter"


def test_reconstruct_surfaces_errors_and_failed_steps():
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {
            "role": "user",
            "content": "hi",
            "seq": 0
        },
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "file_system---read_file",
                    "arguments": '{"path": "x.md"}'
                },
            ],
            "seq":
            1
        },
        # failed tool result -> marks its step; API/turn error -> own message.
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": "no such file",
            "is_error": True,
            "seq": 2
        },
        {
            "_type": "error",
            "message": "APIError: 500",
            "recoverable": False,
            "seq": 3
        },
    ]
    msgs = _reconstruct(rows)

    assert [m.role for m in msgs] == ["user", "assistant", "assistant"]
    step = msgs[1].parts[0].step
    assert step.kind == "tool_call" and step.meta["status"] == "error"
    assert step.meta["error"] == "no such file"
    assert msgs[2].parts[0].kind == "error" and msgs[2].parts[
        0].recoverable is False
    assert "APIError: 500" in msgs[2].content


def test_reconstruct_replays_reasoning_and_skips_compacted_rows():
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {
            "role": "user",
            "content": "hi",
            "seq": 0
        },
        # Persisted reasoning replays as a thought part before the answer.
        {
            "role": "assistant",
            "content": "answer",
            "reasoning_content": "chain of thought",
            "seq": 1
        },
        # Compaction re-appends of earlier rows (the squeezed LLM view + the
        # synthetic summary) must not duplicate the timeline.
        {
            "role": "user",
            "content": "[Conversation Summary] ...",
            "_source": "compaction",
            "seq": 2
        },
        {
            "role": "assistant",
            "content": "answer",
            "_source": "compaction",
            "seq": 3
        },
    ]
    msgs = _reconstruct(rows)
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert [p.kind for p in msgs[1].parts] == ["thought", "text"]
    assert msgs[1].parts[0].text == "chain of thought"
    assert msgs[1].content == "answer"


def test_reconstruct_replays_permission_and_durations():
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {
            "role": "user",
            "content": "write it",
            "seq": 0
        },
        # A restricted-mode authorization (persisted _type=permission), replayed
        # as a resolved auth card in the assistant turn.
        {
            "_type": "permission",
            "tool_name": "file_system---write_file",
            "arguments": {
                "path": "a.md"
            },
            "state": "approved",
            "seq": 1
        },
        {
            "role":
            "assistant",
            "reasoning_content":
            "let me write",
            "reasoning_duration":
            4,
            "tool_calls": [{
                "id": "c1",
                "tool_name": "file_system---write_file",
                "arguments": '{"path": "a.md"}'
            }],
            "seq":
            2
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": "ok",
            "duration_ms": 1180,
            "seq": 3
        },
    ]
    msgs = _reconstruct(rows)
    assert [m.role for m in msgs] == ["user", "assistant"]
    kinds = [p.kind for p in msgs[1].parts]
    # The permission row persists eagerly (seq=1, before the round-boundary
    # assistant/tool rows), but replay must match the LIVE frame order: the
    # turn's reasoning first, then the auth card ADJACENT to the tool step it
    # gated. So: thought → auth card → tool step (not auth → thought → tool).
    # (The permission's dict args match the tool_call's JSON-string args —
    # exercises _perm_key normalization.)
    assert kinds == ["thought", "step", "step"]
    assert msgs[1].parts[0].duration == 4
    auth = msgs[1].parts[1].step
    assert auth.kind == "authorization" and auth.meta["state"] == "approved"
    tool_step = msgs[1].parts[2].step
    assert tool_step.kind == "file_write" and tool_step.meta[
        "duration_ms"] == 1180


def test_reconstruct_pairs_each_permission_with_its_tool_step():
    """Two gated calls in one turn: each auth card sits immediately before the
    tool step it authorized (FIFO match on tool+args), so a rejected write and
    its errored result render adjacent — the case the frontend merges."""
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {
            "role": "user",
            "content": "write two files",
            "seq": 0
        },
        {
            "_type": "permission",
            "tool_name": "file_system---write_file",
            "arguments": {
                "path": "a.md"
            },
            "state": "approved",
            "seq": 1
        },
        {
            "_type": "permission",
            "tool_name": "file_system---write_file",
            "arguments": {
                "path": "b.md"
            },
            "state": "rejected",
            "seq": 2
        },
        {
            "role":
            "assistant",
            "reasoning_content":
            "writing",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "file_system---write_file",
                    "arguments": {
                        "path": "a.md"
                    }
                },
                {
                    "id": "c2",
                    "tool_name": "file_system---write_file",
                    "arguments": {
                        "path": "b.md"
                    }
                },
            ],
            "seq":
            3
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": "ok",
            "seq": 4
        },
        {
            "role": "tool",
            "tool_call_id": "c2",
            "content": "Tool call denied",
            "is_error": True,
            "seq": 5
        },
    ]
    parts = _reconstruct(rows)[1].parts
    kinds = [(p.kind, (p.step.kind if p.kind == "step" else None),
              (p.step.meta.get("state") or p.step.meta.get("status")
               if p.kind == "step" else None)) for p in parts]
    # thought, then (auth approved → its file_write), then the rejected auth
    # card alone — its DENIED tool step is dropped by _history_step (the
    # rejected card already tells the story; showing both duplicated the UI),
    # but the card still sits at the call's original position.
    assert kinds == [
        ("thought", None, None),
        ("step", "authorization", "approved"),
        ("step", "file_write", None),
        ("step", "authorization", "rejected"),
    ]


def test_reconstruct_unmatched_permission_still_renders():
    """An auth record with no matching tool step (unusual) is not dropped — it
    flushes at turn end so the decision stays visible."""
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {
            "role": "user",
            "content": "hi",
            "seq": 0
        },
        {
            "_type": "permission",
            "tool_name": "some---tool",
            "arguments": {
                "x": 1
            },
            "state": "approved",
            "seq": 1
        },
        {
            "role": "assistant",
            "content": "done",
            "seq": 2
        },
    ]
    parts = _reconstruct(rows)[1].parts
    assert any(p.kind == "step" and p.step.kind == "authorization"
               for p in parts)


def test_reconstruct_pairs_permission_by_call_id_exactly():
    """Two IDENTICAL (tool+args) calls in one round with opposite outcomes: the
    call_id link pairs each auth card to its true call — the corner args-FIFO
    can't disambiguate. Permission ask-order is reversed vs the tool_calls array
    (parallel scheduling) to prove ordering-independence."""
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {
            "role": "user",
            "content": "twice",
            "seq": 0
        },
        # asks recorded in the OPPOSITE order to the tool_calls array below
        {
            "_type": "permission",
            "tool_name": "file_system---write_file",
            "arguments": {
                "path": "a.md"
            },
            "state": "rejected",
            "call_id": "c2",
            "seq": 1
        },
        {
            "_type": "permission",
            "tool_name": "file_system---write_file",
            "arguments": {
                "path": "a.md"
            },
            "state": "approved",
            "call_id": "c1",
            "seq": 2
        },
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "file_system---write_file",
                    "arguments": {
                        "path": "a.md"
                    }
                },
                {
                    "id": "c2",
                    "tool_name": "file_system---write_file",
                    "arguments": {
                        "path": "a.md"
                    }
                },
            ],
            "seq":
            3
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": "ok",
            "seq": 4
        },
        {
            "role": "tool",
            "tool_call_id": "c2",
            "content": "denied",
            "is_error": True,
            "seq": 5
        },
    ]
    parts = _reconstruct(rows)[1].parts
    auth_states = [
        p.step.meta.get("state") for p in parts
        if p.kind == "step" and p.step.kind == "authorization"
    ]
    # c1 (first in array) → approved; c2 → rejected — matched by id, not order.
    assert auth_states == ["approved", "rejected"]


def test_reconstruct_populates_changed_files():
    """A turn's write/edit tool_calls populate the assistant message's
    changed_files (deduped, first-write order) for the loop summary; a
    todo_write contributes the session plan file ("plan.md")."""
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {
            "role": "user",
            "content": "build",
            "seq": 0
        },
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "file_system---write_file",
                    "arguments": {
                        "path": "index.html"
                    }
                },
                {
                    "id": "c2",
                    "tool_name": "file_system---edit_file",
                    "arguments": {
                        "path": "style.css"
                    }
                },
                {
                    "id": "c3",
                    "tool_name": "file_system---write_file",
                    "arguments": {
                        "path": "index.html"
                    }
                },  # dup → once
                {
                    "id": "c4",
                    "tool_name": "file_system---read_file",
                    "arguments": {
                        "path": "notes.txt"
                    }
                },  # read → excluded
                {
                    "id": "c5",
                    "tool_name": "todo_list---todo_write",
                    "arguments": {
                        "todos": []
                    }
                },  # plan write → "plan.md"
            ],
            "seq":
            1
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": "ok",
            "seq": 2
        },
        {
            "role": "tool",
            "tool_call_id": "c2",
            "content": "ok",
            "seq": 3
        },
        {
            "role": "tool",
            "tool_call_id": "c3",
            "content": "ok",
            "seq": 4
        },
        {
            "role": "tool",
            "tool_call_id": "c4",
            "content": "text",
            "seq": 5
        },
        {
            "role": "tool",
            "tool_call_id": "c5",
            "content": "ok",
            "seq": 6
        },
        {
            "role": "assistant",
            "content": "done",
            "seq": 7
        },
    ]
    msg = _reconstruct(rows)[1]
    assert msg.changed_files == ["index.html", "style.css", "plan.md"]


def test_reconstruct_reads_loop_end_duration():
    """A persisted loop_end marker supplies the turn's duration_ms on replay
    (changed_files stays derived from the tool_calls). Its seq lands after the
    turn's rows, before the next user row."""
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {
            "role": "user",
            "content": "build",
            "seq": 0
        },
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "file_system---write_file",
                    "arguments": {
                        "path": "a.py"
                    }
                },
            ],
            "seq":
            1
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": "ok",
            "seq": 2
        },
        {
            "role": "assistant",
            "content": "done",
            "seq": 3
        },
        {
            "_type": "loop_end",
            "duration_ms": 8142,
            "changed_files": ["a.py"],
            "seq": 4
        },
    ]
    msg = _reconstruct(rows)[1]
    assert msg.duration_ms == 8142
    assert msg.changed_files == ["a.py"]  # derived, matches the marker
    assert msg.plan_file is None  # no plan write this turn


def test_reconstruct_reads_loop_end_plan_file():
    """A loop_end marker carrying ``plan_file`` (turn rewrote the todo list)
    surfaces it on the assistant message, alongside the derived "plan.md"
    changed-files entry — the frontend keys the plan chip off these."""
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {
            "role": "user",
            "content": "plan it",
            "seq": 0
        },
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "todo_list---todo_write",
                    "arguments": {
                        "todos": []
                    }
                },
            ],
            "seq":
            1
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": "ok",
            "seq": 2
        },
        {
            "role": "assistant",
            "content": "done",
            "seq": 3
        },
        {
            "_type": "loop_end",
            "duration_ms": 900,
            "changed_files": ["plan.md"],
            "plan_file":
            "/home/u/.ms_agent_webui/projects/p/sessions/s/plan.md",
            "seq": 4
        },
    ]
    msg = _reconstruct(rows)[1]
    assert msg.changed_files == ["plan.md"]
    assert msg.plan_file == "/home/u/.ms_agent_webui/projects/p/sessions/s/plan.md"


def test_plan_md_path_resolution():
    """_plan_md_path mirrors the todo tool's join: an absolute configured
    plan_md_filename wins outright; a relative one lands under output_dir;
    unresolvable configs return None."""

    def rt_with(plan_md, output_dir):
        tool = type("T", (), {"plan_md_filename": plan_md})()
        tools = type("Ts", (), {"todo_list": tool})()
        cfg = type("C", (), {"tools": tools, "output_dir": output_dir})()
        agent = type("A", (), {"config": cfg})()
        return type("R", (), {"agent": agent})()

    assert chat._plan_md_path(rt_with("/abs/sessions/s1/plan.md",
                                      "/ws")) == "/abs/sessions/s1/plan.md"
    assert chat._plan_md_path(rt_with("plan.md", "/ws")) == "/ws/plan.md"
    assert chat._plan_md_path(rt_with("", "")) is None


def test_plan_md_path_prefers_canonical_over_render_target():
    """The canonical configured plan.md (what todo_write maintains and GET /plan
    serves) is the plan_file pointer; a todo_render_md target is only a fallback
    when the config can't be resolved — a render to a custom name does NOT
    hijack the pointer away from the canonical plan."""

    def rt_with(plan_md, output_dir, ws=None):
        tool = type("T", (), {"plan_md_filename": plan_md})()
        tools = type("Ts", (), {"todo_list": tool})()
        cfg = type("C", (), {"tools": tools, "output_dir": output_dir})()
        agent = type("A", (), {"config": cfg})()
        project = type("P", (), {"path": ws})() if ws else None
        return type("R", (), {"agent": agent, "project": project})()

    # Config resolvable -> canonical wins, render target ignored.
    rt = rt_with("/abs/sessions/s1/plan.md", "/ws", ws="/ws")
    assert chat._plan_md_path(rt,
                              "custom_plan.md") == "/abs/sessions/s1/plan.md"
    # Config unresolvable -> fall back to the render target (resolved vs ws).
    rt2 = rt_with("", "", ws="/ws")
    assert chat._plan_md_path(rt2, "custom_plan.md") == "/ws/custom_plan.md"


def test_reconstruct_no_loop_end_leaves_duration_none():
    """Turns predating the marker still reconstruct; duration_ms is just None."""
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {
            "role": "user",
            "content": "hi",
            "seq": 0
        },
        {
            "role": "assistant",
            "content": "hello",
            "seq": 1
        },
    ]
    assert _reconstruct(rows)[1].duration_ms is None


def test_reconstruct_rebuilds_plan_from_todo_write():
    """A persisted todo_list---todo_write becomes a `tasks` plan part (like the
    live plan_updated event), not a dropped step; its result carries the merged
    plan and statuses map to the frontend task states."""
    from app.backends.ms_agent.sessions import _reconstruct

    result = json.dumps({
        "status":
        "ok",
        "todos": [
            {
                "content": "step one",
                "id": "T1",
                "status": "completed"
            },
            {
                "content": "step two",
                "id": "T2",
                "status": "in_progress"
            },
            {
                "content": "step three",
                "id": "T3",
                "status": "pending"
            },
        ]
    })
    rows = [
        {
            "role": "user",
            "content": "plan it",
            "seq": 0
        },
        {
            "role":
            "assistant",
            "content":
            "working",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "todo_list---todo_write",
                    "arguments": '{"todos": []}'
                },
            ],
            "seq":
            1
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": result,
            "seq": 2
        },
        # A non-plan todo tool (render) is still dropped, not a step.
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c2",
                    "tool_name": "todo_list---todo_render_md",
                    "arguments": "{}"
                },
            ],
            "seq":
            3
        },
        {
            "role": "tool",
            "tool_call_id": "c2",
            "content": "OK",
            "seq": 4
        },
        {
            "role": "assistant",
            "content": "done",
            "seq": 5
        },
    ]
    msgs = _reconstruct(rows)
    assert [m.role for m in msgs] == ["user", "assistant"]
    parts = msgs[1].parts
    # The tool-call row's real narration ("working") replays as a text part
    # (only the SDK's 'Let me do a tool calling.' filler is dropped); the plan
    # appears once, in stream order, before the final answer.
    assert [p.kind for p in parts] == ["text", "tasks", "text"]
    assert parts[0].text == "working"
    tasks = parts[1].tasks
    assert [(t.id, t.label, t.status) for t in tasks] == [
        ("0", "step one", "done"),
        ("1", "step two", "running"),
        ("2", "step three", "pending"),
    ]
    assert parts[2].text == "done"


def test_reconstruct_appends_plan_snapshot_per_write():
    """Each todo write appends its OWN `tasks` snapshot at that point in the
    timeline (mirrors the live stream: the conversation shows the plan's state
    per update; the composer's pinned panel is the live/merged view)."""
    from app.backends.ms_agent.sessions import _reconstruct

    r1 = json.dumps({"todos": [{"content": "a", "status": "pending"}]})
    r2 = json.dumps({
        "todos": [{
            "content": "a",
            "status": "completed"
        }, {
            "content": "b",
            "status": "pending"
        }]
    })
    rows = [
        {
            "role": "user",
            "content": "go",
            "seq": 0
        },
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "todo_list---todo_write",
                    "arguments": "{}"
                },
            ],
            "seq":
            1
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": r1,
            "seq": 2
        },
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c2",
                    "tool_name": "todo_list---todo_write",
                    "arguments": "{}"
                },
            ],
            "seq":
            3
        },
        {
            "role": "tool",
            "tool_call_id": "c2",
            "content": r2,
            "seq": 4
        },
    ]
    msgs = _reconstruct(rows)
    assert [p.kind for p in msgs[1].parts] == ["tasks", "tasks"]
    # First snapshot: the plan as it was at the first write.
    assert [(t.label, t.status) for t in msgs[1].parts[0].tasks] == [
        ("a", "pending"),
    ]
    # Second snapshot: the updated plan (row a done, row b added).
    assert [(t.label, t.status) for t in msgs[1].parts[1].tasks] == [
        ("a", "done"),
        ("b", "pending"),
    ]


class _FakeSession:
    id = "sid-1"
    name = "Session sid-1"  # default-style name; autoname is a best-effort no-op here


class _FakeProject:
    id = "pid-1"  # done frames now carry project_id (for the new-session redirect)


class _FakeRuntime:

    def __init__(self):
        self.sink = rt_mod.QueueEventSink()
        self.turn_lock = asyncio.Lock()
        self.input_queue: asyncio.Queue = asyncio.Queue()
        self.run_task = _FakeRunTask()
        self.watchers = 0

    async def enqueue(self, text, marker=None):
        # Mirrors SessionRuntime.enqueue: tuple only when a marker rides along.
        await self.input_queue.put((text, marker) if marker else text)


class _FakeRunTask:

    def __init__(self, done: bool = False):
        self._done = done

    def done(self):
        return self._done


async def test_stream_maps_and_terminates(monkeypatch):
    fake_rt = _FakeRuntime()
    monkeypatch.setattr(chat, "_resolve_or_create", lambda req:
                        (_FakeProject(), _FakeSession()))

    async def _fake_get(project, session):
        return fake_rt

    monkeypatch.setattr(chat.registry, "get", _fake_get)

    req = ChatRequest(session_id="sid-1",
                      message=ChatMessage(role="user", content="hi"))
    frames: list[dict] = []

    async def _consume():
        async for frame in chat.stream(req):
            frames.append(frame)

    task = asyncio.create_task(_consume())

    # The stream attaches its sink then enqueues the prompt; wait for that.
    text = await asyncio.wait_for(fake_rt.input_queue.get(), timeout=2)
    assert text == "hi"

    from ms_agent.ui.events import (
        ContentDelta,
        ReasoningDelta,
        ReasoningEnded,
        ReasoningStarted,
        ToolCallCompleted,
        ToolCallStarted,
    )

    fake_rt.sink.emit(ContentDelta(text="Hello"))
    fake_rt.sink.emit(ReasoningStarted())
    fake_rt.sink.emit(ReasoningDelta(text="thinking"))
    fake_rt.sink.emit(ReasoningEnded())
    fake_rt.sink.emit(
        ToolCallStarted(call_id="c1", name="tool", arguments={"a": 1}))
    fake_rt.sink.emit(ToolCallCompleted(call_id="c1", name="tool",
                                        result="ok"))
    fake_rt.sink.push({"type": rt_mod.TURN_END})  # turn boundary -> done

    await asyncio.wait_for(task, timeout=2)

    parsed = [json.loads(f["data"]) for f in frames]
    # An early `session` frame announces the created session before any content.
    assert parsed[0]["type"] == "session"
    assert parsed[0]["meta"]["session_id"] == "sid-1"
    assert parsed[0]["meta"]["project_id"] == "pid-1"
    body = parsed[1:]
    # A `turn` frame follows, carrying the running turn's age so the client's
    # "processing Ns" counter is based on the server clock.
    assert body[0]["type"] == "turn"
    assert isinstance(body[0]["meta"]["elapsed_ms"], int)
    body = body[1:]
    # Reasoning streams (delta frame) then finalizes (duration frame); the tool
    # call emits a live "running" card on start, then its completed result (same
    # call_id) which the frontend uses to replace the running card in place.
    assert [p["type"] for p in body] == [
        "text",
        "thought",
        "thought",
        "step",  # running card (tool_call_started)
        "step",  # completed result (tool_call_completed)
        "done",
    ]
    assert body[0]["content"] == "Hello"
    assert body[1]["content"] == "thinking"
    assert body[2]["content"] == "" and "duration" in body[2]["meta"]
    assert body[3]["meta"]["kind"] == "tool_call"
    assert body[3]["meta"]["status"] == "running"
    assert body[3]["meta"]["call_id"] == "c1"
    assert body[4]["meta"]["kind"] == "tool_call"
    assert body[4]["meta"]["arguments"] == {"a": 1}
    assert body[4]["meta"]["result"] == "ok"
    assert body[4]["meta"]["call_id"] == "c1"
    assert body[-1]["meta"]["session_id"] == "sid-1"
    assert fake_rt.turn_lock.locked() is False


async def test_stream_done_carries_generated_title_and_category(monkeypatch):
    """On a first message the concurrent titler result is folded into the `done`
    frame so the frontend can refresh the lists with the summarized title +
    topic category."""
    fake_rt = _FakeRuntime()
    monkeypatch.setattr(chat, "_resolve_or_create", lambda req:
                        (_FakeProject(), _FakeSession()))

    async def _fake_get(project, session):
        return fake_rt

    monkeypatch.setattr(chat.registry, "get", _fake_get)

    async def _fake_title(_text):
        return ("My Title", "coding")

    monkeypatch.setattr(chat.titler, "generate_title_and_category",
                        _fake_title)

    req = ChatRequest(session_id="sid-1",
                      message=ChatMessage(role="user", content="write code"))
    frames: list[dict] = []

    async def _consume():
        async for frame in chat.stream(req):
            frames.append(frame)

    task = asyncio.create_task(_consume())
    await asyncio.wait_for(fake_rt.input_queue.get(), timeout=2)
    fake_rt.sink.push({"type": rt_mod.TURN_END})
    await asyncio.wait_for(task, timeout=2)

    done = json.loads(frames[-1]["data"])
    assert done["type"] == "done"
    assert done["meta"]["title"] == "My Title"
    assert done["meta"]["category"] == "coding"
    assert done["meta"][
        "project_id"] == "pid-1"  # drives the new-session redirect


async def test_stream_empty_user_message_ends_immediately(monkeypatch):
    monkeypatch.setattr(chat, "_resolve_or_create", lambda req:
                        (_FakeProject(), _FakeSession()))

    async def _fake_get(project, session):  # should not be reached
        raise AssertionError("runtime must not be built for an empty prompt")

    monkeypatch.setattr(chat.registry, "get", _fake_get)

    req = ChatRequest(session_id="sid-1",
                      message=ChatMessage(role="user", content=""))
    frames = [f async for f in chat.stream(req)]
    assert len(frames) == 1
    assert json.loads(frames[0]["data"])["type"] == "done"


async def test_drain_abandoned_turn_keeps_running_then_releases_at_boundary():
    """Navigating away (no explicit stop) keeps the turn running in the
    background: the drain does NOT discard the runtime; it waits (from the
    leaver's cursor) for the turn boundary, then releases the lock. (Explicit
    stop is a separate path — registry.interrupt.)"""
    fake_rt = _FakeRuntime()
    fake_rt.sink.new_turn()
    fake_rt.sink.push({"type": "content_delta", "text": "partial"})
    await fake_rt.turn_lock.acquire()

    drain = asyncio.create_task(
        chat._drain_abandoned_turn(fake_rt, fake_rt.sink.size, "sid-1"))
    # Turn still in flight: the lock stays held (a next message to THIS session
    # would wait) and the runtime is not discarded.
    await asyncio.sleep(0)
    assert fake_rt.turn_lock.locked() is True
    # Reaching the turn boundary lets the drain release the lock and finish.
    fake_rt.sink.push({"type": rt_mod.TURN_END})
    await asyncio.wait_for(drain, timeout=2)
    assert fake_rt.turn_lock.locked() is False


async def test_attach_replays_buffer_then_follows_live_tail(monkeypatch):
    """A late viewer gets a full catch-up of the in-flight turn (from the
    sink's event buffer) and then the live tail until the boundary — the same
    ChatChunk protocol as the original stream."""
    fake_rt = _FakeRuntime()
    fake_rt.sink.new_turn()
    # Events that happened BEFORE the viewer attached:
    fake_rt.sink.push({"type": "reasoning_started"})
    fake_rt.sink.push({"type": "reasoning_delta", "text": "想一想"})
    fake_rt.sink.push({"type": "reasoning_ended"})
    fake_rt.sink.push({"type": "content_delta", "text": "前半段"})
    await fake_rt.turn_lock.acquire()  # turn in flight

    monkeypatch.setattr(chat.registry, "peek", lambda sid: fake_rt)
    monkeypatch.setattr(chat.registry, "is_running", lambda sid: True)

    frames: list[dict] = []

    async def _consume():
        async for f in chat.attach("sid-9"):
            frames.append(json.loads(f["data"]))

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.05)  # catch-up should have flowed already
    kinds = [f["type"] for f in frames]
    # The rejoining client is told the turn's age FIRST (so its counter
    # continues rather than restarting), then the buffer replays.
    assert kinds == ["turn", "thought", "thought", "text"]
    assert isinstance(frames[0]["meta"]["elapsed_ms"], int)
    assert frames[2]["meta"].get("duration") is not None
    assert fake_rt.watchers == 1  # the attached viewer is counted

    # Live tail after attach:
    fake_rt.sink.push({"type": "content_delta", "text": "后半段"})
    fake_rt.sink.push({"type": rt_mod.TURN_END})
    await asyncio.wait_for(task, timeout=2)
    kinds = [f["type"] for f in frames]
    assert kinds == ["turn", "thought", "thought", "text", "text", "done"]
    assert frames[4]["content"] == "后半段"
    assert fake_rt.watchers == 0


async def test_attach_idle_session_yields_done(monkeypatch):
    monkeypatch.setattr(chat.registry, "peek", lambda sid: None)
    frames = [json.loads(f["data"]) async for f in chat.attach("sid-x")]
    assert [f["type"] for f in frames] == ["done"]


async def test_registry_interrupt_discards_and_seals():
    """Explicit stop discards the runtime (cancelling generation) AND seals a
    dangling turn so the rebuilt agent answers the NEXT message."""
    registry = rt_mod.RuntimeRegistry()
    registry._loop = asyncio.get_running_loop()

    log = _FakeLog([{"role": "user", "content": "写长文"}])

    class _Rt:

        def __init__(self):
            self.closed = False
            self.run_task = _FakeRunTask()
            self.agent = type("A", (), {"session_log": log})()

        async def aclose(self):
            self.closed = True

    rt = _Rt()
    registry._runtimes["sid-x"] = rt

    assert await registry.interrupt("sid-x") is True
    assert rt.closed is True  # runtime discarded
    assert "sid-x" not in registry._runtimes
    tail = log.get_all_messages()[-1]
    assert tail["role"] == "assistant" and tail["interrupted"] is True
    assert tail["content"] == "[interrupted]"  # neutral marker, not 中文哨兵


async def test_registry_interrupt_noop_without_live_runtime():
    registry = rt_mod.RuntimeRegistry()
    assert await registry.interrupt("nope") is False


async def test_registry_running_state():
    registry = rt_mod.RuntimeRegistry()
    rt = _FakeRuntime()
    registry._runtimes["sid-r"] = rt

    # Idle: lock free -> not running.
    assert registry.is_running("sid-r") is False
    await rt.turn_lock.acquire()
    assert registry.is_running("sid-r") is True
    assert registry.running_sessions() == ["sid-r"]
    assert registry.is_running("nope") is False


class _FakeLog:

    def __init__(self, messages):
        self._messages = messages

    def get_all_messages(self):
        return self._messages

    def append(self, message):
        self._messages.append(message)
        return len(self._messages)


class _FakeAgentRt:

    def __init__(self, messages):
        self.agent = type("A", (), {"session_log": _FakeLog(messages)})()


def test_seal_interrupted_turn_closes_dangling_user():
    # Fallback only: the SDK normally seals the round itself; a dangling user
    # tail means that persistence never ran, so close it with the marker row.
    rt = _FakeAgentRt([{"role": "user", "content": "写长文"}])
    chat._seal_interrupted_turn(rt)
    tail = rt.agent.session_log.get_all_messages()[-1]
    assert tail == {
        "role": "assistant",
        "content": "[interrupted]",
        "content_placeholder": True,
        "interrupted": True,
    }


def test_seal_interrupted_turn_closes_dangling_tool():
    # Aborted after a tool round: last row is a tool result awaiting a reply.
    rt = _FakeAgentRt([
        {
            "role": "user",
            "content": "跑一下"
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "c1"
            }]
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": "ok"
        },
    ])
    chat._seal_interrupted_turn(rt)
    assert rt.agent.session_log.get_all_messages()[-1]["role"] == "assistant"


def test_seal_interrupted_turn_noop_when_already_answered():
    # A completed turn ends on an assistant answer: nothing to seal.
    msgs = [{
        "role": "user",
        "content": "hi"
    }, {
        "role": "assistant",
        "content": "答案"
    }]
    rt = _FakeAgentRt(list(msgs))
    chat._seal_interrupted_turn(rt)
    assert rt.agent.session_log.get_all_messages() == msgs


def test_reconstruct_hides_placeholder_by_flag_not_string():
    """An interrupted seal row is identified by the structured
    ``content_placeholder`` flag (not by matching a literal): its content is
    hidden and the interrupted badge renders, whatever the placeholder text."""
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {"role": "user", "content": "写长文", "seq": 0},
        {"role": "assistant", "content": "<<sealed>>",
         "content_placeholder": True, "interrupted": True, "seq": 1},
    ]
    parts = _reconstruct(rows)[1].parts
    assert not any(p.kind == "text" for p in parts)  # placeholder not shown
    assert any(p.kind == "interrupted" for p in parts)  # badge shown


def test_placeholder_detection_is_narrow_and_shape_safe():
    """`is_placeholder_content` must not over- or under-reach:

    - list (multimodal) content never raises and is never filler;
    - a GENUINE reply equal to a literal renders (no corroborating structure);
    - the flag wins on any row shape, including a tool_calls row.
    """
    from app.backends.ms_agent.chat import is_placeholder_content

    # multimodal content: no TypeError from an unhashable value, not filler
    assert is_placeholder_content(
        {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}
    ) is False
    # genuine replies that happen to equal a literal: corroboration absent
    assert is_placeholder_content(
        {"role": "assistant", "content": "[interrupted]"}) is False
    assert is_placeholder_content(
        {"role": "assistant", "content": "Let me do a tool calling."}) is False
    # old-log fillers: literal + corroborating structure
    assert is_placeholder_content({
        "role": "assistant", "content": "[interrupted]", "interrupted": True
    }) is True
    assert is_placeholder_content({
        "role": "assistant", "content": "Let me do a tool calling.",
        "tool_calls": [{"id": "c1"}],
    }) is True
    # the structured flag is authoritative on any shape (incl. tool_calls rows)
    assert is_placeholder_content({
        "role": "assistant", "content": "whatever",
        "content_placeholder": True, "tool_calls": [{"id": "c1"}],
    }) is True


def test_reconstruct_survives_multimodal_assistant_content():
    """A list-content assistant row must not crash history rebuild (a raw
    ``content in {...}`` check would TypeError and 500 the whole session)."""
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {"role": "user", "content": "看图", "seq": 0},
        {"role": "assistant",
         "content": [{"type": "text", "text": "图里是一只猫"}], "seq": 1},
    ]
    parts = _reconstruct(rows)[1].parts
    assert any(p.kind == "text" for p in parts)  # rendered, not dropped


def test_reconstruct_keeps_genuine_reply_equal_to_literal():
    """A real answer whose text happens to equal a placeholder literal is NOT
    hidden (the literal fallback requires corroborating structure)."""
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {"role": "user", "content": "复述这句：[interrupted]", "seq": 0},
        {"role": "assistant", "content": "[interrupted]", "seq": 1},
    ]
    parts = _reconstruct(rows)[1].parts
    assert [p.text for p in parts if p.kind == "text"] == ["[interrupted]"]


def test_reconstruct_replays_interrupted_reasoning_duration():
    """A turn interrupted mid-thinking persists its partial reasoning under
    ``interrupted_reasoning`` plus ``reasoning_duration`` — replay shows the
    thought block with that elapsed time (not 0s)."""
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {"role": "user", "content": "想个方案", "seq": 0},
        {"role": "assistant", "content": "[interrupted]",
         "content_placeholder": True, "interrupted": True,
         "interrupted_reasoning": "正在权衡…", "reasoning_duration": 9,
         "seq": 1},
    ]
    parts = _reconstruct(rows)[1].parts
    thought = next(p for p in parts if p.kind == "thought")
    assert thought.text == "正在权衡…"
    assert thought.duration == 9  # not 0s


def test_reconstruct_interrupted_partial_text():
    """A faithfully-sealed mid-text interrupt replays its partial content
    verbatim plus an `interrupted` badge part — no fabricated text."""
    from app.backends.ms_agent.sessions import _reconstruct

    msgs = _reconstruct([
        {
            "role": "user",
            "content": "写篇长文",
            "seq": 0
        },
        {
            "role": "assistant",
            "content": "写到一半的回答",
            "interrupted": True,
            "seq": 1
        },
    ])
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[1].content == "写到一半的回答"
    assert [p.kind for p in msgs[1].parts] == ["text", "interrupted"]


def test_reconstruct_interrupted_reasoning_and_placeholder():
    """Unsigned partial reasoning replays as a thought; the neutral
    `[interrupted]` placeholder is never rendered as text."""
    from app.backends.ms_agent.sessions import _reconstruct

    msgs = _reconstruct([
        {
            "role": "user",
            "content": "推理题",
            "seq": 0
        },
        {
            "role": "assistant",
            "content": "[interrupted]",
            "interrupted_reasoning": "思考到一半…",
            "interrupted": True,
            "seq": 1
        },
    ])
    parts = msgs[1].parts
    assert [p.kind for p in parts] == ["thought", "interrupted"]
    assert parts[0].text == "思考到一半…"
    assert msgs[1].content == ""  # placeholder suppressed


def test_reconstruct_interrupted_mid_tools_marks_steps():
    """SDK-synthesized interrupted tool results mark their steps errored via
    the existing is_error path; the badge closes the turn."""
    from app.backends.ms_agent.sessions import _reconstruct

    msgs = _reconstruct([
        {
            "role": "user",
            "content": "跑工具",
            "seq": 0
        },
        {
            "role":
            "assistant",
            "content":
            "",
            "interrupted":
            True,
            "tool_calls": [{
                "id": "c1",
                "tool_name": "file_system---write_file",
                "arguments": '{"path": "a.md"}'
            }],
            "seq":
            1
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": "[Interrupted: tool execution was cancelled]",
            "is_error": True,
            "interrupted": True,
            "seq": 2
        },
    ])
    parts = msgs[1].parts
    assert [p.kind for p in parts] == ["step", "interrupted"]
    step = parts[0].step
    assert step.kind == "tool_call" and step.meta["status"] == "error"
    assert "Interrupted" in step.meta["error"]


def test_read_plan_prefers_session_scope_with_legacy_fallback(
        monkeypatch, tmp_path):
    """Plans are session-scoped (<session_dir>/plan.json); sessions from before
    the isolation change fall back to the project-shared plan.json."""
    import json as _json

    from app.backends.ms_agent import sessions

    proj_dir = tmp_path / "proj"
    sess_dir = tmp_path / "sessions" / "sid-1"
    proj_dir.mkdir()
    sess_dir.mkdir(parents=True)

    project = type("P", (), {"path": str(proj_dir)})()
    session = type("S", (), {"id": "sid-1"})()
    monkeypatch.setattr(sessions, "find_session", lambda sid:
                        (project, session, object()))
    monkeypatch.setattr("app.backends.ms_agent.config.session_dir",
                        lambda p, s: str(sess_dir))

    # Legacy project plan only -> fallback is used. (read_plan now returns a
    # SessionPlan: tasks + the "written during the running turn" flag; no
    # runtime here, so active stays False.)
    (proj_dir / "plan.json").write_text(
        _json.dumps({"todos": [{
            "content": "legacy",
            "status": "pending"
        }]}))
    plan = sessions.read_plan("sid-1")
    assert [t.label for t in plan.tasks] == ["legacy"]
    assert plan.active is False

    # Session-scoped plan appears -> it wins over the legacy file.
    (sess_dir / "plan.json").write_text(
        _json.dumps({"todos": [{
            "content": "mine",
            "status": "in_progress"
        }]}))
    plan = sessions.read_plan("sid-1")
    assert [(t.label, t.status) for t in plan.tasks] == [("mine", "running")]


def test_reconstruct_placeholder_only_interrupt_kept():
    """A cancel-before-first-chunk seal (placeholder-only row) still yields a
    visible assistant message carrying just the badge."""
    from app.backends.ms_agent.sessions import _reconstruct

    msgs = _reconstruct([
        {
            "role": "user",
            "content": "hi",
            "seq": 0
        },
        {
            "role": "assistant",
            "content": "[interrupted]",
            "interrupted": True,
            "seq": 1
        },
    ])
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert [p.kind for p in msgs[1].parts] == ["interrupted"]
    assert msgs[1].content == ""


async def test_registry_discard_closes_runtime_from_threadpool():
    registry = rt_mod.RuntimeRegistry()
    registry._loop = asyncio.get_running_loop()

    class _ClosableRuntime:

        def __init__(self):
            self.closed = False
            self.run_task = _FakeRunTask()

        async def aclose(self):
            self.closed = True

    fake_rt = _ClosableRuntime()
    registry._runtimes["sid-thread"] = fake_rt

    await asyncio.to_thread(registry.discard, "sid-thread")

    assert fake_rt.closed is True
    assert "sid-thread" not in registry._runtimes


def test_list_artifacts_ledger_from_session_log(monkeypatch, tmp_path):
    """The per-conversation artifact ledger is derived from the immutable
    SessionLog tool-calls: file_system write/edit only, deduped by path in
    first-write order, reads excluded, and a file gone from disk is kept as
    deleted (history is not erased by later user actions)."""
    from app.backends.ms_agent import sessions

    rows = [
        {
            "role": "user",
            "content": "make files",
            "seq": 0
        },
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "file_system---write_file",
                    "arguments": '{"path": "a.md", "content": "x"}'
                },
                {
                    "id": "c2",
                    "tool_name": "file_system---write_file",
                    "arguments": '{"path": "sub/b.txt", "content": "yy"}'
                },
            ],
            "seq":
            1
        },
        {
            "role":
            "assistant",
            "tool_calls": [
                # edit of a.md -> deduped (not a second entry)
                {
                    "id":
                    "c3",
                    "tool_name":
                    "file_system---edit_file",
                    "arguments":
                    '{"path": "a.md", "old_string": "x", "new_string": "z"}'
                },
                # a read -> excluded from the ledger
                {
                    "id": "c4",
                    "tool_name": "file_system---read_file",
                    "arguments": '{"path": "a.md"}'
                },
                # written but later deleted by the user -> kept, marked deleted
                {
                    "id": "c5",
                    "tool_name": "file_system---write_file",
                    "arguments": '{"path": "gone.md", "content": "d"}'
                },
            ],
            "seq":
            2
        },
    ]
    (tmp_path / "a.md").write_text("z")  # 1 byte
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("yy")  # 2 bytes
    # gone.md intentionally absent on disk

    project = type("P", (), {"path": str(tmp_path)})()
    sm = type("SM", (),
              {"get_session_log": staticmethod(lambda s: _FakeLog(rows))})()
    monkeypatch.setattr(sessions, "find_session", lambda sid:
                        (project, _FakeSession(), sm))

    arts = sessions.list_artifacts("sid-1")
    assert [a.path for a in arts] == ["a.md", "sub/b.txt",
                                      "gone.md"]  # order + dedup
    by = {a.path: a for a in arts}
    assert by["a.md"].deleted is False and by["a.md"].size == 1 and by[
        "a.md"].name == "a.md"
    assert by["sub/b.txt"].name == "b.txt" and by["sub/b.txt"].size == 2
    assert by["gone.md"].deleted is True and by["gone.md"].size == 0
    assert by["a.md"].id == sessions._artifact_id(
        "a.md")  # stable, path-derived


def test_list_artifacts_excludes_plan_and_out_of_workspace(
        monkeypatch, tmp_path):
    """The composer's file list (artifact ledger) must not show plan files or
    files written outside the workspace: the model copying its plan into the
    session dir, or rendering it under a custom name, are session/plan state —
    only genuine in-workspace deliverables are listed."""
    from app.backends.ms_agent import sessions

    rows = [
        {
            "role": "user",
            "content": "plan then build",
            "seq": 0
        },
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "todo_list---todo_render_md",
                    "arguments": '{"path": "my_plan.md"}'
                },
            ],
            "seq":
            1
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": "OK: rendered plan markdown to my_plan.md",
            "seq": 2
        },
        {
            "role":
            "assistant",
            "tool_calls": [
                {
                    "id": "c2",
                    "tool_name": "file_system---write_file",
                    "arguments": '{"path": "out.txt", "content": "x"}'
                },
                # plan copied into the session dir (outside the workspace)
                {
                    "id": "c3",
                    "tool_name": "file_system---write_file",
                    "arguments":
                    '{"path": "../sess/plan_copy.md", "content": "p"}'
                },
                # rewrite of the custom-named plan the render produced -> excluded
                {
                    "id":
                    "c4",
                    "tool_name":
                    "file_system---edit_file",
                    "arguments":
                    '{"path": "my_plan.md", "old_string": "a", '
                    '"new_string": "b"}'
                },
            ],
            "seq":
            3
        },
    ]
    (tmp_path / "out.txt").write_text("x")
    (tmp_path / "my_plan.md").write_text(
        "# plan")  # exists, but is a plan file

    project = type("P", (), {"path": str(tmp_path)})()
    sm = type("SM", (),
              {"get_session_log": staticmethod(lambda s: _FakeLog(rows))})()
    monkeypatch.setattr(sessions, "find_session", lambda sid:
                        (project, _FakeSession(), sm))

    arts = sessions.list_artifacts("sid-1")
    paths = [a.path for a in arts]
    assert paths == ["out.txt"]  # only the genuine deliverable


class _FakeSkill:

    def __init__(self, skill_id, name, content):
        self.skill_id = skill_id
        self.name = name
        self.description = f"{name} desc"
        self.content = content
        self.skill_path = f"/skills/{skill_id}"


class _FakeCatalog:

    def __init__(self, *skills):
        self._skills = {s.skill_id: s for s in skills}

    def get_skill(self, name):
        return self._skills.get(name)


class _CatalogRt:

    def __init__(self, catalog):
        self.agent = type("A", (), {"_skill_catalog": catalog})()


def test_expand_skill_request_two_tiers():
    """Tier 1 (structured ids) and tier 2 (anywhere-in-text token) both expand;
    unknown skills / no catalog fall through as plain text."""
    cat = _FakeCatalog(
        _FakeSkill("writer", "Writer",
                   "---\nname: Writer\n---\nGuide: $ARGUMENTS"))
    rt = _CatalogRt(cat)

    # Tier 1: structured id, /token anywhere in the text; args = text - token.
    kind, content, marker = chat._expand_skill_request(rt, "帮我 /Writer 改写这段",
                                                       ["writer"])
    assert kind == "submit"
    assert "Guide: 帮我 改写这段" in content  # $ARGUMENTS filled, token gone
    assert marker == {
        "original_text": "帮我 /Writer 改写这段",
        "skill_ids": ["writer"]
    }

    # Tier 2: no structured ids — first known /token found mid-text wins.
    kind, content, marker = chat._expand_skill_request(rt, "开始 /writer 润色", [])
    assert kind == "submit" and "User's request: 开始 润色" in content
    assert marker["skill_ids"] == ["writer"]

    # No-arg invocation -> the skill body submits too (the model reads it and
    # acts); the tail line flags the missing input, marker keeps the slash form.
    kind, content, marker = chat._expand_skill_request(rt, "/writer", [])
    assert kind == "submit"
    assert "Use the [Writer] skill" in content
    assert "without additional arguments" in content
    assert marker == {"original_text": "/writer", "skill_ids": ["writer"]}

    # Composer skill pick with no typed text: empty prompt, structured id only.
    # The marker falls back to the slash form for a readable replay bubble.
    kind, content, marker = chat._expand_skill_request(rt, "", ["writer"])
    assert kind == "submit" and "without additional arguments" in content
    assert marker == {"original_text": "/writer", "skill_ids": ["writer"]}

    # Unknown token / unknown structured id / no catalog -> passthrough.
    assert chat._expand_skill_request(rt, "看看 /nope 是什么", []) is None
    assert chat._expand_skill_request(rt, "普通消息", ["nope"]) is None
    assert chat._expand_skill_request(
        type("R", (), {"agent": None})(), "/x", []) is None
    # Mid-word slashes never trigger.
    assert chat._expand_skill_request(rt, "路径 a/writer 之类", []) is None


async def test_stream_message_kind_short_circuits_without_a_turn(monkeypatch):
    """The "message" expansion kind (kept as a fallback for non-submit
    CommandResult types — bare /skill now submits) answers directly: one text
    frame, no enqueued turn, lock released."""
    fake_rt = _FakeRuntime()
    monkeypatch.setattr(chat, "_resolve_or_create", lambda req:
                        (_FakeProject(), _FakeSession()))

    async def _fake_get(project, session):
        return fake_rt

    monkeypatch.setattr(chat.registry, "get", _fake_get)
    monkeypatch.setattr(
        chat, "_expand_skill_request", lambda rt, prompt, ids:
        ("message", "Skill: Writer", None))

    req = ChatRequest(session_id="sid-1",
                      message=ChatMessage(role="user", content="/writer"))
    frames = [json.loads(f["data"]) async for f in chat.stream(req)]
    # The early `session` frame precedes the reply text + terminator.
    assert [f["type"] for f in frames] == ["session", "text", "done"]
    assert frames[1]["content"] == "Skill: Writer"
    # The turn lock is taken for the sync+expand window but released for a
    # direct reply — and no turn was enqueued.
    assert not fake_rt.turn_lock.locked()
    assert fake_rt.input_queue.empty()
    assert fake_rt.watchers == 0


async def test_stream_slash_submit_enqueues_expanded_prompt_with_marker(
        monkeypatch):
    fake_rt = _FakeRuntime()
    monkeypatch.setattr(chat, "_resolve_or_create", lambda req:
                        (_FakeProject(), _FakeSession()))

    async def _fake_get(project, session):
        return fake_rt

    monkeypatch.setattr(chat.registry, "get", _fake_get)
    the_marker = {"original_text": "/writer go", "skill_ids": ["writer"]}
    monkeypatch.setattr(
        chat, "_expand_skill_request", lambda rt, prompt, ids:
        ("submit", "ENRICHED PROMPT", the_marker))

    req = ChatRequest(session_id="sid-1",
                      message=ChatMessage(role="user",
                                          content="/writer go",
                                          skills=["writer"]))
    frames: list[dict] = []

    async def _consume():
        async for f in chat.stream(req):
            frames.append(f)

    task = asyncio.create_task(_consume())
    # The expanded prompt (not the raw "/writer go") is what the agent runs,
    # and the display marker rides alongside for the input source to persist.
    item = await asyncio.wait_for(fake_rt.input_queue.get(), timeout=2)
    assert item == ("ENRICHED PROMPT", the_marker)
    fake_rt.sink.push({"type": rt_mod.TURN_END})
    await asyncio.wait_for(task, timeout=2)


def test_reconstruct_skill_invocation_shows_original_text():
    """History replay shows the user's typed text (from the display marker)
    instead of the expanded skill prompt persisted as the user row."""
    from app.backends.ms_agent.sessions import _reconstruct

    msgs = _reconstruct([
        {
            "_type": "skill_invocation",
            "original_text": "/writer 润色这段",
            "skill_ids": ["writer"],
            "seq": 0
        },
        {
            "role": "user",
            "content": "Use the [Writer] skill located at …",
            "seq": 1
        },
        {
            "role": "assistant",
            "content": "润色好了",
            "seq": 2
        },
    ])
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[0].content == "/writer 润色这段"  # original, not the wrapper
    assert msgs[1].content == "润色好了"


def _boom(msg):

    async def _fail(*a, **k):
        raise AssertionError(msg)

    return _fail


def test_sync_runtime_skills_picks_up_live_tree_drop(tmp_path):
    """Turn-boundary sync: a skill dropped into the project live tree after the
    agent was built becomes visible to the live catalog (and thus to slash
    expansion + the next system prompt)."""
    from omegaconf import OmegaConf

    from ms_agent.skill.catalog import SkillCatalog
    from ms_agent.skill.runtime import SkillRuntime
    from ms_agent.tui.managed_config import merge_skills_into_config
    from app.backends.ms_agent.common import home

    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    project = _FakeProject()
    project.path = str(proj_dir)

    cfg = OmegaConf.create({})
    merge_skills_into_config(cfg, home(),
                             project.path)  # baked at build: empty
    catalog = SkillCatalog(config=cfg.get("skills"))
    if cfg.get("skills"):
        catalog.load_from_config(cfg.skills)
    skill_runtime = SkillRuntime(catalog=catalog)
    agent = type("A", (), {"config": cfg, "_skill_runtime": skill_runtime})()
    rt = type("RT", (), {"agent": agent})()

    # Mid-session: drop a skill into the project live tree, no skills.json edit.
    tree = proj_dir / ".ms_agent" / "skills" / "late-skill"
    tree.mkdir(parents=True)
    (tree / "SKILL.md").write_text(
        "---\nname: late-skill\ndescription: added mid-session\n---\n# L\n",
        encoding="utf-8",
    )

    assert catalog.get_skill("late-skill") is None
    chat._sync_runtime_skills(rt, project)
    assert catalog.get_skill("late-skill") is not None
    assert skill_runtime.needs_refresh(
    )  # next round rebuilds the system prompt


def test_resolve_permission_forwards_allow_always_to_the_handler():
    """The three-way authorization card (deny / always allow / allow once) maps
    each action straight onto the SDK's PermissionAction — notably allow_always,
    which the enforcer persists so later identical calls skip the ask."""
    from ms_agent.permission.handler import PermissionAction

    seen: list[PermissionAction] = []

    class _Handler:

        def __init__(self) -> None:
            fut: asyncio.Future = asyncio.get_event_loop().create_future()
            self._pending = {"req-1": fut}

        def resolve(self, request_id, response):
            seen.append(response.action)
            self._pending[request_id].set_result(response)

    async def drive():
        registry = rt_mod.RuntimeRegistry()
        registry._runtimes["s1"] = type("RT", (),
                                        {"permission_handler": _Handler()})()

        assert registry.resolve_permission("s1", "req-1",
                                           "allow_always") is True
        assert seen == [PermissionAction.ALLOW_ALWAYS]
        # Already resolved / unknown request ids are rejected, not re-answered.
        assert registry.resolve_permission("s1", "req-1",
                                           "allow_once") is False
        assert registry.resolve_permission("s1", "nope", "deny") is False
        # An action outside the SDK enum must not resolve the turn.
        registry._runtimes["s2"] = type("RT", (),
                                        {"permission_handler": _Handler()})()
        assert registry.resolve_permission("s2", "req-1",
                                           "allow_forever") is False

    asyncio.run(drive())


def test_reconstruct_replays_tool_row_narration_but_filters_placeholder():
    """Real mid-turn narration on a tool_calls row replays verbatim, but the
    framework's 'Let me do a tool calling.' placeholder (SDK filler for a
    content-less tool-call turn, present in OLD logs) is filtered — it was never
    model output."""
    from app.backends.ms_agent.sessions import _reconstruct

    rows = [
        {
            "role": "user",
            "content": "go",
            "seq": 0
        },
        {
            "role":
            "assistant",
            "content":
            "I'll check the workspace first.",
            "tool_calls": [{
                "id": "c1",
                "tool_name": "file_system---glob",
                "arguments": "{}"
            }],
            "seq":
            1
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": "[]",
            "seq": 2
        },
        {
            "role":
            "assistant",
            "content":
            "Let me do a tool calling.",
            "tool_calls": [{
                "id": "c2",
                "tool_name": "file_system---grep",
                "arguments": "{}"
            }],
            "seq":
            3
        },
        {
            "role": "tool",
            "tool_call_id": "c2",
            "content": "[]",
            "seq": 4
        },
        {
            "role": "assistant",
            "content": "all done",
            "seq": 5
        },
    ]
    msgs = _reconstruct(rows)
    parts = msgs[1].parts
    # The placeholder row yields NO text part (filtered), so the two tool steps
    # sit adjacent between the real narration and the final summary.
    assert [p.kind for p in parts] == ["text", "step", "step", "text"]
    assert parts[0].text == "I'll check the workspace first."  # real narration
    assert parts[-1].text == "all done"                        # summary
    # The framework placeholder never surfaces as text.
    assert all(p.text != "Let me do a tool calling." for p in parts
               if p.kind == "text")


def test_seal_interrupted_turn_records_loop_end_duration():
    """A cancelled turn never reaches loop_end, so without this the replayed
    "processing Ns" header had no duration to show and rendered 0s. Sealing an
    interrupt records the boundary with the elapsed time up to the stop."""
    import time as _time

    class _LogWithLoopEnd(_FakeLog):

        def __init__(self, messages):
            super().__init__(messages)
            self.loop_ends: list[dict] = []

        def record_loop_end(self, event):
            self.loop_ends.append(event)

    log = _LogWithLoopEnd([
        {"role": "user", "content": "写长文"},
        # Partial answer the SDK persisted when the turn was cancelled.
        {"role": "assistant", "content": "开头…", "interrupted": True},
    ])
    rt = type("RT", (), {})()
    rt.agent = type("A", (), {"session_log": log})()
    rt.session = type("S", (), {"id": "s1"})()
    rt.project = None
    # Turn started ~2s ago on the monotonic clock the seal reads.
    rt.turn_started_at = _time.monotonic() - 2.0

    chat._seal_interrupted_turn(rt)

    assert len(log.loop_ends) == 1, "interrupt must record exactly one loop_end"
    duration = log.loop_ends[0]["duration_ms"]
    assert 1500 <= duration <= 4000, f"elapsed not carried over: {duration}"
    # The turn already ended on an assistant row → no extra placeholder row.
    assert log.get_all_messages()[-1]["content"] == "开头…"


def test_persist_loop_end_is_idempotent_per_turn():
    """One Stop drives BOTH the interrupt seal and the aborted-SSE drain, each
    calling _persist_loop_end_from_log for the same turn. Only ONE loop_end may
    be written (the 'at most one loop_end per turn' invariant)."""
    import time as _t

    class _Log:
        def __init__(self):
            self._all: list[dict] = []
            self._seq = 0

        def _next(self):
            s = self._seq
            self._seq += 1
            return s

        def get_all_messages(self):
            return [r for r in self._all if r.get("_type") is None]

        def append(self, rec):
            rec = {**rec, "seq": self._next()}
            self._all.append(rec)
            return rec["seq"]

        def record_loop_end(self, payload):
            self._all.append({"_type": "loop_end", "seq": self._next(), **payload})

        def get_loop_ends(self):
            return [r for r in self._all if r.get("_type") == "loop_end"]

    log = _Log()
    log.append({"role": "user", "content": "写长文"})
    log.append({"role": "assistant", "content": "开头…", "interrupted": True})
    rt = type("RT", (), {})()
    rt.agent = type("A", (), {"session_log": log})()
    rt.session = type("S", (), {"id": "s1"})()
    rt.project = None
    rt.turn_started_at = _t.monotonic() - 1.0

    chat._persist_loop_end_from_log(rt, "s1")  # e.g. the interrupt seal
    chat._persist_loop_end_from_log(rt, "s1")  # e.g. the aborted-SSE drain

    assert len(log.get_loop_ends()) == 1, "duplicate loop_end for one turn"


def test_interrupt_seals_while_holding_create_lock_and_removes_runtime():
    """The stop (pop + aclose + seal) runs entirely under _create_lock so a
    concurrent get() cannot build a second runtime on the same SessionLog while
    the interrupted turn is still being sealed (which lost the turn's history)."""
    reg = rt_mod.RuntimeRegistry()

    class _RT:
        async def aclose(self):
            pass

    reg._runtimes["s1"] = _RT()

    seen: dict = {}
    orig_seal = chat._seal_interrupted_turn

    def _spy(_rt):
        # interrupt() re-imports this from the chat module at call time, so the
        # patch is picked up; record whether the create lock is held right now.
        seen["locked_during_seal"] = reg._create_lock.locked()

    chat._seal_interrupted_turn = _spy
    try:
        stopped = asyncio.run(reg.interrupt("s1"))
    finally:
        chat._seal_interrupted_turn = orig_seal

    assert stopped is True
    assert seen.get("locked_during_seal") is True  # seal ran with the lock held
    assert "s1" not in reg._runtimes  # runtime removed by the stop
