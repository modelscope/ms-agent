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


def _persist_model_to_config(config, new_model: str):
    """Persist the model change to the project-level config patch.

    Writes ``llm.model`` into ``<local_dir>/.ms-agent/config.yaml`` rather than
    mutating the version-controlled source YAML. ``Config.from_task`` merges
    this patch back (patch wins) on the next run, so the override survives
    without ever touching the committed config. Returns the patch path on
    success, or None if no source directory is known or the write fails.
    """
    from omegaconf import OmegaConf

    local_dir = getattr(config, 'local_dir', None)
    if not local_dir:
        return None
    patch_dir = os.path.join(str(local_dir), '.ms-agent')
    patch_path = os.path.join(patch_dir, 'config.yaml')
    try:
        os.makedirs(patch_dir, exist_ok=True)
        patch = (OmegaConf.load(patch_path)
                 if os.path.isfile(patch_path) else OmegaConf.create({}))
        OmegaConf.update(patch, 'llm.model', new_model, merge=True)
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
            content=f'Model: {model}\nService: {service}',
        )

    new_model = ctx.args.strip()
    from omegaconf import OmegaConf

    OmegaConf.update(
        ctx.runtime.llm.config, 'llm.model', new_model, merge=True
    )
    ctx.runtime.llm.model = new_model
    saved_path = _persist_model_to_config(ctx.runtime.llm.config, new_model)
    content = f'Switched to: {new_model}'
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
