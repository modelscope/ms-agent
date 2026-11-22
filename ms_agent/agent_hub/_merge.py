# Copyright (c) ModelScope Contributors. All rights reserved.
"""Section-level Markdown merge engine for cross-framework workspace migration."""
from __future__ import annotations

import difflib
import fnmatch
import re
from dataclasses import dataclass, field

from ms_agent.utils.logger import get_logger

logger = get_logger()


@dataclass
class Section:
    """A markdown section: optional title (## heading) + body lines."""
    title: str  # e.g. "## Active Tasks", empty string for preamble
    body: str  # everything after the title line until the next ## heading


@dataclass
class MergeAction:
    """Describes what happened to a single file or section during merge."""
    path: str
    action: str  # 'import' | 'default' | 'merged' | 'skip'
    detail: str  # human-readable description
    # For overflow merges (a source file with no target equivalent whose content
    # is folded into a catch-all file), record the mapping structurally so the
    # CLI can surface a "merged X -> Y" hint without parsing ``detail``.
    src_path: str = ''
    dst_path: str = ''


@dataclass
class MergeResult:
    """Result of merging a single file."""
    content: str
    actions: list[MergeAction] = field(default_factory=list)


@dataclass
class FullMergeResult:
    """Result of merging an entire resource set."""
    merged_files: dict[str, str] = field(default_factory=dict)
    actions: list[MergeAction] = field(default_factory=list)


class SectionMerger:
    """Markdown section-level merge engine.

    Splits markdown by ``## `` headings, diffs user content against source
    defaults, and produces a merged result using target defaults as the base.
    """

    # ---- Parsing ----

    @staticmethod
    def parse_sections(content: str) -> list[Section]:
        """Split markdown into sections by ``## `` headings.

        Comment-aware: a ``## `` line that falls INSIDE an HTML ``<!-- -->``
        block is template guidance, not a real heading, so it must not open a
        new section. ms-agent's AGENTS.md/PROFILE.md templates carry example
        headings (``## Preferences`` etc.) inside their guidance comment; without
        this guard the merger would treat the comment interior as content
        sections and mangle the template header when folding user content in.
        """
        lines = content.split('\n')
        sections: list[Section] = []
        current_title = ''
        current_lines: list[str] = []
        in_comment = False

        for line in lines:
            stripped = line.strip()
            if in_comment:
                current_lines.append(line)
                if '-->' in stripped:
                    in_comment = False
                continue
            if stripped.startswith('<!--') and '-->' not in stripped:
                in_comment = True
                current_lines.append(line)
                continue
            if re.match(r'^## ', line):
                sections.append(
                    Section(
                        title=current_title,
                        body='\n'.join(current_lines),
                    ))
                current_title = line
                current_lines = []
            else:
                current_lines.append(line)

        sections.append(
            Section(
                title=current_title,
                body='\n'.join(current_lines),
            ))
        return sections

    @staticmethod
    def sections_to_content(sections: list[Section]) -> str:
        """Reconstruct markdown from sections."""
        parts = []
        for sec in sections:
            if sec.title:
                parts.append(sec.title + '\n' + sec.body)
            else:
                parts.append(sec.body)
        return '\n'.join(parts)

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize whitespace for comparison."""
        return text.strip()

    # ---- Diffing ----

    def diff_sections(
        self,
        user_content: str,
        source_default: str,
    ) -> tuple[list[Section], list[Section], list[Section]]:
        """Compare user content against source default.

        Returns:
            (unchanged, modified, added) -- three lists of Section objects.
        """
        user_secs = self.parse_sections(user_content)
        default_secs = self.parse_sections(source_default)

        default_map: dict[str, str] = {}
        for sec in default_secs:
            if sec.title:
                default_map[sec.title] = self._normalize(sec.body)

        unchanged, modified, added = [], [], []

        for sec in user_secs:
            if not sec.title:
                default_preamble = ''
                for ds in default_secs:
                    if not ds.title:
                        default_preamble = self._normalize(ds.body)
                        break
                if self._normalize(sec.body) != default_preamble:
                    modified.append(sec)
                else:
                    unchanged.append(sec)
                continue

            if sec.title in default_map:
                if self._normalize(sec.body) == default_map[sec.title]:
                    unchanged.append(sec)
                else:
                    modified.append(sec)
            else:
                added.append(sec)

        return unchanged, modified, added

    # ---- Merging ----

    def merge(
        self,
        user_content: str,
        source_default: str,
        target_default: str,
    ) -> MergeResult:
        """Merge user content into target default using section-level diff.

        Strategy:
        1. Start with target_default sections as the base.
        2. For sections the user modified: replace the target section body.
        3. For sections the user added: append at the end.
        4. Unchanged sections keep the target default version.
        """
        unchanged, modified, added = self.diff_sections(
            user_content, source_default)
        target_secs = self.parse_sections(target_default)

        actions = []
        # Bucket modified sections BY TITLE INTO LISTS: a user file can
        # legitimately contain several sections with the same heading, and a
        # plain ``{title: sec}`` dict would keep only the last one, silently
        # dropping the earlier bodies (BUG-025). When the target has that
        # heading, ALL of the user's same-titled sections are placed there in
        # their original order.
        modified_by_title: dict[str, list[Section]] = {}
        for sec in modified:
            modified_by_title.setdefault(sec.title, []).append(sec)

        result_secs = []
        for tsec in target_secs:
            if tsec.title and modified_by_title.get(tsec.title):
                user_secs = modified_by_title.pop(tsec.title)
                result_secs.extend(user_secs)
                actions.append(
                    MergeAction(
                        path='',
                        action='user_modified',
                        detail=
                        f"Section '{tsec.title}' -- user modification preserved",
                    ))
            elif not tsec.title and modified_by_title.get(''):
                preamble_sec = modified_by_title.pop('')[0]
                result_secs.append(preamble_sec)
                actions.append(
                    MergeAction(
                        path='',
                        action='user_modified',
                        detail='Preamble -- user modification preserved',
                    ))
            else:
                result_secs.append(tsec)
                if tsec.title:
                    actions.append(
                        MergeAction(
                            path='',
                            action='keep_default',
                            detail=f"Section '{tsec.title}' -- target default",
                        ))

        # Append user-added sections
        for sec in added:
            result_secs.append(sec)
            actions.append(
                MergeAction(
                    path='',
                    action='user_added',
                    detail=
                    f"Section '{sec.title}' -- user custom section added",
                ))

        content = self.sections_to_content(result_secs)

        user_changes = len(modified) + len(added)
        summary = f'target default + {user_changes} user customization(s)'

        return MergeResult(
            content=content,
            actions=[MergeAction(path='', action='merged', detail=summary)]
            + actions,
        )


class HeartbeatMerger(SectionMerger):
    """Specialized merger for HEARTBEAT.md with line-level task merging
    inside the ``## Active Tasks`` section."""

    ACTIVE_TASKS_TITLE = '## Active Tasks'

    def _extract_task_lines(self, body: str) -> list[str]:
        """Extract non-empty, non-comment lines from a section body.

        Tracks multi-line ``<!-- ... -->`` comments: every line inside the
        comment is skipped, not just the opener/closer -- otherwise the
        middle lines of a user's block comment get treated as tasks and
        inserted into the task area (BUG-029).
        """
        lines = []
        in_comment = False
        for line in body.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue
            if in_comment:
                if '-->' in stripped:
                    in_comment = False
                continue
            if stripped.startswith('<!--'):
                if '-->' not in stripped:
                    in_comment = True
                continue
            if stripped.endswith('-->'):
                continue
            lines.append(line)
        return lines

    def merge(
        self,
        user_content: str,
        source_default: str,
        target_default: str,
    ) -> MergeResult:
        """Merge HEARTBEAT.md with line-level Active Tasks merging."""
        user_secs = self.parse_sections(user_content)
        default_secs = self.parse_sections(source_default)

        user_active_body = ''
        default_active_body = ''
        for sec in user_secs:
            if sec.title == self.ACTIVE_TASKS_TITLE:
                user_active_body = sec.body
                break
        for sec in default_secs:
            if sec.title == self.ACTIVE_TASKS_TITLE:
                default_active_body = sec.body
                break

        default_task_lines = set(
            line.strip()
            for line in self._extract_task_lines(default_active_body))
        user_task_lines = self._extract_task_lines(user_active_body)
        new_tasks = [
            line for line in user_task_lines
            if line.strip() not in default_task_lines
        ]

        result = super().merge(user_content, source_default, target_default)

        if not new_tasks:
            return result

        result_secs = self.parse_sections(result.content)
        for i, sec in enumerate(result_secs):
            if sec.title == self.ACTIVE_TASKS_TITLE:
                # The base section merge may already have preserved the
                # user's whole Active Tasks section (it counts as modified),
                # in which case the new tasks are ALREADY in the result --
                # appending them again would duplicate every task (BUG-028).
                # Only insert the ones actually missing.
                present = set(line.strip()
                              for line in self._extract_task_lines(sec.body))
                missing = [t for t in new_tasks if t.strip() not in present]
                if not missing:
                    return result
                body_lines = sec.body.split('\n')
                insert_idx = len(body_lines)
                for j, line in enumerate(body_lines):
                    if '<!--' in line and j > 0:
                        insert_idx = j + 1
                        break
                for task in missing:
                    body_lines.insert(insert_idx, task)
                    insert_idx += 1
                result_secs[i] = Section(
                    title=sec.title,
                    body='\n'.join(body_lines),
                )
                break
        else:
            # Target template has no ``## Active Tasks`` section at all --
            # without a landing spot the user's tasks would be silently
            # dropped (BUG-030). Create the section at the end so the tasks
            # stay traceable in the merged file.
            result_secs.append(
                Section(
                    title=self.ACTIVE_TASKS_TITLE,
                    body='\n' + '\n'.join(new_tasks) + '\n',
                ))

        result.content = self.sections_to_content(result_secs)
        result.actions.append(
            MergeAction(
                path='',
                action='task_merged',
                detail=
                f'{len(new_tasks)} user task(s) merged into Active Tasks',
            ))
        return result


# ---- Full resource merge orchestrator ----

PRODUCT_FILE_CLASSES = {
    'nanobot': {
        'portable':
        frozenset([
            'SOUL.md',
            'USER.md',
            'memory/MEMORY.md',
            'memory/history.jsonl',
        ]),
        'config':
        frozenset([
            'AGENTS.md',
            'HEARTBEAT.md',
        ]),
        'heartbeat':
        'HEARTBEAT.md',
    },
    'openclaw': {
        'portable':
        frozenset([
            'SOUL.md',
            'USER.md',
            'IDENTITY.md',
            'MEMORY.md',
        ]),
        'config':
        frozenset([
            'AGENTS.md',
            'HEARTBEAT.md',
            'TOOLS.md',
            'BOOT.md',
            'BOOTSTRAP.md',
        ]),
        'heartbeat':
        'HEARTBEAT.md',
    },
    'hermes': {
        'portable':
        frozenset([
            'SOUL.md',
            'memories/USER.md',
            'memories/MEMORY.md',
        ]),
        'config':
        frozenset([]),
        'heartbeat':
        '',
    },
    'qwenpaw': {
        'portable': frozenset([
            'SOUL.md',
            'PROFILE.md',
            'MEMORY.md',
        ]),
        'config': frozenset([
            'AGENTS.md',
            'HEARTBEAT.md',
            'BOOTSTRAP.md',
        ]),
        'heartbeat': 'HEARTBEAT.md',
    },
    'openhuman': {
        # Per the official "move to a new PC" guide OpenHuman carries the
        # persona files SOUL/IDENTITY plus the HEARTBEAT task file; the
        # wiki/ vault is imported as-is (not a classified persona file).
        # MEMORY.md is the curated long-term memory injected every session
        # (the wiki mirrors the Memory Tree instead), so it travels too.
        'portable': frozenset([
            'SOUL.md',
            'IDENTITY.md',
            'MEMORY.md',
        ]),
        'config': frozenset([
            'HEARTBEAT.md',
        ]),
        'heartbeat': 'HEARTBEAT.md',
    },
    'qoder': {
        'portable': frozenset([]),
        'config': frozenset([
            'AGENTS.md',
        ]),
        'heartbeat': '',
    },
    'ms-agent': {
        # SOUL/AGENTS/PROFILE are real editable Markdown and carry the
        # cross-framework persona/instructions/profile semantics; SOUL and
        # PROFILE are persona-like (portable), AGENTS is standing instructions
        # (config), matching how the other frameworks classify them. The
        # config.yaml/settings.json/agent.yaml/skills.json files are ms-agent
        # private and preserved on same-framework sync only. Memory is not
        # here (runtime keeps it project-level), so ms-agent carries none.
        'portable': frozenset([
            'SOUL.md',
            'PROFILE.md',
        ]),
        'config': frozenset([
            'AGENTS.md',
        ]),
        'heartbeat': '',
    },
}

_DEFAULT_FILE_CLASS = {
    'portable': frozenset(['SOUL.md', 'USER.md']),
    'config': frozenset(['AGENTS.md', 'HEARTBEAT.md', 'TOOLS.md']),
    'heartbeat': 'HEARTBEAT.md',
}

# Framework-private files: same NAME across frameworks but incompatible FORMAT
# (e.g. hermes vs ms-agent ``config.yaml``, ms-agent vs qwenpaw ``skill.json``).
# They have no cross-framework semantics, so on a convert they must be dropped
# -- NOT carried over verbatim.  The normal safety net (a file with no target
# pattern is filtered out downstream) fails exactly here, because the target
# framework happens to declare an identically-named pattern and would load a
# file it cannot parse.  Same-framework sync is unaffected (that path keeps
# every file verbatim by design).
PRODUCT_PRIVATE_FILES = {
    'hermes': frozenset(['config.yaml', 'hooks/*']),
    'ms-agent': frozenset(['settings.json', 'skills.json', 'mcp.json']),
    'qwenpaw': frozenset(['agent.json', 'skill.json']),
    'openhuman': frozenset(['config.toml']),
}

# openhuman records HOW a skill was installed in a per-skill sidecar:
# ``_meta.json`` (marketplace entry: owner/slug/publishedAt) and
# ``metadata.json`` (github source: repo/path/downloaded_at). Both are
# openhuman-private provenance with no meaning to other frameworks, so a
# cross-framework convert drops them while same-framework sync keeps them
# (BUG-0828).
_SKILL_PROVENANCE_FILES = {
    'openhuman': frozenset(['_meta.json', 'metadata.json']),
}


def _is_private_file(product: str, path: str) -> bool:
    """Whether *path* is a framework-private (non-portable) file of *product*.

    Matches by fnmatch so glob entries like ``hooks/*`` cover their whole tree.
    """
    for pat in PRODUCT_PRIVATE_FILES.get(product, ()):
        if path == pat or fnmatch.fnmatch(path, pat):
            return True
    return False


_section_merger = SectionMerger()
_heartbeat_merger = HeartbeatMerger()

# ---- Cross-product path mapping ----
SEMANTIC_GROUPS = [
    {
        'nanobot': 'SOUL.md',
        'openclaw': 'SOUL.md',
        'hermes': 'SOUL.md',
        'qwenpaw': 'SOUL.md',
        'openhuman': 'SOUL.md',
        'ms-agent': 'SOUL.md'
    },
    {
        # No qwenpaw / qoder entries: neither framework has a USER.md slot,
        # so profile content for them folds into the target's catch-all file
        # with a visible hint instead of landing in a file never read.
        'nanobot': 'USER.md',
        'openclaw': 'USER.md',
        'hermes': 'memories/USER.md',
        'ms-agent': 'PROFILE.md'
    },
    {
        'nanobot': 'memory/MEMORY.md',
        'openclaw': 'MEMORY.md',
        'qwenpaw': 'MEMORY.md',
        'hermes': 'memories/MEMORY.md',
        'openhuman': 'MEMORY.md',
        'qoder': 'memory/MEMORY.md'
    },
    {
        'openclaw': 'IDENTITY.md',
        'openhuman': 'IDENTITY.md'
    },
    {
        'qwenpaw': 'PROFILE.md',
    },
    {
        # openhuman's long-term goals list: no counterpart elsewhere, so
        # cross-framework it folds into the target's catch-all file.
        'openhuman': 'MEMORY_GOALS.md',
    },
    {
        'nanobot': 'AGENTS.md',
        'openclaw': 'AGENTS.md',
        'qwenpaw': 'AGENTS.md',
        'qoder': 'AGENTS.md',
        'ms-agent': 'AGENTS.md'
    },
    {
        'nanobot': 'HEARTBEAT.md',
        'openclaw': 'HEARTBEAT.md',
        'qwenpaw': 'HEARTBEAT.md',
        'openhuman': 'HEARTBEAT.md'
    },
    {
        'openclaw': 'TOOLS.md'
    },
    {
        'openclaw': 'BOOTSTRAP.md',
        'qwenpaw': 'BOOTSTRAP.md'
    },
    {
        'nanobot': 'memory/history.jsonl'
    },
]

_ALL_PRODUCTS = [
    'nanobot', 'openclaw', 'hermes', 'qwenpaw', 'openhuman', 'qoder',
    'ms-agent'
]


def _build_path_map():
    path_map = {}
    for group in SEMANTIC_GROUPS:
        for src_product, src_path in group.items():
            targets = {
                tgt_product: group.get(tgt_product)
                for tgt_product in _ALL_PRODUCTS if tgt_product != src_product
            }
            path_map[(src_product, src_path)] = targets
    return path_map


PATH_MAP = _build_path_map()

PRODUCT_KNOWN_FILES = {
    'nanobot':
    frozenset([
        'SOUL.md',
        'USER.md',
        'AGENTS.md',
        'HEARTBEAT.md',
        'memory/MEMORY.md',
        'memory/history.jsonl',
    ]),
    'openclaw':
    frozenset([
        'SOUL.md',
        'USER.md',
        'AGENTS.md',
        'TOOLS.md',
        'HEARTBEAT.md',
        'IDENTITY.md',
        'BOOT.md',
        'BOOTSTRAP.md',
        'MEMORY.md',
    ]),
    'hermes':
    frozenset([
        'SOUL.md',
        'memories/USER.md',
        'memories/MEMORY.md',
        'config.yaml',
    ]),
    'qwenpaw':
    frozenset([
        'SOUL.md',
        'PROFILE.md',
        'AGENTS.md',
        'MEMORY.md',
        'HEARTBEAT.md',
        'BOOTSTRAP.md',
    ]),
    'openhuman':
    frozenset([
        'SOUL.md',
        'IDENTITY.md',
        'HEARTBEAT.md',
        'MEMORY.md',
    ]),
    'qoder':
    frozenset([
        'AGENTS.md',
    ]),
    'ms-agent':
    frozenset([
        'SOUL.md',
        'AGENTS.md',
        'PROFILE.md',
        'settings.json',
        'skills.json',
        'mcp.json',
    ]),
}


def _resolve_target_path(source_product: str, source_path: str,
                         target_product: str) -> str | None:
    """Resolve the target path for a source file in a cross-product migration."""
    if source_product == target_product:
        return source_path
    key = (source_product, source_path)
    if key in PATH_MAP:
        return PATH_MAP[key].get(target_product)
    return source_path


# Where UNMAPPED loose memory files (detail beside the canonical MEMORY.md
# index) land per target. ``None`` = the target reads a single memory file
# (:data:`_SINGLE_FILE_MEMORY_SLOTS`) and detail is inlined into it -- a file
# the runtime never reads is not a migration. openclaw uses its own
# ``memory/imports/<source>/`` convention; targets without an entry (ms-agent
# has no home-level memory) keep the source path for the spec filter to drop.
_MEMORY_LOOSE_HOME = {
    'hermes': None,
    'openclaw': 'memory/',
    'qwenpaw': 'memory/',
    'qoder': 'memory/',
    'openhuman': None,
    'nanobot': None,
}

# The single memory file each ``None`` target above actually reads.
_SINGLE_FILE_MEMORY_SLOTS = {
    'nanobot': 'memory/MEMORY.md',
    'hermes': 'memories/MEMORY.md',
    'openhuman': 'MEMORY.md',
}

# openhuman injects MEMORY.md into the system prompt under a char cap;
# detail beyond it would never be read, so it is skipped and reported.
_OPENHUMAN_MEMORY_INJECT_CAP = 2000

# hermes memory files are ``§``-delimited entry stores under a per-file char
# budget; an over-budget entry makes hermes refuse further memory writes, so
# overflow is skipped, never truncated.
_HERMES_ENTRY_DELIM = '\n§\n'
_HERMES_CHAR_LIMITS = {
    'memories/MEMORY.md': 2200,
    'memories/USER.md': 1375,
}
# Headings that are really file names add no entry context.
_HERMES_HEADING_DROP_RE = re.compile(
    r'\b(MEMORY|USER|SOUL|AGENTS|TOOLS|IDENTITY|CLAUDE)\.md\b', re.I)


def _normalize_entry_text(text: str) -> str:
    """Whitespace-collapsed lowercase form used for entry dedup."""
    return re.sub(r'\s+', ' ', (text or '').strip()).lower()


def _strip_yaml_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block: metadata, not memory content."""
    lines = text.splitlines()
    if lines and lines[0].strip() == '---':
        for idx in range(1, len(lines)):
            if lines[idx].strip() in ('---', '...'):
                return '\n'.join(lines[idx + 1:])
    return text


def _markdown_to_hermes_entries(text: str) -> list[str]:
    """Split a Markdown memory document into hermes entries: headings become
    context prefixes, bullets and paragraphs become entries, code blocks and
    table rows are skipped, duplicates dropped."""
    entries: list[str] = []
    headings: list[str] = []
    paragraph: list[str] = []

    def add_entry(content: str) -> None:
        prefix = ' > '.join(
            h for h in headings if h and not _HERMES_HEADING_DROP_RE.search(h))
        entries.append(f'{prefix}: {content}' if prefix else content)

    def flush() -> None:
        block = ' '.join(line.strip() for line in paragraph).strip()
        paragraph.clear()
        if block:
            add_entry(block)

    in_code = False
    lines = _strip_yaml_frontmatter(text or '').splitlines()
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code = not in_code
            flush()
            continue
        if in_code:
            continue
        heading = re.match(r'^(#{1,6})\s+(.*\S)\s*$', stripped)
        if heading:
            flush()
            headings[len(heading.group(1)) - 1:] = [heading.group(2).strip()]
            continue
        bullet = re.match(r'^\s*(?:[-*]|\d+\.)\s+(.*\S)\s*$', line)
        if bullet:
            flush()
            add_entry(bullet.group(1).strip())
            continue
        if not stripped or (stripped.startswith('|')
                            and stripped.endswith('|')):
            flush()
            continue
        paragraph.append(stripped)
    flush()

    deduped: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        normalized = _normalize_entry_text(entry)
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(entry.strip())
    return deduped


def _merge_hermes_entries(existing: list[str], incoming: list[str],
                          limit: int) -> tuple[list[str], dict]:
    """Dedupe *incoming* against *existing* under a cumulative char *limit*;
    entries that would bust it are skipped (never truncated) and counted."""
    merged = list(existing)
    seen = {_normalize_entry_text(e) for e in existing if e.strip()}
    stats = {'added': 0, 'duplicates': 0, 'overflowed': 0}
    current = len(_HERMES_ENTRY_DELIM.join(merged))
    for entry in incoming:
        normalized = _normalize_entry_text(entry)
        if not normalized:
            continue
        if normalized in seen:
            stats['duplicates'] += 1
            continue
        candidate = (len(entry) if not merged else
                     current + len(_HERMES_ENTRY_DELIM) + len(entry))
        if candidate > limit:
            stats['overflowed'] += 1
            continue
        merged.append(entry)
        seen.add(normalized)
        current = candidate
        stats['added'] += 1
    return merged, stats


def _hermes_entries_to_markdown(text: str) -> str:
    """Render a ``§``-delimited hermes store as Markdown paragraphs (hermes
    as SOURCE); text without the delimiter is returned unchanged."""
    if _HERMES_ENTRY_DELIM not in text:
        return text
    entries = [e.strip() for e in text.split(_HERMES_ENTRY_DELIM) if e.strip()]
    return ('\n\n'.join(entries) + '\n') if entries else text


def _rehome_loose_memory(path: str, source_product: str,
                         target_product: str) -> str | None:
    """Relocate one loose memory .md onto the target's layout; ``None`` means
    inline it into the target's single memory file. Non-``.md`` payloads and
    targets without a table entry keep the original path (the downstream
    target-spec filter decides their fate)."""
    if not path.endswith('.md'):
        return path
    if target_product not in _MEMORY_LOOSE_HOME:
        return path
    home = _MEMORY_LOOSE_HOME[target_product]
    if home is None:
        return None
    if target_product == 'openclaw':
        home = f'memory/imports/{source_product}/'
    return home + path.split('/', 1)[1]


def _memory_index_paths() -> dict:
    """Per-product canonical memory index path, derived from the MEMORY group."""
    for group in SEMANTIC_GROUPS:
        if group.get('nanobot') == 'memory/MEMORY.md':
            return dict(group)
    return {}


_MEMORY_INDEX_PATHS = _memory_index_paths()

_MD_LINK_RE = re.compile(r'\[([^\]]*)\]\(([^)\s]+)\)')


def _is_memory_slot(target_product: str, target_path: str) -> bool:
    """Whether *target_path* is one of the target's canonical memory files.

    Memory is user data: never rebase it onto a target default template --
    the template's placeholder lines would be read back as real memories
    (a single-file reader like nanobot injects them verbatim).
    """
    if target_path == _MEMORY_INDEX_PATHS.get(target_product):
        return True
    return (target_product == 'hermes'
            and target_path.startswith('memories/')
            and target_path.endswith('.md'))


def _rewrite_memory_index(content: str, src_index_dir: str,
                          moves: dict, tgt_index_dir: str,
                          target_product: str) -> str:
    """Keep index links resolvable after loose files moved or were inlined:
    moved links are rewritten to the new relative location, inlined ones
    de-linked. qoder discovers detail only through index references, so
    unreferenced moves get a line appended (a minimal index is created when
    the source had none)."""
    import posixpath

    # Old link forms (source-relative + unambiguous basenames) -> new link,
    # or None to de-link.
    forms: dict[str, str | None] = {}
    basenames: dict[str, list[str]] = {}
    for src_path, new_path in moves.items():
        rel = posixpath.relpath(src_path, src_index_dir or '.')
        new_rel = (None if new_path is None else
                   posixpath.relpath(new_path, tgt_index_dir or '.'))
        forms[rel] = new_rel
        base = posixpath.basename(src_path)
        basenames.setdefault(base, []).append(rel)
    for base, rels in basenames.items():
        if len(rels) == 1 and base not in forms:
            forms[base] = forms[rels[0]]

    def _sub(m):
        text, link = m.group(1), m.group(2)
        key = link[2:] if link.startswith('./') else link
        if key not in forms:
            return m.group(0)
        new_rel = forms[key]
        return f'[{text}]({new_rel})' if new_rel is not None else text

    content = _MD_LINK_RE.sub(_sub, content)

    if target_product == 'qoder':
        mentioned = {m.group(2) for m in _MD_LINK_RE.finditer(content)}
        missing = []
        for src_path, new_path in sorted(moves.items()):
            if new_path is None:
                continue
            rel = posixpath.relpath(new_path, tgt_index_dir or '.')
            if rel not in mentioned:
                stem = posixpath.basename(new_path)[:-3]
                missing.append(f'- [{stem}]({rel})')
        if missing:
            body = content.rstrip()
            if not body:
                body = '# Memory Index'
            content = body + '\n' + '\n'.join(missing) + '\n'
    return content


def _extract_user_diff_text(user_content: str, source_default: str) -> str:
    """Extract user customizations as a text block.

    Uses a positional line diff (not a global line-membership set): a user's
    own paragraph may legitimately REUSE a line that also appears somewhere
    in the template, and a set-based filter would delete it out of the middle
    of the user's paragraph (BUG-026). The sequence diff only removes lines
    where they positionally correspond to the template; the same text inside
    a user-inserted block is kept intact.
    """
    if not source_default.strip():
        return user_content.strip()

    user_lines = user_content.strip().split('\n')
    default_lines = source_default.strip().split('\n')
    matcher = difflib.SequenceMatcher(
        a=[line.strip() for line in default_lines],
        b=[line.strip() for line in user_lines],
        autojunk=False)

    diff_lines = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ('insert', 'replace'):
            diff_lines.extend(user_lines[j1:j2])

    return '\n'.join(diff_lines).strip()


def _catch_all_file(product: str) -> str:
    """The file that receives mutually-exclusive cross-product content."""
    known = PRODUCT_KNOWN_FILES.get(product)
    if known is None:
        return 'AGENTS.md'
    if 'AGENTS.md' in known:
        return 'AGENTS.md'
    if 'SOUL.md' in known:
        return 'SOUL.md'
    # Products without AGENTS.md/SOUL.md fall back to their persona file
    # (ms-agent's PROFILE.md; the legacy lowercase spelling is accepted too).
    if 'PROFILE.md' in known:
        return 'PROFILE.md'
    if 'profile.md' in known:
        return 'profile.md'
    return 'SOUL.md'


def merge_resources(
    incoming: dict[str, str],
    source_product: str,
    target_product: str,
    source_defaults: dict[str, str],
    target_defaults: dict[str, str],
    existing_skills: list[str] | None = None,
    fill_missing_defaults: bool = True,
    overflow_target: str | None = None,
    identity_source: str | None = None,
) -> FullMergeResult:
    """Merge incoming resources into a target product workspace.

    Args:
        incoming: files from the share snapshot {rel_path: content}
        source_product: product the snapshot came from
        target_product: product the user wants to apply to
        source_defaults: default templates for source product
        target_defaults: default templates for target product
        existing_skills: list of skill dir names already on target
        fill_missing_defaults: when *True*, add target default templates for
            file types that the source did not provide.  Set to *False* for
            convert / download so only files actually present in the source
            are written to the target.
        overflow_target: when given, mutually-exclusive ("overflow") content
            that has no semantic mapping on the target is routed to *this* path
            instead of the shared catch-all file.  Used for file-per-agent
            targets (e.g. qoder ``agents/{name}.md``) so a converted persona
            lands in its own sub-agent file rather than polluting the shared
            ``AGENTS.md``.
        identity_source: the SOURCE's per-agent persona file (file-per-agent
            source, e.g. qoder ``agents/<name>.md``).  Its name embeds the
            agent name so it can never appear in the static semantic path
            map; without this hint the fallback would carry it over under its
            original path and the target-spec filter would then drop it --
            losing the persona.  Marking it here forces the overflow/catch-all
            route (mirror of *overflow_target* for the outbound direction).
    """
    is_cross_product = source_product != target_product
    existing_skill_set = set(existing_skills or [])
    result = FullMergeResult()

    # hermes as SOURCE: its memory files are ``§``-delimited entry stores;
    # cross-framework they are rendered as Markdown paragraphs first.
    if is_cross_product and source_product == 'hermes':
        incoming = {
            p: (_hermes_entries_to_markdown(c)
                if p.startswith('memories/') and p.endswith('.md') else c)
            for p, c in incoming.items()
        }

    src_cls = PRODUCT_FILE_CLASSES.get(source_product, _DEFAULT_FILE_CLASS)
    tgt_cls = PRODUCT_FILE_CLASSES.get(target_product, _DEFAULT_FILE_CLASS)
    portable_files = src_cls['portable'] | tgt_cls['portable']
    config_files = src_cls['config'] | tgt_cls['config']
    heartbeat_file = tgt_cls.get('heartbeat', '')

    handled_target_paths = set()
    overflow_blocks: list[tuple[str, str]] = []
    # Loose detail deferred for inlining into single-file target slots;
    # applied after the loop so the canonical index forms the base.
    loose_inline: list[tuple[str, str]] = []
    # Source -> moved target path (None = inlined); drives the index rewrite.
    loose_moves: dict[str, str | None] = {}

    for path, content in incoming.items():
        # Skills: direct import, skip if exists.  Hermes' official
        # ``optional-skills/`` tree is structurally identical to ``skills/``;
        # cross-product it is normalized to ``skills/`` (no other framework
        # has an optional-skills slot, so keeping the prefix would get the
        # whole tree dropped by the target-spec filter downstream).
        skill_path = path
        if is_cross_product and path.startswith('optional-skills/'):
            skill_path = 'skills/' + path[len('optional-skills/'):]
        # Qoder ``commands/<x>.md`` ARE skills: the host runs them via the
        # skill framework (a ``name``/``description`` frontmatter + body,
        # triggered by ``/<x>``), identical in shape to a ``SKILL.md``. No
        # other framework has a ``commands/`` slot, so carrying the path over
        # verbatim gets it dropped by the target-spec filter (it looks
        # imported but never loads). Cross-product, re-home each command as
        # its own skill dir ``skills/<x>/SKILL.md`` so the target loads it
        # like a native skill; same-product qoder->qoder keeps it as-is.
        elif (is_cross_product and source_product == 'qoder'
              and path.startswith('commands/') and path.endswith('.md')):
            cmd_name = path[len('commands/'):-len('.md')]
            if cmd_name:
                skill_path = f'skills/{cmd_name}/SKILL.md'
        if skill_path.startswith('skills/'):
            parts = skill_path.split('/')
            skill_name = parts[1] if len(parts) > 1 else ''
            # Framework-private per-skill provenance sidecars never travel
            # across frameworks (BUG-0828).
            if (is_cross_product and len(parts) == 3
                    and parts[2] in _SKILL_PROVENANCE_FILES.get(
                        source_product, ())):
                result.actions.append(
                    MergeAction(
                        path=path,
                        action='skip',
                        detail=(f'{path} is {source_product}-private skill '
                                f'provenance, dropped'),
                    ))
                continue
            if skill_name in existing_skill_set:
                result.actions.append(
                    MergeAction(
                        path=path,
                        action='skip',
                        detail=
                        f"Skill '{skill_name}' already exists on target, skipped",
                    ))
                continue
            result.merged_files[skill_path] = content
            result.actions.append(
                MergeAction(
                    path=skill_path,
                    action='import',
                    detail='Skill imported' if skill_path == path else
                    (f'Qoder command converted to skill (from {path})'
                     if path.startswith('commands/') else
                     f'Optional skill imported (from {path})'),
                ))
            continue

        # Framework-private config/manifest with no cross-framework meaning
        # (e.g. hermes vs ms-agent ``config.yaml``): on a convert it must be
        # dropped rather than carried over, since the target framework may
        # declare an identically-named file it cannot parse. Same-framework
        # sync keeps everything, so only guard the cross-product path.
        if is_cross_product and _is_private_file(source_product, path):
            result.actions.append(
                MergeAction(
                    path=path,
                    action='skip',
                    detail=(f'{path} is {source_product}-private '
                            f'(incompatible format on {target_product}), '
                            f'dropped'),
                ))
            continue

        # The source's per-agent persona file (dynamic name, absent from the
        # static path map): force the no-equivalent route so it folds into the
        # target's persona file instead of being carried over verbatim and
        # dropped by the target-spec filter downstream.
        if is_cross_product and identity_source and path == identity_source:
            target_path = None
        else:
            target_path = _resolve_target_path(source_product, path,
                                               target_product)

        if target_path is None:
            if path.startswith('wiki/'):
                result.merged_files[path] = content
                result.actions.append(
                    MergeAction(
                        path=path,
                        action='import',
                        detail=
                        f'No mapping for {target_product}, imported as-is',
                    ))
                continue
            if path.startswith('memory/') or path.startswith('memories/'):
                # Unmapped memory file: re-home (or inline) onto the target's
                # layout instead of dying on its spec filter.
                new_path = _rehome_loose_memory(path, source_product,
                                                target_product)
                slot = _SINGLE_FILE_MEMORY_SLOTS.get(target_product, '')
                if new_path is None:
                    loose_inline.append((path, content))
                    loose_moves[path] = None
                    result.actions.append(
                        MergeAction(
                            path=slot,
                            action='merged',
                            detail=(f'Loose memory detail {path} inlined into '
                                    f'{slot}'),
                            src_path=path,
                            dst_path=slot,
                        ))
                    continue
                loose_moves[path] = new_path
                result.merged_files[new_path] = content
                result.actions.append(
                    MergeAction(
                        path=new_path,
                        action='import',
                        detail=(f'No mapping for {target_product}, '
                                'imported as-is') if new_path == path else
                        (f'Loose memory file rehomed {path} -> {new_path}'),
                    ))
                continue
            user_diff = _extract_user_diff_text(content,
                                                source_defaults.get(path, ''))
            if not user_diff:
                result.actions.append(
                    MergeAction(
                        path=path,
                        action='skip',
                        detail=
                        f'{path} has no equivalent in {target_product} and no user changes, skipped',
                    ))
                continue
            catch_all = overflow_target or _catch_all_file(target_product)
            block = f'## Imported from {source_product} {path}\n\n{user_diff}\n'
            overflow_blocks.append((catch_all, block))
            result.actions.append(
                MergeAction(
                    path=catch_all,
                    action='merged',
                    detail=
                    f'Mutually-exclusive content from {path} merged into {catch_all}',
                    src_path=path,
                    dst_path=catch_all,
                ))
            continue

        handled_target_paths.add(target_path)

        if not is_cross_product:
            if path in portable_files:
                result.merged_files[path] = content
                result.actions.append(
                    MergeAction(
                        path=path,
                        action='import',
                        detail='User data imported directly',
                    ))
            elif path in config_files:
                result.merged_files[path] = content
                result.actions.append(
                    MergeAction(
                        path=path,
                        action='import',
                        detail='Same product, imported directly',
                    ))
            elif path.startswith('memory/') or path.startswith('memories/'):
                result.merged_files[path] = content
                result.actions.append(
                    MergeAction(
                        path=path,
                        action='import',
                        detail='Memory file imported directly',
                    ))
            else:
                result.merged_files[path] = content
                result.actions.append(
                    MergeAction(
                        path=path,
                        action='import',
                        detail='Imported directly',
                    ))
            continue

        # ---- Cross-product logic ----
        if _is_memory_slot(target_product, target_path):
            result.merged_files[target_path] = content
            result.actions.append(
                MergeAction(
                    path=target_path,
                    action='import',
                    detail=f'Memory file imported directly (from {path})',
                ))
            continue

        if path in src_cls['portable']:
            src_default = source_defaults.get(path, '')
            tgt_default = target_defaults.get(target_path, '')

            if target_path == path and tgt_default:
                mr = _section_merger.merge(content, src_default, tgt_default)
                result.merged_files[target_path] = mr.content
                summary = mr.actions[0].detail if mr.actions else 'merged'
                result.actions.append(
                    MergeAction(
                        path=target_path,
                        action='merged',
                        detail=summary,
                    ))
            elif tgt_default:
                user_diff = _extract_user_diff_text(content, src_default)
                if user_diff:
                    merged_content = tgt_default.rstrip() + \
                        f'\n\n## Imported from {source_product} {path}\n\n{user_diff}\n'
                    result.merged_files[target_path] = merged_content
                    result.actions.append(
                        MergeAction(
                            path=target_path,
                            action='merged',
                            detail=f'Target template + user data from {path}',
                        ))
                else:
                    result.merged_files[target_path] = tgt_default
                    result.actions.append(
                        MergeAction(
                            path=target_path,
                            action='default',
                            detail=
                            f'No user changes detected, using {target_product} default',
                        ))
            else:
                result.merged_files[target_path] = content
                result.actions.append(
                    MergeAction(
                        path=target_path,
                        action='import',
                        detail=f'Imported from {path}' +
                        (f' -> {target_path}' if target_path != path else ''),
                    ))
            continue

        if path in config_files:
            src_default = source_defaults.get(path, '')
            tgt_default = target_defaults.get(target_path, '')
            if not tgt_default:
                result.merged_files[target_path] = content
                result.actions.append(
                    MergeAction(
                        path=target_path,
                        action='import',
                        detail='No target default available, imported as-is',
                    ))
            else:
                merger = _heartbeat_merger if target_path == heartbeat_file else _section_merger
                mr = merger.merge(content, src_default, tgt_default)
                result.merged_files[target_path] = mr.content
                summary = mr.actions[0].detail if mr.actions else 'merged'
                result.actions.append(
                    MergeAction(
                        path=target_path,
                        action='merged',
                        detail=summary,
                    ))
            continue

        if path.startswith('memory/') or path.startswith('memories/'):
            # Mapped canonical files travel verbatim; unmapped loose files
            # re-home/inline onto the target's layout (never die silently).
            if PATH_MAP.get((source_product, path), {}).get(
                    target_product) is not None:
                result.merged_files[target_path] = content
                result.actions.append(
                    MergeAction(
                        path=target_path,
                        action='import',
                        detail='Memory file imported directly',
                    ))
                continue
            new_path = _rehome_loose_memory(path, source_product,
                                            target_product)
            slot = _SINGLE_FILE_MEMORY_SLOTS.get(target_product, '')
            if new_path is None:
                loose_inline.append((path, content))
                loose_moves[path] = None
                result.actions.append(
                    MergeAction(
                        path=slot,
                        action='merged',
                        detail=(f'Loose memory detail {path} inlined into '
                                f'{slot}'),
                        src_path=path,
                        dst_path=slot,
                    ))
                continue
            loose_moves[path] = new_path
            result.merged_files[new_path] = content
            result.actions.append(
                MergeAction(
                    path=new_path,
                    action='import',
                    detail='Memory file imported directly'
                    if new_path == path else
                    (f'Loose memory file rehomed {path} -> {new_path}'),
                ))
            continue

        result.merged_files[target_path] = content
        result.actions.append(
            MergeAction(
                path=target_path,
                action='import',
                detail='Imported directly',
            ))

    # Fill in missing files from target defaults (opt-in).
    # Skipped for convert / download so the target only receives files that
    # actually exist in the source.
    if fill_missing_defaults:
        for path, content in target_defaults.items():
            if path not in result.merged_files and path not in handled_target_paths:
                result.merged_files[path] = content
                result.actions.append(
                    MergeAction(
                        path=path,
                        action='default',
                        detail=f'Added from {target_product} default template',
                    ))

    # Append overflow blocks
    for catch_all, block in overflow_blocks:
        base = result.merged_files.get(catch_all)
        if base is None:
            base = target_defaults.get(catch_all, '')
        result.merged_files[catch_all] = (
            base.rstrip() + '\n\n' + block if base.strip() else block)

    # Rewrite the canonical index's links to follow the loose-file moves;
    # runs before the inline append and the hermes entry conversion.
    if is_cross_product and loose_moves:
        import posixpath
        tgt_idx = _MEMORY_INDEX_PATHS.get(target_product)
        if tgt_idx:
            src_idx = _MEMORY_INDEX_PATHS.get(source_product, '')
            tgt_dir = posixpath.dirname(tgt_idx)
            src_dir = posixpath.dirname(src_idx) if src_idx else ''
            index_content = result.merged_files.get(tgt_idx)
            if index_content is not None:
                result.merged_files[tgt_idx] = _rewrite_memory_index(
                    index_content, src_dir, loose_moves, tgt_dir,
                    target_product)
            elif target_product == 'qoder':
                # No source index: qoder discovers detail only through index
                # references, so build a minimal one for the moved files.
                created = _rewrite_memory_index('', src_dir, loose_moves,
                                                tgt_dir, target_product)
                if created.strip():
                    result.merged_files[tgt_idx] = created

    # Inline loose detail into single-file target slots: index as base,
    # sourced sections in deterministic order; openhuman's injection cap
    # skips and reports what would never be read.
    if loose_inline:
        slot = _SINGLE_FILE_MEMORY_SLOTS.get(target_product, '')
        cap = (_OPENHUMAN_MEMORY_INJECT_CAP
               if target_product == 'openhuman' else None)
        base = result.merged_files.get(slot, '').rstrip()
        overflowed: list[str] = []
        for src_path, detail in sorted(loose_inline):
            body = detail.strip()
            if target_product == 'hermes':
                # Inlined files sit mid-document, beyond the extractor's
                # head-only frontmatter strip.
                body = _strip_yaml_frontmatter(body).strip()
            block = (f'## Imported from {source_product} {src_path}\n\n'
                     f'{body}')
            candidate = f'{base}\n\n{block}' if base else block
            if cap is not None and len(candidate) > cap:
                overflowed.append(src_path)
                continue
            base = candidate
        for src_path in overflowed:
            result.actions.append(
                MergeAction(
                    path=slot,
                    action='skip',
                    detail=(f'Loose memory detail {src_path} exceeds the '
                            f'{target_product} injection cap ({cap} chars), '
                            f'left out of {slot}'),
                    src_path=src_path,
                    dst_path=slot,
                ))
        if base:
            result.merged_files[slot] = base + '\n'

    # Convert hermes memory files to ``§`` entry stores; entries over the
    # per-file budget are skipped so the store stays write-acceptable.
    if is_cross_product and target_product == 'hermes':
        for slot, limit in _HERMES_CHAR_LIMITS.items():
            markdown = result.merged_files.get(slot)
            if markdown is None:
                continue
            entries = _markdown_to_hermes_entries(markdown)
            merged, stats = _merge_hermes_entries([], entries, limit)
            result.merged_files[slot] = (
                _HERMES_ENTRY_DELIM.join(merged) + '\n') if merged else ''
            detail = (f'{slot} converted to hermes entry store: '
                      f"{stats['added']} entries")
            if stats['duplicates']:
                detail += f", {stats['duplicates']} duplicates dropped"
            if stats['overflowed']:
                detail += (f", {stats['overflowed']} skipped over the "
                           f'{limit}-char budget')
            result.actions.append(
                MergeAction(path=slot, action='merged', detail=detail))

    return result


def merged_away_pairs(result: FullMergeResult) -> list[tuple[str, str]]:
    """Return ``(src_path, dst_path)`` for every overflow merge in *result*.

    These are source files that have no standalone equivalent on the target
    framework: their user content was folded into a catch-all file (e.g.
    qwenpaw ``PROFILE.md`` -> openclaw ``AGENTS.md``). The CLI uses this to
    show a "merged" hint so such files are not perceived as silently lost.
    """
    return [(a.src_path, a.dst_path) for a in result.actions
            if a.action == 'merged' and a.src_path and a.dst_path]
