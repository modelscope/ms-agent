import os

from ms_agent.command.router import CommandRouter
from ms_agent.command.types import (CommandContext, CommandDef, CommandResult,
                                    CommandResultType)
from ms_agent.command.usage import arg_error, same_as_webui, status_then_usage

CMD_MODEL = CommandDef(
    name='model',
    description='Show, switch, or manage model providers (shared with WebUI)',
    category='config',
)

CMD_CONFIG = CommandDef(
    name='config',
    description='Show current runtime configuration',
    category='config',
    aliases=('settings', ),
)


def _model_usage() -> str:
    return (
        'usage:\n'
        '  /model                         show current provider + model\n'
        '  /model list                    saved providers (same as WebUI)\n'
        '  /model list live [provider]    fetch chat model ids; preview only\n'
        '  /model <model>                 switch model, keep current provider\n'
        '  /model <provider>/<model>      switch both; <provider> must be lowercase\n'
        '  /model <provider> <model>      same; use when <model> contains /\n'
        '  /model provider add <provider> [key=] [url=] [protocol=openai|anthropic] [name=]\n'
        '                                 add a custom provider, or override a builtin\n'
        '  /model provider set <provider> [key=] [url=] [protocol=] [name=]\n'
        '                                 patch only the fields you pass\n'
        '  /model provider key <provider> <key>|clear\n'
        '                                 set or clear the API key\n'
        '  /model provider url <provider> <url>|clear\n'
        '                                 set or clear the base URL\n'
        '  /model provider remove <provider>\n'
        '                                 delete a custom provider (builtins stay)\n'
        '  /model catalog add <provider> <model>\n'
        '                                 pin a model id on that provider list\n'
        '  /model catalog remove <provider> <model>\n'
        '                                 drop that pinned model id (drop is an alias)\n'
        '  /model catalog remove <model>  same, on the current provider\n'
        '<provider>  first column of /model list, e.g. dashscope\n'
        '<model>     model id on that provider, e.g. qwen3.8-flash\n'
        f'{same_as_webui("settings.json")}\n'
        'Example: /model dashscope qwen3.8-flash'
    )


_CLEAR = frozenset({'clear', '-', 'none'})


def _persist_model_to_config(config, new_model: str, service=None):
    """Write a work-dir ``.ms_agent/config.yaml`` pin (not used by ``/model``).

    ``/model`` persists only the WebUI-shared ``default_model`` in settings.json
    so a later WebUI default still wins on the next TUI launch. This helper
    remains for callers that explicitly want a folder pin; that patch still
    outranks the global default when present.
    """
    from omegaconf import OmegaConf

    # Prefer the work dir; fall back to the config's own dir only if unset.
    base_dir = (
        getattr(config, 'output_dir', None)
        or getattr(config, 'local_dir', None))
    if not base_dir:
        return None
    # Write to the new .ms_agent/ dir; migrate an existing legacy
    # .ms-agent/config.yaml so a single patch file remains authoritative.
    patch_dir = os.path.join(str(base_dir), '.ms_agent')
    patch_path = os.path.join(patch_dir, 'config.yaml')
    legacy_path = os.path.join(str(base_dir), '.ms-agent', 'config.yaml')
    try:
        os.makedirs(patch_dir, exist_ok=True)
        source = patch_path if os.path.isfile(patch_path) else legacy_path
        patch = (
            OmegaConf.load(source)
            if os.path.isfile(source) else OmegaConf.create({}))
        OmegaConf.update(patch, 'llm.model', new_model, merge=True)
        if service:
            OmegaConf.update(patch, 'llm.service', service, merge=True)
        OmegaConf.save(patch, patch_path)
        return patch_path
    except OSError:
        return None


def _mgr():
    from ms_agent.config.model_settings import ModelSettingsManager
    from ms_agent.project.paths import global_home
    return ModelSettingsManager(global_home())


def _builtin_ids() -> set[str]:
    from ms_agent.llm.spec import get_registry
    return {spec.name for spec in get_registry().list_providers()}


def _canonical_provider(head: str) -> str | None:
    from ms_agent.llm.spec import get_registry
    spec = get_registry().get(head)
    if spec is not None:
        return spec.name
    try:
        for pid in _mgr().list_custom_providers():
            if str(pid).lower() == head.lower():
                return str(pid)
    except Exception:
        pass
    return None


def _parse_model_arg(arg: str) -> tuple[str | None, str]:
    """Parse a switch argument into ``(provider or None, model)``.

    Model ids from a gateway often contain ``/`` (``MiniMax/MiniMax-M2.1``)
    and that prefix can collide with a builtin id (``minimax``). Rules:

    * ``/model dashscope MiniMax/MiniMax-M2.1`` — space form; first token is
      a known provider (any case).
    * ``/model dashscope/MiniMax/MiniMax-M2.1`` — slash form; the provider
      token must be a known id written in lowercase, matching how builtins
      are registered. ``MiniMax/…`` therefore stays a model id.
    * ``/model openai/gpt-4o`` — lowercase known id, model has no extra rule.
    * anything else is a model id on the current provider.
    """
    import shlex
    text = (arg or '').strip()
    if not text:
        return None, text
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    if len(parts) >= 2:
        canon = _canonical_provider(parts[0])
        if canon:
            return canon, text[len(parts[0]):].strip()
    if '/' in text:
        head, rest = text.split('/', 1)
        head, rest = head.strip(), rest.strip()
        if rest and head == head.lower() and _canonical_provider(head):
            return _canonical_provider(head), rest
    return None, text


def _strip_provider_prefix(service: str, model: str) -> str:
    from ms_agent.config.model_settings import strip_provider_model_prefix
    return strip_provider_model_prefix(service, model)


def _repair_runtime_model(config, llm=None):
    """Un-glue ``minimax MiniMax-M2.1`` in the live config and settings.json.

    Returns ``(service, display_model)``. Display prefers the runtime
    ``llm.model`` label when set, matching ``/model`` with no args.
    """
    from omegaconf import OmegaConf
    service = str(OmegaConf.select(config, 'llm.service', default='') or '')
    cfg_model = str(OmegaConf.select(config, 'llm.model', default='') or '')
    live_model = str(getattr(llm, 'model', '') or '') if llm is not None else ''
    cfg_cleaned = _strip_provider_prefix(service, cfg_model)
    live_cleaned = _strip_provider_prefix(service, live_model)
    if cfg_model and cfg_cleaned != cfg_model:
        OmegaConf.update(config, 'llm.model', cfg_cleaned, merge=True)
    if llm is not None and live_model and live_cleaned != live_model:
        try:
            llm.model = live_cleaned
        except Exception:
            pass
    try:
        stored = _mgr().get_default_model() or ''
        if '/' in stored:
            pid, mid = stored.split('/', 1)
            mid2 = _strip_provider_prefix(pid, mid)
            if mid2 != mid:
                _mgr().set_default_model(mid2, provider=pid)
    except Exception:
        pass
    return service, live_cleaned or cfg_cleaned, cfg_cleaned or live_cleaned


def _switch_cmd(service, model) -> str:
    service = str(service or '').strip()
    model = _strip_provider_prefix(service, model)
    if not service:
        return f'/model {model}'
    if ('/' in model) or (' ' in model):
        return f'/model {service} {model}'
    return f'/model {service}/{model}'


def _format_pair(service, model) -> str:
    service = str(service or '').strip() or '(none)'
    model = _strip_provider_prefix(service, model) or '(none)'
    return f'Provider: {service}\nModel:    {model}'


def _first_keyed_provider(exclude: str | None = None) -> str | None:
    try:
        mgr = _mgr()
    except Exception:
        return None
    skip = (exclude or '').lower()
    for pid, _provider, override in _iter_provider_rows(mgr):
        if skip and pid.lower() == skip:
            continue
        if _effective_api_key(pid, override):
            return pid
    return None


def _live_identity(llm) -> tuple[str, str, str]:
    spec = getattr(llm, 'spec', None)
    transport = getattr(llm, 'transport', None)
    live_provider = str(getattr(spec, 'name', '') or '')
    live_model = str(getattr(llm, 'model', '') or '')
    live_url = str(getattr(transport, 'base_url', '') or '')
    return live_provider, live_model, live_url


def _current_model_text(service, model, llm=None) -> str:
    raw_service = str(service or '').strip()
    service = raw_service or '(none)'
    model = _strip_provider_prefix(raw_service, model) or '(none)'
    lines = [
        f'Provider: {service}',
        f'Model:    {model}',
    ]
    if raw_service and model != '(none)':
        lines.append(f'Switch:   {_switch_cmd(raw_service, model)}')
    try:
        override = _mgr().list_custom_providers().get(raw_service) or {}
        lines.append(
            f'Key:      {_mask_key(_effective_api_key(raw_service, override))}')
    except Exception:
        pass
    live_p, live_m, live_url = _live_identity(llm)
    if live_p or live_url:
        lines.append(f'Live:     {live_p or "?"} / {live_m or model}')
        if live_url:
            lines.append(f'Endpoint: {live_url}')
    if live_p and live_p.lower() != service.lower():
        realign = _switch_cmd(live_p, model)
        lines.append(
            f'WARNING: the running client is {live_p}, not {service}. '
            'A previous /model switch updated the label but kept the old '
            'client (usually the new provider has no API key). '
            f'Set a key with /model provider key {service} <key>, or '
            f'realign with {realign}.'
        )
    return '\n'.join(lines) + '\n'


def _switch_fail_text(target_service, target_model, stay_service,
                      stay_model) -> str:
    target_model = _strip_provider_prefix(target_service or '', target_model)
    stay_model = _strip_provider_prefix(stay_service, stay_model)
    same = bool(
        target_service and stay_service
        and target_service.lower() == stay_service.lower())
    lines: list[str] = []
    if same:
        lines.append(
            f'Cannot use this model: no usable API key for provider '
            f'{target_service}.')
        lines.append('Already on:')
    else:
        lines.append('Cannot switch to:')
        lines.append(_format_pair(target_service, target_model))
        lines.append('No usable API key for that provider.')
        lines.append('Still on:')
    lines.append(_format_pair(stay_service, stay_model))
    if target_service:
        lines.append(
            f'Set a key: /model provider key {target_service} <key>')
    alt = _first_keyed_provider(exclude=target_service or stay_service)
    if alt:
        lines.append(
            f'Or switch to a keyed provider ({alt}):\n'
            f'  /model {alt} <model>')
    elif (stay_service and target_service
          and stay_service.lower() != target_service.lower()):
        lines.append(
            'If this id is from another gateway, keep that provider:\n'
            f'  {_switch_cmd(stay_service, target_model)}')
    return '\n'.join(lines)


def _mask_key(value) -> str:
    if not value:
        return 'missing'
    return 'set'


def _iter_provider_rows(mgr):
    custom = mgr.list_custom_providers()
    order: list[str] = []
    rows: dict = {}
    for provider in mgr.list_providers():
        pid = provider['id']
        if pid not in rows:
            order.append(pid)
        if pid not in rows or provider.get('overrides_builtin'):
            rows[pid] = provider
    for pid in order:
        yield pid, rows[pid], custom.get(pid) or {}


def _provider_kind(provider, override) -> str:
    if provider.get('builtin') or provider.get('overrides_builtin'):
        kind = 'builtin'
        if override:
            kind += '+override'
        return kind
    return 'custom'


def _effective_api_key(pid: str, override: dict) -> str:
    key = str(override.get('api_key') or '').strip()
    if key:
        return key
    from ms_agent.llm.spec import get_registry
    spec = get_registry().get(pid)
    if spec is None:
        return ''
    for env_var in spec.api_key_env:
        value = os.environ.get(env_var)
        if value:
            return value
    return ''


def _effective_base_url(pid: str, override: dict) -> str:
    url = str(override.get('base_url') or '').strip()
    if url:
        return url
    from omegaconf import OmegaConf
    from ms_agent.llm.credentials import CredentialResolver
    from ms_agent.llm.spec import get_registry
    spec = get_registry().get(pid)
    if spec is None:
        return ''
    return CredentialResolver.resolve_base_url(spec, OmegaConf.create({}))


def _effective_protocol(pid: str, provider: dict, override: dict) -> str:
    proto = override.get('protocol') or provider.get('protocol') or ''
    if proto:
        return str(proto)
    from ms_agent.llm.spec import get_registry
    spec = get_registry().get(pid)
    return spec.transport if spec is not None else 'openai'


def _live_fetch_note(pid: str, override: dict, provider: dict):
    """Fetch chat ids. Returns (ids, dropped, skip_reason)."""
    from ms_agent.llm.model_discovery import (
        fetch_model_ids,
        filter_chat_model_ids,
    )
    key = _effective_api_key(pid, override)
    if not key:
        return [], 0, 'skipped (no API key)'
    url = _effective_base_url(pid, override)
    if not url:
        return [], 0, 'skipped (no base url)'
    proto = _effective_protocol(pid, provider, override)
    raw = fetch_model_ids(url, proto, key)
    if not raw:
        return [], 0, 'live: (empty — /models failed or none)'
    kept, dropped = filter_chat_model_ids(raw)
    return kept, dropped, ''


def _provider_status_lines(mgr, *, live: bool = False,
                           only: str | None = None) -> list[str]:
    from ms_agent.llm.model_discovery import (
        format_id_list,
        format_live_model_lines,
    )

    if live:
        lines = [
            'Providers (live /models; preview only):'
        ]
    else:
        lines = ['Providers (same as WebUI):']
    default = mgr.get_default_model()
    if default:
        lines.append(f'Default: {default}')
    only_id = (only or '').strip().lower() or None
    for pid, provider, override in _iter_provider_rows(mgr):
        if only_id and pid.lower() != only_id:
            continue
        catalog = list(override.get('models') or provider.get('models') or [])
        kind = _provider_kind(provider, override)
        key = _mask_key(_effective_api_key(pid, override) or override.get('api_key'))
        url = override.get('base_url') or '(default)'
        proto = _effective_protocol(pid, provider, override)
        if live:
            live_ids, dropped, skip = _live_fetch_note(pid, override, provider)
            lines.append(f'  {pid} ({kind}):')
            lines.append(
                f'    catalog: {format_id_list(catalog) if catalog else "(none listed)"}')
            if skip:
                lines.append(f'    {skip}')
            else:
                drop_note = ''
                if dropped:
                    drop_note = (
                        f'  (dropped {dropped} image/video/embedding)')
                lines.append(f'    live: {len(live_ids)} chat{drop_note}')
                lines.extend(format_live_model_lines(live_ids, indent='      '))
            lines.append(f'    protocol={proto}  key={key}  url={url}')
        else:
            model_txt = ', '.join(catalog) or '(none listed)'
            lines.append(f'  {pid} ({kind}): {model_txt}')
            lines.append(f'    protocol={proto}  key={key}  url={url}')
    if only_id and len(lines) <= (2 if default else 1):
        lines.append(f'  (no provider named {only})')
    return lines


def _install_rebuilt_llm(target, rebuilt) -> bool:
    """Copy ``rebuilt`` onto ``target`` in place. False if the type is frozen."""
    try:
        if type(rebuilt) is not type(target):
            target.__class__ = rebuilt.__class__
        target.__dict__ = rebuilt.__dict__
        return True
    except TypeError:
        return False


def _rebuild_llm(ctx: CommandContext) -> bool:
    if not ctx.runtime or not ctx.runtime.llm:
        return False
    from ms_agent.llm import LLM
    target = ctx.runtime.llm
    config = target.config
    try:
        rebuilt = LLM.from_config(config)
    except Exception:  # noqa: BLE001 - missing key / bad endpoint
        rebuilt = None
    if rebuilt is None:
        return False
    if _install_rebuilt_llm(target, rebuilt):
        return True
    ctx.runtime.llm = rebuilt
    extra = ctx.extra or {}
    agent = extra.get('agent')
    if agent is not None:
        agent.llm = rebuilt
    return True


def _push_provider_to_runtime(ctx: CommandContext, provider_id: str) -> str:
    if not ctx.runtime or not ctx.runtime.llm:
        return ''
    from omegaconf import OmegaConf
    from ms_agent.tui.app import TuiApp
    config = ctx.runtime.llm.config
    service = str(OmegaConf.select(config, 'llm.service', default='') or '')
    if service != provider_id:
        return (
            f' Switch with /model {provider_id} <model> to use this '
            'provider live.')
    TuiApp._apply_provider_credentials(config, overwrite=True)
    _rebuild_llm(ctx)
    return ' Live credentials applied.'


def _split_kv(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    rest: list[str] = []
    fields: dict[str, str] = {}
    for tok in tokens:
        if '=' in tok:
            key, val = tok.split('=', 1)
            fields[key] = val
        else:
            rest.append(tok)
    return rest, fields


def _kv_alias(fields: dict[str, str]) -> dict[str, str]:
    out = dict(fields)
    if 'url' in out and 'base_url' not in out:
        out['base_url'] = out.pop('url')
    elif 'url' in out:
        out.pop('url')
    if 'key' in out and 'api_key' not in out:
        out['api_key'] = out.pop('key')
    elif 'key' in out:
        out.pop('key')
    return out


async def cmd_model(ctx: CommandContext) -> CommandResult:
    if not ctx.runtime or not ctx.runtime.llm:
        return CommandResult(
            type=CommandResultType.MESSAGE, content='No active agent.')

    if not ctx.args:
        service, model, _cfg_model = _repair_runtime_model(
            ctx.runtime.llm.config, ctx.runtime.llm)
        if not service:
            service = getattr(ctx.runtime.llm.config.llm, 'service', 'unknown')
        if not model:
            model = ctx.runtime.llm.model
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=status_then_usage(
                _current_model_text(service, model, ctx.runtime.llm),
                _model_usage()),
        )

    arg = ctx.args.strip()
    import shlex
    try:
        parts = shlex.split(arg)
    except ValueError:
        parts = arg.split()
    head = parts[0].lower()
    if head == 'help' or arg in ('-h', '--help'):
        return CommandResult(
            type=CommandResultType.MESSAGE, content=_model_usage())
    if head == 'list':
        rest = parts[1:]
        live = bool(rest) and rest[0].lower() in ('live', '--live', 'fetch')
        if rest and not live:
            return arg_error(
                '/model list live [provider]',
                reason='Unknown list option',
                ctx=ctx,
            )
        only = rest[1] if live and len(rest) > 1 else None
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content='\n'.join(
                _provider_status_lines(_mgr(), live=live, only=only)),
        )
    if head == 'provider':
        return _cmd_model_provider(ctx, parts[1:])
    if head == 'catalog':
        return _cmd_model_catalog(ctx, parts[1:])
    return _cmd_model_switch(ctx, arg)


def _cmd_model_switch(ctx: CommandContext, arg: str) -> CommandResult:
    service_override, new_model = _parse_model_arg(arg)
    if service_override:
        service_override = _canonical_provider(service_override) or service_override

    from omegaconf import OmegaConf
    from ms_agent.tui.app import TuiApp

    target = ctx.runtime.llm
    config = target.config
    old_service, _display_model, old_model = _repair_runtime_model(
        config, target)
    new_model = _strip_provider_prefix(
        service_override or old_service, new_model)

    OmegaConf.update(config, 'llm.model', new_model, merge=True)
    if service_override:
        OmegaConf.update(config, 'llm.service', service_override, merge=True)
        TuiApp._apply_provider_credentials(config, overwrite=True)

    if not _rebuild_llm(ctx):
        OmegaConf.update(config, 'llm.model', old_model, merge=True)
        if old_service:
            OmegaConf.update(config, 'llm.service', old_service, merge=True)
            TuiApp._apply_provider_credentials(config, overwrite=True)
        target.model = old_model
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=_switch_fail_text(
                service_override, new_model, old_service, old_model),
        )

    settings_provider = service_override or str(
        getattr(getattr(config, 'llm', None), 'service', '') or '') or None
    _mgr().set_default_model(new_model, provider=settings_provider)
    content = 'Switched to:\n' + _current_model_text(
        settings_provider, new_model, ctx.runtime.llm)
    content += 'Saved as the default (same as WebUI).'
    return CommandResult(
        type=CommandResultType.MUTATE_STATE,
        content=content,
    )


def _cmd_model_provider(ctx: CommandContext, tokens: list[str]) -> CommandResult:
    mgr = _mgr()
    if not tokens:
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content='\n'.join(_provider_status_lines(mgr)),
        )
    action = tokens[0].lower()
    rest = tokens[1:]
    if action in ('list', 'ls'):
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content='\n'.join(_provider_status_lines(mgr)),
        )
    if action == 'add':
        names, fields = _split_kv(rest)
        if not names:
            return arg_error(
                '/model provider add <provider> [key=] [url=] [protocol=] [name=]',
                ctx=ctx,
            )
        pid = names[0]
        fields = _kv_alias(fields)
        mgr.add_provider(
            pid,
            name=fields.get('name') or pid,
            protocol=fields.get('protocol') or 'openai',
            api_key=fields.get('api_key'),
            base_url=fields.get('base_url'),
        )
        note = _push_provider_to_runtime(ctx, pid)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Provider {pid} saved.{note}',
        )
    if action in ('set', 'update'):
        names, fields = _split_kv(rest)
        if not names:
            return arg_error(
                '/model provider set <provider> [key=] [url=] [protocol=] [name=]',
                ctx=ctx,
            )
        pid = names[0]
        fields = _kv_alias(fields)
        if not fields:
            return arg_error(
                '/model provider set <provider> [key=] [url=] [protocol=] [name=]',
                reason='No fields to patch',
                ctx=ctx,
            )
        mgr.patch_provider(
            pid,
            name=fields.get('name'),
            protocol=fields.get('protocol'),
            api_key=fields.get('api_key'),
            base_url=fields.get('base_url'),
            clear_api_key=fields.get('api_key', None) == '',
            clear_base_url=fields.get('base_url', None) == '',
        )
        note = _push_provider_to_runtime(ctx, pid)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Updated provider {pid}.{note}',
        )
    if action == 'key':
        if len(rest) < 2:
            return arg_error(
                '/model provider key <provider> <key>|clear',
                ctx=ctx,
            )
        pid, value = rest[0], ' '.join(rest[1:])
        if value.lower() in _CLEAR:
            mgr.patch_provider(pid, clear_api_key=True)
            note = _push_provider_to_runtime(ctx, pid)
            return CommandResult(
                type=CommandResultType.MESSAGE,
                content=f'Cleared API key for {pid}.{note}',
            )
        mgr.patch_provider(pid, api_key=value)
        note = _push_provider_to_runtime(ctx, pid)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Saved API key for {pid}.{note}',
        )
    if action in ('url', 'base_url'):
        if len(rest) < 2:
            return arg_error(
                '/model provider url <provider> <url>|clear',
                ctx=ctx,
            )
        pid, value = rest[0], rest[1]
        if value.lower() in _CLEAR:
            mgr.patch_provider(pid, clear_base_url=True)
            note = _push_provider_to_runtime(ctx, pid)
            return CommandResult(
                type=CommandResultType.MESSAGE,
                content=f'Cleared base URL for {pid}.{note}',
            )
        mgr.patch_provider(pid, base_url=value)
        note = _push_provider_to_runtime(ctx, pid)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Saved base URL for {pid}.{note}',
        )
    if action == 'remove':
        if not rest:
            return arg_error(
                '/model provider remove <provider>',
                ctx=ctx,
            )
        pid = rest[0]
        custom = mgr.list_custom_providers()
        if pid in _builtin_ids() and pid not in custom:
            return CommandResult(
                type=CommandResultType.MESSAGE,
                content=(
                    f'Cannot remove builtin provider {pid}. '
                    'Clear its override with /model provider key '
                    f'{pid} clear'),
            )
        mgr.remove_provider(pid)
        extra = ''
        if pid in _builtin_ids():
            extra = ' Builtin catalog remains; credential override cleared.'
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Removed provider {pid}.{extra}',
        )
    return arg_error(
        '/model provider add|set|key|url|remove <provider> ...',
        reason=f'Unknown provider action {action!r}',
        note='Type /model for all /model commands',
        ctx=ctx,
    )


def _current_provider(ctx: CommandContext) -> str:
    if not ctx.runtime or not getattr(ctx.runtime, 'llm', None):
        return ''
    cfg = getattr(ctx.runtime.llm, 'config', None)
    llm = getattr(cfg, 'llm', None)
    return str(getattr(llm, 'service', '') or '')


def _pinned_models(mgr, pid: str) -> list[str]:
    entry = mgr.list_custom_providers().get(pid) or {}
    return list(entry.get('models') or [])


def _pinned_catalog_lines(mgr) -> list[str]:
    lines = ['Pinned catalogs:']
    found = False
    for pid, _provider, override in _iter_provider_rows(mgr):
        models = list(override.get('models') or [])
        if not models:
            continue
        found = True
        lines.append(f'  {pid}: {", ".join(models)}')
    if not found:
        lines.append('  (none)')
    return lines


def _cmd_model_catalog(ctx: CommandContext,
                       tokens: list[str]) -> CommandResult:
    mgr = _mgr()
    syntax = '/model catalog add|remove <provider> <model>'
    note = 'drop = remove; omit <provider> to use the current one'
    if not tokens:
        lines = _pinned_catalog_lines(mgr)
        lines.append(f'Need: {syntax}')
        lines.append(note)
        return CommandResult(
            type=CommandResultType.MESSAGE, content='\n'.join(lines))
    action = tokens[0].lower()
    if action == 'drop':
        action = 'remove'
    if action not in ('add', 'remove'):
        return arg_error(
            syntax,
            reason=f'Unknown catalog action {action!r}',
            note=note,
            ctx=ctx,
        )
    rest = tokens[1:]
    inferred = False
    if len(rest) >= 2:
        pid, model = rest[0], ' '.join(rest[1:])
    elif len(rest) == 1:
        pid = _current_provider(ctx)
        model = rest[0]
        inferred = True
        if not pid:
            return arg_error(
                f'/model catalog {action} <provider> <model>',
                reason='No current provider to default to',
                note=note,
                ctx=ctx,
            )
    else:
        return arg_error(
            f'/model catalog {action} <provider> <model>',
            note=note,
            ctx=ctx,
        )
    where = f'{pid} catalog'
    if inferred:
        where += ' (current provider)'
    if action == 'add':
        mgr.add_model(pid, model)
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=f'Added {model} to {where}.',
        )
    if pid not in mgr.list_custom_providers():
        return arg_error(
            '/model catalog remove <provider> <model>',
            reason=f'No catalog override for {pid}',
            note='Pin a model first with /model catalog add',
            ctx=ctx,
        )
    if not mgr.remove_model(pid, model):
        pinned = _pinned_models(mgr, pid)
        pinned_txt = ', '.join(pinned) if pinned else '(none)'
        return arg_error(
            '/model catalog remove <provider> <model>',
            reason=f'{model} is not in the {where}',
            note=f'Pinned: {pinned_txt}',
            ctx=ctx,
        )
    return CommandResult(
        type=CommandResultType.MESSAGE,
        content=f'Removed {model} from {where}.',
    )


async def cmd_config(ctx: CommandContext) -> CommandResult:
    if not ctx.runtime or not ctx.runtime.llm:
        return CommandResult(
            type=CommandResultType.MESSAGE, content='No active agent.')

    config = ctx.runtime.llm.config
    from omegaconf import OmegaConf

    # mask sensitive info
    safe = OmegaConf.to_container(config, resolve=True)
    for key in list(safe.get('llm', {}).keys()):
        if 'key' in key.lower():
            safe['llm'][key] = '***'

    import yaml

    text = yaml.dump(safe, default_flow_style=False, allow_unicode=True)
    if len(text) > 2000:
        text = text[:2000] + '\n... (truncated)'
    return CommandResult(type=CommandResultType.MESSAGE, content=text)


def register_config_commands(router: CommandRouter) -> None:
    router.register(CMD_MODEL, cmd_model)
    router.register(CMD_CONFIG, cmd_config)
