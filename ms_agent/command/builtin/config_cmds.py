import os

from ms_agent.command.router import CommandRouter
from ms_agent.command.types import (
    CommandContext,
    CommandDef,
    CommandResult,
    CommandResultType,
)

CMD_MODEL = CommandDef(
    name='model',
    description='Show or switch the current model',
    category='config',
)

CMD_CONFIG = CommandDef(
    name='config',
    description='Show current runtime configuration',
    category='config',
    aliases=('settings',),
)


def _persist_model_to_config(config, new_model: str, service=None):
    """Persist the model (and optional service) change to the project patch.

    Writes ``llm.model`` (and ``llm.service`` when a provider switch happened)
    into ``<work_dir>/.ms_agent/config.yaml`` rather than mutating the
    version-controlled source YAML. Anchored to the **work dir** (``output_dir``)
    — the project — not the config file's directory, so running a shared or
    packaged template config (e.g. ``demos/``) never scatters a ``.ms_agent/``
    next to it. The work-dir patch is merged back (patch wins) on the next run.
    Returns the patch path on success, or None if no dir is known / write fails.
    """
    from omegaconf import OmegaConf

    # Prefer the work dir; fall back to the config's own dir only if unset.
    base_dir = (getattr(config, 'output_dir', None)
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
        patch = (OmegaConf.load(source)
                 if os.path.isfile(source) else OmegaConf.create({}))
        OmegaConf.update(patch, 'llm.model', new_model, merge=True)
        if service:
            OmegaConf.update(patch, 'llm.service', service, merge=True)
        OmegaConf.save(patch, patch_path)
        return patch_path
    except OSError:
        return None


async def cmd_model(ctx: CommandContext) -> CommandResult:
    if not ctx.runtime or not ctx.runtime.llm:
        return CommandResult(
            type=CommandResultType.MESSAGE, content='No active agent.'
        )

    if not ctx.args:
        model = ctx.runtime.llm.model
        service = getattr(ctx.runtime.llm.config.llm, 'service', 'unknown')
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=(f'Model: {model}\nService: {service}\n'
                     'Switch with: /model <model>  or  /model <provider>/<model>'),
        )

    # Accept both "/model <model>" and "/model <provider>/<model>".
    arg = ctx.args.strip()
    service_override = None
    new_model = arg
    if '/' in arg:
        service_override, new_model = arg.split('/', 1)
        service_override = service_override.strip()
        new_model = new_model.strip()

    from omegaconf import OmegaConf

    target = ctx.runtime.llm
    config = target.config
    OmegaConf.update(config, 'llm.model', new_model, merge=True)
    if service_override:
        OmegaConf.update(config, 'llm.service', service_override, merge=True)

    # Always apply the cheap in-place update: legacy LLM classes read
    # ``self.model`` at generate time, so this alone switches the model for
    # them (and keeps behavior unchanged when nothing else is possible).
    target.model = new_model

    # Best-effort: rebuild the LLM so the switch also reaches a provider-router
    # transport, which caches model/base_url/api_key at build time (setting
    # ``.model`` would not reach it). Adopt the rebuilt state into the existing
    # object so every holder of the reference sees it (agent.llm and
    # runtime.llm are the same object). If the rebuild can't complete (missing
    # credentials, test doubles, ...), keep the in-place update above.
    from ms_agent.llm import LLM

    try:
        rebuilt = LLM.from_config(config)
    except Exception:  # noqa: BLE001 - best-effort; in-place update stands
        rebuilt = None
    if rebuilt is not None and type(rebuilt) is type(target):
        target.__dict__ = rebuilt.__dict__
    elif rebuilt is not None:
        target.__class__ = rebuilt.__class__
        target.__dict__ = rebuilt.__dict__

    saved_path = _persist_model_to_config(config, new_model, service_override)
    switched = (f'{service_override}/{new_model}'
                if service_override else new_model)
    content = f'Switched to: {switched}'
    if saved_path:
        content += f'\nSaved to: {saved_path}'
    else:
        content += '\n(in-memory only; no project directory to persist to)'
    return CommandResult(
        type=CommandResultType.MUTATE_STATE,
        content=content,
    )


async def cmd_config(ctx: CommandContext) -> CommandResult:
    if not ctx.runtime or not ctx.runtime.llm:
        return CommandResult(
            type=CommandResultType.MESSAGE, content='No active agent.'
        )

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
