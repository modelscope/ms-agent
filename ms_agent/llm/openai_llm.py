# Copyright (c) Alibaba, Inc. and its affiliates.
import inspect
from typing import Any, Dict, Generator, Iterable, List, Optional

from ms_agent.utils import assert_package_exist, get_logger, retry
from omegaconf import DictConfig, OmegaConf
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall, Function)

from .llm import LLM
from .utils import Message, Tool, ToolCall

logger = get_logger()


class OpenAI(LLM):
    """Base Class for OpenAI SDK LLMs

    Args:
        config(`DictConfig`): The config instance to use.
        base_url(`Optional[str]`): The base_url.
        api_key(`Optional[str]`): The api_key.
    """
    input_msg = {
        'role', 'content', 'tool_calls', 'partial', 'prefix', 'tool_call_id'
    }

    def __init__(self,
                 config: DictConfig,
                 base_url: Optional[str] = None,
                 api_key: Optional[str] = None):
        super().__init__(config)
        assert_package_exist('openai')
        import openai
        self.model: str = config.llm.model
        base_url = base_url or config.llm.openai_base_url
        api_key = api_key or config.llm.openai_api_key
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.args: Dict = OmegaConf.to_container(
            getattr(config, 'generation_config', {}))

    def format_tools(self,
                     tools: Optional[List[Tool]] = None
                     ) -> List[Dict[str, Any]]:
        if tools:
            tools = [{
                'type': 'function',
                'function': {
                    'name':
                    f'{tool["tool_name"]}'
                    if tool.get('server_name') else tool['tool_name'],
                    'description':
                    tool['description'],
                    'parameters':
                    tool['parameters']
                }
            } for tool in tools]
        else:
            tools = None
        return tools

    @retry(max_attempts=12, delay=1.0)
    def generate(self,
                 messages: List[Message],
                 tools: Optional[List[Tool]] = None,
                 **kwargs) -> Message | Generator[Message, None, None]:
        """Generate response.

        Args:
            messages(`List[Message]`): The previous messages.
            tools(`Optional[List[Tool]]`): The tools to use.
            **kwargs: Extra generation kwargs.
        Returns:
            The Message or Genrator of messages.
        """
        parameters = inspect.signature(
            self.client.chat.completions.create).parameters
        args = self.args.copy()
        args.update(kwargs)
        stream = args.get('stream', False)

        args = {key: value for key, value in args.items() if key in parameters}
        completion = self._call_llm(messages, self.format_tools(tools), **args)

        # Complex task may produce long response
        # Call continue_generate to keep generating if the finish_reason is `length`
        if stream:
            return self._stream_continue_generate(messages, completion, tools,
                                                  **args)
        else:
            return self._continue_generate(messages, completion, tools, **args)

    def _call_llm(self,
                  messages: List[Message],
                  tools: Optional[List[Tool]] = None,
                  **kwargs) -> Any:
        messages = self._format_input_message(messages)
        return self.client.chat.completions.create(
            model=self.model, messages=messages, tools=tools, **kwargs)

    def merge_stream_message(self, pre_message_chunk: Optional[Message],
                             message_chunk: Message) -> Optional[Message]:
        """Merge new chunk of message into the previous chunks of a message, used in stream mode.

        Args:
            pre_message_chunk: Previous chunk of message.
            message_chunk: Latest chunk of message.

        Returns:
            Merged message.
        """
        if not pre_message_chunk:
            return message_chunk
        message = pre_message_chunk
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

    def _stream_continue_generate(self,
                                  messages: List[Message],
                                  completion: Iterable,
                                  tools: Optional[List[Tool]] = None,
                                  **kwargs) -> Generator[Message, None, None]:
        """Continue generate in stream mode.

        Args:
            messages(`List[Message]`): The previous messages.
            completion(`Iterable`): Iterable of streaming output messages, usually comes from the output of `call_llm`
            tools(`Optional[List[Tool]]`): List of tools to use.
            **kwargs: Extra generation kwargs.

        Yields:
            the completion chunk
        """
        message = None
        for chunk in completion:
            message_chunk = self._stream_format_output_message(chunk)

            message = self.merge_stream_message(message, message_chunk)
            yield message

            if chunk.choices and chunk.choices[0].finish_reason in [
                    'length', 'null'
            ]:
                print(
                    f'finish_reason: {chunk.choices[0].finish_reason}， continue generate.'
                )
                completion = self._continue_generate_recursive(
                    messages, message, tools, **kwargs)
                for chunk in self._stream_continue_generate(
                        messages, completion, tools, **kwargs):
                    yield chunk

    @staticmethod
    def _stream_format_output_message(completion_chunk) -> Message:
        tool_calls = None
        reasoning_content = ''
        content = ''
        if completion_chunk.choices and completion_chunk.choices[0].delta:
            content = completion_chunk.choices[0].delta.content
            reasoning_content = getattr(completion_chunk.choices[0].delta,
                                        'reasoning_content', '')
            if completion_chunk.choices[0].delta.tool_calls:
                func = completion_chunk.choices[0].delta.tool_calls
                tool_calls = [
                    ToolCall(
                        id=tool_call.id,
                        index=tool_call.index,
                        type=tool_call.type,
                        arguments=tool_call.function.arguments,
                        tool_name=tool_call.function.name)
                    for tool_call in func
                ]
        content = content or ''
        reasoning_content = reasoning_content or ''
        return Message(
            role='assistant',
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            id=completion_chunk.id)

    @staticmethod
    def _format_output_message(completion) -> Message:
        content = completion.choices[0].message.content or ''
        if hasattr(completion.choices[0].message, 'reasoning_content'):
            reasoning_content = completion.choices[
                0].message.reasoning_content or ''
        else:
            reasoning_content = ''
        tool_calls = None
        if completion.choices[0].message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tool_call.id,
                    index=getattr(tool_call, 'index', idx),
                    type=tool_call.type,
                    arguments=tool_call.function.arguments,
                    tool_name=tool_call.function.name) for idx, tool_call in
                enumerate(completion.choices[0].message.tool_calls)
            ]
        return Message(
            role='assistant',
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            id=completion.id)

    @staticmethod
    def _merge_partial_message(messages: List[Message], new_message: Message):
        messages[-1].reasoning_content += new_message.reasoning_content
        messages[-1].content += new_message.content
        if new_message.tool_calls:
            if messages[-1].tool_calls:
                messages[-1].tool_calls += new_message.tool_calls
            else:
                messages[-1].tool_calls = new_message.tool_calls

    def _continue_generate_recursive(self,
                                     messages: List[Message],
                                     new_message,
                                     tools: List[Tool] = None,
                                     **kwargs):
        # ref: https://bailian.console.aliyun.com/?tab=doc#/doc/?type=model&url=https%3A%2F%2Fhelp.aliyun.com%2Fdocument_detail%2F2862210.html&renderType=iframe # noqa
        # TODO: Move to dashscope_llm and find a proper continue way for openai_llm generating
        if messages[-1].to_dict().get('partial', False):
            self._merge_partial_message(messages, new_message)
        else:
            new_message.partial = True
            messages.append(new_message)

        messages = self._format_input_message(messages)
        return self._call_llm(messages, tools, **kwargs)

    def _continue_generate(self,
                           messages: List[Message],
                           completion,
                           tools: List[Tool] = None,
                           **kwargs) -> Message:
        new_message = self._format_output_message(completion)
        if completion.choices[0].finish_reason in ['length', 'null']:
            logger.info(
                f'finish_reason: {completion.choices[0].finish_reason}， continue generate.'
            )
            completion = self._continue_generate_recursive(
                messages, new_message, tools, **kwargs)
            return self._continue_generate(messages, completion, tools,
                                           **kwargs)
        elif messages[-1].to_dict().get('partial', False):
            self._merge_partial_message(messages, new_message)
            messages[-1].partial = False
            return messages.pop(-1)
        else:
            return new_message

    def _format_input_message(self,
                              messages: List[Message]) -> List[Dict[str, Any]]:
        openai_messages = []
        for message in messages:
            if isinstance(message, Message):
                message.content = message.content.strip()
                message = message.to_dict()

            if message.get('tool_calls'):
                tool_calls = list()
                for tool_call in message['tool_calls']:
                    function_data: Function = {
                        'name': tool_call['tool_name'],
                        'arguments': tool_call['arguments']
                    }
                    tool_call: ChatCompletionMessageToolCall = {
                        'id': tool_call['id'],
                        'function': function_data,
                        'type': tool_call['type'],
                    }
                    tool_calls.append(tool_call)
                message['tool_calls'] = tool_calls

            message = {
                key: value.strip() if isinstance(value, str) else value
                for key, value in message.items()
                if key in self.input_msg and value
            }
            if 'content' not in message:
                message['content'] = ''

            openai_messages.append(message)

        return openai_messages


if __name__ == '__main__':
    import os

    # 创建一个嵌套的字典结构
    conf: DictConfig = OmegaConf.create({
        'llm': {
            'model': 'Qwen/Qwen3-235B-A22B',
            'openai_base_url': 'https://api-inference.modelscope.cn/v1',
            'openai_api_key': os.getenv('MODELSCOPE_API_KEY'),
            'generation_config': {
                'stream': True,
                'max_tokens': 50
            }
        }
    })

    messages = [
        Message(role='assistant', content='You are a helpful assistant.'),
        # Message(role='user', content='经度：116.4074，纬度：39.9042是什么地方。用这个名字作为目录名'),
        Message(role='user', content='请你简单介绍杭州'),
    ]

    # tools = [
    #     Tool(server_name='amap-maps', tool_name='maps_regeocode',
    #     description='将一个高德经纬度坐标转换为行政区划地址信息',
    #     parameters={'type': 'object', 'properties': {'location': {'type': 'string', 'description': '经纬度'}},
    #     'required': ['location']}),
    #     Tool(tool_name='mkdir', description='在文件系统创建目录',
    #     parameters={'type': 'object', 'properties': {'dir_name': {'type': 'string', 'description': '目录名'}},
    #     'required': ['dir_name']})
    # ]
    tools = None

    # 打印配置
    print(OmegaConf.to_yaml(conf))

    llm = OpenAI(conf)

    res = llm.generate(
        messages=messages, tools=tools, extra_body={'enable_thinking': False})
    for chunk in res:
        print(chunk)

    # kwargs覆盖conf
    # message = llm.generate(messages=messages, tools=tools, stream=False, extra_body={'enable_thinking': False})
    # print(message)
    # messages.append(message)
    # messages.append(Message(role='tool', content='北京市朝阳区崔各庄阿里巴巴朝阳科技园'))
    # message = llm.generate(messages=messages, tools=tools, stream=False, extra_body={'enable_thinking': False})
    # print(message)
