# Copyright (c) ModelScope Contributors. All rights reserved.
"""Shared bundled/default skill filtering for CoPaw-family frameworks.

Both Hermes and QwenPaw (a.k.a. CoPaw) install a large library of
framework-provided skills (docx, pdf, browser_cdp, cron, QA_source_index, ...)
on startup. Only *user-authored* skills should travel across machines and
frameworks, so this mixin drops every file under a framework skill directory,
identifying framework skills by their ``SKILL.md`` frontmatter.
"""
from __future__ import annotations

import yaml
from pathlib import Path

# Metadata keys whose presence marks a skill as framework-provided (bundled)
# rather than user-authored.
_BUNDLED_SKILL_KEYS = frozenset(
    {'emoji', 'requires', 'install', 'builtin_skill_version'})


class BundledSkillFilterMixin:
    """Exclude framework-provided skills from ``collect``/``collect_bytes``.

    A ``skills/<dir>/`` is treated as framework-provided when its ``SKILL.md``
    frontmatter carries any of: a ``name`` listed in the sibling
    ``.bundled_manifest`` (Hermes's content library); a top-level ``license``
    field (the proprietary document skills); a ``builtin_skill_version`` field;
    or a ``metadata`` block containing ``copaw`` / ``qwenpaw`` /
    ``builtin_skill_version``. User skills carry none of these and are the only
    ones kept. Only the ``skills/`` tree is filtered (Hermes's
    ``optional-skills/`` is left untouched).
    """

    def _walk_matched(self):
        """Reset per-collection skill caches, then run the normal walk.

        ``_user_skill_cache`` / ``_bundled_cache`` are only a *within one
        collection* optimization (so ``_is_excluded_asset`` does not re-walk
        ``skills/`` for every file). A watch daemon reuses a single spec object
        for its whole lifetime, so persisting them across collections would
        freeze the user-skill set at the first poll -- skills created (or
        removed) afterwards would be permanently mis-classified and never sync.
        Clearing here keeps the O(n) benefit inside one pass while making every
        poll observe the current on-disk skill set.
        """
        self.__dict__.pop('_user_skill_cache', None)
        self.__dict__.pop('_bundled_cache', None)
        return super()._walk_matched()

    def _bundled_skill_names(self, skills_rel: str) -> frozenset:
        """Declared names of bundled skills from ``<skills_rel>/.bundled_manifest``
        (lines ``name:hash``). Empty when the manifest is absent (e.g. CoPaw,
        which relies purely on the frontmatter markers). Cached per manifest.
        """
        cache = self.__dict__.setdefault('_bundled_cache', {})
        if skills_rel in cache:
            return cache[skills_rel]
        names: set = set()
        manifest = self.workspace_root / skills_rel / '.bundled_manifest'
        try:
            for line in manifest.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line:
                    names.add(line.split(':', 1)[0])
        except OSError:
            pass
        result = frozenset(names)
        cache[skills_rel] = result
        return result

    def _is_framework_skill(self, skill_md: Path, bundled: frozenset) -> bool:
        """True when a ``SKILL.md`` is framework-provided (not user-authored)."""
        try:
            text = skill_md.read_text(encoding='utf-8')
        except OSError:
            return False
        if not text.startswith('---'):
            return False  # no frontmatter -> user skill (e.g. write, echo-bot)
        end = text.find('\n---', 3)
        block = text[3:end] if end != -1 else text[3:]
        try:
            meta = yaml.safe_load(block)
        except yaml.YAMLError:
            return False
        if not isinstance(meta, dict):
            return False
        name = meta.get('name')
        if isinstance(name, str) and name.strip() in bundled:
            return True
        if 'license' in meta or 'builtin_skill_version' in meta:
            return True
        md = meta.get('metadata')
        if isinstance(md, dict):
            # Bundled skills carry a metadata block that is either keyed by a
            # product name (copaw/qwenpaw/openclaw) or holds a
            # ``builtin_skill_version``; the nested product value carries
            # install hints (``emoji``/``requires``/``install``). User skills
            # have no such block.
            if 'builtin_skill_version' in md or (
                    md.keys() & {'copaw', 'qwenpaw', 'openclaw'}):
                return True
            for v in md.values():
                if isinstance(v, dict) and (v.keys() & _BUNDLED_SKILL_KEYS):
                    return True
        return False

    def _user_skill_dirs(self, skills_rel: str) -> set:
        """Rel-path prefixes (workspace_root-relative) of *user-authored* skill
        dirs -- those whose ``SKILL.md`` is not a framework skill. Cached per
        skills root.
        """
        cache = self.__dict__.setdefault('_user_skill_cache', {})
        if skills_rel in cache:
            return cache[skills_rel]
        bundled = self._bundled_skill_names(skills_rel)
        skills_root = self.workspace_root / skills_rel
        keep: set = set()
        if skills_root.is_dir():
            for skill_md in skills_root.rglob('SKILL.md'):
                if not self._is_framework_skill(skill_md, bundled):
                    keep.add(
                        skill_md.parent.relative_to(
                            self.workspace_root).as_posix())
        cache[skills_rel] = keep
        return keep

    def _is_excluded_asset(self, rel_path: str) -> bool:
        """Keep only files under a *user-authored* skill dir; drop the rest of
        the ``skills/`` tree (bundled skills + category scaffolding).
        """
        parts = rel_path.split('/')
        if 'skills' not in parts:
            return False
        i = parts.index('skills')
        keep = self._user_skill_dirs('/'.join(parts[:i + 1]))
        return not any(rel_path == d or rel_path.startswith(d + '/')
                       for d in keep)
