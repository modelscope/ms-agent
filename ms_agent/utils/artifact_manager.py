# Copyright (c) ModelScope Contributors. All rights reserved.
"""Spill large tool outputs to disk under output_dir/.ms_agent_artifacts/."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class ArtifactManager:
    """When combined stdout+stderr exceeds *max_combined_bytes*, write to artifact file."""

    def __init__(
        self,
        output_dir: Path | str,
        *,
        max_combined_bytes: int = 256 * 1024,
        preview_head_chars: int = 4000,
        preview_tail_chars: int = 2000,
        artifact_subdir: str = '.ms_agent_artifacts',
    ) -> None:
        self._root = Path(output_dir).expanduser().resolve()
        self.max_combined_bytes = max_combined_bytes
        self.preview_head_chars = preview_head_chars
        self.preview_tail_chars = preview_tail_chars
        self._artifact_root = self._root / artifact_subdir

    def pack_text_result(
        self,
        *,
        tool_name: str,
        call_id: str,
        stdout: str,
        stderr: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return payload fields: output, error, truncated, artifact_path (optional)."""
        combined = (stdout or '') + (stderr or '')
        enc = combined.encode('utf-8', errors='replace')
        if len(enc) <= self.max_combined_bytes:
            out: dict[str, Any] = {
                'output': stdout,
                'error': stderr or None,
                'truncated': False,
            }
            if extra:
                out.update(extra)
            return out

        safe_id = ''.join(c if c.isalnum() or c in '-_' else '_'
                          for c in call_id)[:120] or 'call'
        rel_dir = Path(tool_name) / safe_id
        out_dir = self._artifact_root / rel_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        body = f'=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}\n'
        digest = hashlib.sha256(enc).hexdigest()[:16]
        fname = f'combined-{digest}.txt'
        fpath = out_dir / fname
        fpath.write_text(body, encoding='utf-8', errors='replace')
        rel = fpath.relative_to(self._root).as_posix()
        preview = _make_preview(body, self.preview_head_chars,
                                self.preview_tail_chars)
        result = {
            'output':
            stdout[:self.preview_head_chars]
            if len(stdout) > self.preview_head_chars else stdout,
            'error': (stderr[:self.preview_head_chars] if stderr else None),
            'truncated':
            True,
            'artifact_path':
            rel,
            'preview':
            preview,
            'artifact_bytes':
            len(enc),
        }
        if extra:
            result.update(extra)
        return result

    def pack_json_shell_result(
        self,
        *,
        tool_name: str,
        call_id: str,
        payload: dict[str, Any],
    ) -> str:
        """JSON-encode *payload* after applying spill rules to output/error string fields."""
        stdout = str(payload.get('output') or '')
        stderr = str(payload.get('error') or '')
        packed = self.pack_text_result(
            tool_name=tool_name,
            call_id=call_id,
            stdout=stdout,
            stderr=stderr,
            extra={
                k: v
                for k, v in payload.items() if k not in ('output', 'error')
            },
        )
        # pack_text_result merged extra into top level; rebuild standard shell shape
        out = {
            'success': payload.get('success'),
            'output': packed.get('output'),
            'error': packed.get('error'),
            'return_code': payload.get('return_code'),
            'truncated': packed.get('truncated', False),
        }
        if packed.get('artifact_path'):
            out['artifact_path'] = packed['artifact_path']
            out['preview'] = packed.get('preview')
            out['artifact_bytes'] = packed.get('artifact_bytes')
        return json.dumps(out, ensure_ascii=False, indent=2)


def _make_preview(text: str, head: int, tail: int) -> str:
    if len(text) <= head + tail:
        return text
    return (text[:head] + '\n... [truncated] ...\n' + text[-tail:])
