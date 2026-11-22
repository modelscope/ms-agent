"""Per-image delivery: reported live, persisted per turn, and forgettable.

The WebUI had no vision tests at all while it was writing a permanent claim
about every attached image into the session log. These cover the three things it
now owes the user:

* the turn text asserts nothing about visibility (that is the transport's to
  say, and only it knows);
* what actually happened is reported and survives a reload, so a reader can tell
  "the model never received it" from "the model received it and made something
  up";
* an observed refusal can be revoked without restarting the backend.
"""
import pytest

from app.backends.ms_agent import chat, models, sessions
from app.schemas.chat import ChatFile, ChatMessage


# --------------------------------------------------------------------------- #
# Nothing durable may claim visibility
# --------------------------------------------------------------------------- #
def test_composed_turn_makes_no_claim_about_what_the_model_will_see():
    prompt, attachments = chat._compose_turn(
        ChatMessage(
            role="user",
            content="what is this",
            files=[ChatFile(name="a.png", path="user_files/a.png")]))
    assert attachments and attachments[0]["type"] == "image"
    # This text is persisted verbatim and replayed on every later request, so a
    # claim made here outlives the state it described. All of these were in it.
    for banned in ("shown to you directly above", "no need to read those",
                   "use the file tools to read them"):
        assert banned not in prompt
    # The durable file mapping still works: replay rebuilds cards from it.
    assert "- user_files/a.png" in prompt


def test_path_lines_stay_parseable_for_replay():
    prompt, _ = chat._compose_turn(
        ChatMessage(
            role="user",
            content="x",
            files=[ChatFile(name="screenshot (1).png",
                            path="user_files/screenshot (1).png")]))
    lines = [ln[2:] for ln in prompt.splitlines() if ln.startswith("- ")]
    # A filename may legally contain " (", so an inline annotation on this line
    # would be unrecoverable. It has none.
    assert lines == ["user_files/screenshot (1).png"]


# --------------------------------------------------------------------------- #
# Live reporting
# --------------------------------------------------------------------------- #
def _map(mapper, etype, **payload):
    return mapper.map({"type": etype, **payload})


class TestDeliveryEvent:

    def _mapper(self):
        return chat._TurnMapper(session_id="s1")

    def test_degraded_image_produces_an_actionable_step(self):
        m = self._mapper()
        chunks = _map(
            m,
            "image_delivered",
            index=1,
            path="user_files/a.png",
            filename="a.png",
            state="degraded",
            reason="endpoint_rejected")
        assert len(chunks) == 1
        meta = chunks[0].meta
        assert meta["kind"] == "image_delivery"
        assert meta["state"] == "degraded"
        # A machine code, so the sentence the user reads is ours and stays
        # accurate — rather than whatever the model improvised.
        assert meta["reason"] == "endpoint_rejected"
        assert meta["filename"] == "a.png"

    def test_delivered_image_is_still_reported(self):
        # The badge's most valuable case: the picture DID arrive, so a model
        # that describes it wrongly is a model problem, not a config problem.
        m = self._mapper()
        chunks = _map(
            m,
            "image_delivered",
            index=1,
            path="user_files/a.png",
            filename="a.png",
            state="delivered")
        assert chunks[0].meta["state"] == "delivered"

    def test_deliveries_accumulate_on_the_mapper(self):
        m = self._mapper()
        for i, state in enumerate(("delivered", "degraded"), start=1):
            _map(
                m,
                "image_delivered",
                index=i,
                path=f"user_files/{i}.png",
                filename=f"{i}.png",
                state=state)
        assert [d["state"] for d in m._deliveries] == ["delivered", "degraded"]

    def test_unknown_event_types_are_still_ignored(self):
        assert _map(self._mapper(), "something_new", foo=1) == []


# --------------------------------------------------------------------------- #
# Persistence across a reload
# --------------------------------------------------------------------------- #
class _Project:
    id = "p1"

    def __init__(self, tmp_path):
        self.path = str(tmp_path)


def test_attached_files_carry_their_recorded_delivery(tmp_path):
    (tmp_path / "user_files").mkdir()
    (tmp_path / "user_files" / "a.png").write_bytes(b"x")
    files = sessions._attached_files(
        _Project(tmp_path), ["user_files/a.png"],
        {"user_files/a.png": "degraded"})
    assert files[0].delivery == "degraded"


def test_delivery_is_optional_for_older_turns(tmp_path):
    (tmp_path / "user_files").mkdir()
    (tmp_path / "user_files" / "a.png").write_bytes(b"x")
    files = sessions._attached_files(_Project(tmp_path), ["user_files/a.png"])
    # Turns recorded before this existed simply have nothing to show, which the
    # frontend renders as no badge rather than as a wrong one.
    assert files[0].delivery is None


def test_reconstruct_reads_the_stamped_attachment(tmp_path):
    (tmp_path / "user_files").mkdir()
    (tmp_path / "user_files" / "a.png").write_bytes(b"x")
    rows = [{
        "role":
        "user",
        "content":
        "look\n\n[Attached files] (paths are relative to the project "
        "workspace root):\n- user_files/a.png",
        "attachments": [{
            "type": "image",
            "path": "user_files/a.png",
            "delivery": "degraded",
        }],
    }]
    out = sessions._reconstruct(rows, _Project(tmp_path))
    user = [m for m in out if m.role == "user"][0]
    assert [f.delivery for f in user.files] == ["degraded"]


# --------------------------------------------------------------------------- #
# Session model memory
# --------------------------------------------------------------------------- #
def test_degraded_image_notice_uses_the_turn_model():
    from app.backends.ms_agent.mapping import encode_model_id

    mapper = chat._TurnMapper("s1", model_key=("anthropic", "original"))
    frames = mapper.map({"type": "image_delivered", "state": "degraded", "index": 0})
    assert frames[0].meta["model"] == encode_model_id("anthropic", "original")


def test_session_schema_carries_the_model(monkeypatch):
    from app.backends.ms_agent import mapping

    class _S:
        id = "s1"
        name = "t"
        project_id = "p"
        updated_at = __import__("datetime").datetime.now()

    monkeypatch.setattr(mapping.sidecar, "get",
                        lambda kind, key, default=None: {"model_id": mapping.encode_model_id("openai", "M1")})
    assert mapping.session_to_schema(_S()).model_id == mapping.encode_model_id("openai", "M1")
