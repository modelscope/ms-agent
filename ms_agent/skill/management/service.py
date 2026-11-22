"""Skill installation lifecycle, independent of HTTP and UI frameworks."""
from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from ms_agent.config.skills_manager import SkillsConfigManager
from ms_agent.skill.loader import SkillLoader
from ms_agent.utils.atomic_file import atomic_write_json
from ms_agent.utils.file_lock import file_lock

from .content import (changes, copy_content, file_diff, manifest,
                      relative_path, skill_directory_name)
from .models import (FileChange, ItemResult, ManagedSource, PlanItem,
                     SkillManagementError, SkillPlan, SkillScope,
                     SourceCandidate, SourceCollection, SourcePreview,
                     management_error)
from .providers import SkillSourceProvider
from .io import complete_io
from .usage import skill_mutation, skill_read

PLAN_TTL = 1800
CHECK_TTL = 24 * 3600


def _now():
    return datetime.now(timezone.utc).isoformat()


def _expires():
    return datetime.fromtimestamp(time.time() + PLAN_TTL,
                                  timezone.utc).isoformat()


def _id():
    return uuid.uuid4().hex


class SkillManagementService:

    def __init__(self, global_dir: str, provider=None, on_change=None):
        self.config = SkillsConfigManager(global_dir)
        self.root = self.config.global_skills_tree().resolve(
        ).parent / 'skill-state'
        self._provider = provider
        self.on_change = on_change
        self._checks = {}
        self._check_waiters = {}

    @property
    def provider(self):
        if self._provider is None:
            self._provider = SkillSourceProvider()
        return self._provider

    async def aclose(self):
        pending = list(self._checks.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if self._provider is not None:
            await self._provider.aclose()

    def tree(self, scope: SkillScope) -> Path:
        return (self.config.project_skills_tree(scope.project_path)
                if scope.project_path else
                self.config.global_skills_tree()).resolve()

    def _records_path(self, scope):
        return self.tree(scope).parent / 'skill-installs.json'

    @staticmethod
    def _read_json(path):
        try:
            return json.loads(path.read_text('utf-8'))
        except (ValueError, OSError) as exc:
            raise SkillManagementError(
                'STATE_INVALID',
                'The installation record is unreadable.') from exc

    def _read_records(self, scope):
        path = self._records_path(scope)
        if not path.exists():
            return {'schema_version': 1, 'installations': {}}
        data = self._read_json(path)
        if (not isinstance(data, dict) or data.get('schema_version') != 1
                or not isinstance(data.get('installations'), dict)):
            raise SkillManagementError(
                'STATE_INVALID', 'Unsupported installation record format.')
        try:
            for identity, row in data['installations'].items():
                self._directory('validation', identity)
                name = row['runtime_skill_id']
                if not name or name == '.' or relative_path(
                        name).as_posix() != name or '/' in name:
                    raise ValueError('Invalid Skill directory')
                ManagedSource(**row['source'])
                if not isinstance(
                        row['generation'],
                        int) or not row['installed']['content_digest']:
                    raise ValueError('Invalid installation')
                if row.get('backup'):
                    self._directory('validation', row['backup']['id'])
        except (KeyError, TypeError, ValueError, SkillManagementError) as exc:
            raise SkillManagementError('STATE_INVALID',
                                       'Invalid installation record.') from exc
        return data

    def settings(self):
        path = self.root / 'settings.json'
        if not path.exists():
            return {'auto_check': True}
        return {
            'auto_check': self._read_json(path).get('auto_check', True) is True
        }

    def save_settings(self, auto_check: bool):
        path = self.root / 'settings.json'
        with file_lock(path):
            atomic_write_json(path, {'auto_check': bool(auto_check)})
        return {'auto_check': bool(auto_check)}

    def installations(self, scope: SkillScope) -> dict:
        with file_lock(self._records_path(scope)):
            return self._read_records(scope)['installations']

    def installation(self, scope, installation_id):
        row = self.installations(scope).get(installation_id)
        if row is None:
            raise SkillManagementError('INSTALLATION_NOT_FOUND',
                                       'The installation no longer exists.')
        return row

    def _directory(self, category, identity):
        if not isinstance(identity, str) or len(identity) != 32:
            raise SkillManagementError('PLAN_EXPIRED',
                                       'This preview has expired.')
        try:
            int(identity, 16)
        except ValueError:
            raise SkillManagementError('PLAN_EXPIRED',
                                       'This preview has expired.') from None
        return self.root / category / identity

    def _load(self, category, identity):
        folder = self._directory(category, identity)
        if not (folder / 'record.json').exists():
            raise SkillManagementError('PLAN_EXPIRED',
                                       'This preview has expired.')
        data = self._read_json(folder / 'record.json')
        if datetime.fromisoformat(
                data['expires_at']).timestamp() < time.time():
            raise SkillManagementError('PLAN_EXPIRED',
                                       'This preview has expired.')
        return folder, data

    def cleanup(self):
        """Only remove expired, unlocked previews. Never touch recovery logs."""
        for category in ('sources', 'plans'):
            for folder in (self.root / category).glob('*'):
                if not folder.is_dir():
                    continue
                try:
                    with file_lock(folder, timeout=0):
                        record = folder / 'record.json'
                        if record.exists():
                            expired = datetime.fromisoformat(
                                self._read_json(record)
                                ['expires_at']).timestamp() < time.time()
                        else:
                            expired = folder.stat(
                            ).st_mtime + PLAN_TTL < time.time()
                        if expired:
                            shutil.rmtree(folder)
                except (TimeoutError, OSError, SkillManagementError):
                    continue

    async def inspect_source(self, scope: SkillScope,
                             source: str) -> SourcePreview:
        await complete_io(self.cleanup)
        resolved = await self.provider.resolve(source)
        identity = _id()
        folder = self._directory('sources', identity)
        try:
            if isinstance(resolved, SourceCollection):
                return await self._inspect_collection(scope, resolved, folder,
                                                      identity)
            root = await self.provider.materialize(resolved, folder)
            preview = await complete_io(self._discover, scope, resolved, root,
                                        identity)
            atomic_write_json(folder / 'record.json', {
                **asdict(preview), 'root':
                root.relative_to(folder).as_posix()
            })
            return preview
        except BaseException:
            await complete_io(
                lambda: shutil.rmtree(folder, ignore_errors=True))
            raise

    async def _inspect_collection(self, scope, collection, folder, identity):
        semaphore = asyncio.Semaphore(4)
        roots = {}
        total_bytes = 0

        async def inspect_member(member):
            nonlocal total_bytes
            member_folder = folder / _id()
            async with semaphore:
                try:
                    source = await self.provider.resolve_member(member)
                    root = await self.provider.materialize(
                        source, member_folder)
                    preview = await complete_io(self._discover, scope, source,
                                                root, identity)
                    size = await complete_io(lambda: sum(p.stat(
                    ).st_size for p in root.rglob('*') if p.is_file()))
                    if total_bytes + size > 256 * 1024 * 1024:
                        raise SkillManagementError(
                            'PACKAGE_TOO_LARGE',
                            'The collection is too large.')
                    total_bytes += size
                    for candidate in preview.candidates:
                        candidate.source = source
                        candidate.source_label = member
                        roots[candidate.id] = root.relative_to(
                            folder).as_posix()
                    return preview.candidates
                except Exception as exc:
                    await complete_io(lambda: shutil.rmtree(
                        member_folder, ignore_errors=True))
                    return [
                        SourceCandidate(
                            _id(),
                            member.split('/')[-1],
                            '',
                            '',
                            '',
                            source_label=member,
                            error=management_error(exc))
                    ]

        tasks = [
            asyncio.create_task(inspect_member(member))
            for member in collection.members
        ]
        try:
            groups = await asyncio.wait_for(
                asyncio.gather(*tasks), timeout=240)
        except asyncio.TimeoutError as exc:
            raise SkillManagementError(
                'SOURCE_UNAVAILABLE',
                'The collection inspection timed out.') from exc
        finally:
            # gather doesn't cancel siblings on a failed child. Await every
            # owned task before the outer handler removes the snapshot folder.
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        candidates = [candidate for group in groups for candidate in group]
        if len(candidates) > 100:
            raise SkillManagementError(
                'PACKAGE_TOO_LARGE',
                'The collection contains too many Skills.')
        preview = SourcePreview(identity, scope, collection, candidates,
                                _expires())
        await complete_io(atomic_write_json, folder / 'record.json', {
            **asdict(preview), 'roots': roots
        })
        return preview

    @staticmethod
    def _candidate_source(folder, data, candidate):
        if candidate.get('error'):
            raise SkillManagementError('INVALID_SELECTION',
                                       'This Skill could not be inspected.')
        source = replace(
            ManagedSource(**(candidate.get('source') or data['source'])),
            subdir=candidate['subdir'])
        root = (
            data['roots'][candidate['id']]
            if 'roots' in data else data['root'])
        return source, folder / root / candidate['subdir']

    def _discover(self, scope, source, root, identity):
        search = root / source.subdir if source.subdir else root
        manifest(
            root)  # Includes binaries, rejects links and unexpected files.
        loader = SkillLoader()
        roots = (search, ) if (
            search
            / 'SKILL.md').is_file() else loader._iter_skill_directories(search)
        rows = [
            skill for path in roots
            for skill in loader.discover_skills(str(path)).values()
        ]
        candidates = []
        seen = set()
        for skill in rows:
            metadata = loader.parser.parse_yaml_frontmatter(
                skill.content) or {}
            # Archive wrappers contain commit IDs. They must never become an
            # installation's name when SKILL.md omits YAML metadata.
            display_name = str(
                metadata.get('name')
                or (source.repository.split('/')[-1] if skill.skill_path
                    == root else skill.skill_path.name)).strip()
            description = str(metadata.get('description') or display_name)
            name = skill_directory_name(display_name)
            conflict = self._conflict(scope, name, display_name, source)
            if name in seen:
                conflict = 'NAME_CONFLICT'
            seen.add(name)
            version = str(skill.version or '')
            candidates.append(
                SourceCandidate(
                    _id(), display_name, description,
                    skill.skill_path.relative_to(root).as_posix(), name,
                    version if version not in ('', 'latest') else None,
                    conflict))
        counts = {}
        for candidate in candidates:
            counts[candidate.runtime_skill_id] = counts.get(
                candidate.runtime_skill_id, 0) + 1
        for candidate in candidates:
            if counts[candidate.runtime_skill_id] > 1:
                candidate.conflict = 'NAME_CONFLICT'
        if not candidates:
            raise SkillManagementError('SKILL_NOT_FOUND',
                                       'No Skill was found at this location.')
        if len(candidates) > 100:
            raise SkillManagementError(
                'PACKAGE_TOO_LARGE',
                'Use a link to a smaller Skill directory.')
        return SourcePreview(identity, scope, source, candidates, _expires())

    def _conflict(self, scope, runtime_id, name, source=None):
        tree = self.tree(scope)
        if (tree / runtime_id).exists():
            for row in self.installations(scope).values():
                if (row['runtime_skill_id'] == runtime_id and source
                        and ManagedSource(**row['source']).identity
                        == source.identity):
                    return 'ALREADY_INSTALLED'
            return 'NAME_CONFLICT'
        settings = (
            self.config.load_project(scope.project_path)
            if scope.project_path else self.config.load_global())
        from ms_agent.skill.sources import SkillSourceType, parse_skill_source
        for raw in settings.get('sources', []):
            parsed = parse_skill_source(str(raw))
            if parsed.type != SkillSourceType.LOCAL_DIR:
                # A pre-existing remote configuration can shadow the new tree;
                # do not claim a managed install is active without resolving it.
                return 'SOURCE_CONFLICT'
            for skill in SkillLoader().discover_skills(parsed.path).values():
                if (skill.skill_id == runtime_id or skill_directory_name(
                        skill.name) == skill_directory_name(name)):
                    return 'NAME_CONFLICT'
        return None

    def _new_plan(self, kind, scope):
        plan = SkillPlan(_id(), kind, scope, [], _expires())
        folder = self._directory('plans', plan.id)
        folder.mkdir(parents=True)
        return plan, folder

    async def prepare_install(self, scope, source_snapshot_id, candidate_ids):
        return await complete_io(self._prepare_install, scope,
                                 source_snapshot_id, list(candidate_ids))

    def _prepare_install(self, scope, source_snapshot_id, candidate_ids):
        if not candidate_ids or len(candidate_ids) > 100 or len(
                set(candidate_ids)) != len(candidate_ids):
            raise SkillManagementError('INVALID_SELECTION',
                                       'Select one or more Skills.')
        source_folder = self._directory('sources', source_snapshot_id)
        with file_lock(source_folder):
            _, data = self._load('sources', source_snapshot_id)
            if data['scope'] != asdict(scope):
                raise SkillManagementError(
                    'PLAN_STALE', 'The installation location changed.')
            candidates = {x['id']: x for x in data['candidates']}
            if any(identity not in candidates for identity in candidate_ids):
                raise SkillManagementError('INVALID_SELECTION',
                                           'Unknown Skill selection.')
            names = [candidates[i]['runtime_skill_id'] for i in candidate_ids]
            if len(names) != len(set(names)):
                raise SkillManagementError('NAME_CONFLICT',
                                           'Select only one Skill per name.')
            plan, folder = self._new_plan('install', scope)
            try:
                for identity in candidate_ids:
                    candidate = candidates[identity]
                    source, src = self._candidate_source(
                        source_folder, data, candidate)
                    dst = folder / identity / 'candidate'
                    digest = copy_content(src, dst)
                    item = PlanItem(
                        identity,
                        candidate['runtime_skill_id'],
                        candidate['name'],
                        source,
                        digest,
                        None,
                        version_label=candidate['version_label'])
                    item.conflict = self._conflict(scope,
                                                   item.runtime_skill_id,
                                                   item.name, source)
                    item.changes = changes(None, dst)
                    item.safety = self._validate(dst)
                    plan.items.append(item)
                atomic_write_json(folder / 'record.json', plan.to_dict())
                return plan
            except BaseException:
                shutil.rmtree(folder, ignore_errors=True)
                raise

    def _validate(self, path):
        from ms_agent.skill.safety import SkillSafetyScanner
        skill = SkillLoader().load_skills(str(path))
        if not skill:
            raise SkillManagementError('INVALID_PACKAGE',
                                       'Invalid SKILL.md content.')
        report = SkillSafetyScanner(
            cache_path=self.root / 'safety-cache.json',
            cache_ttl=0).scan_skill(next(iter(skill.values())))
        return asdict(report)

    def _local_state(self, scope, row):
        target = self.tree(scope) / row['runtime_skill_id']
        try:
            with skill_read([self.tree(scope)]):
                digest, _ = manifest(target)
        except (SkillManagementError, OSError) as exc:
            return ('missing' if getattr(exc, 'code', None)
                    == 'CONTENT_MISSING' else 'unknown'), None
        baseline = row.get('installed', {}).get('content_digest') if row.get(
            'baseline_known', True) else None
        return ('unknown' if not baseline else
                'clean' if baseline == digest else 'modified'), digest

    async def prepare_link(self, scope, runtime_skill_id, source_snapshot_id,
                           candidate_id):
        """Explicitly associate one existing managed directory with an upstream."""
        return await complete_io(self._prepare_link, scope, runtime_skill_id,
                                 source_snapshot_id, candidate_id)

    def _prepare_link(self, scope, runtime_id, snapshot, candidate_id):
        if runtime_id == '.' or '/' in runtime_id or relative_path(
                runtime_id).as_posix() != runtime_id:
            raise SkillManagementError('INVALID_REQUEST',
                                       'Invalid Skill identity.')
        with file_lock(self._directory('sources', snapshot)):
            source_folder, data = self._load('sources', snapshot)
            if data['scope'] != asdict(scope):
                raise SkillManagementError(
                    'PLAN_STALE', 'The installation location changed.')
            selected = next(
                (c for c in data['candidates'] if c['id'] == candidate_id),
                None)
            if selected is None:
                raise SkillManagementError('INVALID_SELECTION',
                                           'Unknown Skill selection.')
            if any(r['runtime_skill_id'] == runtime_id
                   for r in self.installations(scope).values()):
                raise SkillManagementError(
                    'PLAN_STALE', 'This Skill already has an update source.')
            source, src = self._candidate_source(source_folder, data, selected)
            row = {
                'runtime_skill_id': runtime_id,
                'generation': 0,
                'baseline_known': False,
                'installed': {
                    'content_digest': None,
                    'version_label': None
                }
            }
            return self._prepare_replace('link', scope, None, row, source, src)

    async def check_updates(self, scope, installation_ids=None, force=False):
        selected = None if installation_ids is None else tuple(
            sorted(installation_ids))
        key = (scope.project_path, selected, force)
        task = self._checks.get(key)
        if task is None:
            task = asyncio.create_task(
                self._check_updates(scope, installation_ids, force))
            self._checks[key] = task
        self._check_waiters[key] = self._check_waiters.get(key, 0) + 1
        try:
            return await asyncio.shield(task)
        finally:
            self._check_waiters[key] -= 1
            if not self._check_waiters[key]:
                self._check_waiters.pop(key)
                self._checks.pop(key, None)
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def _check_updates(self, scope, installation_ids, force):
        records = self.installations(scope)
        ids = list(installation_ids) if installation_ids is not None else list(
            records)
        if any(identity not in records for identity in ids):
            raise SkillManagementError('INSTALLATION_NOT_FOUND',
                                       'The installation no longer exists.')
        semaphore = asyncio.Semaphore(4)
        downloads = {}
        revisions = {}
        folders = []

        async def latest_source(source):
            key = (*source.identity, source.ref, source.selector_kind)
            if key not in revisions:
                revisions[key] = asyncio.create_task(
                    self.provider.latest(source))
            latest = await asyncio.shield(revisions[key])
            return replace(latest, subdir=source.subdir, url=source.url)

        async def candidate(source):
            key = (*source.identity, source.revision)
            if key not in downloads:

                async def fetch():
                    folder = self.root / 'checks' / _id()
                    folders.append(folder)
                    return await self.provider.materialize(source, folder)

                downloads[key] = asyncio.create_task(fetch())
            return await asyncio.shield(downloads[key])

        async def check(identity):
            async with semaphore:
                row = records.get(identity)
                if row is None:
                    return {
                        'installation_id': identity,
                        'remote_status': 'unsupported'
                    }
                local_status, _ = await complete_io(self._local_state, scope,
                                                    row)
                old = row.get('update') or {}
                checked = old.get('checked_at')
                ttl = max(60, (old.get('error') or {}).get('retry_after')
                          or 0) if old.get('error') else CHECK_TTL
                if not force and checked and (
                        datetime.fromisoformat(checked).timestamp() + ttl
                        > time.time()):
                    result = {**old, 'local_status': local_status}
                else:
                    result = {
                        'remote_status': 'current',
                        'local_status': local_status,
                        'checked_at': _now(),
                        'stale': False,
                        'error': None
                    }
                    try:
                        source = ManagedSource(**row['source'])
                        if source.selector_kind != 'branch':
                            result['remote_status'] = 'pinned'
                        else:
                            latest = await latest_source(source)
                            known = old.get('latest') or {}
                            if latest.revision == row['installed'].get(
                                    'revision'):
                                digest = row['installed']['content_digest']
                            elif latest.revision == known.get(
                                    'revision') and known.get(
                                        'content_digest'):
                                digest = known['content_digest']
                            else:
                                root = await asyncio.wait_for(
                                    candidate(latest), 150)
                                content = root / source.subdir
                                if not (content / 'SKILL.md').is_file():
                                    raise SkillManagementError(
                                        'SKILL_MOVED_OR_REMOVED',
                                        'The Skill was moved or removed.')
                                digest, _ = await complete_io(
                                    manifest, content)
                            result['remote_status'] = (
                                'current'
                                if digest == row['installed']['content_digest']
                                else 'available')
                            result['latest'] = {
                                'revision': latest.revision,
                                'content_digest': digest
                            }
                    except Exception as exc:
                        result.update(
                            remote_status='failed',
                            stale=True,
                            error=management_error(exc),
                            latest=old.get('latest'),
                            last_known_status=old.get('last_known_status')
                            or old.get('remote_status'))
                with file_lock(self._records_path(scope)):
                    data = self._read_records(scope)
                    live = data['installations'].get(identity)
                    if live and live['generation'] == row['generation']:
                        live['update'] = result
                        atomic_write_json(self._records_path(scope), data)
                return {'installation_id': identity, **result}

        checks = [asyncio.create_task(check(identity)) for identity in ids]
        try:
            return await asyncio.wait_for(asyncio.gather(*checks), 180)
        finally:
            for task in checks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*checks, return_exceptions=True)
            tasks = [*downloads.values(), *revisions.values()]
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for folder in folders:
                shutil.rmtree(folder, ignore_errors=True)

    async def prepare_update(self, scope, installation_id):
        row = self.installation(scope, installation_id)
        source = ManagedSource(**row['source'])
        if source.selector_kind != 'branch':
            raise SkillManagementError('PINNED_VERSION',
                                       'This Skill follows a fixed version.')
        latest = await self.provider.latest(source)
        staging = self.root / 'downloads' / _id()
        try:
            root = await self.provider.materialize(latest, staging)
            return await complete_io(self._prepare_replace, 'update', scope,
                                     installation_id, row, latest,
                                     root / source.subdir)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    async def prepare_restore(self, scope, installation_id):
        row = self.installation(scope, installation_id)
        backup = row.get('backup')
        if not backup:
            raise SkillManagementError('BACKUP_MISSING',
                                       'No previous version is available.')
        root = self.tree(
            scope).parent / 'skill-state' / 'backups' / backup['id']
        return await complete_io(self._prepare_replace, 'restore', scope,
                                 installation_id, row,
                                 ManagedSource(**backup['record']['source']),
                                 root / 'content')

    def _prepare_replace(self, kind, scope, identity, row, source, content):
        plan, folder = self._new_plan(kind, scope)
        item_id = _id()
        item_folder = folder / item_id
        try:
            digest = copy_content(content, item_folder / 'candidate')
            with skill_read([self.tree(scope)]):
                local, local_digest = self._local_state(scope, row)
                if local_digest is None:
                    raise SkillManagementError(
                        'BASELINE_UNKNOWN',
                        'The local content cannot be verified.')
                copy_content(
                    self.tree(scope) / row['runtime_skill_id'],
                    item_folder / 'before')
            if manifest(item_folder / 'before')[0] != local_digest:
                raise SkillManagementError('PLAN_STALE',
                                           'Content changed. Review again.')
            loader = SkillLoader()
            skill = next(
                iter(
                    loader.discover_skills(str(item_folder
                                               / 'candidate')).values()))
            metadata = loader.parser.parse_yaml_frontmatter(
                skill.content) or {}
            name = str(metadata.get('name') or row['runtime_skill_id'])
            item = PlanItem(
                item_id, row['runtime_skill_id'], name, source, digest,
                local_digest, identity, row['generation'], local,
                None if skill.version == 'latest' else str(skill.version),
                row['installed'].get('version_label'),
                changes(item_folder / 'before', item_folder / 'candidate'))
            if kind == 'link' and local_digest == digest:
                item.local_status = 'clean'
            item.safety = self._validate(item_folder / 'candidate')
            if kind == 'link' and not item.changes:
                item.safety = None  # Recording provenance does not introduce files.
            plan.items.append(item)
            data = plan.to_dict()
            if kind == 'restore':
                data['restore_record'] = row['backup']['record']
            atomic_write_json(folder / 'record.json', data)
            return plan
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def get_plan(self, identity):
        _, data = self._load('plans', identity)
        return SkillPlan(
            data['id'], data['kind'], SkillScope(**data['scope']), [
                PlanItem(
                    **{
                        **x, 'source': ManagedSource(**x['source']),
                        'changes': [FileChange(**f) for f in x['changes']]
                    }) for x in data['items']
            ], data['expires_at'])

    def diff(self, plan_id, item_id, path):
        folder, data = self._load('plans', plan_id)
        item = next((x for x in data['items'] if x['id'] == item_id), None)
        if item is None or path not in {f['path'] for f in item['changes']}:
            raise SkillManagementError('FILE_NOT_FOUND',
                                       'File not in this preview.')
        before = folder / item_id / 'before'
        return file_diff(before if before.exists() else None,
                         folder / item_id / 'candidate', path)

    async def apply_plan(self,
                         plan_id,
                         *,
                         local_changes_policy='abort',
                         request_id,
                         acknowledge_risk=False,
                         on_progress=None):
        if local_changes_policy not in (
                'abort', 'replace') or not request_id or len(request_id) > 128:
            raise SkillManagementError('INVALID_REQUEST',
                                       'Invalid apply request.')
        plan = self.get_plan(plan_id)
        results = []
        for item in plan.items:
            await asyncio.sleep(0)  # Cancellation between independent commits.
            try:
                result = await complete_io(self._apply_item, plan_id, item.id,
                                           local_changes_policy, request_id,
                                           acknowledge_risk)
            except asyncio.CancelledError:
                if self.on_change:
                    self.on_change(plan.scope)
                raise
            results.append(result)
            if on_progress:
                on_progress(results, len(plan.items))
            if result.status == 'succeeded' and self.on_change:
                self.on_change(plan.scope)
        return results

    def _apply_item(self, plan_id, item_id, policy, request_id,
                    acknowledge_risk):
        folder = self._directory('plans', plan_id)
        with file_lock(folder):
            _, plan = self._load('plans', plan_id)
            item = next(x for x in plan['items'] if x['id'] == item_id)
            completed = plan.get('results', {}).get(item_id)
            if completed and completed['status'] == 'succeeded':
                return ItemResult(**completed)
            scope = SkillScope(**plan['scope'])
            try:
                result = self._commit(scope, plan, item, folder, policy,
                                      acknowledge_risk, request_id)
            except Exception as exc:
                result = ItemResult(
                    item_id, 'failed', error=management_error(exc))
            plan.setdefault('results', {})[item_id] = asdict(result)
            atomic_write_json(folder / 'record.json', plan)
            return result

    def _commit(self, scope, plan, item, folder, policy, acknowledge_risk,
                request_id):
        tree = self.tree(scope)
        state = tree.parent / 'skill-state'
        records_path = self._records_path(scope)
        candidate = folder / item['id'] / 'candidate'
        # Validate again at apply: a preview must never become permission to
        # replace a different tree, source, local version or downloaded payload.
        if manifest(candidate)[0] != item['candidate_digest']:
            raise SkillManagementError('PLAN_STALE',
                                       'The preview content changed.')
        risk = (item.get('safety') or {}).get('risk_level')
        if risk in ('warning', 'dangerous') and not acknowledge_risk:
            raise SkillManagementError(
                'SAFETY_REVIEW_REQUIRED',
                'Review the Skill safety findings before installing.')
        target = tree / item['runtime_skill_id']
        with skill_mutation(tree), file_lock(records_path):
            self._recover_locked(scope)
            data = self._read_records(scope)
            for saved_id, saved in data['installations'].items():
                if saved.get('last_plan_item') == item['id']:
                    return ItemResult(item['id'], 'succeeded', saved_id,
                                      item['runtime_skill_id'])
            identity = item['installation_id'] or _id()
            old = data['installations'].get(identity)
            prior_record = old
            if plan['kind'] == 'install':
                conflict = self._conflict(scope, item['runtime_skill_id'],
                                          item['name'])
                if conflict:
                    raise SkillManagementError(
                        conflict, 'A Skill already uses this name.')
            elif plan['kind'] == 'link':
                if any(r['runtime_skill_id'] == item['runtime_skill_id']
                       for r in data['installations'].values()):
                    raise SkillManagementError(
                        'PLAN_STALE',
                        'This Skill already has an update source.')
                if manifest(target)[0] != item['local_digest']:
                    raise SkillManagementError(
                        'PLAN_STALE', 'Content changed. Review again.')
                if item['local_status'] != 'clean' and policy != 'replace':
                    raise SkillManagementError(
                        'BASELINE_UNKNOWN',
                        'Confirm replacement of the untracked files.')
                old = {
                    'runtime_skill_id': item['runtime_skill_id'],
                    'name': item['name'],
                    'source': item['source'],
                    'generation': 0,
                    'baseline_known': False,
                    'installed': {
                        'content_digest': item['local_digest'],
                        'revision': None,
                        'version_label': None,
                        'installed_at': _now()
                    }
                }
            else:
                if not old or old['generation'] != item['generation']:
                    raise SkillManagementError('PLAN_STALE',
                                               'The installation changed.')
                local, digest = self._local_state(scope, old)
                if digest != item['local_digest']:
                    raise SkillManagementError(
                        'PLAN_STALE', 'Content changed. Review again.')
                if local != 'clean' and policy != 'replace':
                    raise SkillManagementError(
                        'LOCAL_MODIFIED',
                        'Confirm replacement of local changes.')
                if (plan['kind'] == 'update' and local == 'clean'
                        and digest == item['candidate_digest']):
                    # Rechecking an unchanged Skill must not consume the one
                    # useful backup or manufacture another installed version.
                    old['update'] = {
                        'remote_status': 'current',
                        'local_status': 'clean',
                        'checked_at': _now(),
                        'stale': False,
                        'error': None,
                        'latest': {
                            'revision': item['source']['revision'],
                            'content_digest': digest
                        }
                    }
                    atomic_write_json(records_path, data)
                    return ItemResult(item['id'], 'succeeded', identity,
                                      item['runtime_skill_id'])
            transaction = _id()
            work = state / 'transactions' / transaction
            work.mkdir(parents=True)
            incoming = work / 'incoming'
            backup_id = _id()
            backup = state / 'backups' / backup_id
            try:
                copy_content(candidate, incoming)
                backup.mkdir(parents=True)
            except BaseException:
                shutil.rmtree(work, ignore_errors=True)
                shutil.rmtree(backup, ignore_errors=True)
                raise
            new_record = {
                'runtime_skill_id': item['runtime_skill_id'],
                'name': item['name'],
                'generation': (old or {}).get('generation', 0) + 1,
                'source': item['source'],
                'installed': {
                    'revision':
                    item['source']['revision'],
                    'version_label':
                    item.get('version_label'),
                    'content_digest':
                    item['candidate_digest'],
                    'manifest_version':
                    1,
                    'updated_at':
                    _now(),
                    'installed_at':
                    (old or {}).get('installed',
                                    {}).get('installed_at', _now())
                },
                'update': {
                    'remote_status': 'unchecked',
                    'local_status': 'clean',
                    'checked_at': None,
                    'stale': False,
                    'error': None
                },
                'last_request_id': request_id,
                'last_plan_item': item['id'],
            }
            if plan['kind'] == 'restore':
                restored = plan['restore_record']
                new_record['source'] = restored['source']
                new_record['installed'] = {
                    **restored['installed'], 'updated_at': _now()
                }
                new_record['baseline_known'] = restored.get(
                    'baseline_known', True)
                new_record['update']['local_status'] = (
                    'unknown' if not new_record['baseline_known'] else
                    'clean' if item['candidate_digest']
                    == restored['installed']['content_digest'] else 'modified')
            if plan['kind'] == 'link' and not item['changes']:
                data['installations'][identity] = new_record
                try:
                    atomic_write_json(records_path, data)
                finally:
                    shutil.rmtree(work, ignore_errors=True)
                    shutil.rmtree(backup, ignore_errors=True)
                return ItemResult(item['id'], 'succeeded', identity,
                                  item['runtime_skill_id'])
            if old:
                old_without_backup = {
                    k: v
                    for k, v in old.items() if k != 'backup'
                }
                new_record['backup'] = {
                    'id': backup_id,
                    'created_at': _now(),
                    'record': old_without_backup
                }
            journal = {
                'installation_id': identity,
                'runtime_skill_id': item['runtime_skill_id'],
                'old': prior_record,
                'new': new_record,
                'backup_id': backup_id,
                'had_target': target.exists(),
                'candidate_digest': item['candidate_digest'],
                'phase': 'prepared'
            }
            try:
                atomic_write_json(work / 'journal.json', journal)
            except BaseException:
                shutil.rmtree(work, ignore_errors=True)
                shutil.rmtree(backup, ignore_errors=True)
                raise
            try:
                tree.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    target.rename(backup / 'content')
                incoming.rename(target)
                journal['phase'] = 'replaced'
                atomic_write_json(work / 'journal.json', journal)
                data['installations'][identity] = new_record
                atomic_write_json(records_path, data)
                journal['phase'] = 'committed'
                atomic_write_json(work / 'journal.json', journal)
            except BaseException:
                self._recover_locked(scope)
                if self._read_records(scope)['installations'].get(
                        identity) != new_record:
                    raise
            shutil.rmtree(work, ignore_errors=True)
            if old and old.get('backup'):
                shutil.rmtree(
                    state / 'backups' / old['backup']['id'],
                    ignore_errors=True)
            if not old:
                shutil.rmtree(backup, ignore_errors=True)
            return ItemResult(item['id'], 'succeeded', identity,
                              item['runtime_skill_id'])

    def recover(self, scope):
        if not any((self.tree(scope).parent / 'skill-state'
                    / 'transactions').glob('*/journal.json')):
            return
        with skill_mutation(self.tree(scope)), file_lock(
                self._records_path(scope)):
            self._recover_locked(scope)

    def _recover_locked(self, scope):
        tree = self.tree(scope)
        state = tree.parent / 'skill-state'
        for work in (state / 'transactions').glob('*'):
            journal_path = work / 'journal.json'
            if not journal_path.exists():
                continue
            journal = self._read_json(journal_path)
            data = self._read_records(scope)
            identity = journal['installation_id']
            target = tree / journal['runtime_skill_id']
            backup = state / 'backups' / journal['backup_id'] / 'content'
            current = data['installations'].get(identity)
            complete = current == journal['new'] and target.exists() and (
                manifest(target)[0] == journal['candidate_digest'])
            if not complete:
                if backup.exists():
                    if target.exists():
                        shutil.rmtree(target)
                    backup.rename(target)
                elif not journal.get('had_target', journal['old']
                                     is not None) and target.exists():
                    shutil.rmtree(target)
                elif journal['old'] is not None and not target.exists():
                    raise SkillManagementError(
                        'RESTORE_FAILED',
                        'Could not restore the previous Skill files.')
                if journal['old'] is None:
                    data['installations'].pop(identity, None)
                else:
                    data['installations'][identity] = journal['old']
                atomic_write_json(self._records_path(scope), data)
                shutil.rmtree(backup.parent, ignore_errors=True)
            elif journal['old'] and journal['old'].get('backup'):
                shutil.rmtree(
                    state / 'backups' / journal['old']['backup']['id'],
                    ignore_errors=True)
            elif not journal.get('had_target', journal['old'] is not None):
                shutil.rmtree(backup.parent, ignore_errors=True)
            shutil.rmtree(work)

    def forget(self, scope, runtime_skill_id):
        """Called by a coordinated delete; never touches unrelated installs."""
        with file_lock(self._records_path(scope)):
            data = self._read_records(scope)
            ids = [
                i for i, r in data['installations'].items()
                if r['runtime_skill_id'] == runtime_skill_id
            ]
            for identity in ids:
                row = data['installations'].pop(identity)
                state = self.tree(scope).parent / 'skill-state'
                shutil.rmtree(
                    state / 'baselines' / identity, ignore_errors=True)
                if row.get('backup'):
                    shutil.rmtree(
                        state / 'backups' / row['backup']['id'],
                        ignore_errors=True)
            if ids:
                atomic_write_json(self._records_path(scope), data)

    def invalidate_local(self, scope):
        with file_lock(self._records_path(scope)):
            data = self._read_records(scope)
            for row in data['installations'].values():
                row.setdefault('update', {})['local_status'] = 'unknown'
            if data['installations']:
                atomic_write_json(self._records_path(scope), data)
