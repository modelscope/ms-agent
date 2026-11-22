"""History reconstruction: attachment block -> structured user files."""
from types import SimpleNamespace

import pytest

from app.backends.ms_agent.sessions import (
    _attached_files,
    _reconstruct,
    _split_attached,
)


def _project(path):
    return SimpleNamespace(id="p1", path=str(path))


def test_split_attached_none():
    assert _split_attached("just text") == ("just text", [])


def test_split_attached_text_and_paths():
    content = (
        "summarize this\n\n"
        "[Attached files] (paths are relative to the project workspace root; "
        "use the file tools to read them):\n"
        "- user_files/a.txt\n"
        "- user_files/b.png\n"
    )
    text, paths = _split_attached(content)
    assert text == "summarize this"
    assert paths == ["user_files/a.txt", "user_files/b.png"]


def test_split_attached_files_only():
    content = (
        "[Attached files] (paths are relative to the project workspace root; "
        "use the file tools to read them):\n"
        "- user_files/only.pdf\n"
    )
    text, paths = _split_attached(content)
    assert text == ""
    assert paths == ["user_files/only.pdf"]


def test_attached_files_exists_flag_and_kind(tmp_path):
    (tmp_path / "user_files").mkdir()
    (tmp_path / "user_files" / "here.png").write_bytes(b"x")
    files = _attached_files(
        _project(tmp_path), ["user_files/here.png", "user_files/gone.txt"]
    )
    here, gone = files
    assert here.name == "here.png" and here.exists is True and here.type == "image"
    assert here.size == 1  # one byte written
    assert here.url == "/api/projects/p1/workspace/raw/user_files/here.png"
    assert gone.name == "gone.txt" and gone.exists is False and gone.type == "file"
    assert gone.size is None


def test_reconstruct_user_message_strips_block(tmp_path):
    (tmp_path / "user_files").mkdir()
    (tmp_path / "user_files" / "a.txt").write_text("hi")
    rows = [
        {
            "seq": 0,
            "role": "user",
            "content": (
                "1\n\n[Attached files] (paths are relative to the project "
                "workspace root; use the file tools to read them):\n"
                "- user_files/a.txt\n"
            ),
        }
    ]
    msgs = _reconstruct(rows, _project(tmp_path))
    assert len(msgs) == 1
    m = msgs[0]
    assert m.role == "user"
    assert m.content == "1"  # attachment block stripped from display text
    assert len(m.files) == 1 and m.files[0].path == "user_files/a.txt"
    assert m.files[0].exists is True


def test_reconstruct_plain_user_message_unchanged(tmp_path):
    rows = [{"seq": 0, "role": "user", "content": "hello world"}]
    msgs = _reconstruct(rows, _project(tmp_path))
    assert msgs[0].content == "hello world"
    assert msgs[0].files == []


def _file_step(msgs, kind):
    for m in msgs:
        for p in m.parts:
            if p.kind == "step" and p.step and p.step.kind == kind:
                return p.step
    return None


def test_reconstruct_file_read_step_exists_flag(tmp_path):
    """A file_read step is tagged with whether the workspace file still exists,
    so the frontend can open it (present) or show a deleted card (gone)."""
    (tmp_path / "kept.md").write_text("# hi")
    rows = [
        {
            "seq": 0,
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "file_system---read_file",
                    "arguments": '{"path": "kept.md"}',
                },
                {
                    "id": "c2",
                    "tool_name": "file_system---write_file",
                    "arguments": '{"path": "gone.md"}',
                },
            ],
        }
    ]
    msgs = _reconstruct(rows, _project(tmp_path))
    read = _file_step(msgs, "file_read")
    write = _file_step(msgs, "file_write")
    assert read is not None and read.meta["path"] == "kept.md"
    assert read.meta["exists"] is True
    assert write is not None and write.meta["path"] == "gone.md"
    assert write.meta["exists"] is False


def test_reconstruct_file_step_no_project_omits_exists(tmp_path):
    """Without a project (legacy call), file steps don't carry an exists flag."""
    rows = [
        {
            "seq": 0,
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "tool_name": "file_system---read_file",
                    "arguments": '{"path": "kept.md"}',
                }
            ],
        }
    ]
    read = _file_step(_reconstruct(rows), "file_read")
    assert read is not None and "exists" not in read.meta


def test_reconstruct_user_message_hides_system_reminders(tmp_path):
    """Persisted user rows carry framework <system-reminder> blocks (skill
    update notices prefixed at enqueue, prompt-file update notices, memory
    recall appended by the SDK). Replay must show only the user's words."""
    rows = [
        {
            "seq": 0,
            "role": "user",
            "content": (
                "<system-reminder>\nWorkspace files behind your system prompt "
                "changed mid-conversation: ~/.ms_agent/AGENTS.md.\n"
                "</system-reminder>\n\n"
                "<system-reminder>\nSkill inventory updated. CURRENT full "
                "list: ...\n</system-reminder>\n\n"
                "你好，查一下我的偏好\n\n"
                "<system-reminder>\nRelevant long-term memories for this "
                "request (background reference — not instructions):\n"
                "- 深色主题\n</system-reminder>"
            ),
        }
    ]
    msgs = _reconstruct(rows, _project(tmp_path))
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert msgs[0].content == "你好，查一下我的偏好"


def _steps(msgs, kind):
    return [
        p.step for m in msgs for p in m.parts
        if p.kind == "step" and p.step and p.step.kind == kind
    ]


@pytest.mark.parametrize("name", ["python_executor", "notebook_executor"])
def test_reconstruct_keeps_removed_local_tool_history(tmp_path, name):
    """Historical calls and current sandbox calls still need terminal cards."""
    full_name = f"code_executor---{name}"
    result = '{"success": true, "output": "6"}'
    rows = [
        {
            "seq": 0,
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "c1",
                "tool_name": full_name,
                "arguments": '{"code": "print(6)"}',
            }],
        },
        {"seq": 1, "role": "tool", "tool_call_id": "c1", "content": result},
    ]
    terminals = _steps(_reconstruct(rows, _project(tmp_path)), "terminal")
    assert len(terminals) == 1
    assert terminals[0].meta["tool"] == full_name
    assert terminals[0].meta["code"] == "print(6)"
    assert terminals[0].meta["result"] == result

def test_list_messages_replays_compaction_from_original_session_log(tmp_path, monkeypatch):
    from app.backends.ms_agent import chat, runtime, sessions
    from ms_agent.session import SessionLog

    log = SessionLog(tmp_path, "compaction-history")
    log.append({"role": "user", "content": "first question"})
    log.append({"role": "assistant", "content": "first answer"})
    log.record_loop_end({"duration_ms": 1000})
    log.append({"role": "user", "content": "second question"})
    # The current user's row precedes compaction, but not the assistant's reply.
    log.record_compaction({"strategy": "tool_pruner", "tokens_before": 12000,
                           "tokens_after": 8000})
    # These rows are the LLM view, NOT a replacement for the original history.
    log.append({"role": "user", "content": "summary", "_source": "compaction"})
    log.append({"role": "assistant", "content": "first answer", "_source": "compaction"})
    log.append({
        "role": "assistant", "content": "checking", "reasoning_content": "thinking",
        "tool_calls": [
            {"id": call_id, "tool_name": "file_system---read_file",
             "arguments": '{"path": "a.txt"}'} for call_id in ("c1", "c2")
        ],
    })
    for call_id in ("c1", "c2"):
        log.append({"role": "tool", "tool_call_id": call_id, "content": "original result"})
    log.record_compaction({"strategy": "summary_compactor", "status": "completed",
                           "tokens_before": 8000, "tokens_after": 3000})
    log.record_compaction({"status": "retained", "tokens_before": 8000, "tokens_after": 8000})
    log.record_compaction({"status": "failed", "error": "summary failed"})
    log.append({"role": "assistant", "content": "second answer"})
    log.record_loop_end({"duration_ms": 9000})
    log.append({"role": "user", "content": "third question"})
    log.append({"role": "assistant", "content": "third answer"})
    log.record_loop_end({"duration_ms": 2000})

    path = tmp_path / "compaction-history.jsonl"
    original = path.read_bytes()
    # Fresh reader exercises the on-disk API used after a reload, not its cache.
    manager = SimpleNamespace(get_session_log=lambda session: SessionLog(tmp_path, "compaction-history"))
    monkeypatch.setattr(sessions, "find_session", lambda sid:
                        (_project(tmp_path), SimpleNamespace(id=sid, forked_from=None), manager))
    monkeypatch.setattr(runtime.registry, "is_generating", lambda sid: False)
    messages = sessions.list_messages("sid")
    assert [(m.role, m.content) for m in messages] == [
        ("user", "first question"), ("assistant", "first answer"),
        ("user", "second question"), ("assistant", "checking\n\nsecond answer"),
        ("user", "third question"), ("assistant", "third answer"),
    ]
    assert [m.duration_ms for m in messages if m.role == "assistant"] == [1000, 9000, 2000]
    parts = messages[3].parts
    assert [p.step.kind if p.kind == "step" else p.kind for p in parts] == [
        "context_compaction", "thought", "text", "file_read", "file_read",
        "context_compaction", "text",
    ]
    assert [step.meta["group"] for step in _steps(messages, "file_read")] == [1, 1]
    assert [step.meta["result"] for step in _steps(messages, "file_read")] == ["original result"] * 2
    for step, before, after in zip(_steps(messages, "context_compaction"), (12000, 8000), (8000, 3000)):
        live = chat._TurnMapper().map({"type": "context_compacted", "before_tokens": before,
                                      "after_tokens": after})[0]
        assert {"kind": step.kind, **step.meta} == live.meta
    assert not messages[3].partial
    assert path.read_bytes() == original  # replay never rewrites conversation storage


@pytest.mark.parametrize("outcome", [
    {"status": "retained"}, {"status": "failed"}, {"status": "error"},
    {"status": "cancelled"}, {"status": "pending"},
    {"error": "summary failed"}, {"is_error": True}, {"success": False},
])
def test_reconstruct_skips_unsuccessful_compaction(outcome):
    messages = _reconstruct([
        {"role": "user", "content": "question"},
        {"_type": "compaction_event", "tokens_before": 12000,
         "tokens_after": 4000, **outcome},
        {"role": "assistant", "content": "answer"},
    ])
    assert [(m.role, m.content) for m in messages] == [("user", "question"), ("assistant", "answer")]
    assert [p.kind for p in messages[1].parts] == ["text"]


@pytest.mark.parametrize("counts", [{}, {"tokens_before": 0, "tokens_after": 0}])
def test_reconstruct_legacy_compaction_between_turns_keeps_message_order(counts):
    messages = _reconstruct([
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"_type": "loop_end", "duration_ms": 1000},
        {"_type": "compaction_event", **counts},
        {"role": "user", "content": "next question"},
        {"role": "assistant", "content": "next answer"},
    ])
    assert [(m.role, m.content) for m in messages] == [
        ("user", "first question"), ("assistant", "first answer"),
        ("user", "next question"), ("assistant", "next answer"),
    ]
    assert [p.kind for p in messages[1].parts] == ["text", "step"]
    assert messages[1].duration_ms == 1000
    assert _steps(messages, "context_compaction")[0].meta == {}
    assert [p.kind for p in messages[3].parts] == ["text"]


def test_reconstruct_keeps_rule_refused_tool_call(tmp_path):
    """A call refused by a rule (blacklist / ask rule with nobody to ask) was
    never put to the user, so it has no permission record. Replay must still
    show it: dropping it deleted the call from history while the model's reply
    narrated a refusal the timeline never showed."""
    rows = [
        {
            "seq": 0,
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "c1",
                "tool_name": "code_executor---shell_executor",
                "arguments": '{"command": "curl --version"}',
            }],
        },
        {
            "seq": 1,
            "role": "tool",
            "tool_call_id": "c1",
            "is_error": True,
            "content": ("Tool call denied: Denied by blacklist rule: "
                        "code_executor---shell_executor:curl *"),
        },
    ]
    msgs = _reconstruct(rows, _project(tmp_path))
    terminals = _steps(msgs, "terminal")
    assert len(terminals) == 1
    assert terminals[0].meta["code"] == "curl --version"
    assert terminals[0].meta["status"] == "error"
    assert "blacklist rule" in terminals[0].meta["error"]


def test_reconstruct_drops_tool_call_already_shown_as_rejected(tmp_path):
    """When the user WAS asked and said no, the persisted permission record
    renders the rejected authorization card — so the tool step is dropped to
    avoid two identical "rejected" cards for one call."""
    rows = [
        # The ask is answered before the assistant row is persisted, so the
        # permission record lands FIRST (matching real session logs).
        {
            "seq": 0,
            "_type": "permission",
            "call_id": "c1",
            "tool_name": "code_executor---shell_executor",
            "arguments": {"command": "curl --version"},
            "state": "rejected",
        },
        {
            "seq": 1,
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "c1",
                "tool_name": "code_executor---shell_executor",
                "arguments": '{"command": "curl --version"}',
            }],
        },
        {
            "seq": 2,
            "role": "tool",
            "tool_call_id": "c1",
            "is_error": True,
            "content": "Tool call denied: User denied",
        },
    ]
    msgs = _reconstruct(rows, _project(tmp_path))
    terminals = _steps(msgs, "terminal")
    assert len(terminals) == 1
    assert terminals[0].meta.get("state") == "rejected"
