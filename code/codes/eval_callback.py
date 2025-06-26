# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import subprocess
import sys
from contextlib import contextmanager
from typing import List, Optional

from file_parser import extract_code_blocks
from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.tools.filesystem_tool import FileSystemTool
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class EvalCallback(Callback):
    """Eval the code by compiling and human eval.
    """

    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.feedback_ended = False
        self.file_system = FileSystemTool(config)
        self.compile_round = 20
        self.cur_round = 0

    async def on_task_begin(self, runtime: Runtime, messages: List[Message]):
        self.omit_intermediate_messages(messages)
        await self.file_system.connect()

    @staticmethod
    def omit_intermediate_messages(messages: List[Message]):
        messages[2].tool_calls = None
        tmp = messages[:3]
        messages.clear()
        messages.extend(tmp)

    @contextmanager
    def chdir_context(self, folder: Optional[str] = None):
        path = os.getcwd()
        work_dir = getattr(self.config, 'output_dir', 'output')
        if folder is not None:
            work_dir = os.path.join(work_dir, folder)
        if not path.endswith(work_dir):
            os.chdir(work_dir)
            yield
            os.chdir(path)
        else:
            yield

    @staticmethod
    def check_install():
        try:
            result = subprocess.run(['npm', 'install'],
                                    capture_output=True,
                                    text=True,
                                    check=True)
        except subprocess.CalledProcessError as e:
            output = (e.stdout.decode('utf-8') if e.stdout else '') + '\n' + (
                e.stderr.decode('utf-8') if e.stderr else '')
        else:
            output = result.stdout + '\n' + result.stderr
        return output

    @staticmethod
    def check_runtime():
        try:
            os.system('pkill -f node')
            result = subprocess.run(['npm', 'run', 'dev'],
                                    capture_output=True,
                                    text=True,
                                    timeout=5,
                                    stdin=subprocess.DEVNULL)
        except subprocess.CalledProcessError as e:
            output = (e.stdout.decode('utf-8') if e.stdout else '') + '\n' + (
                e.stderr.decode('utf-8') if e.stderr else '')
        except subprocess.TimeoutExpired as e:
            output = (e.stdout.decode('utf-8') if e.stdout else '') + '\n' + (
                e.stderr.decode('utf-8') if e.stderr else '')
        else:
            output = result.stdout + '\n' + result.stderr
        os.system('pkill -f node')
        return output

    def _run_compile(self):
        if self.cur_round >= self.compile_round:
            return ''
        checks = [self.check_install, self.check_runtime]
        for check in checks:
            output = check()
            if 'failed' not in output.lower() and 'error' not in output.lower(
            ) or 'address already in use' in output.lower():
                pass
            else:
                self.cur_round += 1
                return output
        return ''

    def get_compile_feedback(self, folder: Optional[str] = None):
        with self.chdir_context(folder):
            return self._run_compile()

    def get_human_feedback(self):
        self.cur_round = 0
        return input('>>> Feedback:')

    async def do_arch_update(self, runtime: Runtime, messages: List[Message],
                             updated_arch: str):
        _arch_update_system = """You are an assistant that helps architect maintain and update PRDs & code architectures. The architect's workflow is:

1. Design PRD & architecture based on original requirements
2. Allocate tasks to complete requirements according to PRD & code architecture
3. Fix bugs or add new requirements based on user feedback

However, when fixing bugs or adding new requirements, it may involve the updating the PRD & code architecture.
Next, I will provide you with the original design and the parts that need to be updated.
You need to help me merge these two parts into a complete design.

Your instructions to follow:
1. Accurately assess which parts of the original design need to be modified&merged based on the updates,
and carefully merge them without missing any information
2. Avoid making the PRD & code architecture increasingly lengthy after merging - you need to avoid redundant information
3. Discard any content which does not belong to PRD & architecture, like:
    * Imprecise information
    * Problem description
    * Temporary bug fixing approach
3. Your output format should be:

```text:design.txt
... your merged and refined architectural design here ...
```

Now let's begin:
"""
        query = (f'The system of the architect is: \n\n'
                 f'{messages[0].content}\n\n'
                 f'The original query is :\n\n'
                 f'{messages[1].content}\n\n'
                 f'The original PRD & architectural design is :\n\n'
                 f'{messages[2].content}\n\n'
                 f'The updated part of PRD & architectural design is:\n\n'
                 f'{updated_arch}\n\n'
                 f'Now merge the 2 parts of PRD & architectural design:\n')

        _messages = [
            Message(role='system', content=_arch_update_system),
            Message(role='user', content=query),
        ]
        logger.info('[Arch Updater]: ')
        _content = ''
        for _response_message in runtime.llm.generate(_messages):
            new_content = _response_message.content[len(_content):]
            sys.stdout.write(new_content)
            sys.stdout.flush()
            _content = _response_message.content

        front, design = _response_message.content.split(
            '```text:design.txt', maxsplit=1)  # noqa
        design, end = design.rsplit('```', 1)
        return design

    async def is_feature(self, runtime: Runtime, query: str) -> bool:
        _classify_system = """You are an assistant help me to identify whether a feedback is an issue or a new feature.

You need to follow these instructions:
1. Only return as an issue when it's a pure bug. If the feedback contains any new feature requirements,
define it as a feature.
2. Return only `issue` or `feature`, do not return anything else.

Now begin:
"""
        _messages = [
            Message(role='system', content=_classify_system),
            Message(role='user', content=query),
        ]
        _response_message = runtime.llm.generate(_messages, stream=False)
        for line in _response_message.content.split('\n'):
            for _line in line.split('\\n'):
                logger.info(f'[Arch Updater] {_line}')

        return 'feature' in _response_message.content.lower()

    async def on_generate_response(self, runtime: Runtime,
                                   messages: List[Message]):
        if messages[-1].tool_calls or messages[-1].role == 'tool':  # noqa
            # subtask or tool-calling or tool response, skip
            return

        self.omit_intermediate_messages(messages)
        query = None
        if self.config.name == 'agent.yaml':
            # agent.yaml mainly for react and node.js
            query = self.get_compile_feedback('frontend').strip()
            if not query:
                query = self.get_compile_feedback('backend').strip()
        if not query:
            human_feedback = True
            query = self.get_human_feedback().strip()
        else:
            human_feedback = False
        if not query:
            self.feedback_ended = True
            feedback = (
                'You have called `split_to_sub_task` to generate this project, '
                'but call and response of `split_to_sub_task` messages are omitted. '
                'The project runs Ok, you do not need to do any check of fix.')
        else:
            all_local_files = await self.file_system.list_files()
            is_feature = False
            if human_feedback:
                is_feature = await self.is_feature(runtime, query)
            if is_feature:
                step2 = """Step 2. Update your history architectural.

For example:

//Place your thinking, fix implementations here
To fix this bug, the ... module need to add ... fix ... replace ...

```text:design.txt
//Only place the actual changes of architecture here, you only need to output the **changed** parts,
and mark clearly how to update.
1. Add Route ...
2. Add new files ...
3. User interface changed to ...
```

After output design.txt, call `split_to_sub_task` again to correct the abnormal files or implement the new features.
"""

            else:
                step2 = """Step 2. Call `split_to_sub_task` again to correct the abnormal files.
"""

            feedback = f"""Here is a feedback:

{query}

You have called `split_to_sub_task` to generate this project, the call and response of `split_to_sub_task` messages are omitted, the actual generated files existing on the filesystem are:

{all_local_files}

These files may be not matched with your PRD & design, consider the actual files first.

Detect then conduct a complete report to identify which code file needs to be corrected and how to correct them.
The instructions for problem checking and fixing:
Step 1. First call `split_to_sub_task` at least once to start some subtasks to collect detailed problems from all the related files

An example of your query:

```
You are a subtask to collect information for me, the user feedback is ..., you need to read the ... file and find the root cause, remember you are a evaluator, not a programmer, do not write code, just collect information.
```

You need to consider both the frontend and backend files, some error happens because the http interfaces are not matched between them.

{step2}

**You need to remind the subtask do a minimum change in case that the normal code is damaged**

An example of your query:

```
The problem/feature is ..., you need to fix/implement ... file and ... file, read the existing code file first, then do a minimum change to prevent the damages to the functionalities which work normally.
```

After updating, you do not need to verify or run `npm install/build`, the build/user feedback will be given to you automatically.
""" # noqa
        messages.append(Message(role='user', content=feedback))

    async def after_generate_response(self, runtime: Runtime,
                                      messages: List[Message]):
        design, _ = extract_code_blocks(
            messages[-1].content, target_filename='design.txt')
        if len(design) > 0:
            front, design = messages[-1].content.split(
                '```text:design.txt', maxsplit=1)
            design, end = design.rsplit('```', 1)
            design = design.strip()
            if design:
                messages[2].content = await self.do_arch_update(
                    runtime=runtime, messages=messages, updated_arch=design)

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        runtime.should_stop = runtime.should_stop and self.feedback_ended
