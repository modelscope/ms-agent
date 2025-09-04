import inspect
from copy import deepcopy
from dataclasses import field
from typing import Any, Dict, Generator, List, Literal, Optional, Union

import json5
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
                  stream: bool = False,
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
        if stream:
            return self.client.messages.stream(**params)
        else:
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
        stream = args.pop('stream', False)

        # 过滤出合法参数
        sig_params = inspect.signature(self.client.messages.create).parameters
        filtered_args = {k: v for k, v in args.items() if k in sig_params}

        # 第一次调用
        completion = self._call_llm(messages, formatted_tools, stream,
                                    **filtered_args)

        if stream:
            return self._stream_out(completion)
        else:
            return self._format_output_message(completion)

    def _stream_out(self, stream_manager):
        message = None
        with stream_manager as stream:
            for chunk in stream:
                message_chunk = self._stream_format_output_message(chunk)
                message = self._merge_stream_message(message, message_chunk)
                yield message

    def _merge_stream_message(self, pre_message_chunk: Optional[Message],
                              message_chunk: Message) -> Optional[Message]:
        """Merges a new chunk of message into the previous chunks during streaming.

        Used to accumulate partial results into a complete Message object.

        Args:
            pre_message_chunk (`Optional[Message]`): Previously accumulated message chunk.
            message_chunk (`Message`): New message chunk to merge.

        Returns:
            Optional[Message]: Merged message with updated content and tool calls.

        Note:
            - **Content Merging**: Textual content (`content`, `reasoning_content`) is appended cumulatively.
            - **Tool Call Merging**: If the same tool call index appears in consecutive chunks,
              its `arguments` and `tool_name` will be updated incrementally.
            - If a new tool call index is found, it will be added as a new entry in `tool_calls`.
        """
        if not pre_message_chunk:
            return message_chunk
        message = deepcopy(pre_message_chunk)
        message.reasoning_content += message_chunk.reasoning_content
        message.content += message_chunk.content
        if message_chunk.tool_calls:
            if message.tool_calls:
                if message.tool_calls[0]['index'] == message_chunk.tool_calls[
                        0]['index']:
                    if message_chunk.tool_calls[0]['id']:
                        message.tool_calls[0]['id'] = message_chunk.tool_calls[
                            0]['id']
                    if message_chunk.tool_calls[0]['arguments']:
                        message.tool_calls[0][
                            'arguments'] += message_chunk.tool_calls[0][
                                'arguments']
                    if message_chunk.tool_calls[0]['tool_name']:
                        message.tool_calls[0][
                            'tool_name'] = message_chunk.tool_calls[0][
                                'tool_name']
                else:
                    message.tool_calls.append(
                        ToolCall(
                            id=message_chunk.tool_calls[0]['id'],
                            arguments=message_chunk.tool_calls[0]['arguments'],
                            type='function',
                            tool_name=message_chunk.tool_calls[0]['tool_name'],
                            index=message_chunk.tool_calls[0]['index']))
            else:
                message.tool_calls = message_chunk.tool_calls
        return message

    @staticmethod
    def _stream_format_output_message(completion_chunk) -> Message:
        """Formats a single chunk from the streaming response into a Message object.

        Args:
            completion_chunk: A single item from the streamed response.

        Returns:
            Message: A Message object representing the current chunk.
        """
        msg = Message(
            role='assistant',
            content='',
            tool_calls=[],
            id='',
            prompt_tokens=0,
            completion_tokens=0,
            api_calls=1)

        event_type = getattr(completion_chunk, 'type', None)
        if not event_type:
            return msg

        # ========== message_start ==========
        if event_type == 'message_start':
            msg.id = getattr(completion_chunk.message, 'id', '')
            msg.role = getattr(completion_chunk.message, 'role', 'assistant')
            return msg

        # ========== content_block_start: text ==========
        elif event_type == 'content_block_start':
            block = completion_chunk.content_block
            if block.type == 'text':
                msg.content = ''  # 开始文本块
            elif block.type == 'tool_use':
                # 初始化 tool_call，arguments 为空对象
                tool_call = ToolCall(
                    id=block.id,
                    index=completion_chunk.index,
                    type='function',
                    tool_name=block.name,
                    arguments='{}')
                msg.tool_calls = [tool_call]
            return msg

        # ========== content_block_delta ==========
        elif event_type == 'content_block_delta':
            delta = completion_chunk.delta
            index = completion_chunk.index

            if hasattr(delta, 'text') and delta.text:
                # 文本增量
                msg.content = delta.text
            elif hasattr(delta, 'partial_json'):
                # 工具参数增量
                parsed = json5.loads(delta.partial_json.strip() or '{}')
                arguments_str = json5.dumps(parsed, ensure_ascii=False)

                tool_call = ToolCall(
                    id='',  # 未知，需后续补全
                    index=index,
                    type='function',
                    tool_name='',  # 未知
                    arguments=arguments_str)
                msg.tool_calls = [tool_call]
            return msg

        # ========== InputJsonEvent (自定义事件) ==========
        elif event_type == 'input_json':
            snapshot = getattr(completion_chunk, 'snapshot', {})
            arguments_str = json5.dumps(snapshot, ensure_ascii=False)

            tool_call = ToolCall(
                id='',  # 未知
                index=getattr(completion_chunk, 'index', 0),
                type='function',
                tool_name='',
                arguments=arguments_str)
            msg.tool_calls = [tool_call]
            return msg

        # ========== content_block_stop ==========
        elif event_type == 'content_block_stop':
            block = completion_chunk.content_block
            if block.type == 'text':
                msg.content = block.text
            elif block.type == 'tool_use':
                arguments_str = json5.dumps(block.input, ensure_ascii=False)

                tool_call = ToolCall(
                    id=block.id,
                    index=completion_chunk.index,
                    type='function',
                    tool_name=block.name,
                    arguments=arguments_str)
                msg.tool_calls = [tool_call]
            return msg

        # ========== message_delta ==========
        elif event_type == 'message_delta':
            usage = getattr(completion_chunk, 'usage', None)
            if usage:
                msg.completion_tokens = getattr(usage, 'output_tokens', 0)
                msg.prompt_tokens = getattr(usage, 'input_tokens', 0)
            delta = getattr(completion_chunk, 'delta', None)
            if delta and getattr(delta, 'stop_reason', None):
                msg.partial = False
            else:
                msg.partial = True
            return msg

        # ========== message_stop ==========
        elif event_type == 'message_stop':
            final_msg = completion_chunk.message
            msg.id = final_msg.id
            msg.role = final_msg.role
            msg.completion_tokens = final_msg.usage.output_tokens
            msg.prompt_tokens = final_msg.usage.input_tokens
            msg.partial = False

            # 解析 content: 只取 TextBlock 的文本
            text_parts = []
            tool_calls = []

            for idx, block in enumerate(final_msg.content):
                if isinstance(block, dict):
                    blk_type = block.get('type')
                else:
                    blk_type = getattr(block, 'type', None)

                if blk_type == 'text':
                    text = getattr(block, 'text', '') or ''
                    text_parts.append(text)
                elif blk_type == 'tool_use':
                    tool_id = getattr(block, 'id', f'call_{idx}')
                    tool_name = getattr(block, 'name', '')
                    input_data = getattr(block, 'input', {}) or {}
                    arguments = json5.dumps(input_data, ensure_ascii=False)
                    tool_call = ToolCall(
                        id=tool_id,
                        index=idx,
                        type='function',
                        tool_name=tool_name,
                        arguments=arguments)
                    tool_calls.append(tool_call)

            msg.content = ''.join(text_parts)
            msg.tool_calls = tool_calls
            return msg

        # ========== fallback ==========
        return msg

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

    messages = [
        Message(
            role='user', content='What is the weather like in San Francisco?')
    ]
    llm = Anthropic(config=OmegaConf.create(config))
    result = llm.generate(messages, tools=tools)
    for chunk in result:
        print(chunk)
