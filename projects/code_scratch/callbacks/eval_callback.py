# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import subprocess
from contextlib import contextmanager
from typing import List, Optional

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
        self.compile_round = 300
        self.cur_round = 0
        self.last_issue_length = 0
        self.devtool_prompt = getattr(config.prompt, 'devtool', None)

    async def on_task_begin(self, runtime: Runtime, messages: List[Message]):
        self.omit_intermediate_messages(messages)
        await self.file_system.connect()

    def omit_intermediate_messages(self, messages: List[Message]):
        messages[2].tool_calls = None
        tmp = messages[:3]
        if self.last_issue_length > 0:
            tmp += messages[-self.last_issue_length:]
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
    def _parse_e_msg(e):
        stdout = None
        stderr = None
        if hasattr(e, 'stdout'):
            stdout = e.stdout
            if hasattr(stdout, 'decode'):
                stdout = stdout.decode('utf-8')
        if hasattr(e, 'stderr'):
            stderr = e.stderr
            if hasattr(stderr, 'decode'):
                stderr = stderr.decode('utf-8')
        result = ''
        if stdout or stderr:
            result += (stdout or '') + '\n' + (stderr or '')
        else:
            result += str(e)
        return result

    @staticmethod
    def check_install():
        try:
            result = subprocess.run(['npm', 'install'],
                                    capture_output=True,
                                    text=True,
                                    check=True)
        except subprocess.CalledProcessError as e:
            output = EvalCallback._parse_e_msg(e)
        else:
            output = result.stdout + '\n' + result.stderr
        return output

    @staticmethod
    def check_runtime():
        try:
            result = subprocess.run(['npm', 'run', 'dev'],
                                    capture_output=True,
                                    text=True,
                                    timeout=5,
                                    stdin=subprocess.DEVNULL)
        except subprocess.CalledProcessError as e:
            output = EvalCallback._parse_e_msg(e)
        except subprocess.TimeoutExpired as e:
            output = EvalCallback._parse_e_msg(e)
        else:
            output = result.stdout + '\n' + result.stderr
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
        return input('>>>')

    async def on_generate_response(self, runtime: Runtime,
                                   messages: List[Message]):
        if messages[-1].tool_calls or messages[-1].role == 'tool':  # noqa
            # subtask or tool-calling or tool response, skip
            return

        self.last_issue_length = len(messages) - 3 - self.last_issue_length
        self.omit_intermediate_messages(messages)
        query = self.get_compile_feedback('frontend').strip()

        # compile -> devtools
        if not query:
            feedback_type = 'devtools'
            query = self.devtool_prompt
            self.devtool_prompt = 'Use chrome-devtools to thoroughly test again'
        else:
            feedback_type = 'compling'
            logger.warn(f'[Compile Feedback]: {query}]')

        # devtools -> human
        if not query:
            feedback_type = 'human'
            query = self.get_human_feedback().strip()

        if not query:
            self.feedback_ended = True
            feedback = (
                'The project now runs Ok, you do not need to do any check of fix.'
            )
        else:
            all_local_files = await self.file_system.list_files()
            feedback = (
                f'Feedback from {feedback_type}: {query}\n'
                f'The files on the local system of this project: {all_local_files}\n'
                f'Now please analyze and fix this issue:\n')
        messages.append(Message(role='user', content=feedback))
        logger.info(messages)

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        runtime.should_stop = runtime.should_stop and self.feedback_ended
