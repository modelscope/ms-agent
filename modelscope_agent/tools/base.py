import os
import time
import traceback
from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Dict, List, Optional, Union

import json
import json5
import requests
from modelscope_agent.constants import (BASE64_FILES,
                                        DEFAULT_CODE_INTERPRETER_DIR,
                                        DEFAULT_TOOL_MANAGER_SERVICE_URL,
                                        LOCAL_FILE_PATHS,
                                        MODELSCOPE_AGENT_TOKEN_HEADER_NAME)
from modelscope_agent.tools.utils.openapi_utils import (dot_to_dict,
                                                        execute_api_call,
                                                        get_parameter_value,
                                                        openapi_schema_convert)
from modelscope_agent.utils.base64_utils import decode_base64_to_files
from modelscope_agent.utils.logger import agent_logger as logger
from modelscope_agent.utils.utils import has_chinese_chars

WORK_DIR = os.getenv('CODE_INTERPRETER_WORK_DIR', DEFAULT_CODE_INTERPRETER_DIR)

# ast?
register_map = {
    'amap_weather':
    'AMAPWeather',
    'storage':
    'Storage',
    'web_search':
    'WebSearch',
    'image_gen':
    'TextToImageTool',
    'image_gen_lite':
    'TextToImageLiteTool',
    'image_enhancement':
    'ImageEnhancement',
    'qwen_vl':
    'QWenVL',
    'style_repaint':
    'StyleRepaint',
    'paraformer_asr':
    'ParaformerAsrTool',
    'sambert_tts':
    'SambertTtsTool',
    'wordart_texture_generation':
    'WordArtTexture',
    'detect_for_google_translate':
    'DetectForGoogleTranslate',
    'languages_for_google_translate':
    'LanguagesForGoogleTranslate',
    'translate_for_google_translate':
    'TranslateForGoogleTranslate',
    'get_data_fact_for_numbers':
    'GetDataFactForNumbers',
    'get_math_fact_for_numbers':
    'GetMathFactForNumbers',
    'get_year_fact_for_numbers':
    'GetYearFactForNumbers',
    'model_scope_text_ie':
    'TextinfoextracttoolForAlphaUmi',
    'search_torrents_for_movie_tv_music_search_and_download':
    'SearchTorrentsForMovieTvMusicSearchAndDownload',
    'get_monthly_top_100_music_torrents_for_movie_tv_music_search_and_download':
    'GetMonthlyTop100MusicTorrentsForMovieTvMusicSearchAndDownload',
    'get_monthly_top_100_games_torrents_for_movie_tv_music_search_and_download':
    'GetMonthlyTop100GamesTorrentsForMovieTvMusicSearchAndDownload',
    'get_monthly_top_100_tv_shows_torrents_for_movie_tv_music_search_and_download':
    'GetMonthlyTop100TvShowsTorrentsForMovieTvMusicSearchAndDownload',
    'get_monthly_top_100_movies_torrents_torrents_for_movie_tv_music_search_and_download':
    'GetMonthlyTop100MoviesTorrentsTorrentsForMovieTvMusicSearchAndDownload',
    'listquotes_for_current_exchange':
    'ListquotesForCurrentExchange',
    'exchange_for_current_exchange':
    'exchange_for_current_exchange',
    'similarity_search':
    'SimilaritySearch',
    'hf-tool':
    'HFTool',
    'RenewInstance':
    'AliyunRenewInstanceTool',
    'web_browser':
    'WebBrowser',
    'text-address':
    'TextAddressTool',
    'image-chat':
    'ImageChatTool',
    'text-ner':
    'TextNerTool',
    'speech-generation':
    'TexttoSpeechTool',
    'video-generation':
    'TextToVideoTool',
    'text-ie':
    'TextInfoExtractTool',
    'openapi_plugin':
    'OpenAPIPluginTool',
    'langchain_tool':
    'LangchainTool',
    'code_interpreter':
    'CodeInterpreter',
    'doc_parser':
    'DocParser'
}


def import_from_register(key):
    value = register_map[key]
    exec(f'from . import {value}')


class ToolRegistry(dict):

    def _import_key(self, key):
        try:
            import_from_register(key)
        except Exception as e:
            print(f'import {key} failed, details: {e}')

    def __getitem__(self, key):
        if key not in self.keys():
            self._import_key(key)
        return super().__getitem__(key)

    def __contains__(self, key):
        if key not in self.keys():
            self._import_key(key)
        return super().__contains__(key)


TOOL_REGISTRY = ToolRegistry()


def register_tool(name):

    def decorator(cls):
        TOOL_REGISTRY[name] = {'class': cls}
        return cls

    return decorator


class BaseTool(ABC):
    name: str
    description: str
    parameters: List[Dict]

    def __init__(self, cfg: Optional[Dict] = {}):
        """
        :param schema: Format of tools, default to oai format, in case there is a need for other formats
        """
        self.cfg = cfg.get(self.name, {})

        self.schema = self.cfg.get('schema', 'oai')
        self.function = self._build_function()
        self.function_plain_text = self._parser_function()

    @abstractmethod
    def call(self, params: str, **kwargs):
        """
        The interface for calling tools

        :param params: the parameters of func_call
        :param kwargs: additional parameters for calling tools
        :return: the result returned by the tool, implemented in the subclass
        """
        raise NotImplementedError

    def _verify_args(self, params: str) -> Union[str, dict]:
        """
        Verify the parameters of the function call

        :param params: the parameters of func_call
        :return: the str params or the legal dict params
        """
        try:
            params_json = json5.loads(params)
        except Exception as e:
            print(e)
            params = params.replace('\r', '\\r').replace('\n', '\\n')
            params_json = json5.loads(params)

        for param in self.parameters:
            if 'required' in param and param['required']:
                if param['name'] not in params_json:
                    raise ValueError(f'param `{param["name"]}` is required')
        return params_json

    def _parse_files_input(self, *args, **kwargs):
        # convert image_file_paths from string to list
        if BASE64_FILES in kwargs:
            # if image_file_paths is base64
            base64_files = kwargs.pop(BASE64_FILES)
            local_file_paths = decode_base64_to_files(base64_files, WORK_DIR)
            kwargs[LOCAL_FILE_PATHS] = local_file_paths
        return kwargs

    def _build_function(self):
        """
        The dict format after applying the template to the function, such as oai format

        """
        if self.schema == 'oai':
            function = {
                'name': self.name,
                'description': self.description,
                'parameters': {
                    'type': 'object',
                    'properties': {},
                    'required': [],
                },
            }
            for para in self.parameters:
                function_details = {
                    'type':
                    para['type'] if 'type' in para else para['schema']['type'],
                    'description':
                    para['description']
                }
                if 'enum' in para and para['enum'] not in ['', []]:
                    function_details['enum'] = para['enum']
                function['parameters']['properties'][
                    para['name']] = function_details
                if 'required' in para and para['required']:
                    function['parameters']['required'].append(para['name'])
        else:
            function = {
                'name': self.name,
                'description': self.description,
                'parameters': self.parameters
            }

        return function

    def _parser_function(self):
        """
        Text description of function

        """
        tool_desc_template = {
            'zh':
            '{name}: {name} API。{description} 输入参数: {parameters} Format the arguments as a JSON object.',
            'en':
            '{name}: {name} API. {description} Parameters: {parameters} Format the arguments as a JSON object.'
        }

        if has_chinese_chars(self.function['description']):
            tool_desc = tool_desc_template['zh']
        else:
            tool_desc = tool_desc_template['en']

        return tool_desc.format(
            name=self.function['name'],
            description=self.function['description'],
            parameters=json.dumps(
                self.function['parameters'], ensure_ascii=False),
        )

    @staticmethod
    def parser_function(tools: List[dict]):
        """
        Tool parser function with input
        Args:
            tools: the list of tools, each tool includes key of name, description, parameters

        Returns:

        """

        tool_desc_template = {
            'zh':
            '{name}: {name} API。{description} 输入参数: {parameters} Format the arguments as a JSON object.',
            'en':
            '{name}: {name} API. {description} Parameters: {parameters} Format the arguments as a JSON object.'
        }

        def has_chinese_chars_in_tools(_tools):
            for _tool in _tools:
                _func_info = _tool.get('function', {})
                if 'description' in _func_info:
                    if has_chinese_chars(_func_info['description']):
                        return True

            return False

        if has_chinese_chars_in_tools(tools):
            tool_desc = tool_desc_template['zh']
        else:
            tool_desc = tool_desc_template['en']

        tools_text = []
        for tool in tools:
            func_info = tool.get('function', {})
            if func_info == {}:
                continue
            name = func_info.get('name', '')
            description = func_info.get('description', '')
            tool = tool_desc.format(
                name=name,
                description=description,
                parameters=json.dumps(
                    func_info['parameters'], ensure_ascii=False),
            )
            tools_text.append(tool)
        tools_text = '\n\n'.join(tools_text)
        return tools_text


class ToolServiceProxy(BaseTool):

    def __init__(self,
                 tool_name: str,
                 tool_cfg: dict,
                 tenant_id: str = 'default',
                 tool_service_manager_url: str = os.getenv(
                     'TOOL_MANAGER_SERVICE_URL',
                     DEFAULT_TOOL_MANAGER_SERVICE_URL),
                 user_token: str = None,
                 **kwargs):
        """
        Tool service proxy class
        Args:
            tool_name: tool name might be the name of tool or the address of tool artifacts
            tool_cfg: the configuration of tool
            tenant_id: the tenant id that the tool belongs to, defalut to 'default'
            tool_service_manager_url: the url of tool service manager, default to 'http://localhost:31511'
            user_token: used to pass to the tool service manager to authenticate the user
        """

        self.tool_service_manager_url = tool_service_manager_url
        self.user_token = user_token
        self.tool_name = tool_name
        self.tool_cfg = tool_cfg
        self.tenant_id = tenant_id
        self._register_tool()

        if not self.tool_name:
            print(
                "Skipping tool registration and status check because 'tool_name' is not defined or empty."
            )
            return  # When tool_name is an empty string, skip registration and status check.

        max_retry = 10
        while max_retry > 0:
            status = self._check_tool_status()
            if status == 'running':
                break
            time.sleep(1)
            max_retry -= 1
        if max_retry == 0:
            raise RuntimeError(
                'Tool node not start up successfully, please double check your docker environment'
            )

        tool_info = self._get_tool_info()
        self.name = tool_info['name']
        self.description = tool_info['description']
        self.parameters = tool_info['parameters']
        super().__init__({self.name: self.tool_cfg})

    @staticmethod
    def parse_service_response(response):
        try:
            # Assuming the response is a JSON string
            response_data = response.json()

            # Extract the 'output' field from the response
            output_data = response_data.get('output', {})
            return output_data
        except json.JSONDecodeError:
            # Handle the case where response is not JSON or cannot be decoded
            return None

    def _register_tool(self):
        try:
            # Check if `tool_name` is defined and not empty.
            if not self.tool_name:
                print(
                    "Skipping tool registration because 'tool_name' is not defined or empty."
                )
                return  # Return directly, skipping registration.

            service_token = os.getenv('TOOL_MANAGER_AUTH', '')
            headers = {
                'Content-Type': 'application/json',
                MODELSCOPE_AGENT_TOKEN_HEADER_NAME: self.user_token,
                'authorization': service_token
            }
            print(f'reach here create {headers}')
            response = requests.post(
                f'{self.tool_service_manager_url}/create_tool_service',
                json={
                    'tool_name': self.tool_name,
                    'tenant_id': self.tenant_id,
                    'tool_cfg': self.tool_cfg
                },
                headers=headers)
            response.raise_for_status()
            result = ToolServiceProxy.parse_service_response(response)
            if 'status' not in result:
                raise Exception(
                    'Failed to register tool, the tool service might be done, please use local version'
                )
            if result['status'] not in ['pending', 'running']:
                raise Exception(
                    'Failed to register tool, the tool service might be done, please use local version.'
                )
        except Exception as e:
            raise RuntimeError(
                f'Get error during registering tool from tool manager service with detail {e}.'
            )

    def _check_tool_status(self):
        try:
            service_token = os.getenv('TOOL_MANAGER_AUTH', '')
            headers = {
                'Content-Type': 'application/json',
                MODELSCOPE_AGENT_TOKEN_HEADER_NAME: self.user_token,
                'authorization': service_token
            }
            response = requests.get(
                f'{self.tool_service_manager_url}/check_tool_service_status',
                params={
                    'tool_name': self.tool_name,
                    'tenant_id': self.tenant_id,
                },
                headers=headers)
            response.raise_for_status()
            result = ToolServiceProxy.parse_service_response(response)
            if 'status' not in result:
                raise Exception(
                    'Failed to register tool, the tool service might be done, please use local version'
                )
            return result['status']
        except Exception as e:
            raise RuntimeError(
                f'Get error during checking status from tool manager service: {self.tool_name} {self.tenant_id}. '
                f'detail {e}, {traceback.format_exc()}')

    def _get_tool_info(self):
        try:
            service_token = os.getenv('TOOL_MANAGER_AUTH', '')
            headers = {
                'Content-Type': 'application/json',
                MODELSCOPE_AGENT_TOKEN_HEADER_NAME: self.user_token,
                'authorization': service_token
            }
            logger.query_info(message=f'tool_info requests header {headers}')
            response = requests.post(
                f'{self.tool_service_manager_url}/tool_info',
                json={
                    'tool_name': self.tool_name,
                    'tenant_id': self.tenant_id
                },
                headers=headers)
            response.raise_for_status()
            tool_info = ToolServiceProxy.parse_service_response(response)
            # check required params
            name = tool_info['name']  # noqa
            description = tool_info['description']  # noqa
            parameters = tool_info['parameters']  # noqa
            return tool_info
        except Exception as e:
            raise RuntimeError(
                f'Get error during getting tool info from tool manager, {self.tool_name} {self.tenant_id}. detail {e}, '
                f'{traceback.format_exc()}')

    def call(self, params: str, **kwargs):
        # ms_token
        kwargs['is_remote'] = True
        self.user_token = kwargs.get('user_token', self.user_token)
        service_token = os.getenv('TOOL_MANAGER_AUTH', '')
        headers = {
            'Content-Type': 'application/json',
            MODELSCOPE_AGENT_TOKEN_HEADER_NAME: self.user_token,
            'authorization': service_token
        }
        logger.query_info(message=f'calling tool header {headers}')
        kwargs['is_remote'] = True
        try:
            # visit tool node to call tool
            response = requests.post(
                f'{self.tool_service_manager_url}/execute_tool',
                json={
                    'tool_name': self.tool_name,
                    'tenant_id': self.tenant_id,
                    'params': params,
                    'kwargs': kwargs
                },
                headers=headers)
            logger.query_info(
                message=f'calling tool message {response.json()}')

            response.raise_for_status()
            return ToolServiceProxy.parse_service_response(response)
        except Exception as e:
            raise RuntimeError(
                f'Get error during executing tool from tool manager service with detail {e}'
            )


class OpenapiServiceProxy(BaseTool):

    def __init__(self,
                 openapi: Union[str, Dict],
                 openapi_service_manager_url: str = os.getenv(
                     'TOOL_MANAGER_SERVICE_URL',
                     DEFAULT_TOOL_MANAGER_SERVICE_URL),
                 user_token: str = None,
                 is_remote: bool = True,
                 **kwargs):
        """
        Openapi service proxy class
        Args:
            openapi: The name of  openapi schema store at tool manager or the openapi schema itself
            openapi_service_manager_url: The url of openapi service manager, default to 'http://localhost:31511'
                                        same as tool service manager
            user_token: used to pass to the tool service manager to authenticate the user
        """
        self.is_remote = is_remote
        self.openapi_service_manager_url = openapi_service_manager_url
        self.user_token = user_token
        if isinstance(openapi, str) and is_remote:
            self.openapi_remote_name = openapi
            openapi_schema = self._get_openapi_schema()
        else:
            openapi_schema = openapi
        openapi_formatted_schema = openapi_schema_convert(openapi_schema)
        self.api_info_dict = {}
        for item in openapi_formatted_schema:
            self.api_info_dict[openapi_formatted_schema[item]
                               ['name']] = openapi_formatted_schema[item]
        self.tool_names = list(self.api_info_dict.keys())

    def parser_function_by_tool_name(self, tool_name: str):
        tool_desc_template = {
            'zh':
            '{name}: {name} API。{description} 输入参数: {parameters} Format the arguments as a JSON object.',
            'en':
            '{name}: {name} API. {description} Parameters: {parameters} Format the arguments as a JSON object.'
        }
        function = self.api_info_dict[tool_name]
        if has_chinese_chars(function['description']):
            tool_desc = tool_desc_template['zh']
        else:
            tool_desc = tool_desc_template['en']

        parameters = deepcopy(function.get('parameters', []))
        for parameter in parameters:
            if 'in' in parameter:
                parameter.pop('in')

        return tool_desc.format(
            name=function['name'],
            description=function['description'],
            parameters=json.dumps(parameters, ensure_ascii=False),
        )

    @staticmethod
    def parse_service_response(response):
        try:
            # Assuming the response is a JSON string
            if not isinstance(response, dict):
                response_data = response.json()
            else:
                response_data = response
            # Extract the 'output' field from the response
            if 'output' in response_data:
                output_data = response_data['output']
            else:
                output_data = response_data

            return output_data
        except json.JSONDecodeError:
            # Handle the case where response is not JSON or cannot be decoded
            return None

    def _get_openapi_schema(self):
        try:
            service_token = os.getenv('TOOL_MANAGER_AUTH', '')
            headers = {
                'Content-Type': 'application/json',
                MODELSCOPE_AGENT_TOKEN_HEADER_NAME: self.user_token,
                'authorization': service_token
            }
            logger.query_info(message=f'tool_info requests header {headers}')
            response = requests.post(
                f'{self.openapi_service_manager_url}/openapi_schema',
                json={'openapi_name': self.openapi_remote_name},
                headers=headers)
            response.raise_for_status()
            return OpenapiServiceProxy.parse_service_response(response)
        except Exception as e:
            raise RuntimeError(
                f'Get error during getting tool info from tool manager service with detail {e}'
            )

    def _verify_args(self, params: str, api_info) -> Union[str, dict]:
        """
        Verify the parameters of the function call

        :param params: the parameters of func_call
        :param api_info: the api info of the tool
        :return: the str params or the legal dict params
        """
        try:
            params_json = json5.loads(params)
        except Exception as e:
            print(e)
            params = params.replace('\r', '\\r').replace('\n', '\\n')
            params_json = json5.loads(params)

        for param in api_info['parameters']:
            if 'required' in param and param['required']:
                if param['name'] not in params_json:
                    current = {}
                    current_test = deepcopy(params_json)
                    parts = param['name'].split('.')
                    for i, part in enumerate(parts):
                        if part not in current:
                            current[part] = {}
                        current = current[part]
                        if part not in current_test:
                            raise ValueError(
                                f'param `{".".join(parts[:i])}` is required')
                        current_test = current_test[part]
        return params_json

    def _parse_credentials(self, credentials: dict, headers=None):
        """

        Args:
            credentials: includes auth_type, api_key_header, api_key_value, api_key_header_prefix
                usage:
                {
                    "auth_type": "api_key",
                    "api_key_header": "Authorization",
                    "api_key_value": "xxx",
                    "api_key_header_prefix": "Bearer"
                }
            headers:

        Returns:

        """
        if not headers:
            headers = {}

        if not credentials:
            return headers

        if 'auth_type' not in credentials:
            raise KeyError('Missing auth_type')
        if credentials['auth_type'] == 'api_key':
            api_key_header = 'api_key'

            if 'api_key_header' in credentials:
                api_key_header = credentials['api_key_header']

            if 'api_key_value' not in credentials:
                raise KeyError('Missing api_key_value')
            elif not isinstance(credentials['api_key_value'], str):
                raise KeyError('api_key_value must be a string')

            if 'api_key_header_prefix' in credentials:
                api_key_header_prefix = credentials['api_key_header_prefix']
                if api_key_header_prefix == 'basic' and credentials[
                        'api_key_value']:
                    credentials[
                        'api_key_value'] = f'Basic {credentials["api_key_value"]}'
                elif api_key_header_prefix == 'bearer' and credentials[
                        'api_key_value']:
                    credentials[
                        'api_key_value'] = f'Bearer {credentials["api_key_value"]}'
                elif api_key_header_prefix == 'custom':
                    pass

            headers[api_key_header] = credentials['api_key_value']
        return headers

    def call(self, params: str, **kwargs):
        # ms_token
        tool_name = kwargs.get('tool_name', '')
        if tool_name not in self.api_info_dict:
            raise ValueError(
                f'tool name {tool_name} not in the list of tools {self.tool_names}'
            )
        api_info = self.api_info_dict[tool_name]
        self.user_token = kwargs.get('user_token', self.user_token)
        service_token = os.getenv('TOOL_MANAGER_AUTH', '')
        headers = {
            'Content-Type': 'application/json',
            MODELSCOPE_AGENT_TOKEN_HEADER_NAME: self.user_token,
            'authorization': service_token
        }
        logger.query_info(message=f'calling tool header {headers}')

        params = self._verify_args(params, api_info)

        url = api_info['url']
        method = api_info['method']
        header = api_info['header']
        path_params = {}
        query_params = {}
        cookies = {}
        data = {}
        for parameter in api_info.get('parameters', []):
            value = get_parameter_value(parameter, params)
            if parameter['in'] == 'path':
                path_params[parameter['name']] = value

            elif parameter['in'] == 'query':
                query_params[parameter['name']] = value

            elif parameter['in'] == 'cookie':
                cookies[parameter['name']] = value

            elif parameter['in'] == 'header':
                header[parameter['name']] = value
            else:
                if '.' in parameter['name']:
                    result = dot_to_dict(parameter['name'], value)
                    data.update(result)
                else:
                    data[parameter['name'].split('.')[0]] = value

        for name, value in path_params.items():
            url = url.replace(f'{{{name}}}', f'{value}')
        credentials = kwargs.get('credentials', {})
        header = self._parse_credentials(credentials, header)

        try:
            # visit tool node to call tool
            if self.is_remote and not kwargs.get('is_test', False):
                response = requests.post(
                    f'{self.openapi_service_manager_url}/execute_openapi',
                    json={
                        'openapi_name': self.openapi_remote_name,
                        'url': url,
                        'params': query_params,
                        'headers': header,
                        'method': method,
                        'cookies': cookies,
                        'data': data
                    },
                    headers=headers)
                logger.query_info(
                    message=f'calling tool message {response.json()}')

                response.raise_for_status()
            else:
                response = execute_api_call(url, method, header, query_params,
                                            data, cookies)
            return OpenapiServiceProxy.parse_service_response(response)
        except Exception as e:
            raise RuntimeError(
                f'Get error during executing tool from tool manager service with detail {e}'
            )


if __name__ == '__main__':
    import copy

    test_str = 'openapi_plugin'
    openapi_instance = OpenapiServiceProxy(openapi=test_str)
    schema_info = copy.deepcopy(openapi_instance.api_info_dict)
    for item in schema_info:
        schema_info[item].pop('is_active')
        schema_info[item].pop('is_remote_tool')
        schema_info[item].pop('details')

    print(schema_info)
    print(openapi_instance.api_info_dict)
    function_map = {}
    tool_names = openapi_instance.tool_names
    for tool_name in tool_names:
        openapi_instance_for_specific_tool = copy.deepcopy(openapi_instance)
        openapi_instance_for_specific_tool.name = tool_name
        function_plain_text = openapi_instance_for_specific_tool.parser_function_by_tool_name(
            tool_name)
        openapi_instance_for_specific_tool.function_plain_text = function_plain_text
        function_map[tool_name] = openapi_instance_for_specific_tool

    print(
        openapi_instance.call(
            '{"username":"test"}', tool_name='getTodos', user_token='test'))
