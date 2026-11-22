"""The live stream and a reload must expose the same durable tool image."""
from app.backends.ms_agent.chat import _TurnMapper
from app.backends.ms_agent.sessions import _reconstruct


def test_tool_image_survives_live_and_history_mapping():
    attachments = [{"type": "image", "path": ".ms_agent/artifacts/images/a.png", "media_type": "image/png"}]
    live = _TurnMapper().map({
        "type": "tool_call_completed", "call_id": "c1", "name": "camera---image",
        "result": "image saved", "attachments": attachments,
    })
    assert live[0].meta["attachments"] == attachments
    rows = [
        {"seq": 0, "role": "user", "content": "show image"},
        {"seq": 1, "role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "tool_name": "camera---image", "arguments": "{}"}]},
        {"seq": 2, "role": "tool", "content": "image saved", "tool_call_id": "c1", "attachments": attachments},
        {"seq": 3, "role": "assistant", "content": "red square"},
    ]
    replay = [p.step for m in _reconstruct(rows) for p in m.parts if p.step]
    assert replay[0].meta["attachments"] == attachments
