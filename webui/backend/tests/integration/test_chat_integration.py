"""Integration tests hitting a real LLM. Opt-in:

    RUN_INTEGRATION=1 uv run pytest tests/integration

Guards the two SessionLog-persistence-timing fixes (ms-agent run_loop):
  * a turn's assistant reply is persisted at turn end (not one turn late), and
  * resuming a session does not re-answer the previous user turn.
"""
import json
import os

import pytest

from app.core.settings import settings

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1" or not settings.openai_api_key,
    reason="integration test — set RUN_INTEGRATION=1 with a real LLM key in ../.env",
)


async def _turn(session_id, content):
    from app.backends.ms_agent import chat
    from app.schemas.chat import ChatMessage, ChatRequest

    req = ChatRequest(session_id=session_id, messages=[ChatMessage(role="user", content=content)])
    text, sid = "", session_id
    async for frame in chat.stream(req):
        d = json.loads(frame["data"])
        if d["type"] == "done":
            sid = d["meta"]["session_id"]
            break
        if d["type"] == "text":
            text += d["content"]
    return sid, text


async def test_assistant_persisted_at_turn_end():
    from app.backends.ms_agent.bootstrap import bootstrap
    from app.backends.ms_agent.common import find_session

    bootstrap()
    sid, _ = await _turn(None, "Reply with exactly: pong")
    _proj, sess, sm = find_session(sid)
    roles = [m["role"] for m in sm.get_session_log(sess).get_all_messages()]
    assert roles and roles[-1] == "assistant", f"assistant not persisted at turn end: {roles}"


async def test_resume_does_not_reanswer():
    from app.backends.ms_agent.bootstrap import bootstrap
    from app.backends.ms_agent.runtime import registry

    bootstrap()
    sid, _ = await _turn(None, "Remember the word MANGO. Reply with just: OK")
    await registry.close_all()  # simulate a restart -> forces rebuild + resume
    sid2, t2 = await _turn(sid, "What word did I ask you to remember? One word.")
    assert sid2 == sid
    assert "MANGO" in t2.upper(), "context not restored on resume"
    assert "OK" not in t2.upper().replace("MANGO", ""), f"resume re-answered previous turn: {t2!r}"
