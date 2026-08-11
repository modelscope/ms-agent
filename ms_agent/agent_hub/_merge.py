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
        """Split markdown into sections by ``## `` headings."""
        lines = content.split('\n')
        sections: list[Section] = []
        current_title = ''
        current_lines: list[str] = []

        for line in lines:
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
        'portable': frozenset([
            'SOUL.md',
            'IDENTITY.md',
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
        # Only persona + memory carry cross-framework semantics; the
        # config.yaml/settings.json/agent.yaml/facts.json/skill.json files are
        # ms-agent specific and preserved on same-framework sync only.
        'portable': frozenset([
            'profile.md',
            'MEMORY.md',
        ]),
        'config': frozenset([]),
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
    'ms-agent':
    frozenset(
        ['config.yaml', 'settings.json', 'agent.yaml', 'facts.json',
         'skill.json']),
    'qwenpaw': frozenset(['agent.json', 'skill.json']),
    'openhuman': frozenset(['config.toml']),
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
        'openhuman': 'SOUL.md'
    },
    {
        'nanobot': 'USER.md',
        'openclaw': 'USER.md',
        'hermes': 'memories/USER.md',
        'qwenpaw': 'memory/USER.md'
    },
    {
        'nanobot': 'memory/MEMORY.md',
        'openclaw': 'MEMORY.md',
        'qwenpaw': 'MEMORY.md',
        'ms-agent': 'MEMORY.md',
        'hermes': 'memories/MEMORY.md'
    },
    {
        'openclaw': 'IDENTITY.md',
        'openhuman': 'IDENTITY.md'
    },
    {
        'qwenpaw': 'PROFILE.md',
        'ms-agent': 'profile.md'
    },
    {
        'nanobot': 'AGENTS.md',
        'openclaw': 'AGENTS.md',
        'qwenpaw': 'AGENTS.md',
        'qoder': 'AGENTS.md'
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
    ]),
    'qoder':
    frozenset([
        'AGENTS.md',
    ]),
    'ms-agent':
    frozenset([
        'profile.md',
        'MEMORY.md',
        'config.yaml',
        'settings.json',
        'agent.yaml',
        'facts.json',
        'skill.json',
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
    # Products without AGENTS.md/SOUL.md (e.g. ms-agent) fall back to their
    # persona file so overflow lands in a file the harness actually loads.
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

    src_cls = PRODUCT_FILE_CLASSES.get(source_product, _DEFAULT_FILE_CLASS)
    tgt_cls = PRODUCT_FILE_CLASSES.get(target_product, _DEFAULT_FILE_CLASS)
    portable_files = src_cls['portable'] | tgt_cls['portable']
    config_files = src_cls['config'] | tgt_cls['config']
    heartbeat_file = tgt_cls.get('heartbeat', '')

    handled_target_paths = set()
    overflow_blocks: list[tuple[str, str]] = []

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
            if path.startswith('memory/') or path.startswith(
                    'memories/') or path.startswith('wiki/'):
                result.merged_files[path] = content
                result.actions.append(
                    MergeAction(
                        path=path,
                        action='import',
                        detail=
                        f'No mapping for {target_product}, imported as-is',
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
            result.merged_files[target_path] = content
            result.actions.append(
                MergeAction(
                    path=target_path,
                    action='import',
                    detail='Memory file imported directly',
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
