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

UI-created skills (bundle imports) are **materialized into the scope's live
tree** — no skills.json entry needed; existence is the filesystem. Explicit
sources remain the path for referencing directories outside the trees.
Enable/disable writes the skill_id to skills.json's ``disabled`` list (state is
file-persisted even though existence isn't); a live session picks changes up at
the next turn via the chat turn-boundary sync. Deleting a tree-resident skill
removes its directory; skills from external sources are delete-protected."""
from __future__ import annotations

import base64
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from app.backends.errors import BadRequest, NotFound
from app.backends.ms_agent import sidecar
from app.backends.ms_agent.common import home, pm
from app.schemas.skill import (
    Skill,
    SkillCreate,
    SkillFile,
    SkillFileContent,
    SkillUpdate,
)

_SRC = "src::"
_WEBUI_BUNDLE = "webui.skill.bundle.v1"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip(".-").lower()
    return slug[:64] or "skill"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_scope(scope: str) -> None:
    if scope == "global":
        return
    if scope.startswith("project:"):
        if pm().get(scope.split(":", 1)[1]) is None:
            raise BadRequest(f"unknown project: {scope.split(':', 1)[1]}")
        return
    raise BadRequest(f"invalid scope: {scope!r}")


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
        raise NotFound("skill not found")


def _discovered_for_scope(scope: str, project_path: str | None) -> list[tuple]:
    """(runtime_skill_id, SkillSchema, enabled) for local sources in the scope."""
    from ms_agent.config.skills_manager import SkillsConfigManager
    from ms_agent.skill.loader import SkillLoader
    from ms_agent.skill.sources import SkillSourceType, parse_skill_source

    sk = SkillsConfigManager(global_dir=home())
    if scope == "global":
        sources = sk.list_sources(scope="global")
        disabled = set(sk.load_global().get("disabled", []))
    else:
        sources = sk.list_sources(scope="project", project_path=project_path)
        disabled = set(sk.load_merged(project_path).get("disabled", []))

    loader = SkillLoader()
    out: list[tuple] = []
    for src_str in sources:
        try:
            src = parse_skill_source(str(src_str))
            if src.type != SkillSourceType.LOCAL_DIR or not src.path:
                continue  # skip remote sources — no network in a management call
            for loaded_key, skill in (loader.load_skills(src.path) or {}).items():
                runtime_id = getattr(skill, "skill_id", None) or str(loaded_key).split("@", 1)[0]
                enabled = runtime_id not in disabled and loaded_key not in disabled
                out.append((runtime_id, skill, enabled))
        except Exception:
            continue
    return out


def _discovered_to_schema(scope: str, skill_id: str, skill, enabled: bool) -> Skill:
    return Skill(
        id=_enc_src(scope, skill_id),
        name=getattr(skill, "name", skill_id) or skill_id,
        kind=(getattr(skill, "tags", None) or ["skill"])[0],
        content=getattr(skill, "description", "") or "",
        enabled=enabled,
        scope=scope,
        created_at=datetime.now(timezone.utc),
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
        for skill_id, skill, enabled in _discovered_for_scope(sc, pp):
            item = _discovered_to_schema(sc, skill_id, skill, enabled)
            if (item.name, item.scope) in seen:
                continue  # a webui-local skill of the same name/scope wins
            seen.add((item.name, item.scope))
            rows.append(item)
    rows.sort(key=lambda r: (r.scope, r.name))
    return rows


def _add_local_source(scope: str, path: str) -> Skill:
    """Register a local directory as a skill source so chat actually loads its
    skills (SkillsConfigManager -> skills.json -> merge_skills_into_config)."""
    from ms_agent.config.skills_manager import SkillsConfigManager

    sk = SkillsConfigManager(global_dir=home())
    if scope == "global":
        sk.add_source(path, scope="global")
    else:
        sk.add_source(path, scope="project", project_path=_project_path(scope))
    # Surface a real discovered skill from the newly added source. Other skills
    # from the same source appear on refresh/list.
    from ms_agent.skill.loader import SkillLoader

    for loaded_key, skill in (SkillLoader().load_skills(path) or {}).items():
        runtime_id = getattr(skill, "skill_id", None) or str(loaded_key).split("@", 1)[0]
        return _discovered_to_schema(scope, runtime_id, skill, True)
    # nothing discovered yet — return a source marker
    return Skill(
        id=_enc_src(scope, path), name=os.path.basename(path.rstrip("/")) or path,
        kind="source", content=path, enabled=True, scope=scope,
        created_at=datetime.now(timezone.utc),
    )


def _safe_relpath(path: str) -> Path:
    rel = PurePosixPath(path.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise BadRequest(f"invalid skill file path: {path!r}")
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
            raise BadRequest(f"unknown project: {scope.split(':', 1)[1]}")
        root = SkillsConfigManager.project_skills_tree(proj.path)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _unique_skill_dir(name: str, root: Path) -> Path:
    base = _slug(name)
    candidate = root / base
    if not candidate.exists():
        return candidate
    for idx in range(2, 1000):
        candidate = root / f"{base}-{idx}"
        if not candidate.exists():
            return candidate
    return root / f"{base}-{uuid.uuid4().hex[:8]}"


def _bundle_files_from_content(content: str) -> list[dict]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise BadRequest("invalid skill bundle payload") from exc
    if not isinstance(payload, dict) or payload.get("format") != _WEBUI_BUNDLE:
        raise BadRequest("invalid skill bundle payload")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise BadRequest("skill bundle must contain files")
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
        raise BadRequest("skill bundle must include SKILL.md")

    frontmatter = SkillSchemaParser.parse_yaml_frontmatter(str(skill_md.get("content", "")))
    if not frontmatter or not frontmatter.get("name") or not frontmatter.get("description"):
        raise BadRequest("SKILL.md must include name and description frontmatter")
    bundle_root = _safe_relpath(str(skill_md.get("path", ""))).parent

    skill_dir = _unique_skill_dir(
        str(frontmatter.get("name") or body.name),
        root=_live_tree(body.scope, create=True),
    )
    skill_dir.mkdir(parents=True, exist_ok=False)
    try:
        for entry in files:
            if not isinstance(entry, dict):
                raise BadRequest("invalid skill bundle file")
            rel = _safe_relpath(str(entry.get("path", "")))
            if str(bundle_root) != ".":
                try:
                    rel = rel.relative_to(bundle_root)
                except ValueError:
                    continue
            content = entry.get("content")
            if not isinstance(content, str):
                raise BadRequest(f"invalid content for skill file: {rel}")
            target = skill_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        # Materialized inside the live tree — presence IS registration, no
        # skills.json entry. Surface the discovered skill directly.
        from ms_agent.skill.loader import SkillLoader

        for loaded_key, skill in (SkillLoader().load_skills(str(skill_dir)) or {}).items():
            runtime_id = getattr(skill, "skill_id", None) or str(loaded_key).split("@", 1)[0]
            return _discovered_to_schema(body.scope, runtime_id, skill, True)
        raise BadRequest("skill bundle did not produce a loadable skill")
    except Exception:
        # Leave no half-imported skill behind when validation/write/load fails.
        import shutil

        shutil.rmtree(skill_dir, ignore_errors=True)
        raise


def create_skill(body: SkillCreate) -> Skill:
    _valid_scope(body.scope)
    if body.kind == "bundle":
        return _materialize_bundle(body)

    # If `content` is an existing local directory, treat it as a skill SOURCE
    # (so chat loads it) rather than a content-only sidecar skill. A directory
    # already inside the scope's live tree is registered by presence — don't
    # add a redundant skills.json entry, just surface what the scan sees.
    candidate = os.path.expanduser((body.content or "").strip())
    if candidate and os.path.isdir(candidate):
        if _in_live_tree(body.scope, Path(candidate)):
            from ms_agent.skill.loader import SkillLoader

            for loaded_key, skill in (SkillLoader().load_skills(candidate) or {}).items():
                runtime_id = getattr(skill, "skill_id", None) or str(loaded_key).split("@", 1)[0]
                return _discovered_to_schema(body.scope, runtime_id, skill, True)
            raise BadRequest("no loadable skill found in directory")
        return _add_local_source(body.scope, candidate)
    if body.kind == "source":
        raise BadRequest("local skill source must be an existing directory")

    sid = "sk-" + uuid.uuid4().hex[:12]
    row = {
        "id": sid, "name": body.name, "kind": body.kind, "content": body.content,
        "enabled": body.enabled, "scope": body.scope, "created_at": _now(),
    }
    sidecar.put("skills", sid, row)
    _bridge_enabled(body.name, body.enabled, body.scope)
    return Skill.model_validate(row)


def get_skill(sid: str) -> Skill:
    if sid.startswith(_SRC):
        scope, skill_id = _dec_src(sid)
        pp = None if scope == "global" else _project_path(scope)
        for s, skill, enabled in _discovered_for_scope(scope, pp):
            if s == skill_id:
                return _discovered_to_schema(scope, skill_id, skill, enabled)
        raise NotFound("skill not found")
    row = sidecar.get("skills", sid)
    if not row:
        raise NotFound("skill not found")
    return Skill.model_validate(row)


def _skill_dir_for(sid: str) -> Path | None:
    """Resolve the on-disk directory of a discovered (``src::``) skill; None
    for sidecar-only skills (single markdown body, no directory)."""
    if not sid.startswith(_SRC):
        return None
    scope, skill_id = _dec_src(sid)
    pp = None if scope == "global" else _project_path(scope)
    for s, skill, _enabled in _discovered_for_scope(scope, pp):
        if s != skill_id:
            continue
        p = Path(str(getattr(skill, "skill_path", "") or ""))
        if p.is_file():  # some loaders point at SKILL.md itself
            p = p.parent
        return p if p.is_dir() else None
    raise NotFound("skill not found")


_SKIP_TREE_PARTS = {".git", "__pycache__", ".DS_Store", "node_modules"}


def list_skill_files(sid: str) -> list[SkillFile]:
    """REAL relative file listing of the skill's directory (SKILL.md first).
    Sidecar-only skills expose just their markdown body as SKILL.md."""
    root = _skill_dir_for(sid)
    if root is None:
        get_skill(sid)  # 404 for unknown ids
        return [SkillFile(path="SKILL.md")]
    out: list[SkillFile] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in _SKIP_TREE_PARTS or part.startswith(".")
               for part in rel.parts):
            continue
        try:
            size = p.stat().st_size
        except OSError:
            size = None
        out.append(SkillFile(path=rel.as_posix(), size=size))
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
        raise NotFound("file not found")
    f = root / rel
    if not f.is_file():
        raise NotFound("file not found")
    try:
        return SkillFileContent(path=rel.as_posix(),
                                content=f.read_text("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return SkillFileContent(path=rel.as_posix(), content=None)


def update_skill(sid: str, body: SkillUpdate) -> Skill:
    if sid.startswith(_SRC):
        scope, skill_id = _dec_src(sid)
        if body.enabled is not None:
            _bridge_enabled(skill_id, body.enabled, scope)  # only enable/disable
        return get_skill(sid)
    row = sidecar.get("skills", sid)
    if not row:
        raise NotFound("skill not found")
    for field in ("name", "kind", "content", "enabled"):
        value = getattr(body, field)
        if value is not None:
            row[field] = value
    sidecar.put("skills", sid, row)
    if body.enabled is not None:
        _bridge_enabled(row["name"], row["enabled"], row["scope"])
    return Skill.model_validate(row)


def delete_skill(sid: str) -> None:
    if sid.startswith(_SRC):
        scope, skill_id = _dec_src(sid)
        pp = None if scope == "global" else _project_path(scope)
        for s, skill, _enabled in _discovered_for_scope(scope, pp):
            if s != skill_id:
                continue
            skill_path = Path(getattr(skill, "skill_path", "") or "")
            if skill_path and _in_live_tree(scope, skill_path):
                # Tree-resident: presence is registration, so deletion is
                # removing the directory (filesystem = existence truth).
                import shutil

                shutil.rmtree(skill_path, ignore_errors=True)
                return
            break
        raise BadRequest(
            "skill outside the managed skills tree cannot be deleted; "
            "disable it or remove its source"
        )
    if not sidecar.get("skills", sid):
        raise NotFound("skill not found")
    sidecar.drop("skills", sid)


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
