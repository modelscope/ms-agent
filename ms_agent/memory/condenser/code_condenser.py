import os
from typing import List

import json
from ms_agent.llm import LLM, Message
from ms_agent.memory import Memory
from ms_agent.utils import get_logger
from ms_agent.utils.constants import (DEFAULT_INDEX_DIR, DEFAULT_LOCK_DIR,
                                      DEFAULT_OUTPUT_WRAPPER)
from ms_agent.utils.utils import extract_code_blocks, file_lock

logger = get_logger()


class CodeCondenser(Memory):

    system = """你是一个帮我简化代码并返回缩略信息的机器人。你缩略的文件会给与另一个LLM用来编写代码，因此你生成的缩略文件需要具有充足的供其他文件依赖的信息。

需要保留的信息：
1. 代码框架：类名、方法名、方法参数类型，返回值类型，类型定义的文件
    * 如果无法找到参数和返回值类型，则分析函数实现，给出该参数或输出结构需要/具有哪些字段
    * 注意考察注释部分是否包含有用信息
2. 导入信息：imports依赖
3. 输出信息：exports导出及导出类型，注意不要忽略`default`这类关键字，注意命名导出或默认导出方式
4. 结构体信息：不要缩略任何类或数据结构的名称、字段，如果一个文件包含很多数据结构定义，全部保留
5. 样式信息：如果是css样式代码，保留每个样式名称
6. json格式：保留结构即可
7. http等RPC协议定义信息
8. **以json格式**返回满足要求的缩略信息，不要返回下面结构之外的其他额外信息

* 例子：
    ```xx.ts原始文件
    import {...} from ...
    async function func(a: Record<string, any>): Promise<any> {
        const b = a['some-key'];
        return b;
    }
    export default func;
    ```

    缩略：
    ```xx.ts.index.json
    {
        "imports": [xx/xx.js, ..., ...]" # 文件列表
        "classes": [
            {
                "name": "ClassA", # 类名
                "functions": [ # 类中的方法列表
                    {
                        "name": "async func1", # 方法名
                        "inputs": [
                            {
                                "name": "arg1", # 入参名
                                "type": "Record<string, any>, keys: some-key, ...", # 类型，以及可观测的结构需求
                                "define": "xx/xx.js" # 可推测的定义文件
                            },
                            ...
                        ],
                        "outputs": [
                            {
                                "type": "Record<string, any>", # 类型，以及可观测的结构需求
                                "define": "xx/xx.js" # 可推测的定义文件
                            },
                            ...
                        ]
                    }
                ]
            }
        ],
        "functions": [...], # 结构和上面functions相同，用于列举不在类中的方法
        "styles": [ # css等类型的样式信息，保留所有id的结构、类型和名称
            {
                "name": "some-key", # class/id name
                "type": "component", # usage
                "description": "..."
            }
        ]
        "protocols": [
            {
                "type": "http",
                "url": "...", # http url信息
                "params": "query:str, limit:int", # http输入参数需求，包含param结构和header需求，如果是类结构，给出结构引用信息（例如UserRequest in api/user.xx）
                "responses": "{data:xxx, errorCode:xxx}, defined in xxx/xxx.js" # http具体输出结构和错误定义, 如果是类结构，给出结构引用信息
            }
        ],
        "structs": [ # 结构信息，包含定义的代码结构或json结构等
            {
                "name": "User", # 结构名称
                "fields": ... # 字段和类型列表
            },
            ...
        ],
        "exports": ["default ClassA", ...], # 输出信息
    }
    ```

你的优化目标：
1. 【优先】保留充足的信息供其它代码使用
2. 【其次】保留尽量少的token数量
""" # noqa

    def __init__(self, config):
        super().__init__(config)
        self.llm: LLM = LLM.from_config(self.config)
        mem_config = self.config.memory.code_condenser
        if getattr(mem_config, 'system', None):
            self.system = mem_config.system
        index_dir = getattr(config, 'index_cache_dir', DEFAULT_INDEX_DIR)
        self.index_dir = os.path.join(self.output_dir, index_dir)
        self.lock_dir = os.path.join(self.output_dir, DEFAULT_LOCK_DIR)
        self.code_wrapper = getattr(mem_config, 'code_wrapper',
                                    DEFAULT_OUTPUT_WRAPPER)

    def condense_code(self, message: Message):
        prefix = 'Your generated code was replaced by a index version:\n'
        if message.role == 'assistant':
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    if 'write_file' in tool_call['tool_name']:
                        arguments = tool_call['arguments']
                        if isinstance(arguments, str):
                            arguments = json.loads(arguments)
                        code_file = arguments['path']
                        content = arguments['content']
                        index_content = self.generate_index_file(
                            code_file, content)
                        arguments['content'] = f'{prefix}{index_content}'
                        tool_call['arguments'] = json.dumps(
                            arguments, ensure_ascii=False)
            elif self.code_wrapper[0] in message.content and self.code_wrapper[
                    1] in message.content:
                result, remaining_text = extract_code_blocks(
                    message.content, file_wrapper=self.code_wrapper)
                if result:
                    final_content = remaining_text + prefix
                    for code_block in result:
                        code_file = code_block['filename']
                        content = code_block['code']
                        index_content = self.generate_index_file(
                            code_file, content)
                        final_content += index_content + '\n'
                    message.content = final_content

    async def run(self, messages: List[Message]):
        for message in messages:
            self.condense_code(message)
        return messages

    def generate_index_file(self, file: str, content: str = None):
        os.makedirs(self.index_dir, exist_ok=True)
        index_file = os.path.join(self.index_dir, file)
        with file_lock(self.lock_dir, os.path.join('index', file)):
            if os.path.exists(index_file):
                with open(index_file, 'r') as f:
                    return f.read()

            source_file_path = os.path.join(self.output_dir, file)
            if content:
                file_content = content
            elif not os.path.exists(source_file_path):
                return ''
            else:
                with open(source_file_path, 'r') as f:
                    file_content = f.read()

            query = f'The original source file {file}:\n{file_content}'
            messages = [
                Message(role='system', content=self.system),
                Message(role='user', content=query),
            ]
            content = None
            error = None
            for i in range(3):
                try:
                    response_message = self.llm.generate(
                        messages, stream=False)
                    content = response_message.content.split('\n')
                    if '```' in content[0]:
                        content = content[1:]
                    if '```' in content[-1]:
                        content = content[:-1]
                    content = '\n'.join(content)
                    os.makedirs(os.path.dirname(index_file), exist_ok=True)
                    with open(index_file, 'w') as f:
                        f.write(content)
                    json.loads(
                        content
                    )  # try to load once to ensure the json format is ok
                    break
                except Exception as e:
                    error = e
                    logger.error(
                        f'Code index file generate failed because of {e}')
            if content is None:
                raise error
            return content
