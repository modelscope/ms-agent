# Copyright (c) ModelScope Contributors. All rights reserved.
"""UI-agnostic asynchronous input contract.

The agent's interactive loop obtains the next user prompt through an
:class:`InputSource`. Making ``read_prompt`` *awaitable* is what lets a rich
TUI (and a future WebUI backend) drive the native ``run_loop`` without the
input read blocking the event loop or fighting a streaming renderer for the
terminal — the enabling seam for "route A" (agent owns one lifecycle).

* **TUI** implements it over ``prompt_toolkit.PromptSession.prompt_async``.
* **WebUI backend** implements it as ``await queue.get()`` (input pushed by a
  WebSocket handler).
* **CLI** default is :class:`StdinInputSource` — a blocking ``input()`` run in
  a thread executor, so behavior is identical to bare ``input()`` while still
  cooperating with asyncio.

Pure stdlib; no front-end dependencies.
"""
from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable


@runtime_checkable
class InputSource(Protocol):
    """Async source of user prompts.

    ``read_prompt`` should raise ``EOFError`` (end of input) or
    ``KeyboardInterrupt`` (user abort) to signal that the session should quit;
    callers (``InteractiveSession``) translate those into a quit turn.
    """

    async def read_prompt(self, prompt: str = '>>> ') -> str:
        ...


class StdinInputSource:
    """Default input source: blocking ``input()`` off the event loop.

    Functionally identical to bare ``input()`` (still blocks for a line), but
    runs in the default executor so a single asyncio loop stays responsive to
    other tasks (e.g. a concurrent ``/stop`` reader) while awaiting input.
    """

    async def read_prompt(self, prompt: str = '>>> ') -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, input, prompt)
