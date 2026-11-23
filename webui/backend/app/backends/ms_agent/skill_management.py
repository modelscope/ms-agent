"""HTTP-host adaptation of the SDK Skill lifecycle. No execution or file copies."""
from __future__ import annotations

from functools import wraps
from pathlib import Path

from fastapi import HTTPException

from app.backends.ms_agent.common import home, pm
from app.core.events import event_bus
from ms_agent.skill.management import SkillManagementError, SkillManagementService, SkillScope
from ms_agent.skill.management.operations import SkillOperations
from ms_agent.skill.management.usage import skill_mutation

_services = {}
_operations = {}


def sdk_scope(scope):
    from app.backends.ms_agent.skills import _project_path, _valid_scope
    _valid_scope(scope)
    return SkillScope(_project_path(scope) if scope != 'global' else None)


def _changed(scope):
    from app.backends.ms_agent.skill_change_tracker import skill_change_tracker
    from app.backends.ms_agent.skill_index import skill_index
    if isinstance(scope, SkillScope):
        scopes = ['global'] if scope.project_path is None else [
            f'project:{p.id}' for p in pm().list()
            if str(Path(p.path).resolve()) == scope.project_path
        ]
    else:
        scopes = [scope]
    for value in scopes:
        skill_change_tracker.mark_dirty(value)
        skill_index.invalidate(value)
    event_bus.publish({'path': '/api/skills', 'method': 'PATCH'})


def service():
    key = home()
    if key not in _services:
        _services[key] = SkillManagementService(key, on_change=_changed)
    return _services[key]


def operations():
    key = home()
    if key not in _operations:
        _operations[key] = SkillOperations(service().root / 'operations',
                                           _completed)
    return _operations[key]


def _completed(scope, kind):
    if kind == 'checking':
        # Checks change metadata only. Previewing a download must not force a
        # running catalog to reload its unchanged files on the next turn.
        event_bus.publish({'path': '/api/skills', 'method': 'PATCH'})


async def shutdown():
    for manager in list(_operations.values()):
        await manager.aclose()
    for manager in list(_services.values()):
        await manager.aclose()
    _operations.clear()
    _services.clear()


def recover():
    from app.backends.ms_agent.skills import _scopes_to_scan
    for scope, path in _scopes_to_scan(None):
        service().recover(SkillScope(path))


def guarded_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except SkillManagementError as exc:
        status = (410 if exc.code == 'PLAN_EXPIRED' else
                  404 if exc.code in ('INSTALLATION_NOT_FOUND',
                                      'OPERATION_NOT_FOUND',
                                      'FILE_NOT_FOUND') else 409)
        raise HTTPException(status, str(exc)) from exc


def settings():
    return service().settings()


def save_settings(auto_check):
    return service().save_settings(auto_check)


def identify(skill_id):
    from app.backends.ms_agent.skills import _SRC, _dec_src, _skill_dir_for
    if not skill_id.startswith(_SRC):
        raise HTTPException(422, 'This Skill does not have a managed source.')
    scope, runtime_id = _dec_src(skill_id)
    sdk = sdk_scope(scope)
    effective = _skill_dir_for(skill_id)
    expected = service().tree(sdk) / runtime_id
    if effective is None or effective.resolve() != expected:
        raise HTTPException(409,
                            'Another source currently supplies this Skill.')
    for identity, row in service().installations(sdk).items():
        if row['runtime_skill_id'] == runtime_id:
            return scope, sdk, identity
    raise HTTPException(422, 'This Skill is not linked to an update source.')


def enrich(rows, scope):
    """No network or content hashing during normal list requests."""
    from app.backends.ms_agent.skills import _dec_src
    try:
        records = service().installations(sdk_scope(scope))
    except SkillManagementError:
        return rows
    by_runtime = {
        r['runtime_skill_id']: (identity, r)
        for identity, r in records.items()
    }
    for skill in rows:
        if skill.scope != scope or skill.origin != 'managed':
            continue
        _, runtime_id = _dec_src(skill.id)
        found = by_runtime.get(runtime_id)
        if not found:
            skill.capabilities = {'can_link': True}
            continue
        identity, row = found
        skill.installation = {
            'id': identity,
            'source': row['source'],
            'version_label': row['installed'].get('version_label'),
            'revision_short': (row['installed'].get('revision') or '')[:7],
            'updated_at': row['installed'].get('updated_at'),
            'backup_at': (row.get('backup') or {}).get('created_at'),
        }
        skill.update = row.get('update') or {
            'remote_status': 'unchecked',
            'local_status': 'unknown'
        }
        skill.capabilities = {
            'can_check': True,
            'can_update': row['source']['selector_kind'] == 'branch',
            'can_restore': bool(row.get('backup'))
        }
    return rows


def submit_check(scope, force=False, skill_ids=None):
    sdk = sdk_scope(scope)
    identities = None
    if skill_ids is not None:
        identities = []
        for sid in skill_ids:
            current_scope, _, identity = identify(sid)
            if current_scope != scope:
                raise HTTPException(
                    409, 'The selected Skill belongs to another location.')
            identities.append(identity)
    if not force and not settings()['auto_check']:
        return operations().submit('checking', scope, _empty)
    return operations().submit(
        'checking', scope,
        lambda: service().check_updates(sdk, identities, force))


async def _empty():
    return []


def submit_inspect(scope, source):
    sdk = sdk_scope(scope)
    return operations().submit('resolving', scope,
                               lambda: service().inspect_source(sdk, source))


def submit_install(scope, snapshot, candidates):
    sdk = sdk_scope(scope)
    return operations().submit(
        'preparing', scope,
        lambda: service().prepare_install(sdk, snapshot, candidates))


def submit_replace(skill_id, kind):
    scope, sdk, identity = identify(skill_id)
    prepare = service().prepare_restore if kind == 'restore' else service(
    ).prepare_update
    return operations().submit('preparing', scope,
                               lambda: prepare(sdk, identity))


def submit_link(skill_id, snapshot, candidate):
    from app.backends.ms_agent.skills import get_skill, _dec_src, _skill_dir_for
    skill = get_skill(skill_id)
    if skill.origin != 'managed' or skill.installation:
        raise HTTPException(409,
                            'Only untracked managed Skills can be linked.')
    scope, runtime_id = _dec_src(skill_id)
    sdk = sdk_scope(scope)
    if _skill_dir_for(skill_id).resolve() != service().tree(sdk) / runtime_id:
        raise HTTPException(409,
                            'Another source currently supplies this Skill.')
    return operations().submit(
        'preparing', scope,
        lambda: service().prepare_link(sdk, runtime_id, snapshot, candidate))


def submit_apply(plan_id, policy, request_id, acknowledge_risk):
    plan = guarded_call(service().get_plan, plan_id)
    scope = 'global'
    if plan.scope.project_path:
        project = next(
            (p for p in pm().list()
             if str(Path(p.path).resolve()) == plan.scope.project_path), None)
        if not project:
            raise HTTPException(409, 'The project no longer exists.')
        scope = f'project:{project.id}'

    def recovered_results():
        _, data = service()._load('plans', plan_id)
        return list(data.get('results', {}).values())

    manager = operations()

    async def apply():
        return await service().apply_plan(
            plan_id,
            local_changes_policy=policy,
            request_id=request_id,
            acknowledge_risk=acknowledge_risk,
            on_progress=lambda results, total: manager.progress(
                operation['id'], results, total))

    operation = manager.submit(
        'applying', scope, apply, recovery_result=recovered_results)
    return operation


def coordinated_mutation(scope_for):
    """Keep legacy WebUI import/delete paths in the same SDK mutation gate."""

    def decorate(function):

        @wraps(function)
        def wrapped(*args, **kwargs):
            scope = scope_for(*args, **kwargs)
            sdk = sdk_scope(scope)
            try:
                with skill_mutation(service().tree(sdk)):
                    result = function(*args, **kwargs)
                    service().invalidate_local(sdk)
                    _changed(scope)
                    return result
            except SkillManagementError as exc:
                raise HTTPException(409, str(exc)) from exc

        return wrapped

    return decorate
