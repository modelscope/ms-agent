# flake8: noqa
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Literal

import json
from ms_agent.utils.logger import get_logger
from openai import OpenAI, Stream
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

logger = get_logger()

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletion


class OpenAIChat:

    def __init__(self,
                 api_key: str = None,
                 base_url: str = None,
                 model: str = None,
                 **kwargs):
        """
        Initialize the OpenAIChat client.
        """
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

        self._model = model
        self._kwargs = kwargs

    def chat(self,
             messages: List[Dict[str, Any]],
             tools: List[Dict[str, Any]] = None,
             **kwargs) -> Dict[str, Any]:

        completion: ChatCompletion = self._client.chat.completions.create(
            messages=messages, model=self._model, tools=tools, **kwargs)

        res_d: Dict[str, Any] = dict(
            role='assistant',
            reasoning_content='',
            content=completion.choices[0].message.content,
            tool_calls=completion.choices[0].message.tool_calls if hasattr(
                completion.choices[0].message, 'tool_calls') else [],
            finish_reason=completion.choices[0].
            finish_reason,  # 'stop', 'tool_calls', 'length', None
            usage=completion.usage.to_dict(),
        )

        return res_d

    def chat_stream(self,
                    messages: List[Dict[str, Any]],
                    tools: List[Dict[str, Any]] = None,
                    **kwargs):
        """
        Get chat response from OpenAI API using streaming.

        messages:
            A list of dictionaries representing the chat messages.
            Each dictionary should have 'role' (e.g., 'user', 'assistant') and 'content'.
            Fully compatible with OpenAI's chat completion API.
            [
                {
                "role": str,                # Required, one of 'user', 'assistant', 'system', 'tool'
                "content": Optional[str],   # Optional, required if role is 'user' or 'assistant'
                "name": Optional[str],      # Optional, required if role is 'tool'
                "tool_calls": Optional[List[Dict]],     # Optional, required if role is 'tool'
                "tool_call_id": Optional[str],          # Optional, required if role is 'tool'
                "function_call": Optional[Dict],        # Deprecated, use 'tool_calls' instead
                }
            ]

        tools:
            A list of dictionaries representing the tools available for the chat.
            Each dictionary should have 'type' (e.g., 'function') and 'function' (with 'name', 'description', and 'parameters').
            Fully compatible with OpenAI's chat completion API.
            [
                {
                    "type": "function",
                    "function": {
                        "name": str,
                        "description": str,
                        "parameters": {
                            "type": "object",
                            "properties": {...},
                            "required": [...]
                        }
                    }
                }
            ]

        """

        if 'stream' not in kwargs:
            kwargs['stream'] = True

        assert kwargs.get(
            'stream', True
        ), "Streaming must be enabled by setting 'stream=True' in kwargs."

        logger.info(f"Temperature: {kwargs.get('temperature', -1)}")

        completion: Stream = self._client.chat.completions.create(
            messages=messages,
            model=self._model,
            tools=tools,
            # Note: Gemini2.5-Pro does not support parallel_tool_calls
            # parallel_tool_calls=True,
            **kwargs)

        res_d: Dict[str, Any] = dict(
            role='assistant',
            reasoning_content='',
            content='',
            tool_calls=[],
            finish_reason=None,  # 'stop', 'tool_calls', 'length', None
            usage={
                'completion_tokens': 0,
                'prompt_tokens': 0,
                'total_tokens': 0
            },
        )

        for chunk in completion:
            if chunk is None:
                continue
            if not hasattr(chunk, 'choices') or not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            res_d['role'] = delta.role
            res_d['reasoning_content'] = delta.reasoning_content if hasattr(
                delta, 'reasoning_content') else ''
            res_d['content'] = delta.content
            res_d['tool_calls'] = delta.tool_calls if hasattr(
                delta, 'tool_calls') else []
            res_d['finish_reason'] = chunk.choices[0].finish_reason
            if hasattr(chunk, 'usage') and chunk.usage:
                res_d['usage'] = {
                    'completion_tokens': chunk.usage.completion_tokens,
                    'prompt_tokens': chunk.usage.prompt_tokens,
                    'total_tokens': chunk.usage.total_tokens
                }

            yield res_d

    @staticmethod
    def aggregate_stream_chunks(
            stream_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Aggregate the streaming chunks into a single response dictionary within current round of chat.

        stream_chunks:
            A list of dictionaries representing the streaming chunks.

        returns:
            A dictionary containing the aggregated response with keys:
            - 'role': The role of the assistant.
            - 'reasoning_content': Aggregated reasoning content.
            - 'content': Aggregated content.
            - 'tool_calls': List of tool calls made during the chat.
                Example: [ChoiceDeltaToolCall(index=None, id='', function=ChoiceDeltaToolCallFunction(arguments='{"location":"Hangzhou, China"}', name='get_current_weather'), type='function')]
            - 'finish_reason': The reason for finishing the chat (e.g., 'stop', 'tool_calls', 'length').
            - 'usage': A dictionary with token usage statistics.
        """
        res_d: Dict[str, Any] = dict(
            role='assistant',
            reasoning_content='',
            content='',
            tool_calls=[],
            finish_reason=None,  # 'stop', 'tool_calls', 'length', None
            usage={
                'completion_tokens': 0,
                'prompt_tokens': 0,
                'total_tokens': 0
            },
        )
        for chunk_d in stream_chunks:
            res_d['role'] = chunk_d.get('role')
            res_d['reasoning_content'] += chunk_d.get(
                'reasoning_content',
                '') if chunk_d.get('reasoning_content') is not None else ''
            res_d['content'] += chunk_d.get(
                'content', '') if chunk_d.get('content') is not None else ''

            if chunk_d.get('tool_calls') is not None:
                res_d['tool_calls'].extend(chunk_d.get('tool_calls', []))
            res_d['finish_reason'] = chunk_d.get('finish_reason',
                                                 res_d['finish_reason'])

            # Get the last usage information as final usage for current round (consider cache tokens)
            if chunk_d.get('usage') is not None:
                res_d['usage']['completion_tokens'] = chunk_d['usage'].get(
                    'completion_tokens', 0)
                res_d['usage']['prompt_tokens'] = chunk_d['usage'].get(
                    'prompt_tokens', 0)
                res_d['usage']['total_tokens'] = chunk_d['usage'].get(
                    'total_tokens', 0)

        return res_d

    @staticmethod
    def convert_message(role: Literal['assistant', 'tool'],
                        round_message: Dict[str, Any]) -> Dict[str, Any]:

        if role == 'assistant':
            res_msg: Dict[str, Any] = {
                'role': 'assistant',
                'content': round_message.get('content', ''),
                'tool_calls': [],
            }

            tmp_tool_calls = []
            for tool_call in round_message['tool_calls']:
                if isinstance(tool_call, ChoiceDeltaToolCall):
                    if not tool_call.id:
                        tool_call.id = f'tc_{uuid.uuid4().hex}'
                    tool_call = tool_call.model_dump(
                        include=['id', 'index', 'type', 'function'])
                else:
                    raise ValueError(
                        f'Unsupported tool call type: {type(tool_call)}. Expected ChoiceDeltaToolCall.'
                    )
                tmp_tool_calls.append(tool_call)

            res_msg['tool_calls'] = tmp_tool_calls

        elif role == 'tool':
            # TODO: tbd ...
            raise ValueError(
                '`tool message` is to be implemented in the future.')

        else:
            raise ValueError(
                f"Unsupported role: {role}. Supported roles are 'assistant' and 'tool' for now."
            )

        return res_msg

    def chat_stream_mt(self,
                       messages: List[Dict[str, Any]],
                       available_functions: Dict[str, Any],
                       tools: List[Dict[str, Any]] = None,
                       history: List[Dict[str, Any]] = None,
                       **kwargs):
        """
        Get chat response from OpenAI API using streaming for multi-turn chat.
        """

        if history is None:
            history = []

        # Add a system message if not present
        roles: List[str] = [msg['role'] for msg in messages]
        if 'system' not in roles:
            system_message: Dict[str, Any] = {
                'role': 'system',
                'content': 'You are a helpful assistant.'
            }
            messages.insert(0, system_message)

        assert len(
            messages
        ) >= 2, 'At least two messages are required: user and system'

        ## User Message
        history.extend(messages)

        while True:
            try:
                # Sliding Window for history messages
                # TODO: Deal with the history messages length limit
                messages = history[-5:]

                # Get the streaming results and aggregate them
                streaming_chunks: List[Dict[str, Any]] = []
                for chunk_d in self.chat_stream(messages, tools, **kwargs):
                    streaming_chunks.append(chunk_d)

                round_d: Dict[str, Any] = self.aggregate_stream_chunks(
                    streaming_chunks)
                yield round_d

                # Convert `round_d` to OpenAI's chat messages format
                ## Assistant Message
                if round_d['role'] == 'assistant':

                    assistant_message = self.convert_message(
                        role='assistant', round_message=round_d)
                    history.append(assistant_message)

                    # Execute tool calls and append the tool messages
                    # TODO: Execute tool calls async
                    for tool_call in assistant_message.get('tool_calls', []):
                        if tool_call['type'] == 'function':
                            function_name = tool_call['function']['name']
                            function_args = json.loads(
                                tool_call['function']['arguments'])
                            # Call the function and get the result
                            tool_call_result = available_functions[
                                function_name](**function_args)

                            # Construct a tool message with the result
                            # TODO: Check the `tool_call_id` is empty ?
                            tool_message = {
                                'role': 'tool',
                                'name': function_name,
                                'tool_call_id': tool_call['id'],
                                'content': tool_call_result,
                            }
                            history.append(tool_message)

                # If the response is complete, break the loop
                if round_d['finish_reason'] in [
                        'stop', 'tool_calls', 'length'
                ]:
                    break

            except Exception as e:
                logger.error(f'Error occurred: {e}')
                break

        # Note: must contain role=assistant(with tool_calls) and role=tool
        if history[-1]['role'] == 'tool':
            messages = history + [{
                'role':
                'user',
                'content':
                'Please output the tool calling results very briefly.'
            }]
            round_item: dict = self.aggregate_stream_chunks([
                chunk_item for chunk_item in self.chat_stream(
                    messages=messages, tools=tools, **kwargs)
            ])

            yield round_item
