# Copyright (c) ModelScope Contributors. All rights reserved.
"""Telling a model that what it can do has changed since the earlier turns.

A conversation carries no trace of which model produced which turn, or of what
that model was allowed to do at the time. Everything reads as one continuous
participant, so when capabilities change mid-conversation the model has to
explain the resulting contradiction with what it has — and what it has *is* the
contradiction.

Measured, without this notice:

* a session read two images correctly under a vision model, then continued on a
  text-only one. The new model, seeing the images marked absent next to a
  detailed description of them in its own voice, concluded the description had
  been a hallucination and retracted it;
* with the SAME model and only the image switch turned off, a model that had
  just read one picture went on to describe the next one from its filename —
  it had no reason to think anything about it had changed.

Two things change what a model can do, and both are announced here:

* **which model** is answering — capabilities differ across models;
* **what that model is permitted to receive** — the per-model image switch.

The notice is about identity and permission, not about images specifically: the
same blind spot produces the same class of error for tool availability or
context length, so the wording generalises.

Mirrors ``prompting/workspace_files.render_update_notice`` — same shape, same
voice, same reason for existing ("the files changed — you did not misremember").
"""
from __future__ import annotations

from typing import Optional

MODEL_SWITCH_MARKER = 'Mid-conversation change'


def capability_signature(model: str, images_enabled: bool) -> str:
    """A comparable record of "who is answering, and with what permitted".

    Stored on the session so the next turn can tell whether either half moved.
    """
    return f'{model or ""}|images:{"on" if images_enabled else "off"}'


def _parse(signature: str) -> tuple:
    model, _, images = (signature or '').partition('|')
    return model, images == 'images:on'


def render_capability_change_notice(previous: str,
                                    current: str) -> Optional[str]:
    """The ``<system-reminder>`` for a mid-conversation capability change.

    ``None`` when nothing that matters moved.
    """
    old_model, old_images = _parse(previous)
    new_model, new_images = _parse(current)
    changes = []
    if old_model and new_model and old_model != new_model:
        changes.append(f'earlier turns were answered by "{old_model}", this '
                       f'turn by "{new_model}"')
    if old_images != new_images:
        changes.append(
            f'image understanding is now {"on" if new_images else "off"}, so '
            f'images {"are sent again" if new_images else "are no longer sent"}')
    if not changes:
        return None
    return ('<system-reminder>\n'
            f'{MODEL_SWITCH_MARKER}: {"; ".join(changes)}. Earlier replies were '
            'produced under the previous setup — treat them as sound unless you '
            'have positive evidence otherwise, and do not retract them merely '
            'because you cannot reproduce them now. Do not mention this unless '
            'the user asks.\n'
            '</system-reminder>')
