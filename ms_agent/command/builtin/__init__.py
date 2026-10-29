from ms_agent.command.builtin.config_cmds import register_config_commands
from ms_agent.command.builtin.context_cmds import register_context_commands
from ms_agent.command.builtin.info_cmds import register_info_commands
from ms_agent.command.builtin.instruction_cmds import (
    register_instruction_commands)
from ms_agent.command.builtin.memory_cmds import register_memory_commands
from ms_agent.command.builtin.resource_cmds import register_resource_commands
from ms_agent.command.builtin.search_cmds import register_search_commands
from ms_agent.command.builtin.session_cmds import register_session_commands
from ms_agent.command.router import CommandRouter


def register_builtin_commands(router: CommandRouter) -> None:
    register_session_commands(router)
    register_info_commands(router)
    register_config_commands(router)
    register_context_commands(router)
    register_resource_commands(router)
    register_search_commands(router)
    register_instruction_commands(router)
    register_memory_commands(router)
