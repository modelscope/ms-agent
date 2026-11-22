# Copyright (c) ModelScope Contributors. All rights reserved.
"""Spill large tool outputs to disk under output_dir/.ms_agent/artifacts/."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
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
        artifact_subdir: str = '.ms_agent/artifacts',
    ) -> None:
        self._root = Path(output_dir).expanduser().resolve()
        self.max_combined_bytes = max_combined_bytes
        self.preview_head_chars = preview_head_chars
        self.preview_tail_chars = preview_tail_chars
        self._artifact_root = self._root / artifact_subdir

    def store_image(self, encoded: str, media_type: str) -> dict[str, Any]:
        """Persist tool pixels as a workspace reference, shared by session forks.

        The content hash avoids duplicate writes and server-controlled paths.
        Artifacts outlive the connection: replay must still resolve the image.
        """
        from PIL import Image, UnidentifiedImageError

        from ms_agent.utils.atomic_file import atomic_write_bytes

        extensions = {
            'image/png': 'png',
            'image/jpeg': 'jpg',
            'image/webp': 'webp',
            'image/gif': 'gif',
            'image/bmp': 'bmp',
            'image/tiff': 'tiff',
        }
        limit = 16 * 1024 * 1024
        if media_type not in extensions:
            raise ValueError('Unsupported tool image media type')
        if len(encoded) > 4 * ((limit + 2) // 3):
            raise ValueError('Tool image exceeds the 16 MiB input limit')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError('Tool image contains invalid base64') from exc
        if len(raw) > limit:
            raise ValueError('Tool image exceeds the 16 MiB input limit')
        try:
            with Image.open(io.BytesIO(raw)) as img:
                if img.width * img.height > 40_000_000:
                    raise ValueError(
                        'Tool image exceeds the 40 megapixel limit')
                if Image.MIME.get(img.format) != media_type:
                    raise ValueError(
                        'Tool image bytes do not match its media type')
                img.verify()
        except (UnidentifiedImageError, OSError,
                Image.DecompressionBombError) as exc:
            raise ValueError('Tool image is not a readable image') from exc
        digest = hashlib.sha256(raw).hexdigest()
        path = self._artifact_root / 'images' / f'{digest}.{extensions[media_type]}'
        if not path.resolve().is_relative_to(self._root):
            raise ValueError(
                'Tool image artifact path is outside the workspace')
        atomic_write_bytes(path, raw)
        return {
            'type': 'image',
            'path': path.relative_to(self._root).as_posix(),
            'media_type': media_type
        }

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
