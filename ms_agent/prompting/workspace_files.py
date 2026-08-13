# Copyright (c) ModelScope Contributors. All rights reserved.
"""Workspace prompt files — the *environment* half of the system prompt.

User-editable Markdown sources:

- ``~/.ms_agent/SOUL.md``               persona (additive layer)
- ``~/.ms_agent/AGENTS.md``             global standing instructions
- ``~/.ms_agent/PROFILE.md``            who the user is
- ``<work_dir>/AGENTS.md``              project instructions (shared slot)
- ``<work_dir>/.ms_agent/AGENTS.md``    project instructions (private slot)

Behavioral contract (docs: prompt-context design-final §2.1/§3/§5.4):

- **Seeded != injected.** Templates keep guidance inside HTML comments; the
  injection pipeline strips frontmatter + HTML comments and skips empty
  results, so a pristine template contributes nothing.
- **Ensure-on-first-read** (lazy, entrance-agnostic) with a sha256 sidecar per
  home file: pristine files upgrade silently on template bumps, user-edited
  files are never overwritten, deleted files stay deleted.
- **Legacy PROFILE rebuild**: an old free-text ``profile.md`` is rebuilt once
  into the new format (template header + old text as free region), with a
  ``.bak`` and a non-pristine sidecar so upgrades never clobber user content.
- **mtime cache** so the per-round system-prompt rebuild does no repeat IO.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

from ms_agent.prompting.builtin import (HOME_FILE_TEMPLATES, TEMPLATE_VERSION)
from ms_agent.project.paths import global_home, local_internal_dir
from ms_agent.utils.logger import get_logger

logger = get_logger()

#: Per-file cap on injected characters (hermes-style context cap).
MAX_FILE_CHARS = 20_000

_FRONTMATTER_RE = re.compile(r'^\s*---\s*\n.*?\n---\s*\n?', re.DOTALL)
_HTML_COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)
_CALL_ME_RE = re.compile(r'^\s*[-*]\s*\**\s*Call me\s*\**\s*[:：]\s*(.*)$',
                         re.IGNORECASE)

#: name -> sidecar filename (records what the framework materialized).
_SIDECAR_NAMES = {
    'SOUL.md': '.soul.builtin',
    'AGENTS.md': '.agents.builtin',
    'PROFILE.md': '.profile.builtin',
}

# (path -> (mtime_ns, size, text)) read cache; (path) set for truncate warns.
_read_cache: Dict[str, Tuple[int, int, str]] = {}
_warned_truncate: set = set()
_ensured_homes: set = set()


def reset_cache() -> None:
    """Testing/tooling hook: forget cached reads and ensure state."""
    _read_cache.clear()
    _warned_truncate.clear()
    _ensured_homes.clear()


# ── strip pipeline ───────────────────────────────────────────────────────────


def strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub('', text, count=1)


def strip_html_comments(text: str) -> str:
    return _HTML_COMMENT_RE.sub('', text)


def strip_for_injection(text: str) -> str:
    """frontmatter → HTML comments → trim. Empty result means "inject nothing"."""
    return strip_html_comments(strip_frontmatter(text)).strip()


def _escape_closing(body: str, tag: str) -> str:
    """Keep user content from breaking out of its source-labelled wrapper."""
    return body.replace(f'</{tag}>', f'<\\/{tag}>')


def wrap_block(tag: str, source: str, body: str) -> str:
    return f'<{tag} source="{source}">\n{_escape_closing(body, tag)}\n</{tag}>'


# ── cached raw reads ─────────────────────────────────────────────────────────


def _read_raw(path: Path) -> str:
    """mtime-cached raw read; '' when missing/unreadable."""
    key = str(path)
    try:
        st = path.stat()
    except OSError:
        _read_cache.pop(key, None)
        return ''
    cached = _read_cache.get(key)
    if cached and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
        return cached[2]
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    _read_cache[key] = (st.st_mtime_ns, st.st_size, text)
    return text


def _capped(body: str, path: Path) -> str:
    if len(body) <= MAX_FILE_CHARS:
        return body
    if str(path) not in _warned_truncate:
        _warned_truncate.add(str(path))
        logger.warning(
            f'[workspace_files] {path} exceeds {MAX_FILE_CHARS} chars; '
            f'truncating its injected content')
    return body[:MAX_FILE_CHARS] + '\n\n[...truncated: file exceeds limit...]'


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(path)


# ── sidecar bookkeeping ──────────────────────────────────────────────────────


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _sidecar_path(home: Path, name: str) -> Path:
    return home / _SIDECAR_NAMES[name]


def _load_sidecar(home: Path, name: str) -> Optional[dict]:
    try:
        return json.loads(_sidecar_path(home, name).read_text('utf-8'))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _save_sidecar(home: Path, name: str, data: dict) -> None:
    try:
        _atomic_write(_sidecar_path(home, name), json.dumps(data, indent=1))
    except OSError as e:  # sidecar failures must never break the agent
        logger.warning(f'[workspace_files] cannot write sidecar for {name}: {e}')


# ── ensure / rebuild (route B) ───────────────────────────────────────────────


def _ensure_one(home: Path, name: str, template: str) -> None:
    path = home / name
    sidecar = _load_sidecar(home, name)
    if not path.exists():
        if sidecar is not None:
            return  # user deleted it — respect the deletion, never re-seed
        try:
            _atomic_write(path, template)
        except OSError as e:
            logger.warning(f'[workspace_files] cannot materialize {name}: {e}')
            return
        _save_sidecar(home, name, {
            'template_version': TEMPLATE_VERSION,
            'sha256': _sha256(template),
            'pristine': True,
        })
        logger.info(f'[workspace_files] materialized default {name} in {home}')
        return
    # Existing file: silent upgrade only when pristine (hash matches what we
    # wrote) and the built-in template moved forward.
    if (sidecar and sidecar.get('pristine')
            and sidecar.get('template_version', 0) < TEMPLATE_VERSION
            and _sha256(_read_raw(path)) == sidecar.get('sha256')):
        try:
            _atomic_write(path.with_name(name + '.bak'), _read_raw(path))
            _atomic_write(path, template)
        except OSError as e:
            logger.warning(f'[workspace_files] cannot upgrade {name}: {e}')
            return
        _save_sidecar(home, name, {
            'template_version': TEMPLATE_VERSION,
            'sha256': _sha256(template),
            'pristine': True,
        })
        logger.info(f'[workspace_files] upgraded pristine {name} to '
                    f'template v{TEMPLATE_VERSION}')


def _is_new_format(raw: str) -> bool:
    """New-format files start with a frontmatter block carrying ``version:``."""
    if not raw.lstrip().startswith('---'):
        return False
    m = _FRONTMATTER_RE.match(raw.lstrip())
    return bool(m and re.search(r'^version\s*:', m.group(0), re.MULTILINE))


def _rebuild_legacy_profile(home: Path) -> None:
    """One-time rebuild of a legacy free-text profile into the new format.

    New file = template header (frontmatter + comment guidance) + the old text
    verbatim as the free region. Old content is backed up; the sidecar is
    written non-pristine so template upgrades can never clobber user text.
    """
    target = home / 'PROFILE.md'
    legacy = home / 'profile.md'
    src = target if target.exists() else (legacy if legacy.exists() else None)
    if src is None:
        return
    raw = _read_raw(src)
    if _is_new_format(raw):
        return
    template = HOME_FILE_TEMPLATES['PROFILE.md']
    rebuilt = template.rstrip('\n') + '\n'
    if raw.strip():
        rebuilt += '\n' + raw.strip() + '\n'
    try:
        _atomic_write(target.with_name('PROFILE.md.bak'), raw)
        _atomic_write(target, rebuilt)
        # On case-sensitive filesystems the legacy lowercase file is a distinct
        # entry; drop it (its content lives in the .bak and in the new file).
        # On case-insensitive filesystems (macOS/Windows default) they are the
        # same file and os.replace() KEEPS the existing directory entry's case
        # — fix the case with an explicit rename so the file really is
        # PROFILE.md everywhere.
        if legacy.exists():
            try:
                same = legacy.samefile(target)
            except OSError:
                same = False
            if not same:
                legacy.unlink(missing_ok=True)
            else:
                try:
                    legacy.rename(target)  # case-only rename
                except OSError:
                    pass
    except OSError as e:
        # Read-only FS etc.: keep reading the legacy file in place — the strip
        # pipeline treats plain text as free region, injection is unaffected.
        logger.warning(f'[workspace_files] profile rebuild skipped: {e}')
        return
    _save_sidecar(home, 'PROFILE.md', {
        'template_version': TEMPLATE_VERSION,
        'sha256': _sha256(rebuilt),
        'pristine': False,
        'rebuilt_from': src.name,
    })
    logger.info(f'[workspace_files] rebuilt legacy {src.name} -> PROFILE.md '
                f'(backup: PROFILE.md.bak)')


def ensure_home_files(home: Optional[Path] = None) -> None:
    """Materialize missing home files + run the one-time PROFILE rebuild.

    Idempotent and cheap after the first call per home (keyed by path so tests
    that redirect ``MS_AGENT_HOME`` re-ensure their own home).
    """
    home = home or global_home()
    key = str(home)
    if key in _ensured_homes:
        return
    _rebuild_legacy_profile(home)
    for name, template in HOME_FILE_TEMPLATES.items():
        _ensure_one(home, name, template)
    _ensured_homes.add(key)


# ── PROFILE region model (R0 header / R1 managed / R2 free) ─────────────────


def _line_comment_flags(lines):
    """Per-line flag: True when the line is entirely comment/blank inside a
    ``<!-- -->`` block (template guidance), i.e. carries no injectable text."""
    flags = []
    in_comment = False
    for line in lines:
        stripped_spans = _HTML_COMMENT_RE.sub('', line)
        if in_comment:
            if '-->' in line:
                in_comment = False
                rest = line.split('-->', 1)[1]
                flags.append(not rest.strip())
            else:
                flags.append(True)
            continue
        opens = line.count('<!--') > line.count('-->')
        if opens:
            in_comment = True
            before = line.split('<!--', 1)[0]
            flags.append(not before.strip())
        else:
            flags.append(not stripped_spans.strip() and bool(
                _HTML_COMMENT_RE.search(line)))
    return flags


def split_profile_regions(text: str) -> Tuple[str, str, str]:
    """Split PROFILE text into (R0 header, R1 managed block, R2 free region).

    R0 = frontmatter + leading comment/blank lines; R1 = an uncommented
    ``# About Me`` heading plus its consecutive list lines (if it is the first
    visible content); R2 = everything else. ``text == r0 + r1 + r2``.
    """
    fm = _FRONTMATTER_RE.match(text)
    fm_end = fm.end() if fm else 0
    rest = text[fm_end:]
    lines = rest.splitlines(keepends=True)
    flags = _line_comment_flags([ln.rstrip('\n') for ln in lines])

    i = 0
    while i < len(lines) and (flags[i] or not lines[i].strip()):
        i += 1
    r0 = text[:fm_end] + ''.join(lines[:i])

    j = i
    if i < len(lines) and lines[i].strip().lower() == '# about me':
        j = i + 1
        while j < len(lines):
            s = lines[j].strip()
            if not s:
                # blank line ends the managed block unless a list item follows
                nxt = lines[j + 1].strip() if j + 1 < len(lines) else ''
                if re.match(r'^[-*]\s', nxt):
                    j += 1
                    continue
                break
            if re.match(r'^[-*]\s', s):
                j += 1
                continue
            break
    r1 = ''.join(lines[i:j])
    r2 = ''.join(lines[j:])
    return r0, r1, r2


def get_call_me(text: str) -> str:
    """Read the managed ``- Call me:`` value (comment-aware)."""
    lines = text.splitlines()
    flags = _line_comment_flags(lines)
    for line, in_comment in zip(lines, flags):
        if in_comment:
            continue
        m = _CALL_ME_RE.match(line)
        if m:
            return m.group(1).strip()
    return ''


def set_call_me(text: str, value: str) -> str:
    """Surgical single-line edit of the managed ``- Call me:`` line.

    Empty ``value`` removes the line. Everything else in the file is preserved
    byte-for-byte.
    """
    value = ' '.join(value.split())[:80]
    lines = text.splitlines(keepends=True)
    flags = _line_comment_flags([ln.rstrip('\n') for ln in lines])
    for idx, (line, in_comment) in enumerate(zip(lines, flags)):
        if in_comment:
            continue
        if _CALL_ME_RE.match(line.rstrip('\n')):
            if value:
                nl = '\n' if line.endswith('\n') else ''
                lines[idx] = f'- Call me: {value}{nl}'
            else:
                lines[idx] = ''
            return ''.join(lines)
    if not value:
        return text
    r0, r1, r2 = split_profile_regions(text)
    if r1:
        # Insert right under the "# About Me" heading.
        r1_lines = r1.splitlines(keepends=True)
        r1_lines.insert(1, f'- Call me: {value}\n')
        return r0 + ''.join(r1_lines) + r2
    block = f'# About Me\n- Call me: {value}\n'
    sep_before = '' if (not r0 or r0.endswith('\n\n')) else (
        '\n' if r0.endswith('\n') else '\n\n')
    sep_after = '\n' if r2.strip() else ''
    return r0 + sep_before + block + sep_after + r2


def get_free_region(text: str) -> str:
    return split_profile_regions(text)[2]


def set_free_region(text: str, new_free: str) -> str:
    r0, r1, _ = split_profile_regions(text)
    if new_free and not new_free.endswith('\n'):
        new_free += '\n'
    return r0 + r1 + new_free


# ── raw file access (shared by UI backends; same ensure/rebuild semantics) ──


def read_home_file(name: str) -> str:
    """Raw text of a home workspace file (SOUL/AGENTS/PROFILE), after the
    ensure/rebuild pass. '' when missing."""
    ensure_home_files()
    return _read_raw(global_home() / name)


def write_home_file(name: str, text: str) -> None:
    """Atomic write of a home workspace file. The mtime bump makes the next
    agent round pick the change up through the content compare."""
    _atomic_write(global_home() / name, text)


#: AGENTS.md has no managed block; the same splitter degrades to (R0, '', R2).
split_regions = split_profile_regions


# ── injected block builders (consumed by LLMAgent) ───────────────────────────


def soul_content() -> str:
    """Layer ②: the persona body (stripped, no wrapper — first-person voice)."""
    ensure_home_files()
    path = global_home() / 'SOUL.md'
    return _capped(strip_for_injection(_read_raw(path)), path)


def global_instructions_block(legacy_fallback: str = '') -> str:
    """Layer ③ body. File wins only when it has real (stripped) content; a
    pristine template must NOT shadow the legacy settings field (§7)."""
    ensure_home_files()
    path = global_home() / 'AGENTS.md'
    body = _capped(strip_for_injection(_read_raw(path)), path)
    if body:
        return wrap_block('instructions', '~/.ms_agent/AGENTS.md', body)
    legacy = (legacy_fallback or '').strip()
    if legacy:
        return wrap_block('instructions', 'legacy:settings.json', legacy)
    return ''


def project_instructions_block(work_dir: Optional[str],
                               legacy_fallback: str = '') -> str:
    """Layer ④ body: shared slot then private slot, additive (never either-or)."""
    blocks = []
    if work_dir:
        shared = Path(work_dir) / 'AGENTS.md'
        body = _capped(strip_for_injection(_read_raw(shared)), shared)
        if body:
            blocks.append(wrap_block('instructions', 'AGENTS.md', body))
        private = local_internal_dir(work_dir) / 'AGENTS.md'
        body = _capped(strip_for_injection(_read_raw(private)), private)
        if body:
            blocks.append(
                wrap_block('instructions', '.ms_agent/AGENTS.md', body))
    if blocks:
        return '\n\n'.join(blocks)
    legacy = (legacy_fallback or '').strip()
    if legacy:
        return wrap_block('instructions', 'legacy:project.instruction', legacy)
    return ''


def profile_block() -> str:
    """Layer ⑤ body: the whole PROFILE (managed + free regions), stripped."""
    ensure_home_files()
    path = global_home() / 'PROFILE.md'
    raw = _read_raw(path)
    if not raw:
        # Rebuild fallback path: a legacy lowercase file may still be the only
        # readable copy (read-only FS degradation).
        raw = _read_raw(global_home() / 'profile.md')
    body = _capped(strip_for_injection(raw), path)
    if body:
        return wrap_block('profile', '~/.ms_agent/PROFILE.md', body)
    return ''


# ── hot-reload update notices ────────────────────────────────────────────────
#
# The head layers rebuild every round (content compare in
# SkillRuntime.maybe_refresh_system_prompt), so a mid-conversation edit to any
# file above is silently live from the next round. Silent is the problem: the
# model sees the *new* content with no event, cannot tell "the file changed"
# from "I misremembered", and may even deny that it can see mid-session edits.
# LLMAgent therefore fingerprints these sources per user turn and, when they
# drifted since the model last saw them, prefixes the new user message with a
# durable <system-reminder> naming the changed files (same delivery as skill
# update notices: part of the persisted turn, survives context reassembly,
# keeps requests prefix-extensions of each other).

#: Matches any <system-reminder> block (skill notices, recall attachments,
#: update notices). Used to strip notices out of retrieval queries and
#: display copies — the blocks are framework metadata, not user words.
REMINDER_BLOCK_RE = re.compile(r'<system-reminder>.*?</system-reminder>\s*',
                               re.DOTALL)

#: Stable first-line marker of a prompt-files update notice.
UPDATE_NOTICE_MARKER = 'Workspace files behind your system prompt changed'


def head_source_fingerprints(work_dir: Optional[str] = None) -> Dict[str, str]:
    """Per-source content hashes of the hot-reloadable head files.

    Keys are the display labels used in update notices (aligned with the
    ``source=`` labels of the injected wrappers). Values hash the *injected*
    body (stripped), so comment-only template edits and frontmatter churn do
    not fire notices — only changes the model can actually see do.
    """
    ensure_home_files()
    home = global_home()

    def _body(path: Path) -> str:
        return _capped(strip_for_injection(_read_raw(path)), path)

    sources = {
        '~/.ms_agent/SOUL.md': _body(home / 'SOUL.md'),
        '~/.ms_agent/AGENTS.md': _body(home / 'AGENTS.md'),
        '~/.ms_agent/PROFILE.md': _body(home / 'PROFILE.md'),
    }
    if work_dir:
        sources['<project>/AGENTS.md'] = _body(Path(work_dir) / 'AGENTS.md')
        sources['<project>/.ms_agent/AGENTS.md'] = _body(
            local_internal_dir(work_dir) / 'AGENTS.md')
    return {label: _sha256(body) for label, body in sources.items()}


def render_update_notice(changed: list) -> str:
    """The <system-reminder> announcing which head files changed."""
    files = ', '.join(changed)
    return ('<system-reminder>\n'
            f'{UPDATE_NOTICE_MARKER} mid-conversation: {files}.\n'
            'Your system prompt has been refreshed in place and already '
            'reflects the latest file content. Where it differs from what '
            'earlier parts of this conversation assumed, the files changed — '
            'you did not misremember. Do not mention this notice to the user '
            'unless they ask about the change.\n'
            '</system-reminder>')
