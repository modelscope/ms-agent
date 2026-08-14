"""MemoryOrchestrator — thin proxy that delegates to a MemoryBackend.

The Orchestrator itself contains NO business logic about storage formats,
prompt injection, retrieval strategies, or tool definitions.  All of that
lives inside the MemoryBackend implementation selected by configuration.

What it DOES own is the write/read discipline around the backend:

* **Serialization** — every access to the store (``run``, ``add``, ``search``,
  ``flush``, teardown) takes one asyncio lock per *store*, because embedded
  vector stores (mem0 + local qdrant) have no internal locking at all and
  mem0 even fans out worker threads inside ``add``. Lock per store, not per
  orchestrator: a transient client (the WebUI's read path) may be on the same
  directory.
* **Background ingestion** — ``schedule_add`` takes the extraction-LLM +
  embedding cost (seconds) off the turn's critical path. Tasks are retained
  for ``flush_pending`` so a teardown cannot silently drop the last write.
  If no loop is running the write happens inline — slower, never lost.
* **Delta ledger** — every ingested message's content hash is remembered
  (in memory + ``<base_dir>/ingest_state.json``), so each ingest sends only
  the messages the store has not seen. Without this, every ingest re-sent
  the whole conversation: cost O(rounds x history), and re-extraction of old
  turns. Hashes are only recorded AFTER a successful backend write, so a
  failed ingest retries naturally on the next turn (the analog of a
  watermark that only advances on a confirmed write).
* **Status** — ``ingest_status`` reports the last ingest outcome so a UI can
  show "memory updated / failed" instead of silence.

Registered as ``unified_memory`` in ``memory_mapping``.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time
from dataclasses import fields
from typing import Any, Dict, List, Optional, Set

from ms_agent.llm.utils import Message
from ms_agent.memory.base import Memory
# Single canonical deserializer, shared with ContextAssembler. A second local
# copy previously drifted and silently dropped `tool_call_id` / `name`.
from ms_agent.session.context_assembler import _dicts_to_messages
from ms_agent.utils.logger import get_logger
from .config import MemoryConfig
from .protocols import (RECALL_BLOCK_MARKER, MemoryBackend, MemoryEntry)
from .registry import backend_registry

logger = get_logger()

# One lock per storage directory. Never per orchestrator instance: the HTTP
# read path and any other transient client over the same path must serialize
# against this orchestrator's writes.
#
# Keyed by (loop, path), not path alone: an asyncio.Lock binds itself to the
# loop that first has to *wait* on it, and raises for good once a second loop
# contends. A process that runs more than one loop over its lifetime -- the
# inline `asyncio.run` ingest path below, a test suite calling asyncio.run per
# case, a notebook -- would otherwise wedge on a lock belonging to a loop that
# is already closed. Same shape as PermissionEnforcer._ask_lock_for_loop.
# (Two loops alive at once over one store still get one lock each and would not
# exclude each other; that is inherent to any per-loop scheme, and no such
# caller exists -- embedded stores are single-client by construction.)
_STORE_LOCKS: Dict[str, Any] = {}  # path -> (loop, lock)


def _store_lock(base_dir: str) -> asyncio.Lock:
    path = os.path.abspath(str(base_dir or '.'))
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # sync caller: nothing to serialize against yet
        loop = None
    entry = _STORE_LOCKS.get(path)
    # Identity of the loop object, not its id(): an id is reused after the loop
    # is collected, which would hand back a lock bound to the dead one.
    if entry is None or entry[0] is not loop:
        lock = asyncio.Lock()
        _STORE_LOCKS[path] = (loop, lock)
        return lock
    return entry[1]


# Only conversational text is ingested (mirrors what backends extract from);
# system prompts and tool payloads never become long-term memory rows.
_INGEST_ROLES = ('user', 'assistant')

_LEDGER_FILE = 'ingest_state.json'
_LEDGER_MAX = 4096

# Config fields the backend re-reads from ``mem_config`` on every call, so a
# change to them can be applied by mutating the live config object. Everything
# else decides which backend exists or which store it points at, and needs a
# teardown (see ``MemoryOrchestrator.reconfigure``).
_SOFT_FIELDS = ('recall_top_k', 'ingest_interval')


def _content_hash(msg: Dict[str, Any]) -> str:
    raw = f"{msg.get('role', '')}\x1f{msg.get('content', '')}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def _ingestable_hashes(msg_dicts: List[Dict[str, Any]]) -> Set[str]:
    return {
        _content_hash(m)
        for m in msg_dicts
        if m.get('role') in _INGEST_ROLES and m.get('content')
    }


def _changed_fields(old: MemoryConfig, new: MemoryConfig) -> Set[str]:
    # Field-by-field rather than ``asdict``: that deep-copies every value,
    # and ``llm_config`` / ``backend_options`` can hold anything.
    return {
        f.name
        for f in fields(old)
        if getattr(old, f.name, None) != getattr(new, f.name, None)
    }


class MemoryOrchestrator(Memory):
    """Thin adapter between the ms-agent ``Memory`` ABC and a
    ``MemoryBackend`` implementation.

    Responsibilities (and ONLY these):
    1. Parse config -> resolve the correct backend class from the registry.
    2. Forward ``run()`` -> ``backend.inject()``.
    3. Forward ``add()`` -> ``backend.on_messages()``.
    4. Expose ``flush()`` / ``search()`` / tool helpers as thin delegates.

    Everything else -- file I/O, snapshot caching, prompt formatting,
    tool definitions, security scanning -- is the backend's concern.
    """

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self.mem_config = self._parse_config(config)
        self._backend: Optional[MemoryBackend] = None
        self._started = False
        # Retired by close(): a closed orchestrator never reopens its store.
        self._closed = False
        # Background ingestion bookkeeping (see module docstring).
        self._pending: Set[asyncio.Task] = set()
        # Hashes a scheduled ingest has claimed but not yet written. The ledger
        # may not advance past them from anywhere else (see mark_ingested).
        self._inflight: Set[str] = set()
        self._turns_since_ingest = 0
        self._ledger: Optional[Set[str]] = None  # lazy-loaded from disk
        self._ledger_order: List[str] = []
        self._status: Dict[str, Any] = {
            'state': 'idle',
            'at': None,
            'count': None,
            'error': None
        }

    # ------------------------------------------------------------------
    # Lazy backend construction
    # ------------------------------------------------------------------

    def _get_backend(self) -> MemoryBackend:
        if self._backend is None:
            backend_name = self.mem_config.storage_backend
            cls = backend_registry.resolve(backend_name)
            self._backend = cls(self.mem_config)
            logger.info(f"[orchestrator] Created backend '{backend_name}' "
                        f'-> {cls.__name__}')
        return self._backend

    async def _ensure_started(self, **kwargs: Any) -> MemoryBackend:
        backend = self._get_backend()
        if not self._started:
            await backend.start(**kwargs)
            self._started = True
        return backend

    # ------------------------------------------------------------------
    # Memory ABC -- run()
    # ------------------------------------------------------------------

    async def run(self, messages: List[Message]) -> List[Message]:
        if not self.mem_config.enabled or self._closed:
            return messages

        # Retrieval must not overlap a write: the embedded stores underneath
        # (qdrant local) are single-client, lock-free code. A scheduled ingest
        # normally finishes while the user reads the previous answer, so this
        # rarely actually waits.
        async with _store_lock(self.mem_config.base_dir):
            backend = await self._ensure_started()
            msg_dicts = _messages_to_dicts(messages)
            injected = await backend.inject(msg_dicts)
        return _dicts_to_messages(injected)

    # ------------------------------------------------------------------
    # Durable recall (attached to the user turn by LLMAgent)
    # ------------------------------------------------------------------

    #: Attach-idempotency marker for LLMAgent (matches the first line every
    #: recall_block() implementation renders).
    recall_marker = RECALL_BLOCK_MARKER

    async def recall_block(self, query: str) -> str:
        """Formatted recall for a NEW user turn; '' when the backend has no
        per-query recall (file backend) or memory is disabled. Same store
        lock as run() — retrieval must not overlap a write.

        Closed is terminal here too: this is a store access like any other,
        and going through ``_ensure_started`` after the owner released the
        store would retake the embedded store's file lock.
        """
        if not self.mem_config.enabled or self._closed:
            return ''
        async with _store_lock(self.mem_config.base_dir):
            backend = await self._ensure_started()
            fn = getattr(backend, 'recall_block', None)
            if fn is None:
                return ''
            return await fn(query)

    # ------------------------------------------------------------------
    # Memory ABC -- add() / schedule_add()
    # ------------------------------------------------------------------

    async def add(self, messages: List[Message], **kwargs: Any) -> None:
        """Awaited ingestion (legacy callers / inline fallback)."""
        if not self._should_ingest():
            return
        await self._ingest(_messages_to_dicts(messages), **kwargs)

    def schedule_add(self, messages: List[Message],
                     **kwargs: Any) -> Optional[asyncio.Task]:
        """Ingest in the background; returns the task (None when skipped or
        run inline). The message list is snapshotted to dicts NOW — the
        caller's list keeps mutating after this returns (the next user turn
        is appended to it)."""
        if not self._should_ingest():
            return None
        msg_dicts = _messages_to_dicts(messages)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            # No loop to defer to — do the write inline rather than lose it.
            asyncio.run(self._ingest(msg_dicts, **kwargs))
            return None
        self._status.update(state='scheduled', error=None)
        # Claim the messages NOW, synchronously. A task does not start until
        # the loop gets around to it, and an interrupt landing in that gap
        # would otherwise mark them as ingested before the write ever looked.
        claimed = _ingestable_hashes(msg_dicts)
        self._inflight |= claimed
        task = loop.create_task(self._ingest(msg_dicts, **kwargs))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        task.add_done_callback(
            lambda _t: self._inflight.difference_update(claimed))
        return task

    def _should_ingest(self) -> bool:
        if not self.mem_config.enabled:
            return False
        interval = max(1, int(getattr(self.mem_config, 'ingest_interval', 1)))
        self._turns_since_ingest += 1
        if self._turns_since_ingest < interval:
            return False
        self._turns_since_ingest = 0
        return True

    async def _ingest(self, msg_dicts: List[Dict[str, Any]],
                      **kwargs: Any) -> int:
        """The single write path: locked, delta-only, status-reporting.

        Never raises — a memory write must not break anything above it; the
        outcome lands in ``ingest_status`` instead.
        """
        if self._closed:
            # Scheduled before the teardown, woken after it. Writing now would
            # reopen a store its owner has already released.
            logger.debug('[orchestrator] ingest dropped: orchestrator closed')
            return 0
        # Also claimed here, not only in schedule_add: `add()` reaches this
        # directly. Claiming twice is harmless — both releases drop the same
        # hashes.
        claimed = _ingestable_hashes(msg_dicts)
        self._inflight |= claimed
        try:
            async with _store_lock(self.mem_config.base_dir):
                backend = await self._ensure_started()
                delta = self._ledger_delta(msg_dicts)
                if not delta:
                    self._set_status('ok', count=0)
                    return 0
                self._set_status('running')
                result = await backend.on_messages(delta, **kwargs)
                # Record hashes only after the backend accepted the write, so
                # a failure leaves them un-marked and the next turn's delta
                # carries them again (retry-by-construction).
                self._ledger_mark(delta)
                count = result if isinstance(result, int) else len(delta)
                self._set_status('ok', count=count)
                return count
        except asyncio.CancelledError:
            self._set_status('error', error='cancelled')
            raise
        except Exception as e:  # noqa: BLE001 - reported via status
            logger.error(f'[orchestrator] memory ingest failed, nothing was '
                         f'persisted for this turn: {type(e).__name__}: {e}')
            self._set_status('error', error=f'{type(e).__name__}: {e}')
            return 0
        finally:
            self._inflight -= claimed

    def mark_ingested(self, messages: List[Message]) -> None:
        """Advance the ledger WITHOUT ingesting (interrupted turns): a
        half-finished answer must not be swept into the next turn's delta.

        Pass ONLY the interrupted round's own messages. Anything a scheduled
        ingest has already claimed is skipped regardless: marking a message
        that is still being written would either make that write a no-op (the
        delta comes out empty) or, if it fails, deny it the retry the ledger
        exists to guarantee — either way the memory is silently lost.
        """
        dicts = [
            m for m in _messages_to_dicts(messages)
            if m.get('role') in _INGEST_ROLES and m.get('content')
            and _content_hash(m) not in self._inflight
        ]
        self._ledger_mark(dicts, persist=True)

    async def flush_pending(self, timeout: float = 15.0) -> None:
        """Barrier: wait for scheduled ingests (teardown must not drop the
        final write). Timeout guards against a wedged provider call."""
        pending = {t for t in self._pending if not t.done()}
        if not pending:
            return
        done, still = await asyncio.wait(pending, timeout=timeout)
        if still:
            logger.warning(
                f'[orchestrator] {len(still)} memory ingest(s) still running '
                f'after {timeout}s flush timeout')

    @property
    def ingest_status(self) -> Dict[str, Any]:
        status = dict(self._status)
        status['pending'] = sum(1 for t in self._pending if not t.done())
        return status

    def _set_status(self, state: str, count: Optional[int] = None,
                    error: Optional[str] = None) -> None:
        self._status.update(
            state=state,
            at=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
            count=count,
            error=error)

    # ------------------------------------------------------------------
    # Ingest ledger (content hashes of already-ingested messages)
    # ------------------------------------------------------------------

    def _ledger_path(self) -> str:
        return os.path.join(str(self.mem_config.base_dir), _LEDGER_FILE)

    def _ledger_load(self) -> Set[str]:
        if self._ledger is None:
            hashes: List[str] = []
            try:
                with open(self._ledger_path(), encoding='utf-8') as fh:
                    hashes = list(json.load(fh).get('hashes') or [])
            except (OSError, ValueError):
                pass
            self._ledger_order = hashes[-_LEDGER_MAX:]
            self._ledger = set(self._ledger_order)
        return self._ledger

    def _ledger_delta(
            self, msg_dicts: List[Dict[str,
                                       Any]]) -> List[Dict[str, Any]]:
        """Conversational messages not yet ingested, in order. Repeated
        identical texts dedup to their first occurrence — a repeat carries no
        new fact, and it keeps the ledger content-addressed (stable across
        context compression rewriting the list)."""
        seen = self._ledger_load()
        delta: List[Dict[str, Any]] = []
        batch: Set[str] = set()
        for m in msg_dicts:
            if m.get('role') not in _INGEST_ROLES or not m.get('content'):
                continue
            h = _content_hash(m)
            if h in seen or h in batch:
                continue
            batch.add(h)
            delta.append(m)
        return delta

    def _ledger_mark(self, msg_dicts: List[Dict[str, Any]],
                     persist: bool = True) -> None:
        seen = self._ledger_load()
        added = False
        for m in msg_dicts:
            h = _content_hash(m)
            if h not in seen:
                seen.add(h)
                self._ledger_order.append(h)
                added = True
        if not added or not persist:
            return
        if len(self._ledger_order) > _LEDGER_MAX:
            for stale in self._ledger_order[:-_LEDGER_MAX]:
                seen.discard(stale)
            self._ledger_order = self._ledger_order[-_LEDGER_MAX:]
        try:
            os.makedirs(str(self.mem_config.base_dir), exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self.mem_config.base_dir), suffix='.tmp')
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                json.dump({'version': 1, 'hashes': self._ledger_order}, fh)
            os.replace(tmp, self._ledger_path())
        except OSError as e:  # pragma: no cover - bookkeeping never breaks
            logger.warning(f'[orchestrator] ingest ledger write failed: {e}')

    # ------------------------------------------------------------------
    # Flush (pre-compression)
    # ------------------------------------------------------------------

    async def flush(self, messages: List[Message]) -> None:
        if not self.mem_config.enabled or self._closed:
            return
        async with _store_lock(self.mem_config.base_dir):
            backend = await self._ensure_started()
            msg_dicts = _messages_to_dicts(messages)
            await backend.on_pre_compress(msg_dicts)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(self, query: str, limit: int = 10) -> List[MemoryEntry]:
        if self._closed:
            return []
        # Under the store lock like every other access: an embedded store has
        # no locking of its own, and this one used to be the single reader that
        # could land in the middle of a background write.
        async with _store_lock(self.mem_config.base_dir):
            backend = await self._ensure_started()
            return await backend.search(query, limit)

    # ------------------------------------------------------------------
    # Tool interface (called by the agent's ToolManager)
    # ------------------------------------------------------------------

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return self._get_backend().get_tool_schemas()

    async def handle_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> str:
        backend = await self._ensure_started()
        return await backend.handle_tool_call(tool_name, arguments)

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def invalidate_snapshot(self) -> None:
        if self._backend is not None:
            self._backend.invalidate()

    # ------------------------------------------------------------------
    # LLM injection (for backends that need the agent's LLM)
    # ------------------------------------------------------------------

    def set_llm(self, llm: Any) -> None:
        backend = self._get_backend()
        if hasattr(backend, 'set_llm'):
            backend.set_llm(llm)

    def init_update_queue(self) -> None:
        backend = self._get_backend()
        if hasattr(backend, 'init_update_queue'):
            backend.init_update_queue()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def _shutdown_backend(self, retire: bool = False) -> None:
        """Drain scheduled writes, then release the backend (and with it the
        store's file lock). ``retire`` additionally makes the orchestrator
        refuse to ever reopen the store; ``reconfigure`` leaves it False,
        because everyone holding this instance must keep working with it.

        Order matters. Draining comes FIRST: a write that was already
        scheduled is part of what a teardown promises to persist. Retiring
        comes right after, so a straggler past ``flush_pending``'s timeout
        finds the door closed instead of going through ``_ensure_started``,
        which would restart the backend and take the embedded store's file
        lock again — after its owner believed it released.

        Stragglers are deliberately NOT cancelled: a backend write runs in a
        worker thread (mem0 extraction + embedding), so cancelling only
        abandons the await while the thread keeps writing — and we would then
        close the client under it. Waiting on the store lock below is what
        actually makes the teardown safe.
        """
        await self.flush_pending()
        if retire:
            self._closed = True
        if self._backend is not None and self._started:
            async with _store_lock(self.mem_config.base_dir):
                await self._backend.close()
            self._started = False

    async def close(self) -> None:
        await self._shutdown_backend(retire=True)

    # ------------------------------------------------------------------
    # Reconfiguration
    # ------------------------------------------------------------------

    async def reconfigure(self, config: Any) -> bool:
        """Adopt ``config`` on this live instance. Returns True when the
        backend had to be torn down, False for a no-op or an in-place update.

        Applied to the instance instead of by replacing it, because
        ``SharedMemoryManager`` hands ONE instance per store to every agent
        that asks: a replacement would leave earlier holders pointing at an
        orchestrator whose store was closed under them, and two live
        orchestrators over one embedded store is exactly the exclusive-lock
        conflict that sharing exists to prevent. Mutating the shared object
        updates every holder at once.
        """
        new_cfg = self._parse_config(config)
        changed = _changed_fields(self.mem_config, new_cfg)
        if not changed:
            return False
        if not changed - set(_SOFT_FIELDS):
            # The live backend holds a reference to this very MemoryConfig, so
            # writing the fields through reaches it without a teardown.
            for field in _SOFT_FIELDS:
                setattr(self.mem_config, field, getattr(new_cfg, field))
            logger.info(f'[orchestrator] memory config updated in place: '
                        f'{sorted(changed)}')
            return False
        logger.info(f'[orchestrator] memory config changed '
                    f'({sorted(changed)}) -> rebuilding backend')
        # Release the old store, but keep the instance usable — everyone
        # holding it must keep working, now against the new configuration.
        await self._shutdown_backend()
        self._backend = None
        if 'base_dir' in changed:
            # A different store keeps a different ledger.
            self._ledger = None
            self._ledger_order = []
        self.mem_config = new_cfg
        return True

    # ------------------------------------------------------------------
    # Config parsing
    # ------------------------------------------------------------------

    def _parse_config(self, config: Any) -> MemoryConfig:
        if isinstance(config, MemoryConfig):
            return config
        if hasattr(config, 'memory') and hasattr(config.memory,
                                                 'unified_memory'):
            mc = MemoryConfig.from_dict_config(config.memory.unified_memory)
            self._default_base_dir(mc, config)
            return mc
        if hasattr(config, 'unified_memory'):
            return MemoryConfig.from_dict_config(config.unified_memory)
        return MemoryConfig.from_dict_config(config)

    @staticmethod
    def _default_base_dir(mc: MemoryConfig, config: Any) -> None:
        """When base_dir is unset ('.'), root memory under <work>/.ms_agent/memory
        instead of the CWD (so MEMORY.md / facts / index don't scatter)."""
        if str(getattr(mc, 'base_dir', '.')).strip() in ('.', '', './'):
            from ms_agent.project.paths import memory_dir
            work = getattr(config, 'output_dir', None) or '.'
            mc.base_dir = str(memory_dir(work))


# ===================================================================
# Message conversion helpers
# ===================================================================


def _messages_to_dicts(messages: List[Message]) -> List[Dict[str, Any]]:
    """Serialize for ``backend.inject()`` — must be lossless.

    This round-trip (``run()``: messages -> dicts -> inject -> messages) runs on
    EVERY turn, so any field dropped here is dropped from the live LLM context,
    not just from storage. ``tool_call_id`` in particular is mandatory on the
    wire for ``role='tool'`` rows: losing it makes OpenAI-compatible providers
    reject the request with ``missing field 'tool_call_id'``. Keep this the
    exact inverse of ``_dicts_to_messages`` below.
    """
    result: List[Dict[str, Any]] = []
    for m in messages:
        if isinstance(m, dict):
            result.append(m)
        elif isinstance(m, Message):
            d: Dict[str, Any] = {'role': m.role, 'content': m.content or ''}
            if m.tool_calls:
                d['tool_calls'] = m.tool_calls
            if m.tool_call_id:
                d['tool_call_id'] = m.tool_call_id
            if m.name:
                d['name'] = m.name
            if m.reasoning_content:
                d['reasoning_content'] = m.reasoning_content
            if m.reasoning_signature:
                d['reasoning_signature'] = m.reasoning_signature
            result.append(d)
        else:
            result.append({'role': 'user', 'content': str(m)})
    return result
