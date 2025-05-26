import os
import random
import re
import time
import traceback
from functools import wraps
from werkzeug.utils import secure_filename

import json
import requests
import yaml
from builder_core import (CONFIG_UPDATED_STEP, LOGO_UPDATED_STEP,
                          beauty_output, gen_response_and_process)
from config_utils import (DEFAULT_AGENT_DIR, Config, get_ci_dir,
                          get_user_ci_dir, get_user_dir,
                          is_valid_plugin_configuration, parse_configuration,
                          save_builder_configuration,
                          save_plugin_configuration)
from flask import (Flask, Response, g, jsonify, make_response, request,
                   send_from_directory)
from modelscope_agent.constants import (MODELSCOPE_AGENT_TOKEN_HEADER_NAME,
                                        ApiNames)
from modelscope_agent.schemas import Message
from modelscope_agent.tools.base import OpenapiServiceProxy
from publish_util import (pop_user_info_from_config, prepare_agent_zip,
                          reload_agent_dir)
from server_logging import logger, request_id_var
from server_utils import (IMPORT_ZIP_TEMP_DIR, STATIC_FOLDER, SessionManager,
                          unzip_with_folder)

app = Flask(__name__, static_folder=STATIC_FOLDER, static_url_path='/static')

app.session_manager = SessionManager()


def get_auth_token():
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        return auth_header[7:]  # Slice off the 'Bearer ' prefix
    return None


def get_modelscope_agent_token():
    token = None
    # Check if authorization header is present
    if MODELSCOPE_AGENT_TOKEN_HEADER_NAME in request.headers:
        auth_header = request.headers[MODELSCOPE_AGENT_TOKEN_HEADER_NAME]
        # Check if the value of the header starts with 'Bearer'
        if auth_header.startswith('Bearer '):
            # Extract the token part from 'Bearer token_value'
            token = auth_header[7:]
        else:
            # Extract the token part from auth_header
            token = auth_header
    return token


@app.before_request
def set_request_id():
    request_id = request.headers.get('X-Modelscope-Request-Id', 'unknown')
    request_id_var.set(request_id)


def with_request_id(func):

    @wraps(func)
    def wrapper(*args, **kwargs):
        request_id = request_id_var.get('')
        response = func(*args, **kwargs)
        if isinstance(response, app.response_class):
            response.headers['X-Modelscope-Request-Id'] = request_id
            return response
        elif isinstance(response[0], app.response_class):
            response[0].headers['X-Modelscope-Request-Id'] = request_id
            return response
        else:
            logger.error(
                f'with_request_id: unexpected response type {response}')
            return response

    return wrapper


# builder对话接口
@app.route('/builder/chat/<uuid_str>', methods=['POST'])
@with_request_id
def builder_chat(uuid_str):
    logger.info(f'builder_chat: uuid_str_{uuid_str}')
    params_str = request.form.get('params')
    params = json.loads(params_str)
    input_content = params.get('content')
    files = request.files.getlist('files')
    file_paths = []
    for file in files:
        ci_dir = get_user_ci_dir()
        os.makedirs(ci_dir, exist_ok=True)
        secure_fn = secure_filename(file.filename)
        file_path = os.path.join(ci_dir, uuid_str + '_' + secure_fn)
        if '../' in file_path:
            raise Exception('Access not allowed.')
        file.save(file_path)
        file_paths.append(file_path)

    def generate():
        try:
            builder_agent, builder_memory = app.session_manager.get_builder_bot(
                uuid_str)
            builder_memory.history = builder_memory.load_history()

            logger.info(f'input_content: {input_content}')
            response = ''
            is_final = False

            for frame in gen_response_and_process(
                    builder_agent,
                    query=input_content,
                    memory=builder_memory,
                    print_info=True,
                    uuid_str=uuid_str):

                llm_result = frame.get('llm_text', '')
                exec_result = frame.get('exec_result', '')
                step_result = frame.get('step', '')
                if len(exec_result) != 0:
                    if isinstance(exec_result, dict):
                        exec_result = exec_result['result']
                        assert isinstance(exec_result, Config)
                        builder_cfg = exec_result.to_dict()
                        save_builder_configuration(builder_cfg, uuid_str)
                        app.session_manager.clear_user_bot(uuid_str)
                        res = json.dumps(
                            {
                                'data': response,
                                'config': builder_cfg,
                                'is_final': is_final,
                            },
                            ensure_ascii=False)
                        logger.info(f'res: {res}')
                        yield f'data: {res}\n\n'
                else:
                    # llm result
                    if isinstance(llm_result, dict):
                        content = llm_result['content']
                    else:
                        content = llm_result
                    if frame.get('is_final', False):
                        is_final = True
                    frame_text = content
                    response = beauty_output(f'{response}{frame_text}',
                                             step_result)
                    res = json.dumps({
                        'data': response,
                        'is_final': is_final,
                    },
                                     ensure_ascii=False)  # noqa E126
                    logger.info(f'res: {res}')
                    yield f'data: {res}\n\n'

            final_res = json.dumps(
                {
                    'data': response,
                    'is_final': True,
                    'request_id': request_id_var.get('')
                },
                ensure_ascii=False)
            yield f'data: {final_res}\n\n'

            builder_memory.save_history()
        except Exception as e:
            stack_trace = traceback.format_exc()
            stack_trace = stack_trace.replace('\n', '\\n')
            logger.error(
                f'builder_chat_generate_error: {str(e)}, {stack_trace}')
            raise e

    return Response(generate(), mimetype='text/event-stream')


@app.route('/builder/chat/<uuid_str>', methods=['DELETE'])
@with_request_id
def delete_builder_chat(uuid_str):
    logger.info(f'delete_builder_chat: uuid_str_{uuid_str}')
    app.session_manager.clear_builder_bot(uuid_str)
    logger.info(f'delete_builder_chat: {uuid_str}')
    return jsonify({'success': True, 'request_id': request_id_var.get('')})


@app.route('/builder/chat/<uuid_str>', methods=['GET'])
@with_request_id
def get_builder_chat_history(uuid_str):
    logger.info(f'get_builder_chat_history: uuid_str_{uuid_str}')
    _, builder_memory = app.session_manager.get_builder_bot(uuid_str)
    history = builder_memory.get_history()
    logger.info(f'history: {json.dumps(history)}')

    for item in history:
        if item['role'] == 'system' or item['role'] == 'user':
            continue
        content = item['content']
        re_pattern_config = re.compile(
            pattern=r'([\s\S]+)Config: ([\s\S]+)\nRichConfig')
        res = re_pattern_config.search(content)
        if res:
            item['content'] = res.group(
                1) + CONFIG_UPDATED_STEP + LOGO_UPDATED_STEP

    return jsonify({
        'history': history,
        'success': True,
        'request_id': request_id_var.get('')
    })


# builder导入配置
@app.route('/builder/import/<uuid_str>', methods=['POST'])
@with_request_id
def import_builder(uuid_str):
    logger.info(f'import_builder: uuid_str_{uuid_str}')

    # 检查是否有文件被上传
    if 'file' in request.files:
        # 获取上传的文件
        file = request.files['file']

        # 如果用户没有选择文件
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        # 保存文件到服务器的文件系统
        secure_fn = secure_filename(file.filename)
        file_path = os.path.join(IMPORT_ZIP_TEMP_DIR, uuid_str, secure_fn)
        if '../' in file_path:
            raise Exception('Access not allowed.')
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        file.save(file_path)
        archive_dir = unzip_with_folder(file_path)
        # return jsonify({'message': 'File uploaded successfully', 'path': file_path}), 201
    else:
        url = request.get_json().get('url')
        # 发起请求获取数据
        response = requests.get(url)

        file_name = 'archive.zip'
        file_path = os.path.join(IMPORT_ZIP_TEMP_DIR, uuid_str, file_name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'wb') as f:
            f.write(response.content)
        archive_dir = unzip_with_folder(file_path)
    logger.info(f'archive_dir: {archive_dir}')
    reload_agent_dir(archive_dir, DEFAULT_AGENT_DIR, uuid_str)

    return jsonify({'success': True, 'request_id': request_id_var.get('')})


# 获取用户当前builder config
@app.route('/builder/config/<uuid_str>')
@with_request_id
def get_builder_config(uuid_str):
    logger.info(f'get_builder_config: uuid_str_{uuid_str}')

    builder_cfg, model_cfg, tool_cfg, available_tool_list, _, _ = parse_configuration(
        uuid_str)
    data = {
        'builder_config': builder_cfg.to_dict(),
        'model_config': model_cfg.to_dict(),
        'tool_config': tool_cfg.to_dict(),
        'available_tool_list': available_tool_list,
    }
    logger.info(f'preview_config: {json.dumps(data, ensure_ascii=False)}')
    return jsonify({
        'success': True,
        'data': data,
        'request_id': request_id_var.get('')
    })


# 获取用户当前builder额外文件，例如头像、上传的其他知识库等
@app.route('/builder/config_files/<uuid_str>/<file_name>', methods=['GET'])
@with_request_id
def get_builder_file(uuid_str, file_name):
    logger.info(
        f'get_builder_file: uuid_str_{uuid_str} file_name: {file_name}')
    as_attachment = request.args.get('as_attachment') == 'true'
    directory = get_user_dir(uuid_str)
    try:
        if '../' in file_name:
            raise Exception('Access not allowed.')
        if os.path.exists(os.path.join(directory, file_name)):
            response = make_response(
                send_from_directory(
                    directory, file_name, as_attachment=as_attachment))
        else:
            response = make_response(
                send_from_directory(
                    './config', file_name, as_attachment=as_attachment))
        return response
    except Exception as e:
        return jsonify({
            'success': False,
            'status': 404,
            'message': str(e),
            'request_id': request_id_var.get('')
        }), 404


# 保存用户当前配置
@app.route('/builder/update/<uuid_str>', methods=['POST'])
@with_request_id
def save_builder_config(uuid_str):
    logger.info(f'save_builder_config: uuid_str_{uuid_str}')
    builder_config_str = request.form.get('builder_config')
    logger.info(f'builder_config: {builder_config_str}')
    builder_config = json.loads(builder_config_str)
    if 'knowledge' in builder_config:
        builder_config['knowledge'] = [
            os.path.join(get_user_dir(uuid_str), os.path.basename(k))
            for k in builder_config['knowledge']
        ]
    files = request.files.getlist('files')
    upload_dir = get_user_dir(uuid_str)
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
    for file in files:
        secure_fn = secure_filename(file.filename)
        file_path = os.path.join(upload_dir, secure_fn)
        if '../' in file_path:
            raise Exception('Access not allowed.')
        file.save(file_path)
    if len(builder_config['openAPIConfigs']) > 0:
        openapi_config = builder_config['openAPIConfigs'][0]
        openapi_schema = openapi_config.get('schema', '')
        try:
            try:
                schema_dict = json.loads(openapi_schema)
            except json.decoder.JSONDecodeError:
                schema_dict = yaml.safe_load(openapi_schema)
            except Exception as e:
                logger.error(
                    f'OpenAPI schema format error, should be one of json and yaml: {e}'
                )

            openapi_plugin_cfg = {
                'schema': schema_dict,
                'auth': {
                    'type': openapi_config.get('authenticationType'),
                    'apikey': openapi_config.get('apiKey'),
                    'apikey_type': openapi_config.get('apiKeyType')
                },
                'privacy_policy': ''
            }
            if is_valid_plugin_configuration(openapi_plugin_cfg):
                save_plugin_configuration(
                    openapi_plugin_cfg=openapi_plugin_cfg, uuid_str=uuid_str)
        except Exception as e:
            logger.query_error(
                uuid=uuid_str,
                error=str(e),
                details={'error_traceback': traceback.format_exc()})
    save_builder_configuration(builder_cfg=builder_config, uuid_str=uuid_str)
    app.session_manager.clear_user_bot(uuid_str)

    return jsonify({'success': True, 'request_id': request_id_var.get('')})


# 获取用户发布包
@app.route('/builder/publish/zip/<uuid_str>', methods=['GET'])
@with_request_id
def preview_publish_get_zip(uuid_str):
    logger.info(f'preview_publish_get_zip: uuid_str_{uuid_str}')

    name = f'publish_{uuid_str}'
    env_params = {}
    env_params.update(pop_user_info_from_config(DEFAULT_AGENT_DIR, uuid_str))
    output_url, envs_required = prepare_agent_zip(name, DEFAULT_AGENT_DIR,
                                                  uuid_str, None)
    env_params.update(envs_required)
    return jsonify({
        'success': True,
        'output_url': output_url,
        'envs_required': envs_required,
        'request_id': request_id_var.get(''),
    })


# 预览对话接口
@app.route('/preview/chat/<uuid_str>/<session_str>', methods=['POST'])
@with_request_id
def preview_chat(uuid_str, session_str):
    user_token = get_modelscope_agent_token()
    if not user_token:
        # If token is not found, return 401 Unauthorized response
        return jsonify({'message': 'Token is missing!'}), 401

    logger.info(f'preview_chat: uuid_str_{uuid_str}_session_str_{session_str}')

    params_str = request.form.get('params')
    params = json.loads(params_str)
    input_content = params.get('content')
    files = request.files.getlist('files')
    file_paths = []
    for file in files:
        ci_dir = get_user_ci_dir()
        os.makedirs(ci_dir, exist_ok=True)
        file_path = os.path.join(ci_dir, uuid_str + '_' + file.filename)
        if '../' in file_path:
            raise Exception('Access not allowed.')
        file.save(file_path)
        file_paths.append(file_path)
    logger.info(f'/preview/chat/{uuid_str}/{session_str}: files: {file_paths}')
    # Generating the kwargs dictionary
    kwargs = {}

    def generate():
        try:
            start_time = time.time()
            seed = random.randint(0, 1000000000)
            user_agent, user_memory = app.session_manager.get_user_bot(
                uuid_str, session_str, user_token=user_token)
            user_agent.seed = seed
            logger.info(
                f'get method: time consumed {time.time() - start_time}')

            # get chat history from memory
            user_memory.load_history()
            history = user_memory.get_history()

            logger.info(
                f'load history method: time consumed {time.time() - start_time}'
            )

            # skip
            filtered_files = [
                item for item in file_paths
                if not item.lower().endswith(('.jpeg', '.png', '.jpg', '.wav',
                                              '.gif', '.mp3'))
            ]

            use_llm = True if len(user_agent.function_list) else False
            ref_doc = user_memory.run(
                query=input_content,
                url=filtered_files,
                checked=True,
                use_llm=use_llm)
            logger.info(
                f'load knowledge method: time consumed {time.time() - start_time}, '
                f'the uploaded_file name is {filtered_files}')  # noqa

            response = ''

            logger.info(f'input_content: {input_content}')
            res = json.dumps(
                {
                    'data': '',
                    'is_final': False,
                    'request_id': request_id_var.get('')
                },
                ensure_ascii=False)

            for frame in user_agent.run(
                    input_content,
                    history=history,
                    ref_doc=ref_doc,
                    append_files=file_paths,
                    uuid_str=uuid_str,
                    user_token=user_token,
                    **kwargs):
                logger.info('frame, {}'.format(
                    str(frame).replace('\n', '\\n')))
                # important! do not change this
                response += frame
                res = json.dumps(
                    {
                        'data': response,
                        'is_final': False,
                        'request_id': request_id_var.get('')
                    },
                    ensure_ascii=False)
                yield f'data: {res}\n\n'

            if len(history) == 0:
                user_memory.update_history(
                    Message(role='system', content=user_agent.system_prompt))
            res = json.dumps(
                {
                    'data': response,
                    'is_final': True,
                    'request_id': request_id_var.get('')
                },
                ensure_ascii=False)
            logger.info(f'response: {res}')
            user_memory.update_history([
                Message(role='user', content=input_content),
                Message(role='assistant', content=response),
            ])
            user_memory.save_history()
            logger.info('user_memory save_history complete.')
            yield f'data: {res}\n\n'
        except Exception as e:
            stack_trace = traceback.format_exc()
            stack_trace = stack_trace.replace('\n', '\\n')
            logger.error(
                f'preview_chat_generate_error: {str(e)}, {stack_trace}')
            error_info = f'data: Please check your configuration and try again. Error: {str(e)}, {stack_trace}\n\n'
            res = json.dumps(
                {
                    'data': error_info,
                    'is_final': True,
                    'request_id': request_id_var.get('')
                },
                ensure_ascii=False)
            yield f'data: {res}\n\n'

    return Response(generate(), mimetype='text/event-stream')


# 清除当前预览对话实例
@app.route('/preview/chat/<uuid_str>/<session_str>', methods=['DELETE'])
@with_request_id
def delete_preview_chat(uuid_str, session_str):
    logger.info(
        f'delete_preview_chat: uuid_str_{uuid_str}_session_str_{session_str}')

    app.session_manager.clear_user_bot(uuid_str, session_str)
    return jsonify({'success': True, 'request_id': request_id_var.get('')})


@app.route('/preview/chat/<uuid_str>/<session_str>', methods=['GET'])
@with_request_id
def get_preview_chat_history(uuid_str, session_str):
    logger.info(
        f'get_preview_chat_history: uuid_str_{uuid_str}_session_str_{session_str}'
    )
    user_token = get_modelscope_agent_token()
    if not user_token:
        # If token is not found, return 401 Unauthorized response
        return jsonify({'message': 'Token is missing!'}), 401

    _, user_memory = app.session_manager.get_user_bot(
        uuid_str, session_str, user_token=user_token)
    return jsonify({
        'history': user_memory.get_history(),
        'success': True,
        'request_id': request_id_var.get('')
    })


@app.route('/preview/chat_file/<uuid_str>/<session_str>', methods=['GET'])
@with_request_id
def get_preview_chat_file(uuid_str, session_str):
    logger.info(
        f'get_preview_chat_file: uuid_str_{uuid_str}_session_str_{session_str}'
    )

    file_path = request.args.get('file_path')
    logger.info(f'uuid_str: {uuid_str} session_str: {session_str}')
    as_attachment = request.args.get('as_attachment') == 'true'
    try:
        if not file_path.startswith(get_ci_dir()) or '../' in file_path:
            raise Exception('Access not allowed.')
        response = make_response(
            send_from_directory(
                os.path.dirname(file_path),
                os.path.basename(file_path),
                as_attachment=as_attachment))
        return response
    except Exception as e:
        return jsonify({
            'success': False,
            'status': 404,
            'message': str(e),
            'request_id': request_id_var.get('')
        }), 404


@app.route('/openapi/schema/<uuid_str>', methods=['POST'])
@with_request_id
def openapi_schema_parser(uuid_str):
    logger.info(f'parse openapi schema for: uuid_str_{uuid_str}')
    params_str = request.get_data(as_text=True)
    params = json.loads(params_str)
    openapi_schema = params.get('openapi_schema')
    try:
        if isinstance(openapi_schema, dict):
            host = openapi_schema.get('host', '')
            basePath = openapi_schema.get('basePath', '')
            if host and basePath:
                return make_response(
                    jsonify({
                        'success':
                        False,
                        'status':
                        429,
                        'message':
                        'The Swagger 2.0 format is not support, '
                        'please convert it to OpenAPI 3.0 format at https://petstore.swagger.io/',
                        'request_id':
                        request_id_var.get('')
                    }), 429)
        if not isinstance(openapi_schema, dict):
            openapi_schema = json.loads(openapi_schema)
    except json.decoder.JSONDecodeError:
        openapi_schema = yaml.safe_load(openapi_schema)
    except Exception as e:
        logger.error(
            f'OpenAPI schema format error, should be a valid json with error message: {e}'
        )
    if not openapi_schema:
        return make_response(
            jsonify({
                'success': False,
                'status': 429,
                'message':
                'OpenAPI schema format error, should be a valid json',
                'request_id': request_id_var.get('')
            }), 429)
    openapi_schema_instance = OpenapiServiceProxy(openapi=openapi_schema)
    import copy
    schema_info = copy.deepcopy(openapi_schema_instance.api_info_dict)
    output = []
    for item in schema_info:
        schema_info[item].pop('is_active')
        schema_info[item].pop('is_remote_tool')
        schema_info[item].pop('details')
        schema_info[item].pop('header')
        output.append(schema_info[item])

    return jsonify({
        'success': True,
        'schema_info': output,
        'request_id': request_id_var.get('')
    })


@app.route('/openapi/test/<uuid_str>', methods=['POST'])
@with_request_id
def openapi_test_parser(uuid_str):
    logger.info(f'parse openapi schema for: uuid_str_{uuid_str}')
    params_str = request.get_data(as_text=True)
    params = json.loads(params_str)
    tool_params = params.get('tool_params')
    tool_name = params.get('tool_name')
    credentials = params.get('credentials')
    openapi_schema = params.get('openapi_schema')

    try:
        if not isinstance(openapi_schema, dict):
            openapi_schema = json.loads(openapi_schema)
    except json.decoder.JSONDecodeError:
        openapi_schema = yaml.safe_load(openapi_schema)
    except Exception as e:
        logger.error(
            f'OpenAPI schema format error, should be a valid json with error message: {e}'
        )
    if not openapi_schema:
        return jsonify({
            'success': False,
            'message': 'OpenAPI schema format error, should be valid json',
            'request_id': request_id_var.get('')
        })
    openapi_schema_instance = OpenapiServiceProxy(
        openapi=openapi_schema, is_remote=False)
    result = openapi_schema_instance.call(
        tool_params, **{
            'tool_name': tool_name,
            'credentials': credentials,
            'is_test': True
        })
    if not result:
        return jsonify({
            'success': False,
            'result': None,
            'request_id': request_id_var.get('')
        })
    return jsonify({
        'success': True,
        'result': result,
        'request_id': request_id_var.get('')
    })


# Mock database
todos_db = {}


@app.route('/todos/<string:username>', methods=['GET'])
def get_todos(username):
    if username in todos_db:
        return jsonify({'output': {'todos': todos_db[username]}})
    else:
        return jsonify({'output': {'todos': []}})


@app.route('/todos/<string:username>', methods=['POST'])
def add_todo(username):
    if not request.is_json:
        return jsonify({'output': 'Missing JSON in request'}), 400

    todo_data = request.get_json()
    todo = todo_data.get('todo')

    if not todo:
        return jsonify({'output': "Missing 'todo' in request"}), 400

    if username in todos_db:
        todos_db[username].append(todo)
    else:
        todos_db[username] = [todo]

    return jsonify({'output': 'Todo added successfully'}), 200


@app.route('/todos/<string:username>', methods=['DELETE'])
def delete_todo(username):
    if not request.is_json:
        return jsonify({'output': 'Missing JSON in request'}), 400

    todo_data = request.get_json()
    todo_idx = todo_data.get('todo_idx')

    if todo_idx is None:
        return jsonify({'output': "Missing 'todo_idx' in request"}), 400

    if username in todos_db and 0 <= todo_idx < len(todos_db[username]):
        deleted_todo = todos_db[username].pop(todo_idx)
        return jsonify(
            {'output': f"Todo '{deleted_todo}' deleted successfully"}), 200
    else:
        return jsonify({'output': "Invalid 'todo_idx' or username"}), 400


@app.errorhandler(Exception)
@with_request_id
def handle_error(error):
    stack_trace = traceback.format_exc()
    stack_trace = stack_trace.replace('\n', '\\n')
    logger.error(f'{str(error)}, {stack_trace}')
    # 处理错误并返回统一格式的错误信息
    error_message = {
        'success': False,
        'message': str(error),
        'status': 500,
        'request_id': request_id_var.get('')
    }
    return jsonify(error_message), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', '5001'))
    app.run(host='0.0.0.0', port=port, debug=False)
