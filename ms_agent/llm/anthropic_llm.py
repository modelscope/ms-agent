import inspect
from typing import Any, Dict, Generator, Iterator, List, Optional, Union

import json5
from ms_agent.llm import LLM
from ms_agent.llm.utils import Message, Tool, ToolCall
from ms_agent.utils import assert_package_exist, get_logger, retry
from omegaconf import DictConfig, OmegaConf


class Anthropic(LLM):

    def __init__(
        self,
        config: DictConfig,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        super().__init__(config)
        assert_package_exist('anthropic', 'anthropic')
        import anthropic

        self.model: str = config.llm.model

        base_url = base_url or config.llm.get('anthropic_base_url')
        api_key = api_key or config.llm.get('anthropic_api_key')

        if not api_key:
            raise ValueError('Anthropic API key is required.')

        self.client = anthropic.Anthropic(
            api_key=api_key,
            base_url=base_url,
        )

        self.args: Dict = OmegaConf.to_container(
            getattr(config, 'generation_config', DictConfig({})))

    def format_tools(self,
                     tools: Optional[List[Tool]]) -> Optional[List[Dict]]:
        if not tools:
            return None

        formatted_tools = []
        for tool in tools:
            formatted_tools.append({
                'name': tool['tool_name'],
                'description': tool.get('description', ''),
                'input_schema': {
                    'type': 'object',
                    'properties': tool.get('parameters',
                                           {}).get('properties', {}),
                    'required': tool.get('parameters', {}).get('required', []),
                }
            })
        return formatted_tools

    def _format_input_message(self,
                              messages: List[Message]) -> List[Dict[str, Any]]:
        """Converts a list of Message objects into the format expected by the Anthropic API.

        Args:
            messages (`List[Message]`): List of Message objects.

        Returns:
            List[Dict[str, Any]]: List of dictionaries compatible with Anthropic's input format.
        """
        formatted_messages = []
        for msg in messages:
            content = []

            if msg.content:
                content.append({'type': 'text', 'text': msg.content})

            if msg.tool_calls:
                for tool_call in msg.tool_calls:
                    content.append({
                        'type': 'tool_use',
                        'id': tool_call['id'],
                        'name': tool_call['tool_name'],
                        'input': tool_call.get('arguments', {})
                    })

            if msg.role == 'tool':
                formatted_messages.append({
                    'role':
                    'user',
                    'content': [{
                        'type': 'tool_result',
                        'tool_use_id': msg.tool_call_id,
                        'content': msg.content
                    }]
                })
                continue

            formatted_messages.append({'role': msg.role, 'content': content})
        return formatted_messages

    def _call_llm(self,
                  messages: List[Message],
                  tools: Optional[List[Dict]] = None,
                  stream: bool = False,
                  **kwargs) -> Any:

        formatted_messages = self._format_input_message(messages)
        formatted_messages = [m for m in formatted_messages if m['content']]

        system = None
        if formatted_messages[0]['role'] == 'system':
            system = formatted_messages[0]['content']
            formatted_messages = formatted_messages[1:]
        params = {
            'model': self.model,
            'messages': formatted_messages,
            'max_tokens': kwargs.pop('max_tokens', 1024),
        }

        if system:
            params['system'] = system
        if tools:
            params['tools'] = tools
        params.update(kwargs)

        if stream:
            return self.client.messages.stream(**params)
        else:
            return self.client.messages.create(**params)

    @retry(max_attempts=3, delay=1.0)
    def generate(self,
                 messages: List[Message],
                 tools: Optional[List[Tool]] = None,
                 max_continue_runs: Optional[int] = None,
                 **kwargs) -> Union[Message, Generator[Message, None, None]]:

        formatted_tools = self.format_tools(tools)
        args = self.args.copy()
        args.update(kwargs)
        stream = args.pop('stream', False)

        sig_params = inspect.signature(self.client.messages.create).parameters
        filtered_args = {k: v for k, v in args.items() if k in sig_params}

        completion = self._call_llm(messages, formatted_tools, stream,
                                    **filtered_args)

        if stream:
            return self._stream_format_output_message(completion)
        else:
            return self._format_output_message(completion)

    def _stream_format_output_message(self,
                                      stream_manager) -> Iterator[Message]:
        current_message = Message(
            role='assistant',
            content='',
            tool_calls=[],
            id='',
            completion_tokens=0,
            prompt_tokens=0,
            api_calls=1,
            partial=True,
        )
        tool_call_id_map = {}  # index -> tool_call_id (用于去重 yield)
        with stream_manager as stream:
            for event in stream:
                event_type = getattr(event, 'type')
                if event_type == 'message_start':
                    msg = event.message
                    current_message.id = msg.id
                    tool_call_id_map = {}
                    yield current_message
                elif event_type == 'text':
                    current_message.content = event.snapshot
                    yield current_message
                elif event_type == 'message_stop':
                    final_msg = getattr(event, 'message')
                    full_content = ''
                    used_tool_call_ids = set()
                    for idx, block in enumerate(event.message.content):
                        if block is None:
                            continue
                        if block.type == 'text':
                            full_content += block.text
                        elif block.type == 'tool_use':
                            tool_call_id = tool_call_id_map.get(idx)
                            tool_call = ToolCall(
                                id=tool_call_id,
                                index=len(current_message.tool_calls),
                                type='function',
                                tool_name=block.name,
                                arguments=json5.dumps(block.input),
                            )
                            current_message.tool_calls.append(tool_call)
                            used_tool_call_ids.add(tool_call_id)
                    current_message.content = full_content
                    current_message.partial = False
                    current_message.completion_tokens = getattr(
                        final_msg.usage, 'output_tokens',
                        current_message.completion_tokens)
                    current_message.prompt_tokens = getattr(
                        final_msg.usage, 'input_tokens',
                        current_message.prompt_tokens)

                    yield current_message

    @staticmethod
    def _format_output_message(completion) -> Message:
        """
        Formats the full non-streaming response from Anthropic into a Message object.

        Args:
            completion: The raw response from the Anthropic API (e.g., a Message object from anthropic SDK).

        Returns:
            Message: A Message object containing the final response.
        """
        # Extract text content
        content = ''
        tool_calls = []

        # Anthropic responses have a list of content blocks
        for block in completion.content:
            if block.type == 'text':
                content += block.text
            elif block.type == 'tool_use':
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        index=len(tool_calls),  # index based on appearance
                        type=
                        'function',  # or "tool_use" depending on your schema
                        arguments=block.input,
                        tool_name=block.name,
                    ))

        # Anthropic does not have a native "reasoning_content" field
        reasoning_content = ''

        return Message(
            role='assistant',
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls if tool_calls else None,
            id=completion.id,
            prompt_tokens=completion.usage.input_tokens,
            completion_tokens=completion.usage.output_tokens,
        )


if __name__ == '__main__':
    import os
    config = {
        'llm': {
            'model': 'Qwen/Qwen2.5-VL-72B-Instruct',
            'anthropic_api_key': os.getenv('MODELSCOPE_API_KEY'),
            'anthropic_base_url': 'https://api-inference.modelscope.cn'
        },
        'generation_config': {
            'stream': True,
        }
    }
    tools = [{
        'tool_name': 'get_weather',
        'description': 'Get the current weather in a given location',
        'parameters': {
            'type': 'object',
            'properties': {
                'location': {
                    'type': 'string',
                    'description': 'City and state'
                },
                'unit': {
                    'type': 'string',
                    'enum': ['celsius', 'fahrenheit']
                }
            },
            'required': ['location']
        }
    }]

    messages = [Message(role='user', content='描述杭州，300字')]
    # messages = [Message(role='user', content='去伦敦现在该带什么样的衣服？')]

    llm = Anthropic(config=OmegaConf.create(config))
    result = llm.generate(messages, tools=tools)
    for chunk in result:
        print(chunk)
