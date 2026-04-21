from typing import Any, Dict, List

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils.logger import get_logger

logger = get_logger()

A2A_TOOL_PREFIX = 'a2a'


class A2AAgentTool(ToolBase):
    """A ``ToolBase`` that wraps all configured remote A2A agents.

    Each agent becomes a separate tool entry (``a2a_<name>---<name>``)
    with its own description, so the LLM can select the right agent
    based on capability descriptions -- mirroring how ``ACPAgentTool``
    exposes ``acp_<name>---<name>`` entries.
    """

    def __init__(self, config, a2a_agents_config: dict | None = None):
        super().__init__(config)
        self._a2a_config: dict = a2a_agents_config or {}
        from ms_agent.a2a.client import A2AClientManager
        self._client_manager = A2AClientManager(self._a2a_config)

    @classmethod
    def from_config(cls, config) -> 'A2AAgentTool | None':
        """Create an ``A2AAgentTool`` if the config has ``a2a_agents``."""
        if not hasattr(config, 'a2a_agents'):
            return None
        from omegaconf import OmegaConf
        raw = OmegaConf.to_container(config.a2a_agents, resolve=True)
        if not raw:
            return None
        return cls(config, a2a_agents_config=raw)

    async def connect(self) -> None:
        pass

    async def cleanup(self) -> None:
        await self._client_manager.close_all()

    async def _get_tools_inner(self) -> Dict[str, Any]:
        tools: Dict[str, List[Tool]] = {}
        for agent_name, agent_cfg in self._a2a_config.items():
            server_name = f'{A2A_TOOL_PREFIX}_{agent_name}'
            tool_entry: Tool = {
                'tool_name':
                agent_name,
                'description':
                agent_cfg.get('description',
                              f'A2A remote agent: {agent_name}'),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'query': {
                            'type':
                            'string',
                            'description':
                            'The task or query to send to this remote agent',
                        },
                    },
                    'required': ['query'],
                },
            }
            tools[server_name] = [tool_entry]
        return tools

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        agent_name = server_name.replace(f'{A2A_TOOL_PREFIX}_', '', 1)
        query = tool_args.get('query', '')
        if not query:
            return 'Error: "query" parameter is required'
        logger.info('Calling A2A agent %s with query: %s', agent_name,
                    query[:200])
        return await self._client_manager.call_agent(agent_name, query)
