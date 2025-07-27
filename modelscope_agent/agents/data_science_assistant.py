# Implementation inspired by the paper "DATA INTERPRETER: AN LLM AGENT FOR DATA SCIENCE"
import os
import time
from datetime import datetime
from typing import Dict, Iterator, List, Optional, Union

import json
import json5
import nbformat
from modelscope_agent.agents.role_play import RolePlay
from modelscope_agent.llm.base import BaseChatModel
from modelscope_agent.schemas import CodeCell, Plan, Task
from modelscope_agent.tools.code_interpreter.code_interpreter_nb import \
    CodeInterpreter
from modelscope_agent.tools.metagpt_tools.task_type import TaskType
from modelscope_agent.tools.metagpt_tools.tool_recommend import ToolRecommender
from modelscope_agent.utils.logger import agent_logger as logger
from modelscope_agent.utils.utils import parse_code

try:
    import streamlit as st  # noqa
    from nbconvert import HTMLExporter
    from traitlets.config import Config
except Exception as e:
    print(f'import error: {str(e)}, please install streamlit and nbconvert')
PLAN_TEMPLATE = """
# Context:
{context}
# Available Task Types:
- **eda**: For performing exploratory data analysis
- **data preprocessing**: For preprocessing dataset in a data analysis or machine learning task ONLY,\
general data operation doesn't fall into this type
- **feature engineering**: Only for creating new columns fo input data.
- **model train**: Only for training model.
- **model evaluate**: Only for evaluating model.
- **ocr**: Only for OCR tasks.
- **other**: Any tasks not in the defined categories

# Task:
Based on the context, write a simple plan or modify an existing plan of what you should do to achieve the goal.

Output a list of jsons following the format:
```json
[
    {{
        "task_id": str = "unique identifier for a task in plan, can be an ordinal",
        "dependent_task_ids": list[str] = "ids of tasks prerequisite to this task",
        "instruction": "what you should do in this task, one short phrase or sentence",
        "task_type": "type of this task, should be one of Available Task Types",
    }},
    ...
]
```
"""

DECOMPOSE_TASK_TEMPLATE = """
# Context:
{context}
# Available Task Types:
- **eda**: For performing exploratory data analysis
- **data preprocessing**: For preprocessing dataset in a data analysis or machine learning task ONLY,\
general data operation doesn't fall into this type
- **feature engineering**: Only for creating new columns fo input data.
- **model train**: Only for training model.
- **model evaluate**: Only for evaluating model.
- **ocr**: Only for OCR tasks.
- **other**: Any tasks not in the defined categories

# Previous Tasks
We have already generated the following tasks:
{previous_tasks}
# Task:
The current task is:
{current_task}
Currently, the current task is too complex to be executed in one step. Please decompose the task into smaller tasks, \
and output a list of jsons following the format:
Output a list of jsons following the format:

```json
[
    {{
        "task_id": str = "unique identifier for a task in plan, can be an ordinal, \
        should be unique and not conflict with previous task ids",
        "dependent_task_ids": list[str] = "ids of tasks prerequisite to this task",
        "instruction": "what you should do in this task, one short phrase or sentence",
        "task_type": "type of this task, should be one of Available Task Types",
    }},
    ...
]
```
"""

CODE_TEMPLATE = """
# Task
you are a code generator, you need to generate a code python block in jupyter notebook to achieve the \
current task:
{instruction}

## Task Guidance
{task_guidance}

## User Request
current task is part of the whole plan to achieve the user request:
{user_request}

# Previous executed code
previous code blocks are as follows and have been executed successfully in the previous jupyter notebook code blocks, \
which means you can use the variables defined in the previous code blocks.\
the code you need to generate should follow previous code, no need to repeat.

{previous_code}

{data_info}

# Constraints
- Ensure the output new code is executable in the same Jupyter notebook as the previous executed code.
- Always prioritize using pre-defined tools for the same functionality. When using pre-defined tools, you MUST\
 follow the 'tool_path' in order to successfully import the tool.
- the code format MUST be followed:

```python
# your code
```



"""
CODE_REFLECT_TEMPLATE = """
# Role
you are a code generator, you need to generate a code python block in jupyter notebook to achieve the \
current task:

# Task
{instruction}

## Task Guidance
{task_guidance}

## User Request
current task is part of the whole plan to achieve the user request:
{user_request}

# Previous executed code
previous code blocks are as follows and have been executed successfully in the previous jupyter notebook code blocks, \
which means you can use the variables defined in the previous code blocks.\
the code you need to generate should follow previous code, no need to repeat. If previous code is empty, \
you can ignore this part.

{previous_code}

{data_info}

## Generated Code and Error
the code we have generated for current task is as follows, you can use it as a reference to generate the correct code:
{code_and_error}

# Constraints
- Ensure the output new code is executable in the same Jupyter notebook as the previous executed code.
- Always prioritize using pre-defined tools for the same functionality. When using pre-defined tools, \
you MUST follow the 'tool_path' in order to successfully import the tool.
- the code format MUST be followed, otherwise the code interpreter will not be able to parse\
the code correctly,the code format is as follows:
- If certain package are not installed in the environment, you can install them by adding the following code:
!pip install <package_name>
- Your answer must contain one and only one code block.
- the code format MUST be followed, the code format is as follows:

```python
# your code
```

"""
CODE_USING_TOOLS_TEMPLATE = """
# Task
you are a code generator, you need to generate a code python block in jupyter notebook to achieve the \
current task:
{instruction}

## Task Guidance
{task_guidance}

## User Request
current task is part of the whole plan to achieve the user request:
{user_request}

# Previous executed code
previous code blocks are as follows and have been executed successfully in the previous jupyter notebook code blocks, \
which means you can use the variables defined in the previous code blocks.\
the code you need to generate should follow previous code, no need to repeat.

{previous_code}

{data_info}

# Tool Info (If is empty, you can ignore this part)
{tool_info}

# Constraints
- Ensure the output new code is executable in the same Jupyter notebook as the previous executed code.
- Always prioritize using pre-defined tools for the same functionality. When using pre-defined tools, \
you MUST follow the 'tool_path' in order to successfully import the tool.
- Your answer must contain one and only one code block.
- the code format MUST be followed, the code format is as follows:
```python
# your code
```
"""
CODE_USING_TOOLS_REFLECTION_TEMPLATE = """
# Role
you are a code generator, you need to generate a code python block in jupyter notebook to achieve the \
current task:

# Task
{instruction}

## Task Guidance
{task_guidance}

## User Request
current task is part of the whole plan to achieve the user request:
{user_request}

# Previous executed code
previous code blocks are as follows and have been executed successfully in the previous jupyter notebook code blocks, \
which means you can use the variables defined in the previous code blocks.\
the code you need to generate should follow previous code, no need to repeat. If previous code is empty, \
you can ignore this part.

{previous_code}

{data_info}

## Generated Code and Error
the code we have generated for current task is as follows, you can use it as a reference to generate the correct code:
{code_and_error}

#Tool Info
{tool_info}


# Constraints
- Ensure the output new code is executable in the same Jupyter notebook as the previous executed code.
- Always prioritize using pre-defined tools for the same functionality. When using pre-defined tools, \
you MUST follow the 'tool_path' in order to successfully import the tool.
- If certain package are not installed in the environment, you can install them by adding the following code:
!pip install <package_name>
- Your answer must contain one and only one code block.
- the code format MUST be followed, otherwise the code interpreter will not be able to parse\
the code correctly,the code format is as follows!!!:
```python
# your code
```
"""
JUDGE_TEMPLATE = """
take a deep breath and think step by step.
you are a code judge, you need to think step by step to judge whether the code block in jupyter notebook achieve the \
current task, at the end of your thought, you need to give the final judgement( orrect or incorrect).
[current task]
{instruction}

this is the code block you need to judge, it contains code and execution result:
{code}

Even if the code has been executed successfully, doesn't mean it's totally correct. You need to carefully \
check the code logic to ensure the code can accomplish the task correctly. Ignore the warning messages. \
You don't need to check the metrics of the model.

these are the previous code blocks, which have been executed successfully in the previous jupyter notebook code blocks \
{previous_code_blocks}

at the end of your thought, you need to give the final judgement with a new line( correct or incorrect).
don't generate code , just give the reason why the code is correct or incorrect.

## Attention
don't use the word 'incorrect' in your step by step thought.
your answer should be short and clear, don't need to be too long.
"""

CHECK_DATA_PROMPT = """
# Background
Check latest data info to guide subsequent tasks.

## Finished Tasks
```python
{code_written}
```end

# Task
Check code in finished tasks, print key variables to guide your following actions.
Specifically, if it is a data analysis or machine learning task, print the the latest column information using \
the following code, with DataFrame variable from 'Finished Tasks' in place of df:
```python
from modelscope_agent.tools.metagpt_tools.libs.data_preprocess import get_column_info

column_info = get_column_info(df)
print("column_info")
print(column_info)
```end
Otherwise, print out any key variables you see fit. Return an empty string if you think there \
is no important data to check.

# Constraints:
- Your code is to be added to a new cell in jupyter.

# Instruction
Output code following the format:
```python
your code
```
"""

DATA_INFO = """
# Latest Data Info
Latest data info after previous tasks:
{info}
"""

ERROR_KEYWORDS = ['Error']


class TaskEncoder(json.JSONEncoder):

    def default(self, obj):
        if isinstance(obj, Task):
            return obj.__dict__  # 或者根据需要自定义每个属性
        elif isinstance(obj, CodeCell):
            return obj.__dict__
        return super(TaskEncoder, self).default(obj)


class DataScienceAssistant(RolePlay):

    def __init__(self,
                 function_list: Optional[List[Union[str, Dict]]] = None,
                 llm: Optional[Union[Dict, BaseChatModel]] = None,
                 storage_path: Optional[str] = None,
                 name: Optional[str] = None,
                 description: Optional[str] = None,
                 instruction: Union[str, dict] = None,
                 tool_recommender: Optional[ToolRecommender] = None,
                 **kwargs):
        super().__init__(
            function_list=function_list,
            llm=llm,
            storage_path=storage_path,
            name=name,
            description=description,
            instruction=instruction,
            **kwargs)
        self.tool_recommender = tool_recommender
        self.code_interpreter = CodeInterpreter()
        self.plan = None
        self.total_token = 0
        self.streamlit = False

    def _update_plan(self, user_request: str, curr_plan: Plan = None) -> Plan:
        call_llm_success = False
        call_llm_count = 0
        tasks_text = ''
        messages = [{
            'role':
            'user',
            'content':
            PLAN_TEMPLATE.format(
                context='User Request: ' + user_request + '\n', )
        }]
        while not call_llm_success and call_llm_count < 10:
            resp = self._call_llm(prompt=None, messages=messages, stop=None)
            resp_streamlit = resp
            tasks_text = ''
            if self.streamlit:
                st.write('#### Generate a plan based on the user request')
                tasks_text = st.write_stream(resp_streamlit)
            else:
                for r in resp:
                    tasks_text += r
            if 'Error code' in tasks_text:
                call_llm_count += 1
                time.sleep(10)
            else:
                call_llm_success = True
        print('Tasks_text: ', tasks_text)
        tasks_text = parse_code(text=tasks_text, lang='json')

        logger.info(f'tasks: {tasks_text}')
        tasks = json5.loads(tasks_text)
        tasks = [Task(**task) for task in tasks]

        if curr_plan is None:
            new_plan = Plan(goal=user_request)
            new_plan.add_tasks(tasks=tasks)
            return new_plan
        else:
            if len(tasks) == 1 or tasks[0].dependent_task_ids:
                if tasks[0].dependent_task_ids and len(tasks) > 1:
                    logger.warning(
                        'Current plan will take only the first generated task if the generated tasks are not a '
                        'complete plan')

                if curr_plan.has_task_id(tasks[0].task_id):

                    curr_plan.replace_task(tasks[0])
                else:

                    curr_plan.append_task(tasks[0])
            else:

                curr_plan.add_tasks(tasks)
            return curr_plan

    @staticmethod
    def _save(nb: nbformat.NotebookNode, plan: Plan, **kwargs):
        if not os.path.exists('data'):
            os.makedirs('data')
        if kwargs.get('dir_name'):
            dir_name = 'data/' + kwargs.get('dir_name') + '/'
        dir_name = 'data/' + str(
            datetime.now().strftime('%Y-%m-%d-%H-%M-%S')) + '/'
        if not os.path.exists(dir_name):
            os.makedirs(dir_name)
        if (kwargs.get('name')):
            file_name = dir_name + kwargs.get('name') + '.ipynb'
        else:
            file_name = dir_name + 'result' + '.ipynb'
        # save ipynb
        with open(file_name, 'w', encoding='utf-8') as file:
            nbformat.write(nb, file)
        # save plan.tasks
        tasks_list = plan.tasks

        # 将Task列表转换为字典列表，以便于序列化
        tasks_dict_list = [task.model_dump() for task in tasks_list]

        # 将字典列表转换为JSON字符串
        tasks_json = json.dumps(tasks_dict_list, indent=4)

        # 将JSON字符串写入文件
        with open(dir_name + 'plan.json', 'w', encoding='utf-8') as file:
            file.write(tasks_json)

    def _get_task_codes(self, task: Task, n: int = 3) -> str:
        codes = task.code_cells
        n = min(len(codes), n)
        task_codes = ''
        index = len(codes) - n
        for i in range(n):
            task_codes += f'\ncode_{i + 1}:\n```python\n{codes[index + i].code}\n```\n'
            task_codes += f'code_{i + 1} Output:\n{codes[index + i].result}\n\n'
        return task_codes

    def _generate_code(self, code_counter: int, task: Task,
                       user_request: str) -> str:
        """
        Generate code for the current task
        """
        data_info = self._check_data()
        if code_counter == 0:
            # first time to generate code
            if self.tool_recommender:
                tool_info = self.tool_recommender.get_recommended_tool_info(
                    plan=self.plan)
                prompt = CODE_USING_TOOLS_TEMPLATE.format(
                    instruction=task.instruction,
                    user_request=user_request,
                    task_guidance=TaskType.get_type(task.task_type).guidance,
                    previous_code=self._get_previous_code_blocks(),
                    tool_info=tool_info,
                    data_info=data_info)

            else:
                prompt = CODE_TEMPLATE.format(
                    instruction=task.instruction,
                    user_request=user_request,
                    task_guidance=TaskType.get_type(task.task_type).guidance,
                    previous_code=self._get_previous_code_blocks(),
                    data_info=data_info)

        else:
            # reflect the error and ask user to fix the code
            if self.tool_recommender:
                tool_info = self.tool_recommender.get_recommended_tool_info(
                    plan=self.plan)
                prompt = CODE_USING_TOOLS_REFLECTION_TEMPLATE.format(
                    instruction=task.instruction,
                    task_guidance=TaskType.get_type(task.task_type).guidance,
                    previous_code=self._get_previous_code_blocks(),
                    code_and_error=self._get_task_codes(task),
                    user_request=user_request,
                    tool_info=tool_info,
                    data_info=data_info)
            else:
                prompt = CODE_REFLECT_TEMPLATE.format(
                    instruction=task.instruction,
                    task_guidance=TaskType.get_type(task.task_type).guidance,
                    previous_code=self._get_previous_code_blocks(),
                    code_and_error=self._get_task_codes(task),
                    user_request=user_request,
                    data_info=data_info)
        logger.info(
            f'code generate prompt for task{task.task_id} count{code_counter}: \n{prompt}'
        )
        messages = [{'role': 'user', 'content': prompt}]
        success = False
        call_llm_count = 0
        code = ''
        while call_llm_count < 20 and not success:
            resp = self._call_llm(
                prompt=None,
                messages=messages,
                stop=None,
            )
            llm_result = ''
            try:
                for s in resp:
                    llm_result += s
                self._get_total_tokens()
                if 'Error code' in llm_result:
                    raise AttributeError
                code = parse_code(text=llm_result, lang='python')
                success = True
            except Exception as e:
                logger.error(e)
                call_llm_count += 1
                time.sleep(20)
        if not success:
            raise AttributeError('generate code failed')
        return code

    def _get_previous_code_blocks(self) -> str:
        """
        Get previous code blocks with outputs
        """
        previous_code_blocks = ''
        counter = 0
        for task in self.plan.tasks:
            if task.is_finished:
                counter += 1
                previous_code_blocks += (
                    f'\nCodeblock_{counter}:\n```python\n{task.code}\n```\n'
                    f'Codeblock_{counter} Output:\n{task.result}\n')
        return previous_code_blocks

    def _get_previous_code_blocks_without_outputs(self) -> str:
        """
        Get previous code blocks without outputs
        """
        previous_code_blocks = ''
        for task in self.plan.tasks:
            if task.is_finished:
                previous_code_blocks += task.code + '\n'
        return previous_code_blocks

    def _check_data(self):
        """
        Check data information to guide subsequent tasks
        """
        if (not self.plan.get_finished_tasks()
                or self.plan.current_task.task_type not in [
                    TaskType.DATA_PREPROCESS.type_name,
                    TaskType.FEATURE_ENGINEERING.type_name,
                    TaskType.MODEL_TRAIN.type_name
                ]):  # noqa
            return ''

        prompt = CHECK_DATA_PROMPT.format(
            code_written=self._get_previous_code_blocks_without_outputs())
        logger.info(f'check data prompt: \n {prompt}')
        messages = [{'role': 'user', 'content': prompt}]
        call_llm_count = 0
        call_llm_success = False
        code = ''
        while call_llm_count < 5 and not call_llm_success:
            try:
                resp = self._call_llm(
                    prompt=None,
                    messages=messages,
                    stop=None,
                )
                code = ''
                for s in resp:
                    code += s
                self._get_total_tokens()
                if 'Error code' in code:
                    call_llm_count += 1
                    time.sleep(10)
                else:
                    call_llm_success = True
                code = parse_code(text=code, lang='python')
            except Exception as e:
                logger.error(e)
                call_llm_count += 1
                call_llm_success = False
                time.sleep(10)
        if not call_llm_success:
            raise Exception('call llm failed')
        logger.info(f'check data code: \n {code}')
        success, result = self.code_interpreter.call(
            params=json.dumps({'code': code}), nb_mode=True)
        del self.code_interpreter.nb.cells[-1]
        if success:
            logger.info(f'check data result: \n {result}')
            return DATA_INFO.format(info=result)

    def _judge_code(self, task, previous_code_blocks, code,
                    code_interpreter_resp):
        judge_prompt = JUDGE_TEMPLATE.format(
            instruction=task.instruction,
            previous_code_blocks=previous_code_blocks,
            code=f'Code:\n {code}\n Excution Result:\n{code_interpreter_resp}')
        logger.info(f'judge prompt: \n {judge_prompt}')
        messages = [{'role': 'user', 'content': judge_prompt}]
        call_llm_count = 0
        call_llm_success = False
        while call_llm_count < 5 and not call_llm_success:
            resp = self._call_llm(
                prompt=None,
                messages=messages,
                stop=None,
            )
            judge_result = ''
            for s in resp:
                judge_result += s
            self._get_total_tokens()
            if 'Error code' in judge_result:
                call_llm_count += 1
                time.sleep(5)
            else:
                call_llm_success = True
        if not call_llm_success:
            raise Exception('call llm failed')
        logger.info(f'judge result for task{task.task_id}: \n {judge_result}')
        if 'incorrect' in judge_result.split('\n')[-1]:
            success = False
            failed_reason = (
                'Though the code executes successfully, The code logic is \
                incorrect, here is the reason: ' + judge_result)
            return success, failed_reason

        else:
            return True, judge_result

    def _run(self, user_request, save: bool = True, **kwargs):
        before_time = time.time()
        try:
            self.streamlit = kwargs.get('streamlit', False)
            if self.streamlit:
                st.write("""# DataScience Assistant """)
                st.write("""### The user request is: \n""")
                st.write(user_request)
            print('streamlit: ', self.streamlit)
            self.plan = self._update_plan(user_request=user_request)
            jupyter_file_path = ''
            dir_name = ''
            if save:
                dir_name = 'data/' + str(
                    datetime.now().strftime('%Y-%m-%d-%H-%M-%S')) + '/'
                if not os.path.exists(dir_name):
                    os.makedirs(dir_name)
                jupyter_file_path = dir_name + 'result' + '.ipynb'

            while self.plan.current_task_id:
                task = self.plan.task_map.get(self.plan.current_task_id)
                if self.streamlit:
                    st.write(
                        f"""### Task {task.task_id}: {task.instruction}\n""")
                logger.info(
                    f'new task starts: task_{task.task_id} , instruction: {task.instruction}'
                )
                previous_code_blocks = self._get_previous_code_blocks()
                success = False
                code_counter = 0
                max_try = kwargs.get('max_try', 1)
                while not success and code_counter < max_try:
                    code_execute_success = False
                    code_logic_success = False
                    temp_code_interpreter = CodeInterpreter()
                    temp_code_interpreter.call(
                        params=json.dumps({
                            'code':
                            self._get_previous_code_blocks_without_outputs()
                        }),
                        nb_mode=True,
                        silent_mode=True)
                    # generate code
                    code = self._generate_code(code_counter, task,
                                               user_request)
                    code = '%matplotlib inline \n' + code
                    code_execute_success, code_interpreter_resp = temp_code_interpreter.call(
                        params=json.dumps({'code': code}),
                        nb_mode=True,
                        silent_mode=True)
                    if self.streamlit:
                        st.divider()
                        st_notebook = nbformat.v4.new_notebook()
                        st_notebook.cells = [
                            temp_code_interpreter.nb.cells[-1]
                        ]
                        c = Config()
                        c.HTMLExporter.preprocessors = [
                            'nbconvert.preprocessors.ConvertFiguresPreprocessor'
                        ]
                        # create the new exporter using the custom config
                        html_exporter_with_figs = HTMLExporter(config=c)
                        (html, resources_with_fig
                         ) = html_exporter_with_figs.from_notebook_node(
                             st_notebook)
                        st.write(
                            'We have generated the code for the current task')
                        st.html(html)
                    judge_resp = ''
                    if not code_execute_success:
                        logger.error(
                            f'code execution failed, task{task.task_id} code_counter{code_counter}:\n '
                            f'{code_interpreter_resp}')
                        if self.streamlit:
                            st.write(
                                'The code execution failed. Now we will take a reflection and regenerate the code.'
                            )
                    else:
                        logger.info(
                            f'code execution success, task{task.task_id} code_counter{code_counter}:\n '
                            f'{code_interpreter_resp}')
                        if self.streamlit:
                            st.write(
                                'The code execution is successful. Now we will ask the judge to check the code.'
                            )
                        code_logic_success, judge_resp = self._judge_code(
                            task=task,
                            previous_code_blocks=previous_code_blocks,
                            code=code,
                            code_interpreter_resp=code_interpreter_resp)
                        if self.streamlit:
                            st.write(
                                'The judge has checked the code, here is the result.'
                            )
                            st.write(judge_resp)
                    success = code_execute_success and code_logic_success
                    task.code_cells.append(
                        CodeCell(
                            code=code,
                            result=code_interpreter_resp + '\n' + judge_resp,
                            is_success=False))

                    if success:
                        self.code_interpreter.call(
                            params=json.dumps({'code': code}), nb_mode=True)
                        if self.streamlit:
                            st.write(
                                'The code is correct, we will move to the next task.'
                            )
                        task.code = code
                        task.result = code_interpreter_resp
                    code_counter += 1

                    # save the successful code in jupyter notebook
                if success:
                    self.plan.finish_current_task()
                    if save:
                        with open(
                                jupyter_file_path, 'w',
                                encoding='utf-8') as file:
                            nbformat.write(self.code_interpreter.nb, file)
                else:
                    decomposed_tasks = self._decompose_task(task)
                    if decomposed_tasks:
                        self.plan.replace_task(task, decomposed_tasks)
                    else:
                        self.plan = self._update_plan(
                            user_request=user_request, curr_plan=self.plan)
                        self.code_interpreter.reset()
            # save the plan into json file
            if save:
                after_time = time.time()
                time_cost = after_time - before_time
                total_token = self.total_token
                plan_dict = {
                    'time_cost': time_cost,
                    'llm': self.llm.model,
                    'total_token': total_token,
                    'plan': self.plan.tasks
                }
                print(f'plan_dict: {str(plan_dict)}')
                try:
                    with open(
                            dir_name + 'plan.json', 'w',
                            encoding='utf-8') as file:
                        file.write(
                            json.dumps(plan_dict, indent=4, cls=TaskEncoder))
                except Exception as e:
                    print(f'json write error: {str(e)}')
                if self.streamlit:
                    st.divider()
                    st.write('### We have finished all the tasks! ')
                    st.balloons()
                    st.write(
                        f"""#### The total time cost is: {time_cost}\n #### The total token cost is: {total_token}"""
                    )

        except Exception as e:
            logger.error(f'error: {e}')
            raise e

    def _get_total_tokens(self):
        try:
            logger.info(f'usage: {str(self.llm.get_usage())}')
            self.total_token += self.llm.get_usage().get('total_tokens')
            logger.info(f'total token: {self.total_token}')
        except Exception as e:
            logger.error(f'get total token error: {e}')
        pass

    def _decompose_task(self, task):
        try:
            print(f'decompose task {task.task_id}')
            messages = [{
                'role':
                'user',
                'content':
                DECOMPOSE_TASK_TEMPLATE.format(
                    context='User Request: ' + task.instruction + '\n',
                    previous_tasks='\n'.join([
                        json.dumps({
                            'task_id': t.task_id,
                            'dependent_task_ids': t.dependent_task_ids,
                            'instruction': t.instruction,
                            'task_type': t.task_type
                        }) for t in self.plan.tasks
                    ]),
                    current_task=json.dumps({
                        'task_id': task.task_id,
                        'dependent_task_ids': task.dependent_task_ids,
                        'instruction': task.instruction,
                        'task_type': task.task_type
                    }))
            }]
            resp = self._call_llm(prompt=None, messages=messages, stop=None)
            tasks_text = ''
            for r in resp:
                tasks_text += r
            tasks_text = parse_code(text=tasks_text, lang='json')
            logger.info(f'decomposed tasks: {tasks_text}')

            tasks = json5.loads(tasks_text)
            tasks = [Task(**task) for task in tasks]
            return tasks
        except Exception as e:
            logger.error(f'decompose task error: {e}')
            return None
