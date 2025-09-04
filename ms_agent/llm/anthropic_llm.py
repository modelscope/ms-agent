import inspect
from dataclasses import field
from typing import Any, Dict, Generator, List, Literal, Optional, Union

from ms_agent.llm import LLM
from ms_agent.llm.utils import Message, Tool, ToolCall
from ms_agent.utils import (MAX_CONTINUE_RUNS, assert_package_exist,
                            get_logger, retry)
from omegaconf import DictConfig, OmegaConf
from typing_extensions import TypedDict


class Anthropic(LLM):
    input_msg = {
        'role', 'content', 'tool_calls', 'partial', 'prefix', 'tool_call_id'
    }

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
        self.max_continue_runs = getattr(config.llm, 'max_continue_runs',
                                         None) or MAX_CONTINUE_RUNS

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
        """将 Tool 列表转换为 Anthropic 所需的 tools 格式"""
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
        # 将 Message 转换为 Anthropic 所需的 messages 格式
        formatted_messages = []
        for msg in messages:
            content = []

            # 处理文本内容
            if msg.content:
                content.append({'type': 'text', 'text': msg.content})

            # 处理工具调用
            if msg.tool_calls:
                for tool_call in msg.tool_calls:
                    content.append({
                        'type': 'tool_use',
                        'id': tool_call['id'],
                        'name': tool_call['tool_name'],
                        'input': tool_call.get('arguments', {})
                    })

            # 处理工具结果
            if msg.role == 'tool':
                # Anthropic 使用 'user' 角色来传递 tool_result
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
                  **kwargs) -> Any:
        """
        调用 Anthropic API 的核心方法
        """
        formatted_messages = self._format_input_message(messages)

        # 移除空 content 的 message（避免非法请求）
        formatted_messages = [m for m in formatted_messages if m['content']]

        # 构造请求参数
        params = {
            'model': self.model,
            'messages': formatted_messages,
            'max_tokens': kwargs.pop('max_tokens', 1024),
        }

        if tools:
            params['tools'] = tools

        # 添加其他参数（如 temperature 等）
        params.update(kwargs)

        # 调用 API
        return self.client.messages.create(**params)

    def generate(self,
                 messages: List[Message],
                 tools: Optional[List[Tool]] = None,
                 max_continue_runs: Optional[int] = None,
                 **kwargs) -> Union[Message, Generator[Message, None, None]]:
        """
        生成回复，支持工具调用和继续生成
        """
        formatted_tools = self.format_tools(tools)
        args = self.args.copy()
        args.update(kwargs)
        stream = args.get('stream', False)

        # 过滤出合法参数
        sig_params = inspect.signature(self.client.messages.create).parameters
        filtered_args = {k: v for k, v in args.items() if k in sig_params}

        # 第一次调用
        completion = self._call_llm(messages, formatted_tools, **filtered_args)

        if stream:
            return self._stream_format_output_message(completion)
        else:
            return self._format_output_message(completion)

    @staticmethod
    def _stream_format_output_message(completion_chunk) -> Message:
        """Formats a single chunk from the streaming response into a Message object.

        Args:
            completion_chunk: A single item from the streamed response.

        Returns:
            Message: A Message object representing the current chunk.
        """
        raise NotImplementedError

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
            'anthropic_base_url': 'https://api-inference.modelscope.cn',
            'max_continue_runs': 3,
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

    messages = [
        Message(
            role='user', content='What is the weather like in San Francisco?')
    ]
    llm = Anthropic(config=OmegaConf.create(config))
    result = llm.generate(messages, tools=tools)
    print(result)
