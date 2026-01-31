import os
import sys
from typing import List, OrderedDict

import json
from coding import CodingAgent
from ms_agent import LLMAgent
from ms_agent.llm import Message
from ms_agent.memory.condenser.refine_condenser import RefineCondenser
from ms_agent.utils import get_logger
from ms_agent.utils.constants import DEFAULT_TAG
from omegaconf import DictConfig

logger = get_logger()


class RefineAgent(LLMAgent):

    def __init__(self,
                 config: DictConfig = DictConfig({}),
                 tag: str = DEFAULT_TAG,
                 trust_remote_code: bool = False,
                 **kwargs):
        # Validate and adjust config before passing to parent
        config = self._validate_config(config)
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.refine_condenser = RefineCondenser(config)

    def _validate_config(self, config: DictConfig) -> DictConfig:
        """Validate config and disable features if credentials are missing."""
        from omegaconf import OmegaConf

        # Make config mutable for modifications
        config = OmegaConf.to_container(config, resolve=True)

        # Check edit_file_config.api_key
        edit_file_api_key = None
        try:
            edit_file_api_key = config.get('tools', {}).get(
                'file_system', {}).get('edit_file_config', {}).get('api_key')
        except Exception:
            pass

        if not edit_file_api_key:
            # Remove edit_file from include list
            try:
                include_list = config.get('tools',
                                          {}).get('file_system',
                                                  {}).get('include', [])
                if 'edit_file' in include_list:
                    include_list.remove('edit_file')
                    logger.warning(
                        '[refine] edit_file_config.api_key not set, removing edit_file from tools'
                    )
            except Exception:
                pass
        else:
            logger.info('[refine] edit_file_config.api_key is configured')

        # Check EDGEONE_PAGES_API_TOKEN
        edgeone_token = None
        try:
            edgeone_token = config.get('tools', {}).get(
                'edgeone-pages-mcp', {}).get('env',
                                             {}).get('EDGEONE_PAGES_API_TOKEN')
        except Exception:
            pass

        if not edgeone_token:
            # Remove edgeone-pages-mcp entirely
            try:
                if 'edgeone-pages-mcp' in config.get('tools', {}):
                    del config['tools']['edgeone-pages-mcp']
                    logger.warning(
                        '[refine] EDGEONE_PAGES_API_TOKEN not set, removing edgeone-pages-mcp from tools'
                    )
            except Exception:
                pass
        else:
            logger.info(
                f'[refine] EDGEONE_PAGES_API_TOKEN is configured: {edgeone_token[:10]}...'
            )

        return OmegaConf.create(config)

    async def condense_memory(self, messages):
        return await self.refine_condenser.run([m for m in messages])

    async def run(self, messages, **kwargs):
        with open(os.path.join(self.output_dir, 'topic.txt')) as f:
            topic = f.read()
        with open(os.path.join(self.output_dir, 'framework.txt')) as f:
            framework = f.read()
        with open(os.path.join(self.output_dir, 'protocol.txt')) as f:
            protocol = f.read()
        with open(os.path.join(self.output_dir, 'tasks.txt')) as f:
            file_info = f.read()

        file_relation = OrderedDict()
        CodingAgent.refresh_file_status(self, file_relation)
        CodingAgent.construct_file_information(self, file_relation, False)
        messages = [
            Message(role='system', content=self.config.prompt.system),
            Message(
                role='user',
                content=f'Original requirements (topic.txt): {topic}\n'
                f'Tech stack (framework.txt): {framework}\n'
                f'Communication protocol (protocol.txt): {protocol}\n'
                f'File list:\n{file_info}\n'
                # f'Your shell tool workspace_dir is {self.output_dir}; '
                f'all tools should use this directory as the current working directory.\n'
                f'When creating the deployment zip file, name it workspace.zip.\n'
                f'Python executable: {sys.executable}\n'
                f'Please refine the project and deploy it to EdgeOne Pages:'),
        ]
        return await super().run(messages, **kwargs)

    async def after_tool_call(self, messages: List[Message]):
        await super().after_tool_call(messages)

        if self.runtime.should_stop:
            import sys
            if not sys.stdin.isatty():
                # Running in WebUI - notify user that agent is waiting for input
                logger.info(
                    '[refine] Agent completed initial refinement. Waiting for user feedback.'
                )

                # Add a system message to notify the user
                messages.append(
                    Message(
                        role='system',
                        content='✅ Initial refinement completed.',
                    ))

                logger.info('[refine] Waiting for user input from stdin...')
                try:
                    query = sys.stdin.readline().strip()
                    if query:
                        logger.info(
                            f'[refine] Received input from WebUI: {query}')
                        messages.append(Message(role='user', content=query))
                        self.runtime.should_stop = False
                        return
                    else:
                        logger.warning(
                            '[refine] Received empty input, continuing to wait...'
                        )
                        return
                except (EOFError, OSError, ValueError) as e:
                    logger.error(f'[refine] Error reading from stdin: {e}')
                    return
            else:
                query = input('>>>')
                if query:
                    messages.append(Message(role='user', content=query))
                    self.runtime.should_stop = False
