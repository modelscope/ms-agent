# Copyright (c) ModelScope Contributors. All rights reserved.
"""
Offload oversized web_search tool payloads to disk so LLM context stays bounded.

When
----
Estimated inline character volume (per-result ``content``, ``summary``, ``abstract``,
and ``chunks[*].content``) exceeds ``spill_max_inline_chars``.

Where / lifecycle
-----------------
``{output_dir}/{spill_subdir}/{run_key}/`` — same lifecycle as the task
``output_dir`` (delete the run workdir to reclaim space; no automatic pruning).

Naming
------
``run_key = {UTC compact}_{call_id_or_random}`` — unique, sortable, filesystem-safe.

Files
-----
* ``manifest.json`` — index (query, engine, URLs, paths, sizes, previews).
* ``bodies/{i:03d}.md`` — UTF-8 full text for spilled rows (sections for content /
  abstract / chunks).

Return payload
--------------
JSON gains ``spill`` with ``digest`` (instructions + quick index) and paths relative
to ``output_dir`` so ``read_file`` can open them.
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
import uuid
from typing import Any, Dict, List, Tuple


def _item_inline_chars(it: Dict[str, Any]) -> int:
    n = 0
    for k in ('content', 'summary', 'abstract'):
        v = it.get(k)
        if isinstance(v, str):
            n += len(v)
    chunks = it.get('chunks')
    if isinstance(chunks, list):
        for c in chunks:
            if isinstance(c, dict):
                s = c.get('content')
                if isinstance(s, str):
                    n += len(s)
    return n


def _total_inline_chars(items: List[Dict[str, Any]]) -> int:
    return sum(_item_inline_chars(x) for x in items)


def _preview(text: str, max_chars: int) -> str:
    t = (text or '').strip()
    if len(t) <= max_chars:
        return t
    return t[:max_chars].rstrip() + '\n…'


def _safe_run_key(call_id: str) -> str:
    ts = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    tail = (call_id or '').strip()
    tail = re.sub(r'[^a-zA-Z0-9._-]+', '_', tail)[:24]
    if not tail:
        tail = uuid.uuid4().hex[:12]
    return f'{ts}_{tail}'


def _build_spill_markdown(item: Dict[str, Any]) -> str:
    """Assemble full text for one result row."""
    lines: List[str] = []
    url = item.get('url', '')
    title = item.get('title', '')
    lines.append(f'# {title or "(no title)"}\n')
    lines.append(f'**URL:** {url}\n')
    summary = item.get('summary')
    if isinstance(summary, str) and summary.strip():
        lines.append('\n## Summary (search snippet)\n\n')
        lines.append(summary)
        lines.append('\n')
    content = item.get('content')
    if isinstance(content, str) and content.strip():
        lines.append('\n## Content\n\n')
        lines.append(content)
        lines.append('\n')
    abstract = item.get('abstract')
    if isinstance(abstract, str) and abstract.strip():
        lines.append('\n## Abstract\n\n')
        lines.append(abstract)
        lines.append('\n')
    chunks = item.get('chunks')
    if isinstance(chunks, list) and chunks:
        lines.append('\n## Chunks\n\n')
        for c in chunks:
            if not isinstance(c, dict):
                continue
            cid = c.get('chunk_id', '')
            body = c.get('content', '')
            lines.append(f'### chunk `{cid}`\n\n')
            if isinstance(body, str):
                lines.append(body)
            lines.append('\n')
    return ''.join(lines)


def _shrink_item_after_spill(item: Dict[str, Any], spill_preview_chars: int) -> Dict[str, Any]:
    """Replace heavy fields with short previews + pointers."""
    out = dict(item)
    note = (
        'Full text spilled to disk; see content_path / manifest_path in parent '
        'JSON spill block. Use read_file on content_path for this row.'
    )
    sm = out.get('summary')
    if isinstance(sm, str) and sm.strip():
        out['summary'] = _preview(sm, spill_preview_chars)
        out.setdefault('content_note', note)
    main = out.get('content') or ''
    if isinstance(main, str) and main.strip():
        out['content'] = _preview(main, spill_preview_chars)
        out['content_note'] = note
    ab = out.get('abstract')
    if isinstance(ab, str) and ab.strip():
        out['abstract'] = _preview(ab, min(800, spill_preview_chars))
    ch = out.get('chunks')
    if isinstance(ch, list) and ch:
        out['chunks'] = [
            {
                'chunk_id': c.get('chunk_id', ''),
                'content': _preview(str(c.get('content', '')), min(400, spill_preview_chars)),
            }
            for c in ch
            if isinstance(c, dict)
        ]
        out['chunks_note'] = 'Full chunk bodies are in the spilled markdown file.'
    return out


def maybe_spill_web_search_payload(
    *,
    output_dir: str,
    spill_subdir: str,
    spill_max_inline_chars: int,
    spill_preview_chars: int,
    query: str,
    engine: str,
    results: List[Dict[str, Any]],
    call_id: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    If total inline chars exceed threshold, spill largest rows first until under.

    Returns:
        (possibly_mutated_results, spill_meta_dict)
        spill_meta_dict is empty if no spill occurred.
    """
    if not output_dir or not results:
        return results, {}

    work = copy.deepcopy(results)
    total = _total_inline_chars(work)
    if total <= spill_max_inline_chars:
        return results, {}

    run_key = _safe_run_key(call_id)
    root = os.path.abspath(os.path.join(output_dir, spill_subdir, run_key))
    bodies_dir = os.path.join(root, 'bodies')
    os.makedirs(bodies_dir, exist_ok=True)

    spilled_indices: List[int] = []
    manifest_rows: List[Dict[str, Any]] = []

    def order_by_size() -> List[int]:
        sizes = [(i, _item_inline_chars(work[i])) for i in range(len(work))]
        sizes.sort(key=lambda x: x[1], reverse=True)
        return [i for i, sz in sizes if sz > 0]

    while _total_inline_chars(work) > spill_max_inline_chars:
        order = order_by_size()
        if not order:
            break
        idx = order[0]
        item = work[idx]
        if _item_inline_chars(item) == 0:
            break
        full_md = _build_spill_markdown(item)
        rel_body = os.path.join(spill_subdir, run_key, 'bodies', f'{idx:03d}.md').replace('\\', '/')
        abs_body = os.path.normpath(os.path.join(output_dir, rel_body.replace('/', os.sep)))
        os.makedirs(os.path.dirname(abs_body), exist_ok=True)
        header = f'<!-- web_search spill | engine={engine} | row_index={idx} -->\n'
        with open(abs_body, 'w', encoding='utf-8') as bf:
            bf.write(header + full_md)

        spilled_indices.append(idx)
        before_chars = _item_inline_chars(item)
        work[idx] = _shrink_item_after_spill(item, spill_preview_chars)
        work[idx]['content_spilled'] = True
        work[idx]['content_path'] = rel_body
        work[idx]['content_chars_spilled'] = before_chars

        preview_src = (item.get('content') or item.get('summary') or item.get('abstract') or '')[:4000]
        manifest_rows.append(
            {
                'index': idx,
                'url': item.get('url', ''),
                'title': item.get('title', ''),
                'body_file': f'bodies/{idx:03d}.md',
                'content_path': rel_body,
                'chars_spilled': before_chars,
                'preview': _preview(preview_src, min(500, spill_preview_chars)),
            }
        )

    manifest: Dict[str, Any] = {
        'version': 1,
        'created_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'query': query,
        'engine': engine,
        'run_key': run_key,
        'lifecycle': (
            'Ephemeral: lives under this task output_dir; delete the task directory '
            'to remove. ms-agent does not auto-prune.'
        ),
        'inline_chars_before': total,
        'inline_chars_after': _total_inline_chars(work),
        'spill_threshold_chars': spill_max_inline_chars,
        'spilled_row_indices': spilled_indices,
        'rows': manifest_rows,
    }
    rel_manifest = os.path.join(spill_subdir, run_key, 'manifest.json').replace('\\', '/')
    abs_manifest = os.path.normpath(os.path.join(output_dir, rel_manifest.replace('/', os.sep)))
    with open(abs_manifest, 'w', encoding='utf-8') as mf:
        json.dump(manifest, mf, ensure_ascii=False, indent=2)

    lines = [
        'Large web_search payload was written to disk under this task output_dir.',
        f'- **Manifest (map of rows → files, sizes)**: `{rel_manifest}`',
        f'- **Bodies**: `{spill_subdir}/{run_key}/bodies/`',
        'Read **manifest.json** first, then **read_file** on specific `bodies/NNN.md` files as needed.',
        '',
        '**Quick index**',
    ]
    for row in manifest_rows:
        lines.append(
            f'{row["index"]}. {row.get("title") or "(no title)"} — '
            f'`{row["content_path"]}` ({row.get("chars_spilled", 0)} chars)'
        )
    digest = '\n'.join(lines)

    spill_meta = {
        'spilled': True,
        'run_key': run_key,
        'artifact_dir': f'{spill_subdir}/{run_key}'.replace('\\', '/'),
        'manifest_path': rel_manifest,
        'digest': digest,
        'inline_chars_before_spill': total,
        'inline_chars_after_spill': _total_inline_chars(work),
    }
    return work, spill_meta
