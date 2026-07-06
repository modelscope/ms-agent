from typing import Any, Dict, List

from ms_agent.acp.client import ACPClientManager
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils.logger import get_logger

logger = get_logger()

ACP_TOOL_PREFIX = 'acp'


class ACPAgentTool(ToolBase):
    """A ``ToolBase`` that wraps all configured external ACP agents.

    Each agent becomes a separate tool entry (``acp---<name>``) with its
    own description, so the LLM can select the right agent based on
    capability descriptions -- mirroring how ``MCPClient`` exposes
    ``server---tool`` entries.
    """

    def __init__(self, config, acp_agents_config: dict | None = None):
        super().__init__(config)
        self._acp_config: dict = acp_agents_config or {}
        self._client_manager = ACPClientManager(self._acp_config)
        self._cwd: str = getattr(config, 'output_dir', '/tmp')

    @classmethod
    def from_config(cls, config) -> 'ACPAgentTool | None':
        """Create an ``ACPAgentTool`` if the config has ``acp_agents``."""
        if not hasattr(config, 'acp_agents'):
            return None
        from omegaconf import OmegaConf
        raw = OmegaConf.to_container(config.acp_agents, resolve=True)
        if not raw:
            return None
        return cls(config, acp_agents_config=raw)

    async def connect(self) -> None:
        pass

    async def cleanup(self) -> None:
        await self._client_manager.close_all()

    async def _get_tools_inner(self) -> Dict[str, Any]:
        tools: Dict[str, List[Tool]] = {}
        for agent_name, agent_cfg in self._acp_config.items():
            server_name = f'{ACP_TOOL_PREFIX}_{agent_name}'
            tool_entry: Tool = {
                'tool_name':
                agent_name,
                'description':
                agent_cfg.get('description', f'ACP agent: {agent_name}'),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'query': {
                            'type':
                            'string',
                            'description':
                            'The task or query to send to this agent',
                        },
                    },
                    'required': ['query'],
                },
            }
            tools[server_name] = [tool_entry]
        return tools

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        agent_name = server_name.replace(f'{ACP_TOOL_PREFIX}_', '', 1)
        query = tool_args.get('query', '')
        if not query:
            return 'Error: "query" parameter is required'
        logger.info('Calling ACP agent %s with query: %s', agent_name,
                    query[:200])
        return await self._client_manager.call_agent(
            agent_name, query, cwd=self._cwd)
