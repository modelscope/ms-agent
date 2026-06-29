from ms_agent.command.router import CommandRouter
from ms_agent.command.builtin.session_cmds import register_session_commands
from ms_agent.command.builtin.info_cmds import register_info_commands
from ms_agent.command.builtin.config_cmds import register_config_commands
from ms_agent.command.builtin.context_cmds import register_context_commands


def register_builtin_commands(router: CommandRouter) -> None:
    register_session_commands(router)
    register_info_commands(router)
    register_config_commands(router)
    register_context_commands(router)
