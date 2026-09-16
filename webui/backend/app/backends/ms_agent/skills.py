"""Skills adapter.

Two kinds of skills are surfaced:
  * **webui-local** — created in the UI with content; the SDK has no content-skill
    model, so these live in the sidecar with full CRUD.
  * **source-discovered** — skills found in the **local** dir sources reported by
    the SDK's SkillsConfigManager: the per-scope **live tree** (``<home>/skills``
    globally, ``<project>/.ms_agent/skills`` per project — implicit, presence =
    registered) plus the explicit local sources in skills.json (remote
    modelscope/git sources are skipped here to avoid network in a management
    call). Their id encodes the scope + skill_id (prefix ``src::``).

UI-created skills (folder uploads and server-readable path imports) are copied
into the scope's live tree — no skills.json entry needed; existence is the
filesystem. Explicit local sources remain read-compatible for older configs but
new WebUI imports never create them.
Enable/disable writes the skill_id to skills.json's ``disabled`` list (state is
file-persisted even though existence isn't); a live session picks changes up at
the next turn via the chat turn-boundary sync. Deleting a tree-resident skill
removes its directory; deleting an old explicit path removes that registration
but never its original files; automatically discovered standard trees are
delete-protected."""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from app.backends.errors import BadRequest, Conflict, NotFound
from app.backends.ms_agent import sidecar
from app.backends.ms_agent.common import home, pm
from app.core.filetypes import guess_type
from app.schemas.skill import (
    Skill,
    SkillCreate,
    SkillFile,
    SkillFileContent,
    SkillPathImport,
    SkillUpdate,
)

_SRC = "src::"
_WEBUI_BUNDLE = "webui.skill.bundle.v1"
_SKIP_TREE_PARTS = {".git", "__pycache__", ".DS_Store", "node_modules"}


# What a path component genuinely cannot carry: control codes, path separators,
# the characters Windows rejects, and whitespace (legal, but hostile in paths).
# Everything else — CJK, accents, emoji — is kept: the SDK derives `skill_id`
# from the directory name and only requires it to be non-empty (skill/schema.py),
# and the filesystems we target store UTF-8 names. An ASCII allowlist used to
# erase such names entirely, so `中文技能` became the literal fallback "skill" —
# and a second CJK-named skill then collided with the first for no visible reason.
_UNSAFE_NAME_CHARS = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|\s]+')
# Reserved device names on Windows; harmless to avoid everywhere.
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)
}
# Filesystems cap a path component at 255 BYTES, not characters — which only
# started to matter once non-ASCII survived (64 emoji = 256 bytes). Well under
# the limit so the `.<name>.incoming` / `.<name>.backup` staging names fit too.
_MAX_NAME_BYTES = 128


def _slug(value: str) -> str:
    """The directory name a skill takes inside the live tree.

    Lower-cased because macOS/Windows filesystems are case-insensitive: treating
    ``MySkill`` and ``myskill`` as different names would report no conflict and
    then fail on ``mkdir`` against the directory that already exists. Leading dots
    are stripped so a skill can never look hidden or collide with the staging
    directories used for overwrite.
    """
    s = _UNSAFE_NAME_CHARS.sub("-", value.strip()).strip(". -").lower()
    # Truncate on the encoded form; `errors="ignore"` drops a character the cut
    # landed in the middle of.
    s = s.encode()[:_MAX_NAME_BYTES].decode(errors="ignore").strip(". -")
    if not s or s.upper() in _RESERVED_NAMES:
        return "skill"
    return s


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_scope(scope: str) -> None:
    if scope == "global":
        return
    if scope.startswith("project:"):
        if pm().get(scope.split(":", 1)[1]) is None:
            raise BadRequest("Project not found.")
        return
    raise BadRequest("Invalid skill location.")


def _bridge_enabled(name: str, enabled: bool, scope: str) -> None:
    """Reflect enable/disable into skills.json (honored by the runtime)."""
    try:
        from ms_agent.config.skills_manager import SkillsConfigManager

        sk = SkillsConfigManager(global_dir=home())
        if scope == "global":
            sk.set_skill_enabled(name, enabled, scope="global")
        else:
            proj = pm().get(scope.split(":", 1)[1])
            if proj is not None:
                sk.set_skill_enabled(name, enabled, scope="project", project_path=proj.path)
    except Exception:
        pass


def _invalidate_scope(scope: str) -> None:
    from app.backends.ms_agent.skill_index import skill_index

    skill_index.invalidate(scope)


# -- source-discovered skills (local dirs only) --------------------------------


def _enc_src(scope: str, skill_id: str) -> str:
    raw = base64.urlsafe_b64encode(f"{scope}\x1f{skill_id}".encode()).decode().rstrip("=")
    return _SRC + raw


def _dec_src(sid: str) -> tuple[str, str]:
    try:
        raw = sid[len(_SRC):]
        pad = "=" * (-len(raw) % 4)
        scope, skill_id = base64.urlsafe_b64decode(raw + pad).decode().split("\x1f", 1)
        return scope, skill_id
    except Exception:
        raise NotFound("Skill not found.")


def _discovered_for_scope(scope: str, project_path: str | None) -> list[tuple]:
    """(runtime_skill_id, descriptor, enabled) for local scope sources."""
    from app.backends.ms_agent.skill_index import skill_index

    return list(skill_index.snapshot(scope, project_path).rows)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _origin_context(scope: str, project_path: str | None = None) -> dict:
    """Resolve ownership roots once for a whole list operation."""
    from ms_agent.config.skills_manager import (
        SkillsConfigManager,
        global_standard_skills_tree,
        project_standard_skills_tree,
    )
    from ms_agent.skill.sources import SkillSourceType, parse_skill_source

    if scope != "global" and project_path is None:
        project_path = _project_path(scope)
    manager = SkillsConfigManager(global_dir=home())
    sdk_scope = "global" if scope == "global" else "project"
    kwargs = {} if sdk_scope == "global" else {"project_path": project_path}
    explicit: list[Path] = []
    for source_text in manager.list_explicit_sources(scope=sdk_scope, **kwargs):
        try:
            source = parse_skill_source(str(source_text))
            if source.type == SkillSourceType.LOCAL_DIR and source.path:
                explicit.append(Path(source.path).expanduser())
        except Exception:
            continue
    standard = (
        global_standard_skills_tree()
        if scope == "global"
        else project_standard_skills_tree(str(project_path))
    )
    return {
        "managed": _live_tree(scope),
        "standard": standard,
        "explicit": tuple(explicit),
    }


def _skill_origin(path: Path, context: dict) -> str:
    if _path_is_within(path, context["managed"]):
        return "managed"
    if _path_is_within(path, context["standard"]):
        return "standard"
    if any(_path_is_within(path, root) for root in context["explicit"]):
        return "legacy-path"
    return "external"


def _discovered_to_schema(
    scope: str,
    skill_id: str,
    skill,
    enabled: bool,
    *,
    origin_context: dict | None = None,
) -> Skill:
    raw_path = str(getattr(skill, "skill_path", "") or "")
    origin = (
        _skill_origin(Path(raw_path), origin_context or _origin_context(scope))
        if raw_path
        else "external"
    )
    return Skill(
        id=_enc_src(scope, skill_id),
        name=getattr(skill, "name", skill_id) or skill_id,
        kind=(getattr(skill, "tags", None) or ["skill"])[0],
        content=getattr(skill, "description", "") or "",
        enabled=enabled,
        scope=scope,
        created_at=datetime.now(timezone.utc),
        origin=origin,
        removable=origin in {"managed", "legacy-path"},
    )


def _scopes_to_scan(scope: str | None) -> list[tuple[str, str | None]]:
    if scope == "global":
        return [("global", None)]
    if scope and scope.startswith("project:"):
        proj = pm().get(scope.split(":", 1)[1])
        return [(scope, proj.path)] if proj is not None else []
    # all scopes
    out: list[tuple[str, str | None]] = [("global", None)]
    for proj in pm().list():
        out.append((f"project:{proj.id}", proj.path))
    return out


# -- endpoints -----------------------------------------------------------------


def list_skills(scope: str | None = None) -> list[Skill]:
    rows = [
        Skill.model_validate(r)
        for r in sidecar.section("skills").values()
        if scope is None or r.get("scope") == scope
    ]
    seen = {(r.name, r.scope) for r in rows}
    for sc, pp in _scopes_to_scan(scope):
        context = _origin_context(sc, pp)
        # SDK catalog registration is last-source-wins.  Collapse in that same
        # direction before applying the sidecar compatibility layer, otherwise
        # the card can point at a different directory than the running agent.
        effective_by_id: dict[str, Skill] = {}
        for skill_id, skill, enabled in _discovered_for_scope(sc, pp):
            item = _discovered_to_schema(
                sc,
                skill_id,
                skill,
                enabled,
                origin_context=context,
            )
            effective_by_id[skill_id] = item
        # Keep the existing UI rule that one display name produces one card,
        # but only after resolving the SDK's real identity (directory-derived
        # skill_id). Otherwise a standard and managed Skill with the same id but
        # different frontmatter names produced two cards that both addressed
        # the same id, and one card could delete/read the wrong source.
        discovered: dict[str, Skill] = {}
        for item in effective_by_id.values():
            discovered[_slug(item.name)] = item
        for item in discovered.values():
            if (item.name, item.scope) in seen:
                continue  # a webui-local skill of the same name/scope wins
            seen.add((item.name, item.scope))
            rows.append(item)
    rows.sort(key=lambda r: (r.scope, r.name))
    return rows


def _safe_relpath(path: str) -> Path:
    rel = PurePosixPath(path.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise BadRequest("Invalid file path in this skill.")
    return Path(*rel.parts)


def _live_tree(scope: str, *, create: bool = False) -> Path:
    """The scope's live skills tree — presence there IS registration.

    Global: ``<home>/skills``. Project: ``<project>/.ms_agent/skills`` (reads
    honor the legacy ``.ms-agent`` spelling via the SDK helper; writes always
    use the new one)."""
    if scope == "global":
        root = Path(home()).expanduser() / "skills"
    else:
        from ms_agent.config.skills_manager import SkillsConfigManager

        proj = pm().get(scope.split(":", 1)[1])
        if proj is None:
            raise BadRequest("Project not found.")
        root = SkillsConfigManager.project_skills_tree(proj.path)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _existing_same_name(scope: str, name: str) -> tuple[object, Path | None] | None:
    """The skill already registered in *scope* under the same name, if any.

    Collisions are resolved by NAME, not by whether ``<tree>/<slug>`` happens to
    exist: a skill can be registered from a nested or external source (e.g.
    ``<tree>/webui/docker-expert`` via skills.json), in which case a plain
    directory check reports "free" and the import quietly creates a SECOND skill
    with the same name for the registry to shadow. Comparing slugs (not raw
    names) because that is what would share a directory.

    Returns ``(skill, directory)``; the directory is None when the SDK does not
    expose a path for it.
    """
    target = _slug(name)
    pp = None if scope == "global" else _project_path(scope)
    for _sid, skill, _enabled in reversed(_discovered_for_scope(scope, pp)):
        existing = getattr(skill, "name", "") or ""
        if _slug(str(existing)) != target:
            continue
        raw = str(getattr(skill, "skill_path", "") or "")
        return skill, (Path(raw) if raw else None)
    return None


def _discover_directory_skills(path: Path) -> list[tuple[str, Path]]:
    """Return every Skill root below *path* without reading support files."""
    from ms_agent.skill.loader import SkillLoader

    discovered = SkillLoader().discover_skills(str(path)) or {}
    entries = [
        (
            str(getattr(skill, "name", "") or key),
            Path(str(getattr(skill, "skill_path", "") or path)).resolve(),
        )
        for key, skill in discovered.items()
    ]
    if not entries:
        raise BadRequest("No skill was found in this folder.")
    entries.sort(key=lambda row: str(row[1]))
    seen: dict[str, str] = {}
    destinations: dict[str, str] = {}
    for name, _source in entries:
        key = _slug(name)
        if key in seen:
            raise BadRequest(
                f"This folder contains duplicate skill names: {seen[key]!r} "
                f"and {name!r}."
            )
        seen[key] = name
    for name, source in entries:
        key = _slug(source.name)
        if key in destinations:
            raise BadRequest(
                f"This folder contains Skill directories that copy to the same "
                f"name: {destinations[key]!r} and {source.name!r}."
            )
        destinations[key] = source.name
    return entries


def _copy_skill_tree(source: Path, destination: Path) -> None:
    """Copy one Skill tree without following links outside that tree."""
    if source.is_symlink():
        raise BadRequest(f"Skill folder {str(source)!r} cannot be a symbolic link.")
    destination.mkdir(parents=True, exist_ok=False)
    for current, dirs, files in os.walk(source):
        current_path = Path(current)
        rel = current_path.relative_to(source)
        target_dir = destination / rel
        target_dir.mkdir(parents=True, exist_ok=True)

        kept_dirs: list[str] = []
        for name in sorted(dirs):
            if name in _SKIP_TREE_PARTS or name.startswith("."):
                continue
            child = current_path / name
            if child.is_symlink():
                raise BadRequest(
                    f"Skill folder contains a symbolic link: "
                    f"{child.relative_to(source).as_posix()}."
                )
            kept_dirs.append(name)
        dirs[:] = kept_dirs

        for name in sorted(files):
            if name in _SKIP_TREE_PARTS or name.startswith("."):
                continue
            src = current_path / name
            if src.is_symlink():
                raise BadRequest(
                    f"Skill folder contains a symbolic link: "
                    f"{src.relative_to(source).as_posix()}."
                )
            shutil.copy2(src, target_dir / name)


def _copy_skills_to_live_tree(
    scope: str,
    entries: list[tuple[str, Path]],
    *,
    overwrite: bool,
    ignored_existing_paths: set[Path] | None = None,
) -> list[Skill]:
    """Validate, stage and install a batch of local Skill directories.

    Every incoming tree is ready before the first destination changes.  Existing
    managed directories are kept as backups until the complete batch has been
    swapped, so a later failure restores the previous state.
    """
    from ms_agent.skill.loader import SkillLoader

    root = _live_tree(scope, create=True)
    ignored = {
        path.resolve() for path in (ignored_existing_paths or set())
    }
    context = _origin_context(scope)
    conflicts: list[str] = []
    records: list[dict] = []
    transaction = uuid.uuid4().hex[:10]

    for name, source in entries:
        # Preserve the source directory name because the SDK uses it as the
        # runtime skill_id (slash commands and disabled state depend on it).
        default_dir = root / _slug(source.name)
        existing = _existing_same_name(scope, name)
        existing_path: Path | None = None
        if existing is not None:
            raw = str(getattr(existing[0], "skill_path", "") or "")
            candidate = Path(raw) if raw else existing[1]
            if candidate is not None and candidate.resolve() not in ignored:
                existing_path = candidate

        destination = default_dir
        if existing_path is not None:
            if not overwrite:
                conflicts.append(name)
                continue
            origin = _skill_origin(existing_path, context)
            if origin == "managed":
                destination = existing_path
            elif origin == "standard":
                # Standard directories are never modified.  A managed copy has
                # higher priority and safely shadows it.
                destination = default_dir
            else:
                raise BadRequest(
                    f"Skill {name!r} still comes from an external source. "
                    "Convert that source to managed copies before overwriting it."
                )

        # Runtime identity comes from the directory name, while duplicate
        # detection above deliberately follows the user-facing Skill name. A
        # differently named Skill can therefore already occupy the incoming
        # directory. Never replace that unrelated Skill, even after the caller
        # approved overwriting same-name conflicts.
        if destination.exists() and (
            existing_path is None
            or destination.resolve() != existing_path.resolve()
        ):
            raise Conflict(
                f"Skill folder {destination.name!r} is already used by another "
                "Skill. Rename the imported folder and try again."
            )

        if source.resolve() == destination.resolve():
            continue
        records.append({
            "name": name,
            "source": source,
            "destination": destination,
            "stage": root / f".{destination.name}.incoming-{transaction}",
            "backup": root / f".{destination.name}.backup-{transaction}",
            "installed": False,
            "had_old": False,
        })

    if conflicts:
        raise Conflict(
            "Skills already exist here: " + ", ".join(sorted(conflicts))
        )

    try:
        for record in records:
            shutil.rmtree(record["stage"], ignore_errors=True)
            shutil.rmtree(record["backup"], ignore_errors=True)
            _copy_skill_tree(record["source"], record["stage"])
            loaded = SkillLoader().load_skills(str(record["stage"])) or {}
            if not loaded:
                raise BadRequest(
                    f"Skill {record['name']!r} could not be loaded after copying."
                )

        for record in records:
            destination = record["destination"]
            if destination.exists():
                destination.rename(record["backup"])
                record["had_old"] = True
            try:
                record["stage"].rename(destination)
                record["installed"] = True
            except Exception:
                if record["had_old"] and record["backup"].exists():
                    record["backup"].rename(destination)
                    record["had_old"] = False
                raise
    except Exception:
        for record in reversed(records):
            destination = record["destination"]
            if record["installed"] and destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            if record["had_old"] and record["backup"].exists():
                record["backup"].rename(destination)
            shutil.rmtree(record["stage"], ignore_errors=True)
            shutil.rmtree(record["backup"], ignore_errors=True)
        raise

    for record in records:
        shutil.rmtree(record["backup"], ignore_errors=True)

    _invalidate_scope(scope)
    results: list[Skill] = []
    context = _origin_context(scope)
    for record in records:
        for loaded_key, skill in (
            SkillLoader().load_skills(str(record["destination"])) or {}
        ).items():
            runtime_id = (
                getattr(skill, "skill_id", None)
                or str(loaded_key).split("@", 1)[0]
            )
            results.append(
                _discovered_to_schema(
                    scope,
                    runtime_id,
                    skill,
                    True,
                    origin_context=context,
                )
            )
    return results


def _configured_source_for(
    scope: str,
    project_path: str | None,
    skill_path: Path,
):
    """The explicit local source that owns *skill_path*, if any."""
    from ms_agent.config.skills_manager import SkillsConfigManager
    from ms_agent.skill.sources import SkillSourceType, parse_skill_source

    manager = SkillsConfigManager(global_dir=home())
    sdk_scope = "global" if scope == "global" else "project"
    kwargs = {} if sdk_scope == "global" else {"project_path": project_path}
    target = skill_path.resolve()
    for source_text in manager.list_explicit_sources(scope=sdk_scope, **kwargs):
        try:
            source = parse_skill_source(str(source_text))
            if source.type != SkillSourceType.LOCAL_DIR or not source.path:
                continue
            root = Path(source.path).expanduser().resolve()
            if root == target or root in target.parents:
                return manager, sdk_scope, kwargs, str(source_text), root
        except Exception:
            continue
    return None


def _migrate_legacy_source(
    scope: str,
    project_path: str | None,
    skill_path: Path,
) -> None:
    """Copy every Skill from one old path reference, then remove the reference."""
    configured = _configured_source_for(scope, project_path, skill_path)
    if configured is None:
        raise BadRequest(
            "This skill is discovered outside the managed skills folder and "
            "has no removable path reference. Disable it instead."
        )
    manager, sdk_scope, kwargs, source_text, source_root = configured
    entries = _discover_directory_skills(source_root)
    _copy_skills_to_live_tree(
        scope,
        entries,
        overwrite=True,
        ignored_existing_paths={path for _name, path in entries},
    )
    manager.remove_source(source_text, scope=sdk_scope, **kwargs)
    _invalidate_scope(scope)


def import_skills_from_path(body: SkillPathImport) -> list[Skill]:
    """Copy all Skills below a server-readable directory into this scope."""
    _valid_scope(body.scope)
    candidate = Path(os.path.expanduser(body.path.strip()))
    if not candidate.is_dir():
        raise BadRequest(
            "This folder does not exist. Enter an existing folder path."
        )
    candidate = candidate.resolve()
    entries = _discover_directory_skills(candidate)

    # A path already inside the managed tree needs no second copy.
    if all(_in_live_tree(body.scope, source) for _name, source in entries):
        from ms_agent.skill.loader import SkillLoader

        context = _origin_context(body.scope)
        results: list[Skill] = []
        for loaded_key, skill in (SkillLoader().load_skills(str(candidate)) or {}).items():
            runtime_id = (
                getattr(skill, "skill_id", None)
                or str(loaded_key).split("@", 1)[0]
            )
            results.append(
                _discovered_to_schema(
                    body.scope,
                    runtime_id,
                    skill,
                    True,
                    origin_context=context,
                )
            )
        return results

    if body.overwrite:
        migrated_roots: set[Path] = set()
        context = _origin_context(body.scope)
        project_path = None if body.scope == "global" else _project_path(body.scope)
        for name, _source in entries:
            existing = _existing_same_name(body.scope, name)
            if existing is None:
                continue
            raw = str(getattr(existing[0], "skill_path", "") or "")
            if not raw:
                continue
            existing_path = Path(raw)
            if _skill_origin(existing_path, context) != "legacy-path":
                continue
            configured = _configured_source_for(
                body.scope, project_path, existing_path
            )
            if configured is None or configured[-1] in migrated_roots:
                continue
            migrated_roots.add(configured[-1])
            _migrate_legacy_source(body.scope, project_path, existing_path)

    results = _copy_skills_to_live_tree(
        body.scope,
        entries,
        overwrite=body.overwrite,
    )
    if not results:
        # All entries were already the exact managed destinations.
        return list_skills(body.scope)
    return results


def _bundle_files_from_content(content: str) -> list[dict]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise BadRequest("This skill file is not valid. Re-export it and try again.") from exc
    if not isinstance(payload, dict) or payload.get("format") != _WEBUI_BUNDLE:
        raise BadRequest("This skill file is not valid. Re-export it and try again.")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise BadRequest("This skill file is empty.")
    return files


def _materialize_bundle(body: SkillCreate) -> Skill:
    from ms_agent.skill.schema import SkillSchemaParser

    files = _bundle_files_from_content(body.content or "")
    skill_md = next(
        (
            f
            for f in files
            if isinstance(f, dict)
            and str(f.get("path", "")).replace("\\", "/").split("/")[-1] == "SKILL.md"
        ),
        None,
    )
    if not skill_md:
        raise BadRequest("This skill is missing its SKILL.md file.")

    frontmatter = SkillSchemaParser.parse_yaml_frontmatter(str(skill_md.get("content", "")))
    if not frontmatter or not frontmatter.get("name") or not frontmatter.get("description"):
        raise BadRequest("SKILL.md must declare a name and a description.")
    bundle_root = _safe_relpath(str(skill_md.get("path", ""))).parent

    # The directory name IS the identity: a skill is registered by its presence in
    # the live tree, so a colliding name has to be resolved here rather than
    # side-stepped. `_unique_skill_dir` used to invent `<name>-2`, which the SDK's
    # registry then shadowed behind the original — the import reported success
    # while the list never changed. Now it is explicit: reject, or replace.
    root = _live_tree(body.scope, create=True)
    skill_name = str(frontmatter.get("name") or body.name)
    default_dir = root / _slug(skill_name)

    # Look the collision up BY NAME across everything registered in the scope,
    # not just at `<root>/<slug>`: a skill sourced from a nested/external path
    # occupies the name without occupying that directory, and checking only the
    # directory let a second same-named skill be created for the registry to hide.
    found = _existing_same_name(body.scope, skill_name)
    existing_dir: Path | None = None
    if found is not None:
        _existing_skill, existing_dir = found
        if not body.overwrite:
            raise Conflict(
                f"A skill named {skill_name!r} already exists here.")
        if existing_dir is None:
            raise BadRequest("This skill has no directory that can be replaced.")
        origin = _skill_origin(existing_dir, _origin_context(body.scope))
        if origin == "legacy-path":
            # Preserve every sibling from the old shared source as a managed
            # copy, remove that one reference, then replace only the requested
            # Skill.  The user's original directory is never modified.
            _migrate_legacy_source(
                body.scope,
                None if body.scope == "global" else _project_path(body.scope),
                existing_dir,
            )
            found = _existing_same_name(body.scope, skill_name)
            existing_dir = found[1] if found is not None else None
            if existing_dir is None or not _in_live_tree(body.scope, existing_dir):
                raise BadRequest("The old path reference could not be converted.")
        elif origin == "standard":
            # .agents/skills remains read-only; the managed copy comes later in
            # source order and becomes the effective version.
            existing_dir = None
        elif origin != "managed":
            raise BadRequest(
                "This skill is outside the managed skills folder and has no "
                "removable path reference. Disable it instead."
            )

    # Replace the directory the existing skill actually occupies (which is not
    # necessarily `<root>/<slug>`), so its source registration keeps pointing at
    # live files instead of being orphaned next to a new copy.
    skill_dir = existing_dir if existing_dir is not None else default_dir
    existed = skill_dir.exists()

    # Replace via a side directory so a failed overwrite cannot destroy the
    # skill that was already there: the old one stays untouched until the new
    # tree is written AND loads, and is restored if anything raises.
    write_dir = skill_dir if not existed else skill_dir.parent / f".{skill_dir.name}.incoming"
    backup_dir = skill_dir.parent / f".{skill_dir.name}.backup" if existed else None
    shutil.rmtree(write_dir, ignore_errors=True)
    if backup_dir is not None:
        shutil.rmtree(backup_dir, ignore_errors=True)
    write_dir.mkdir(parents=True, exist_ok=False)
    try:
        for entry in files:
            if not isinstance(entry, dict):
                raise BadRequest("This skill file is not valid. Re-export it and try again.")
            rel = _safe_relpath(str(entry.get("path", "")))
            if str(bundle_root) != ".":
                try:
                    rel = rel.relative_to(bundle_root)
                except ValueError:
                    continue
            content = entry.get("content")
            if not isinstance(content, str):
                raise BadRequest("A file in this skill has invalid content.")
            target = write_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        # Validate the incoming tree BEFORE it takes the real name, so a bundle
        # that doesn't load can't replace a working skill.
        from ms_agent.skill.loader import SkillLoader

        loaded = SkillLoader().load_skills(str(write_dir)) or {}
        if not loaded:
            raise BadRequest("This skill could not be loaded. Check its contents and try again.")

        if existed:
            # Swap: old -> backup, incoming -> real name. Two renames within one
            # directory, so neither crosses a filesystem boundary.
            skill_dir.rename(backup_dir)
            try:
                write_dir.rename(skill_dir)
            except Exception:
                backup_dir.rename(skill_dir)  # put the original back
                raise
            shutil.rmtree(backup_dir, ignore_errors=True)

        # Materialized inside the live tree — presence IS registration, no
        # skills.json entry. Surface the discovered skill directly.
        for loaded_key, skill in (SkillLoader().load_skills(str(skill_dir)) or {}).items():
            runtime_id = getattr(skill, "skill_id", None) or str(loaded_key).split("@", 1)[0]
            return _discovered_to_schema(body.scope, runtime_id, skill, True)
        raise BadRequest("This skill could not be loaded. Check its contents and try again.")
    except Exception:
        # Leave no half-imported skill behind, and never lose the original.
        shutil.rmtree(write_dir, ignore_errors=True)
        if backup_dir is not None and backup_dir.exists() and not skill_dir.exists():
            backup_dir.rename(skill_dir)
        if backup_dir is not None:
            shutil.rmtree(backup_dir, ignore_errors=True)
        raise


def create_skill(body: SkillCreate) -> Skill:
    _valid_scope(body.scope)
    if body.kind == "bundle":
        result = _materialize_bundle(body)
        _invalidate_scope(body.scope)
        return result

    # Backward-compatible POST shape: a directory-valued content field now uses
    # the same copy importer as the dedicated /import-path endpoint.  It returns
    # the first copied Skill because this legacy endpoint has a singular schema;
    # callers that need the complete batch use import_skills_from_path().
    candidate = os.path.expanduser((body.content or "").strip())
    if candidate and os.path.isdir(candidate):
        imported = import_skills_from_path(
            SkillPathImport(
                path=candidate,
                scope=body.scope,
                overwrite=body.overwrite,
            )
        )
        if imported:
            return imported[0]
        raise BadRequest("No skill was found in this folder.")
    if body.kind == "source":
        raise BadRequest("This folder does not exist. Enter an existing folder path.")

    sid = "sk-" + uuid.uuid4().hex[:12]
    row = {
        "id": sid, "name": body.name, "kind": body.kind, "content": body.content,
        "enabled": body.enabled, "scope": body.scope, "created_at": _now(),
    }
    sidecar.put("skills", sid, row)
    _bridge_enabled(body.name, body.enabled, body.scope)
    _invalidate_scope(body.scope)
    return Skill.model_validate(row)


def get_skill(sid: str) -> Skill:
    if sid.startswith(_SRC):
        scope, skill_id = _dec_src(sid)
        pp = None if scope == "global" else _project_path(scope)
        from app.backends.ms_agent.skill_index import skill_index

        found = skill_index.snapshot(scope, pp).find(skill_id)
        if found is None:
            raise NotFound("Skill not found.")
        skill, enabled = found
        return _discovered_to_schema(scope, skill_id, skill, enabled)
    row = sidecar.get("skills", sid)
    if not row:
        raise NotFound("Skill not found.")
    return Skill.model_validate(row)


def _skill_dir_for(sid: str) -> Path | None:
    """Resolve the on-disk directory of a discovered (``src::``) skill; None
    for sidecar-only skills (single markdown body, no directory)."""
    if not sid.startswith(_SRC):
        return None
    scope, skill_id = _dec_src(sid)
    pp = None if scope == "global" else _project_path(scope)
    from app.backends.ms_agent.skill_index import skill_index

    found = skill_index.snapshot(scope, pp).find(skill_id)
    if found is not None:
        skill, _enabled = found
        path = Path(str(getattr(skill, "skill_path", "") or ""))
        if path.is_file():  # some loaders point at SKILL.md itself
            path = path.parent
        return path if path.is_dir() else None
    raise NotFound("Skill not found.")


def list_skill_files(sid: str) -> list[SkillFile]:
    """REAL relative file listing of the skill's directory (SKILL.md first).
    Sidecar-only skills expose just their markdown body as SKILL.md."""
    root = _skill_dir_for(sid)
    if root is None:
        get_skill(sid)  # 404 for unknown ids
        return [SkillFile(path="SKILL.md")]
    out: list[SkillFile] = []
    try:
        for current, dirs, files in os.walk(root):
            dirs[:] = sorted(
                name for name in dirs
                if name not in _SKIP_TREE_PARTS and not name.startswith("."))
            for name in sorted(files):
                if name in _SKIP_TREE_PARTS or name.startswith("."):
                    continue
                path = Path(current) / name
                rel = path.relative_to(root)
                try:
                    size = path.stat().st_size
                except OSError:
                    size = None
                out.append(SkillFile(path=rel.as_posix(), size=size))
    except OSError:
        pass
    # SKILL.md first, then alphabetical — mirrors what the viewer opens first.
    out.sort(key=lambda f: (f.path != "SKILL.md", f.path))
    return out


def read_skill_file(sid: str, path: str) -> SkillFileContent:
    """UTF-8 content of one file inside the skill directory (path-traversal
    safe). ``content=None`` flags a binary file."""
    rel = _safe_relpath(path)
    root = _skill_dir_for(sid)
    if root is None:
        sk = get_skill(sid)
        if rel.as_posix() == "SKILL.md":
            return SkillFileContent(path="SKILL.md", content=sk.content)
        raise NotFound("File not found.")
    f = root / rel
    if not f.is_file():
        raise NotFound("File not found.")
    try:
        return SkillFileContent(path=rel.as_posix(),
                                content=f.read_text("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return SkillFileContent(path=rel.as_posix(), content=None)


def raw_skill_file(sid: str, path: str) -> tuple[Path, str]:
    """Resolve a skill file to (path, mime) for raw byte serving — what an
    in-viewer preview loads its images, styles and scripts from."""
    rel = _safe_relpath(path)
    root = _skill_dir_for(sid)
    if root is None:
        raise NotFound("File not found.")
    f = root / rel
    if not f.is_file():
        raise NotFound("File not found.")
    return f, guess_type(f.name) or "application/octet-stream"


def update_skill(sid: str, body: SkillUpdate) -> Skill:
    if sid.startswith(_SRC):
        scope, skill_id = _dec_src(sid)
        if body.enabled is not None:
            _bridge_enabled(skill_id, body.enabled, scope)  # only enable/disable
            _invalidate_scope(scope)
        return get_skill(sid)
    row = sidecar.get("skills", sid)
    if not row:
        raise NotFound("Skill not found.")
    for field in ("name", "kind", "content", "enabled"):
        value = getattr(body, field)
        if value is not None:
            row[field] = value
    sidecar.put("skills", sid, row)
    if body.enabled is not None:
        _bridge_enabled(row["name"], row["enabled"], row["scope"])
    _invalidate_scope(str(row["scope"]))
    return Skill.model_validate(row)


def delete_skill(sid: str) -> None:
    if sid.startswith(_SRC):
        scope, skill_id = _dec_src(sid)
        pp = None if scope == "global" else _project_path(scope)
        from app.backends.ms_agent.skill_index import skill_index

        found = skill_index.snapshot(scope, pp).find(skill_id)
        if found is None:
            raise NotFound("Skill not found.")
        skill, _enabled = found
        raw = str(getattr(skill, "skill_path", "") or "")
        skill_path = Path(raw)
        origin = (
            _skill_origin(skill_path, _origin_context(scope, pp))
            if raw
            else "external"
        )
        forget_path: Path | None = None
        if origin == "managed":
            # Tree-resident: presence is registration, so deletion is
            # removing the directory (filesystem = existence truth).
            shutil.rmtree(skill_path, ignore_errors=True)
            forget_path = skill_path
        elif origin == "legacy-path":
            # A legacy path may contribute several Skill cards.  The source
            # is the actual registration unit, so remove that one reference
            # and leave every original file untouched.  The UI warns that
            # siblings from the same old reference leave together.
            _remove_source_of(scope, pp, skill_path)
        else:
            raise BadRequest(
                "This skill comes from an automatically discovered or "
                "read-only directory. Disable it instead."
            )
        _forget_skill_state(
            scope, pp, skill_id,
            version=str(getattr(skill, "version", "") or "") or None,
            skill_path=forget_path,
        )
        _invalidate_scope(scope)
        return
    row = sidecar.get("skills", sid)
    if not row:
        raise NotFound("Skill not found.")
    sidecar.drop("skills", sid)
    # A sidecar skill is bridged into skills.json by NAME (see create/update),
    # so that is the key its disabled flag lives under.
    row_scope = str(row.get("scope") or "global")
    _forget_skill_state(
        row_scope,
        _project_path(row_scope) if row_scope.startswith("project:") else None,
        str(row.get("name") or ""),
    )
    _invalidate_scope(row_scope)


def _forget_skill_state(scope: str, project_path: str | None, skill_id: str, *,
                        version: str | None = None,
                        skill_path: Path | None = None) -> None:
    """Drop what skills.json still claims about a skill that no longer exists.

    Deleting used to take the files (or the source entry) and leave the rest
    behind: the ``disabled`` flag outlived the skill it named, so re-importing
    one that had been switched off brought it back switched off — and a source
    pointing AT the deleted directory kept being scanned for a path that is no
    longer there.

    Only entries naming THIS skill are touched, never a sweep of everything the
    scan cannot see: a ``disabled`` entry may belong to a skill from a remote
    source, which this module deliberately never loads.
    """
    from ms_agent.config.skills_manager import SkillsConfigManager

    sc = "global" if scope == "global" else "project"
    if sc == "project" and not project_path:
        return
    sk = SkillsConfigManager(global_dir=home())
    kwargs = {} if sc == "global" else {"project_path": project_path}

    # Read before writing: set_skill_enabled would otherwise CREATE skills.json
    # just to store an empty `disabled` list for a skill that was never off.
    data = (sk.load_global() if sc == "global"
            else sk.load_project(str(project_path)))
    disabled = set(data.get("disabled") or [])
    # Both spellings the enabled check accepts: bare id and `id@version`.
    keys = {skill_id} | ({f"{skill_id}@{version}"} if version else set())
    for key in keys & disabled:
        sk.set_skill_enabled(key, True, scope=sc, **kwargs)

    if skill_path is None:
        return
    from ms_agent.skill.sources import SkillSourceType, parse_skill_source

    target = skill_path.resolve()
    for src_str in sk.list_sources(scope=sc, **kwargs):
        try:
            src = parse_skill_source(str(src_str))
            if src.type != SkillSourceType.LOCAL_DIR or not src.path:
                continue
            # Only a source that IS this directory. A parent that also provides
            # other skills stays — same rule _remove_source_of enforces, and
            # the implicit live tree is never a stored entry anyway.
            if Path(src.path).expanduser().resolve() != target:
                continue
        except Exception:
            continue
        sk.remove_source(str(src_str), scope=sc, **kwargs)
        return


def _remove_source_of(scope: str, project_path: str | None,
                      skill_path: Path) -> None:
    """Remove the old explicit source that contributes *skill_path*.

    A single source can contain several Skills, so they leave the catalog
    together.  Their original directories remain untouched.
    """
    from ms_agent.skill.loader import SkillLoader

    configured = _configured_source_for(scope, project_path, skill_path)
    if configured is None:
        raise BadRequest(
            "This skill has no registered source to remove. Disable it instead."
        )
    manager, sdk_scope, kwargs, source_text, source_root = configured
    affected = SkillLoader().load_skills(str(source_root)) or {}
    manager.remove_source(source_text, scope=sdk_scope, **kwargs)
    for loaded_key, skill in affected.items():
        runtime_id = (
            getattr(skill, "skill_id", None)
            or str(loaded_key).split("@", 1)[0]
        )
        _forget_skill_state(
            scope,
            project_path,
            runtime_id,
            version=str(getattr(skill, "version", "") or "") or None,
        )


def _in_live_tree(scope: str, path: Path) -> bool:
    """True when *path* resolves inside the scope's live tree (rmtree guard —
    relative_to avoids startswith prefix bypasses)."""
    try:
        path.resolve().relative_to(_live_tree(scope).resolve())
        return True
    except (ValueError, OSError):
        return False


def _project_path(scope: str) -> str | None:
    proj = pm().get(scope.split(":", 1)[1])
    return proj.path if proj is not None else None
