import copy
import os
from abc import ABC, abstractmethod
from functools import wraps
from typing import Dict, Iterator, List, Optional, Tuple, Union

from modelscope_agent.callbacks import BaseCallback, CallbackManager
from modelscope_agent.llm import get_chat_model
from modelscope_agent.llm.base import BaseChatModel
from modelscope_agent.tools.base import (TOOL_REGISTRY, BaseTool,
                                         OpenapiServiceProxy, ToolServiceProxy)
from modelscope_agent.utils.utils import has_chinese_chars


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
                 function_list: Optional[List[Union[str, Dict]]] = None,
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
            self.llm = get_chat_model(**self.llm_config)
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
    def run(self, *args, **kwargs) -> Union[str, Iterator[str]]:
        if 'lang' not in kwargs:
            if has_chinese_chars([args, kwargs]):
                kwargs['lang'] = 'zh'
            else:
                kwargs['lang'] = 'en'
        result = self._run(*args, **kwargs)
        return result

    @abstractmethod
    def _run(self, *args, **kwargs) -> Union[str, Iterator[str]]:
        raise NotImplementedError

    def _call_llm(self,
                  prompt: Optional[str] = None,
                  messages: Optional[List[Dict]] = None,
                  stop: Optional[List[str]] = None,
                  **kwargs) -> Union[str, Iterator[str]]:
        return self.llm.chat(
            prompt=prompt,
            messages=messages,
            stop=stop,
            stream=self.stream,
            **kwargs)

    def _call_tool(self, tool_list: list, **kwargs):
        """
        Use when calling tools in bot()

        """
        # version < 0.6.6 only one tool is in the tool_list
        tool_name = tool_list[0]['name']
        tool_args = tool_list[0]['arguments']
        # for openapi tool only
        kwargs['tool_name'] = tool_name
        self.callback_manager.on_tool_start(tool_name, tool_args)
        try:
            result = self.function_map[tool_name].call(tool_args, **kwargs)
        except BaseException as e:
            import traceback
            print(
                f'The error is {e}, and the traceback is {traceback.format_exc()}'
            )
            result = f'Tool api {tool_name} failed to call. Args: {tool_args}.'
            result += f'Details: {str(e)[:200]}'
        self.callback_manager.on_tool_end(tool_name, result)
        return result

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
        tool_name = None
        tool_cfg = {}

        # # Check if the tool is a dictionary and extract the tool name and configuration from it.
        if isinstance(tool, dict):
            try:
                tool_name = next(iter(tool))
                tool_cfg = tool[tool_name]
            except StopIteration:
                # If the tool is an empty dictionary, proceed to register the next tool.
                print(
                    'Empty tool dictionary provided, skipping the registration of the current tool'
                )
                return

        # If the tool is a string, assign it directly to tool_name.
        elif isinstance(tool, str):
            tool_name = tool

        # If the tool_name is empty, skip the registration of the current tool.
        if not tool_name:
            print(
                'No tool name provided, skipping the registration of the current tool'
            )
            return

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

        func_calls = []
        assert isinstance(message, dict)
        # deprecating
        if 'function_call' in message and message['function_call']:
            func_call = message['function_call']
            func_calls.append(func_call)

        # Follow OpenAI API, allow multi func_calls
        if 'tool_calls' in message and message['tool_calls']:
            for item in message['tool_calls']:
                func_call = item['function']
                func_calls.append(func_call)

        text = message.get('content', '')

        return (len(func_calls) > 0), func_calls, text

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
