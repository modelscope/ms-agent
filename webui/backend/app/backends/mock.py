"""Mock backend — in-memory seed data, no SDK required.

Chat streaming lives here (moved out of api/chat.py). Management endpoints still
read/write app.core.store directly in their routes when running on this backend;
methods are added here only as domains are ported to the facade.

The stream emits the same task/step view-model the real backend produces
(frontend/app/lib/agentProvider.ts), so `AGENT_BACKEND=mock` drives the full
message UI (thinking header, todo timeline, step cards) without an LLM.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.schemas.chat import ChatChunk, ChatRequest

MOCK_INTRO = "已为您创建项目并生成待办任务，点击任务可查看执行进度。\n\n"

MOCK_THOUGHT = (
    "先梳理用户意图，拆解成可执行的待办任务，再依次调用文件、终端、技能等工具，"
    "最后把产物写回工作区。"
)

MOCK_TERMINAL = (
    "if ! command -v flutter &>/dev/null; then\n"
    '  echo "===> installing Flutter..."\n'
    "  brew install --cask flutter\n"
    "fi\n"
)

# (task_id, label, [step meta, ...]) — one entry per frontend StepKind card.
_MOCK_TASKS: list[tuple[str, str, list[dict]]] = [
    ("1", "任务一：解析输入并制定计划", [{"kind": "tool_call", "name": "planner"}]),
    ("2", "任务二：在终端安装依赖", [
        {"kind": "terminal", "code": MOCK_TERMINAL, "language": "shell"},
    ]),
    ("3", "任务三：读写工作区文件", [
        {"kind": "file_read", "path": "docs/spec.md"},
        {"kind": "file_write", "path": "report/outline.md"},
    ]),
    ("4", "任务四：加载技能并检索资料", [
        {"kind": "skill_load", "name": "writer"},
        {"kind": "browser", "title": "参考资料页面", "url": "https://example.com/report"},
    ]),
    ("5", "任务五：产出交付物", [
        {"kind": "artifact", "name": "报告.pdf", "file_type": "pdf", "byte": 1310720},
    ]),
]


def _tokenize(text: str) -> list[str]:
    """Tiny pseudo-tokenizer that keeps markdown roughly intact."""
    out: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in " \n,.;!?，。；！？":
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def _delta(chunk: ChatChunk) -> dict:
    # Plain SSE `data:` frame (default `message` event); frontend routes on
    # the payload's `type`, terminal frame is a chunk with type=="done".
    return {"data": chunk.model_dump_json()}


class MockBackend:
    def chat_stream(self, req: ChatRequest) -> AsyncIterator[dict]:
        return self._mock_stream(req)

    def chat_attach(self, session_id: str) -> AsyncIterator[dict]:
        # Mock turns are never in flight between requests: nothing to attach.
        return self._mock_attach(session_id)

    async def _mock_attach(self, session_id: str) -> AsyncIterator[dict]:
        yield _delta(ChatChunk(type="done", meta={"session_id": session_id}))

    async def _mock_stream(self, req: ChatRequest) -> AsyncIterator[dict]:
        last_user = req.message.content if req.message else ""

        # 1. one reasoning block (drives the "thinking Ns" header).
        yield _delta(ChatChunk(
            type="thought",
            content=f"用户意图：{last_user[:80]}\n{MOCK_THOUGHT}" if last_user else MOCK_THOUGHT,
            meta={"duration": 6},
        ))
        await asyncio.sleep(0.2)

        # 2. streamed markdown body.
        for token in _tokenize(MOCK_INTRO):
            yield _delta(ChatChunk(type="text", content=token))
            await asyncio.sleep(0.02)

        # 3. todo timeline: each task flips running -> done, with nested steps.
        for task_id, label, steps in _MOCK_TASKS:
            yield _delta(ChatChunk(
                type="task", meta={"id": task_id, "label": label, "status": "running"}))
            await asyncio.sleep(0.15)
            for step in steps:
                yield _delta(ChatChunk(type="step", meta={**step, "task_id": task_id}))
                await asyncio.sleep(0.12)
            yield _delta(ChatChunk(
                type="task", meta={"id": task_id, "label": label, "status": "done"}))

        # 4. terminator.
        yield {"data": ChatChunk(
            type="done", meta={"session_id": req.session_id or "demo"}
        ).model_dump_json()}
