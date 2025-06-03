import copy
import os
from abc import ABC
from functools import wraps
from typing import Dict, Iterator, List, Optional, Tuple, Union

import json
from modelscope_agent.callbacks import BaseCallback, CallbackManager
from modelscope_agent.tools.base import (TOOL_REGISTRY, BaseTool,
                                         OpenapiServiceProxy, ToolServiceProxy)
from modelscope_agent.utils.qwen_agent.base import (BaseChatModel,
                                                    get_chat_model)


def enable_run_callback(func):

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        callbacks = self.callback_manager
        if callbacks.callbacks:
            callbacks.on_run_start(*args, **kwargs)
        response = func(self, *args, **kwargs)
        name = self.name or self.__class__.__name__
        if not isinstance(response, str):
            response = enable_stream_callback(name, response, callbacks)
        else:
            response = enable_no_stream_callback(name, response, callbacks)
        return response

    return wrapper


def enable_stream_callback(name, rsp, callbacks):
    for s in rsp:
        yield s
    callbacks.on_run_end(name, rsp)


def enable_no_stream_callback(name, rsp, callbacks):
    callbacks.on_run_end(name, rsp)
    return rsp


class Agent(ABC):
    function_map: dict = {
    }  # used to record all the tools' instance, moving here to avoid `del` method crash.

    def __init__(self,
                 function_list: Union[Dict, List[Union[str, Dict]],
                                      None] = None,
                 llm: Optional[Union[Dict, BaseChatModel]] = None,
                 storage_path: Optional[str] = None,
                 name: Optional[str] = None,
                 description: Optional[str] = None,
                 instruction: Union[str, dict] = None,
                 use_tool_api: bool = False,
                 callbacks: list = None,
                 openapi_list: Optional[List[Union[str, Dict]]] = None,
                 **kwargs):
        """
        init tools/llm/instruction for one agent

        Args:
            function_list: A list of tools
                (1)When str: tool names
                (2)When Dict: tool cfg
            llm: The llm config of this agent
                (1) When Dict: set the config of llm as {'model': '', 'api_key': '', 'model_server': ''}
                (2) When BaseChatModel: llm is sent by another agent
            storage_path: If not specified otherwise, all data will be stored here in KV pairs by memory
            name: the name of agent
            description: the description of agent, which is used for multi_agent
            instruction: the system instruction of this agent
            use_tool_api: whether to use the tool service api, else to use the tool cls instance
            callbacks: the callbacks that could be used during different phase of agent loop
            openapi_list: the openapi list for remote calling only
            kwargs: other potential parameters
        """
        if isinstance(llm, Dict):
            self.llm_config = llm
            self.llm = get_chat_model(cfg=self.llm_config)
        else:
            self.llm = llm
        self.stream = kwargs.get('stream', True)
        self.use_tool_api = use_tool_api

        self.function_list = []
        self.function_map = {}
        if function_list:
            for function in function_list:
                self._register_tool(function, **kwargs)

        # this logic is for remote openapi calling only, by using this method apikey only be accessed by service.
        if openapi_list:
            for openapi_name in openapi_list:
                self._register_openapi_for_remote_calling(
                    openapi_name, **kwargs)

        self.storage_path = storage_path
        self.mem = None
        self.name = name
        self.description = description
        self.instruction = instruction
        self.uuid_str = kwargs.get('uuid_str', None)

        if isinstance(callbacks, BaseCallback):
            callbacks = [callbacks]
        self.callback_manager = CallbackManager(callbacks)

    @enable_run_callback
    def run(self, messages: List[Union[Dict, 'Message']], **kwargs
            ) -> Union[Iterator[List['Message']], Iterator[List[Dict]]]:
        from modelscope_agent.utils.qwen_agent.schema import CONTENT, ROLE, SYSTEM, ContentItem, Message
        """Return one response generator based on the received messages.

        This method performs a uniform type conversion for the inputted messages,
        and calls the _run method to generate a reply.

        Args:
            messages: A list of messages.

        Yields:
            The response generator.
        """
        messages = copy.deepcopy(messages)
        _return_message_type = 'dict'
        new_messages = []
        # Only return dict when all input messages are dict
        if not messages:
            _return_message_type = 'message'
        for msg in messages:
            if isinstance(msg, dict):
                new_messages.append(Message(**msg))
            else:
                new_messages.append(msg)
                _return_message_type = 'message'
        print(f'new_messages: {new_messages}')
        if self.instruction:
            if not new_messages or new_messages[0][ROLE] != SYSTEM:
                # Add the system instruction to the agent
                new_messages.insert(
                    0, Message(role=SYSTEM, content=self.instruction))
            else:
                # Already got system message in new_messages
                if isinstance(new_messages[0][CONTENT], str):
                    new_messages[0][
                        CONTENT] = self.instruction + '\n\n' + new_messages[0][
                            CONTENT]
                else:
                    assert isinstance(new_messages[0][CONTENT], list)
                    assert new_messages[0][CONTENT][0].text
                    new_messages[0][CONTENT] = [
                        ContentItem(text=self.instruction + '\n\n')
                    ] + new_messages[0][CONTENT]  # noqa

        for rsp in self._run(messages=new_messages, **kwargs):
            if _return_message_type == 'message':
                yield [Message(**x) if isinstance(x, dict) else x for x in rsp]
            else:
                yield [
                    x.model_dump() if not isinstance(x, dict) else x
                    for x in rsp
                ]

    # @abstractmethod
    def _run(self, messages: List, *args, **kwargs):
        from modelscope_agent.utils.qwen_agent.schema import FUNCTION

        stream = kwargs.get('stream', True)
        messages = copy.deepcopy(messages)
        num_llm_calls_available = 20
        response = []
        extra_generate_cfg = {'lang': 'zh'}
        if kwargs.get('seed') is not None:
            extra_generate_cfg['seed'] = kwargs['seed']
        while True and num_llm_calls_available > 0:
            num_llm_calls_available -= 1
            output_stream = self.llm.chat(
                messages=messages,
                functions=[
                    func.function for func in self.function_map.values()
                ],
                stream=stream,
                extra_generate_cfg=extra_generate_cfg)
            output = []
            for output in output_stream:
                if output:
                    yield response + output
            if output:
                response.extend(output)
                messages.extend(output)
                used_any_tool = False
                for out in output:
                    use_tool, tool_name, tool_args, _ = self._detect_tool(out)
                    if use_tool:
                        tool_result = self._call_tool(tool_name, tool_args,
                                                      **kwargs)
                        fn_msg = {
                            'role': FUNCTION,
                            'name': tool_name,
                            'content': tool_result,
                        }
                        messages.append(fn_msg)
                        response.append(fn_msg)
                        yield response
                        used_any_tool = True
                if not used_any_tool:
                    break
        yield response

    def _call_tool(self,
                   tool_name: str,
                   tool_args: Union[str, dict] = '{}',
                   **kwargs) -> Union[str, List]:
        """The interface of calling tools for the agent.

        Args:
            tool_name: The name of one tool.
            tool_args: Model generated or user given tool parameters.

        Returns:
            The output of tools.
        """
        if tool_name not in self.function_map:
            return f'Tool {tool_name} does not exists.'
        tool = self.function_map[tool_name]
        try:
            tool_result = tool.call(tool_args, **kwargs)
        except Exception as ex:
            import traceback
            exception_type = type(ex).__name__
            exception_message = str(ex)
            traceback_info = ''.join(traceback.format_tb(ex.__traceback__))
            error_message = f'An error occurred when calling tool `{tool_name}`:\n' \
                            f'{exception_type}: {exception_message}\n' \
                            f'Traceback:\n{traceback_info}'
            print(error_message)
            return error_message

        if isinstance(tool_result, str):
            return tool_result
        elif isinstance(tool_result, list) and all(
                isinstance(item, ContentItem) for item in tool_result):
            return tool_result  # multimodal tool results
        else:
            return json.dumps(tool_result, ensure_ascii=False, indent=4)

    def _register_openapi_for_remote_calling(self, openapi: Union[str, Dict],
                                             **kwargs):
        """
        Instantiate the openapi the will running remote on
        Args:
            openapi: the remote openapi schema name or the json schema itself
            **kwargs:

        Returns:

        """
        openapi_instance = OpenapiServiceProxy(openapi, **kwargs)
        tool_names = openapi_instance.tool_names
        for tool_name in tool_names:
            openapi_instance_for_specific_tool = copy.deepcopy(
                openapi_instance)
            openapi_instance_for_specific_tool.name = tool_name
            function_plain_text = openapi_instance_for_specific_tool.parser_function_by_tool_name(
                tool_name)
            openapi_instance_for_specific_tool.function_plain_text = function_plain_text
            self.function_map[tool_name] = openapi_instance_for_specific_tool

    def _register_tool(self,
                       tool: Union[str, Dict],
                       tenant_id: str = 'default',
                       **kwargs):
        """
        Instantiate the tool for the agent

        Args:
            tool: the tool should be either in a string format with name as value
            and in a dict format, example
            (1) When str: amap_weather
            (2) When dict: {'amap_weather': {'token': 'xxx'}}
            tenant_id: the tenant_id of the tool is now  for code interpreter that need to keep track of the tenant
        Returns:

        """
        tool_name = tool
        tool_cfg = {}
        if isinstance(tool, dict) and 'mcpServers' in tool:
            from modelscope_agent.tools.mcp import MCPManager
            tools = MCPManager(tool).get_tools()
            for tool in tools:
                tool_name = tool.name
                if tool_name not in self.function_map:
                    self.function_map[tool_name] = tool
            return
        if isinstance(tool, dict):
            tool_name = next(iter(tool))
            tool_cfg = tool[tool_name]
        if tool_name not in TOOL_REGISTRY and not self.use_tool_api:
            raise NotImplementedError
        if tool_name not in self.function_list:
            self.function_list.append(tool_name)

            try:
                tool_class_with_tenant = TOOL_REGISTRY[tool_name]

                # adapt the TOOL_REGISTRY[tool_name] to origin tool class
                if (isinstance(tool_class_with_tenant, type) and issubclass(
                        tool_class_with_tenant, BaseTool)) or isinstance(
                            tool_class_with_tenant, BaseTool):
                    tool_class_with_tenant = {
                        'class': TOOL_REGISTRY[tool_name]
                    }
                    TOOL_REGISTRY[tool_name] = tool_class_with_tenant

            except KeyError as e:
                print(e)
                if not self.use_tool_api:
                    raise KeyError(
                        f'Tool {tool_name} is not registered in TOOL_REGISTRY, please register it first.'
                    )
                tool_class_with_tenant = {'class': ToolServiceProxy}

            # check if the tenant_id of tool instance or tool service are exists
            # TODO: change from use_tool_api=True to False, to get the tenant_id of the tool changes to

            if tenant_id in tool_class_with_tenant and self.use_tool_api:
                return

            try:
                if self.use_tool_api:
                    # get service proxy as tool instance, call method will call remote tool service
                    tool_instance = ToolServiceProxy(tool_name, tool_cfg,
                                                     tenant_id, **kwargs)

                    # if the tool name is running in studio, remove the studio prefix from tool name
                    # TODO: it might cause duplicated name from different studio
                    in_ms_studio = os.getenv('MODELSCOPE_ENVIRONMENT', 'none')
                    if in_ms_studio == 'studio':
                        tool_name = tool_name.split('/')[-1]

                else:
                    # instantiation tool class as tool instance
                    tool_instance = TOOL_REGISTRY[tool_name]['class'](tool_cfg)

                self.function_map[tool_name] = tool_instance

            except TypeError:
                # When using OpenAPI, tool_class is already an instantiated object, not a corresponding class
                self.function_map[tool_name] = TOOL_REGISTRY[tool_name][
                    'class']
            except Exception as e:
                raise RuntimeError(e)

            # store the instance of tenant to tool registry on this tool
            tool_class_with_tenant[tenant_id] = self.function_map[tool_name]

    def _detect_tool(self, message: Union[str,
                                          dict]) -> Tuple[bool, list, str]:
        """
        A built-in tool call detection for func_call format

        Args:
            message: one message
                (1) When dict: Determine whether to call the tool through the function call format.
                (2) When str: The tool needs to be parsed from the string, and at this point, the agent subclass needs
                              to implement a custom _detect_tool function.

        Returns:
            - bool: need to call tool or not
            - list: tool list
            - str: text replies except for tool calls
        """

        func_name = None
        func_args = None

        if message.function_call:
            func_call = message.function_call
            func_name = func_call.name
            func_args = func_call.arguments
        text = message.content
        if not text:
            text = ''

        return (func_name is not None), func_name, func_args, text

    def _parse_image_url(self, image_url: List[Union[str, Dict]],
                         messages: List[Dict]) -> List[Dict]:

        assert len(messages) > 0

        if isinstance(image_url[0], str):
            image_url = [{'url': url} for url in image_url]

        images = [{
            'type': 'image_url',
            'image_url': image
        } for image in image_url]

        origin_message: str = messages[-1]['content']
        parsed_message = [{'type': 'text', 'text': origin_message}, *images]
        messages[-1]['content'] = parsed_message
        return messages

    # del the tools as well while del the agent
    def __del__(self):
        try:
            for tool_instance in self.function_map.items():
                del tool_instance
        except Exception:
            pass
