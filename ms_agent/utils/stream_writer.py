# Copyright (c) Alibaba, Inc. and its affiliates.
"""
SubAgentStreamWriter — incremental JSONL writer for sub-agent execution progress.

When a parent agent calls a sub-agent via AgentTool, the sub-agent produces messages
incrementally. This writer appends new messages to a JSONL file on every chunk event,
allowing external tools (e.g. ``tail -f``) or the parent agent itself to watch the
sub-agent's progress in real time.

File format (one JSON object per line):

.. code-block:: text

    {"type": "header",  "call_id": "...", "tool_name": "...", "agent_tag": "...", "ts": "..."}
    {"type": "message", "index": 0, "message": {...}, "ts": "..."}
    {"type": "message", "index": 1, "message": {...}, "ts": "..."}
    ...
    {"type": "footer",  "call_id": "...", "status": "complete", "total_messages": N, "ts": "..."}

On error the footer's *status* field is ``"error"`` and an ``"error"`` field is included.

File path: ``{output_dir}/subagents/{call_id}.stream.jsonl``
"""
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ms_agent.utils import get_logger

logger = get_logger()


class SubAgentStreamWriter:
    """Thread-safe incremental JSONL writer for sub-agent chunk events.

    Each instance owns exactly one file.  It deduplicates history by tracking
    how many messages have already been written (``_last_written_count``), so
    calling ``on_chunk(full_history)`` multiple times is safe — only the newly
    appended messages are written.

    All public methods are safe to call from multiple threads.
    """

    def __init__(self, output_dir: str, call_id: str, tool_name: str) -> None:
        self._call_id: str = call_id or 'unknown'
        self._tool_name: str = tool_name
        self._lock = threading.Lock()
        self._last_written_count: int = 0
        self._closed: bool = False
        self._agent_tag: Optional[str] = None
        self._file = None  # opened lazily in on_start

        subagents_dir = os.path.join(output_dir, 'subagents')
        os.makedirs(subagents_dir, exist_ok=True)
        safe_id = self._call_id.replace('/', '_').replace('\\', '_')
        self._path: str = os.path.join(subagents_dir, f'{safe_id}.stream.jsonl')

    @property
    def stream_path(self) -> str:
        """Absolute path to the JSONL stream file."""
        return self._path

    def on_start(self, agent_tag: Optional[str]) -> None:
        """Open the file and write the header record.

        Args:
            agent_tag: The sub-agent's tag string, if known at start time.
                       May be ``None`` when running in a subprocess (tag is
                       only resolved after the process finishes).
        """
        with self._lock:
            if self._closed:
                return
            self._agent_tag = agent_tag
            try:
                self._file = open(self._path, 'w', encoding='utf-8')
                self._write_line({
                    'type': 'header',
                    'call_id': self._call_id,
                    'tool_name': self._tool_name,
                    'agent_tag': agent_tag or '',
                    'ts': _now_iso(),
                })
            except Exception as exc:
                logger.warning(
                    'SubAgentStreamWriter: failed to open %s: %s', self._path, exc)
                self._file = None

    def on_chunk(self, history: Any) -> None:
        """Append only new messages from *history* since the last call.

        Args:
            history: The full accumulated message list returned by a streaming
                     chunk.  May be ``None`` or an empty list; in that case
                     nothing is written.
        """
        messages = _coerce_to_list(history)
        if not messages:
            return
        with self._lock:
            if self._closed or self._file is None:
                return
            for msg in messages[self._last_written_count:]:
                self._write_line({
                    'type': 'message',
                    'index': self._last_written_count,
                    'message': _msg_to_dict(msg),
                    'ts': _now_iso(),
                })
                self._last_written_count += 1

    def on_end(self, history: Any) -> None:
        """Flush any remaining messages, write footer record, then close.

        Args:
            history: Final full message list (same shape as ``on_chunk``).
        """
        # Write any messages that arrived in the final chunk before closing.
        self.on_chunk(history)
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._file is not None:
                try:
                    self._write_line({
                        'type': 'footer',
                        'call_id': self._call_id,
                        'agent_tag': self._agent_tag or '',
                        'status': 'complete',
                        'total_messages': self._last_written_count,
                        'ts': _now_iso(),
                    })
                    self._file.flush()
                    self._file.close()
                except Exception as exc:
                    logger.warning(
                        'SubAgentStreamWriter: close error on %s: %s', self._path, exc)
                finally:
                    self._file = None

    def on_error(self, error: str) -> None:
        """Write an error footer and close the file.

        Args:
            error: Human-readable error description.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._file is not None:
                try:
                    self._write_line({
                        'type': 'footer',
                        'call_id': self._call_id,
                        'agent_tag': self._agent_tag or '',
                        'status': 'error',
                        'error': error,
                        'total_messages': self._last_written_count,
                        'ts': _now_iso(),
                    })
                    self._file.flush()
                    self._file.close()
                except Exception:
                    pass
                finally:
                    self._file = None

    # ── private helpers ────────────────────────────────────────────────────

    def _write_line(self, record: Dict[str, Any]) -> None:
        """Serialize *record* as JSON and append a newline.

        Caller **must** hold ``self._lock``.  Each line is flushed immediately
        so that ``tail -f`` sees it without buffering.
        """
        if self._file is None:
            return
        try:
            self._file.write(json.dumps(record, ensure_ascii=False) + '\n')
            self._file.flush()
        except Exception as exc:
            logger.warning('SubAgentStreamWriter: write failed: %s', exc)


# ── module-level helpers ────────────────────────────────────────────────────


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _coerce_to_list(value: Any) -> List[Any]:
    """Return *value* if it is a list, otherwise an empty list."""
    return value if isinstance(value, list) else []


def _msg_to_dict(msg: Any) -> Dict[str, Any]:
    """Convert a Message object (or plain dict) to a serialisable dict."""
    if hasattr(msg, 'to_dict'):
        return msg.to_dict()
    if isinstance(msg, dict):
        return msg
    return {'role': 'unknown', 'content': str(msg)}
