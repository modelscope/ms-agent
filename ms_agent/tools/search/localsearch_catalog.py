# Copyright (c) ModelScope Contributors. All rights reserved.
"""Build a compact file catalog for localsearch tool descriptions using sirchmunk's DirectoryScanner."""

from __future__ import annotations
import hashlib
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import json


def catalog_cache_path(work_path: Path, fingerprint: str) -> Path:
    work_path.mkdir(parents=True, exist_ok=True)
    return work_path / f'localsearch_description_catalog.{fingerprint}.json'


def catalog_fingerprint(
    roots: List[str],
    max_files: int,
    max_depth: int,
    max_preview_chars: int,
    max_chars: int,
    exclude: Optional[List[str]],
) -> str:
    payload = {
        'roots': sorted(roots),
        'max_files': max_files,
        'max_depth': max_depth,
        'max_preview_chars': max_preview_chars,
        'max_chars': max_chars,
        'exclude': sorted(exclude or []),
    }
    raw = json.dumps(
        payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()[:24]


def load_cached_catalog(
    path: Path,
    ttl_seconds: float,
) -> Optional[str]:
    if ttl_seconds <= 0 or not path.is_file():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        created = float(data.get('created_at', 0))
        if time.time() - created > ttl_seconds:
            return None
        text = data.get('catalog')
        return str(text) if text is not None else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def save_cached_catalog(path: Path, catalog: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    payload = {'created_at': time.time(), 'catalog': catalog}
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _int_from_block(block: Any, key: str, default: int) -> int:
    if block is None:
        return default
    v = block.get(key, default) if hasattr(block, 'get') else getattr(
        block, key, default)
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _bool_from_block(block: Any, key: str, default: bool = False) -> bool:
    if block is None:
        return default
    v = block.get(key, default) if hasattr(block, 'get') else getattr(
        block, key, default)
    if isinstance(v, str):
        return v.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(v)


def _exclude_from_block(block: Any) -> Optional[List[str]]:
    if block is None:
        return None
    raw = block.get('description_catalog_exclude', None) if hasattr(
        block, 'get') else getattr(block, 'description_catalog_exclude', None)
    if raw is None:
        return None
    if isinstance(raw, str):
        return [raw] if raw.strip() else None
    if isinstance(raw, (list, tuple)):
        out = [str(x).strip() for x in raw if str(x).strip()]
        return out or None
    return None


def description_catalog_settings(block: Any) -> Tuple[bool, Dict[str, Any]]:
    """Parse ``tools.localsearch`` (or legacy ``knowledge_search``) catalog options."""
    enabled = _bool_from_block(block, 'description_catalog', True)
    opts = {
        'max_files':
        max(
            1,
            min(2000,
                _int_from_block(block, 'description_catalog_max_files', 120))),
        'max_depth':
        max(
            1,
            min(20, _int_from_block(block, 'description_catalog_max_depth',
                                    5))),
        'max_chars':
        max(
            500,
            min(100_000,
                _int_from_block(block, 'description_catalog_max_chars',
                                3_000))),
        'max_preview_chars':
        max(
            80,
            min(
                4000,
                _int_from_block(block, 'description_catalog_max_preview_chars',
                                400))),
        'cache_ttl_seconds':
        max(
            0,
            _int_from_block(block, 'description_catalog_cache_ttl_seconds',
                            300)),
        'exclude_extra':
        _exclude_from_block(block),
        # Files larger than this are skipped during catalog scan (default 50 MB).
        # Set to 0 to disable the cap.
        'max_file_size_mb':
        max(0,
            _int_from_block(block, 'description_catalog_max_file_size_mb',
                            50)),
        # Wall-clock timeout (seconds) for extracting the first page of an
        # oversized PDF.  Corrupt or pathological PDFs are abandoned after this
        # and only their filename + size appear in the catalog.
        'oversized_pdf_timeout_s':
        max(
            0.1,
            _int_from_block(block,
                            'description_catalog_oversized_pdf_timeout_s', 1)),
    }
    return enabled, opts


_DIR_SKIP: Set[str] = {
    '.git',
    '.svn',
    'node_modules',
    '__pycache__',
    '.idea',
    '.vscode',
    '.cache',
    '.tox',
    '.eggs',
    'dist',
    'build',
    '.DS_Store',
}

# Directories that typically contain generated/compiled artifacts, not source.
# These are skipped by default to keep the tree focused on meaningful content.
_DIR_SKIP_GENERATED: Set[str] = {
    '_build',
    '_static',
    '_templates',
    '_sphinx_design_static',
    '__pycache__',
    '.mypy_cache',
    '.pytest_cache',
    '.ruff_cache',
    'htmlcov',
    'site-packages',
    'egg-info',
    '.egg-info',
}


def _build_dir_tree(
    root: Path,
    max_depth: int,
    exclude: Optional[List[str]],
    max_chars: int = 4000,
) -> str:
    """Fast filesystem-only directory tree (no file content reads).

    Produces a compact indented listing:
      📁 ms_agent/
        📁 tools/
          📁 search/  (8 files)
          agent_tool.py  base.py  ...  +3
        __init__.py  llm_agent.py  ...

    Strategy — two passes:
    1. DFS pre-scan: collect every (depth, line) pair without any char limit.
    2. Breadth-first selection: sort collected lines by depth, take lines from
       shallowest levels first until the char budget is exhausted.  This
       guarantees all top-level directories appear before any second-level
       directories are shown, etc.

    The final output is re-sorted by original DFS order so indentation is
    visually coherent.
    """
    skip = set(_DIR_SKIP) | _DIR_SKIP_GENERATED
    if exclude:
        skip.update(exclude)

    # --- Pass 1: DFS, collect (depth, seq, line_text) ---
    collected: List[tuple] = []  # (depth, seq, line_text)
    seq = [0]

    def _dfs(p: Path, depth: int, indent: str) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(
                p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        except PermissionError:
            return

        dirs = [
            e for e in entries
            if e.is_dir() and not e.name.startswith('.') and e.name not in skip
        ]
        files = [
            e for e in entries if e.is_file() and not e.name.startswith('.')
            and e.name not in skip
        ]

        child_indent = indent + '  '

        for d in dirs:
            try:
                file_count = sum(1 for _ in d.iterdir()
                                 if _.is_file() and not _.name.startswith('.'))
            except PermissionError:
                file_count = 0
            count_hint = f'  ({file_count} files)' if file_count else ''
            collected.append(
                (depth, seq[0], f'{indent}📁 {d.name}/{count_hint}'))
            seq[0] += 1
            _dfs(d, depth + 1, child_indent)

        if files:
            MAX_SHOW = 5
            shown = [f.name for f in files[:MAX_SHOW]]
            overflow = len(files) - MAX_SHOW
            file_line = f'{indent}  ' + '  '.join(shown)
            if overflow > 0:
                file_line += f'  … +{overflow}'
            # File hint lines get depth + 0.5 so they sort after their parent
            # dir line but before the parent's children directories.
            collected.append((depth + 0.5, seq[0], file_line))
            seq[0] += 1

    _dfs(root, 0, '')

    # --- Pass 2: breadth-first selection within char budget ---
    # Sort by (depth, seq) to process shallowest lines first.
    by_depth = sorted(collected, key=lambda t: (t[0], t[1]))
    budget = max_chars - 40  # reserve for truncation note
    selected_seqs: set = set()
    used = 0
    truncated = False
    for depth, s, line in by_depth:
        cost = len(line) + 1
        if used + cost > budget:
            truncated = True
            break
        selected_seqs.add(s)
        used += cost

    # Re-sort selected lines by original DFS seq to restore correct indentation
    output_lines = [line for (_, s, line) in collected if s in selected_seqs]

    result = '\n'.join(output_lines)
    if truncated:
        result += '\n… (tree truncated — deeper directories omitted)'
    return result


def _compact_file_summary(candidate: Any, root_dir: str,
                          max_preview: int) -> str:
    """Single-line or two-line compact summary for a FileCandidate.

    Format:
      - path/to/file.py (.py, 12KB) — Title or first-line preview
    """
    from pathlib import Path as _Path
    try:
        rel = _Path(candidate.path).relative_to(_Path(root_dir)).as_posix()
    except (ValueError, TypeError):
        rel = _Path(candidate.path).as_posix()

    size = candidate.size_bytes
    if size < 1024:
        size_str = f'{size}B'
    elif size < 1024 * 1024:
        size_str = f'{size / 1024:.0f}KB'
    else:
        size_str = f'{size / 1024 / 1024:.1f}MB'

    label = candidate.title or ''
    if not label and candidate.preview:
        # First sentence / line of preview, capped
        label = candidate.preview.replace('\n', ' ').strip()
    label = label[:max_preview] if label else ''

    base = f'- {rel} ({candidate.extension or "?"}, {size_str})'
    return f'{base} — {label}' if label else base


async def build_file_catalog_text(
    roots: List[str],
    *,
    max_files: int,
    max_depth: int,
    max_preview_chars: int,
    exclude_extra: Optional[List[str]],
    max_file_size_mb: int = 50,
    oversized_pdf_timeout_s: float = 1.0,
    max_chars: int = 10_000,
) -> str:
    """Build a two-section catalog for the localsearch tool description.

    Section 1 — Directory tree (filesystem walk, no IO beyond stat):
        Gives the model the full directory structure so it understands where
        to look without needing to enumerate every file.  Capped at ~60% of
        the max_chars budget so that file summaries always get space too.

    Section 2 — File summaries (from DirectoryScanner, capped by max_files):
        Compact one-liners: relative path, size, and a short content hint.
        Sorted by path so related files appear together.

    The combined output fits within max_chars (the caller may still apply
    _truncate_catalog_text for final trimming of the file-summary entries).
    """
    try:
        from sirchmunk.scan.dir_scanner import DirectoryScanner
    except ImportError as e:
        raise ImportError('sirchmunk is required for description_catalog. '
                          f'Import failed: {e}') from e

    # Tree gets 60% of the budget; file summaries get the remaining 40%.
    # Each root shares the budget equally.
    num_roots = max(1, len(roots))
    per_root_budget = max(500, max_chars // num_roots)
    tree_budget = max(300, int(per_root_budget * 0.60))

    max_file_size_bytes = (max_file_size_mb * 1024
                           * 1024) if max_file_size_mb > 0 else None
    # Merge the built-in skip sets with any user-provided excludes so the
    # scanner also skips generated/artifact directories.
    scanner_exclude: List[str] = sorted(_DIR_SKIP | _DIR_SKIP_GENERATED)
    if exclude_extra:
        scanner_exclude.extend(exclude_extra)
    scanner = DirectoryScanner(
        llm=None,
        max_depth=max_depth,
        max_files=max_files,
        max_preview_chars=max_preview_chars,
        exclude_patterns=scanner_exclude,
        max_file_size_bytes=max_file_size_bytes,
        oversized_pdf_timeout_s=oversized_pdf_timeout_s,
    )

    sections: List[str] = []
    for root in roots:
        p = Path(root)
        if not p.exists():
            sections.append(f'### `{root}`\n(missing on disk)')
            continue

        # --- Section 1: directory tree (fast, no content reads) ---
        tree = _build_dir_tree(
            p,
            max_depth=max_depth,
            exclude=exclude_extra,
            max_chars=tree_budget)
        tree_block = f'#### Directory structure of `{p}`\n{tree}' if tree else ''

        # --- Section 2: per-file compact summaries ---
        result = await scanner.scan(p)
        # Sort first so round-robin within each subdir is deterministic
        all_candidates = sorted(result.candidates, key=lambda c: c.path)
        # Stratified reorder: root files first, then round-robin across
        # subdirectories (smallest subdir first for maximum coverage).
        # Always reorder regardless of count — the char-budget trim below
        # does the actual limiting.
        reordered = _stratified_sample(all_candidates, p, len(all_candidates))

        # Trim to the files char budget (40% of total per-root budget).
        # Trimming the *reordered* list ensures diverse coverage is preserved.
        files_budget = max(200, per_root_budget - tree_budget - 80)
        file_lines: List[str] = []
        omitted = 0
        if reordered:
            used_f = 0
            for c in reordered:
                line = _compact_file_summary(c, str(p), max_preview=100)
                if used_f + len(line) + 1 > files_budget:
                    omitted = len(reordered) - len(file_lines)
                    break
                file_lines.append(line)
                used_f += len(line) + 1
        else:
            file_lines.append('_(no scannable files in depth budget)_')

        total_scanned = len(all_candidates)
        header = f'#### File summaries ({len(file_lines)} of {total_scanned} sampled)'
        if omitted:
            file_block = header + '\n' + '\n'.join(
                file_lines) + f'\n… ({omitted} more files not shown)'
        else:
            file_block = header + '\n' + '\n'.join(file_lines)

        root_section = f'### Under `{p}`\n\n{tree_block}\n\n{file_block}'
        sections.append(root_section.strip())

    return '\n\n---\n\n'.join(sections).strip()


def _stratified_sample(candidates: List[Any], root: Path,
                       max_entries: int) -> List[Any]:
    """Return a stratified sample of candidates so every subdirectory gets
    representation, rather than simply taking the first N by path.

    Algorithm:
    1. Root-level files first (high information density — README, pyproject, etc.)
    2. One representative per unique immediate subdirectory, round-robin until
       the budget is exhausted.  Subdirectories with fewer files are serviced
       first so smaller modules are not crowded out by large doc/data trees.

    Within each group files are ordered by path so the result is deterministic.
    Always reorders — callers rely on this even when len(candidates) == max_entries.
    """
    # Split into root-level vs sub-directory files
    root_files: List[Any] = []
    by_subdir: dict = {}
    for c in candidates:
        try:
            rel = Path(c.path).relative_to(root)
        except ValueError:
            rel = Path(c.path)
        parts = rel.parts
        if len(parts) == 1:
            root_files.append(c)
        else:
            subdir = parts[0]
            by_subdir.setdefault(subdir, []).append(c)

    result: List[Any] = []

    # Always include all root-level files first (usually just a handful)
    result.extend(root_files)

    if not by_subdir:
        return result[:max_entries]

    # Round-robin across subdirectories.
    # Sort subdirs by file count ascending so smaller directories (which are
    # likely to have fewer but more targeted files) get their representative
    # entry before large documentation/data directories exhaust the budget.
    subdirs = sorted(by_subdir.keys(), key=lambda s: len(by_subdir[s]))
    subdir_iters = {s: iter(by_subdir[s]) for s in subdirs}
    while len(result) < max_entries and subdir_iters:
        exhausted = []
        for s in subdirs:
            if len(result) >= max_entries:
                break
            it = subdir_iters.get(s)
            if it is None:
                continue
            try:
                result.append(next(it))
            except StopIteration:
                exhausted.append(s)
        for s in exhausted:
            del subdir_iters[s]
        if not subdir_iters:
            break

    return result[:max_entries]
