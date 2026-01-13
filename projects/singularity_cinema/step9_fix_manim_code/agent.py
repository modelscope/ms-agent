# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Union

import json
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class FixManimCode(CodeAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        self.num_parallel = getattr(self.config, 'llm_num_parallel', 10)
        self.code_fix_dir = os.path.join(self.work_dir, 'code_fix')
        os.makedirs(self.code_fix_dir, exist_ok=True)

    async def execute_code(self, messages: Union[str, List[Message]],
                           **kwargs) -> List[Message]:
        logger.info('Fixing manim code.')
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)

        manim_code_dir = os.path.join(self.work_dir, 'manim_code')
        manim_code = []
        pre_errors = []
        pre_error_mode = False
        for i in range(len(segments)):
            with open(os.path.join(manim_code_dir, f'segment_{i+1}.py'),
                      'r') as f:
                manim_code.append(f.read())
            error_file = os.path.join(self.code_fix_dir,
                                      f'code_fix_{i + 1}.txt')
            if os.path.exists(error_file):
                pre_error_mode = True
                with open(error_file, 'r') as _f:
                    pre_error = _f.read()
                    pre_error = pre_error or ''
            else:
                pre_error = None
            pre_errors.append(pre_error)
        assert len(manim_code) == len(segments)
        if pre_error_mode:
            pre_errors = [e or '' for e in pre_errors]
            assert len(pre_errors) == len(segments)
        else:
            pre_errors = [None] * len(segments)

        tasks = [(i, pre_error, code)
                 for i, (code,
                         pre_error) in enumerate(zip(manim_code, pre_errors))
                 if code]
        results = {}

        with ThreadPoolExecutor(max_workers=self.num_parallel) as executor:
            futures = {
                executor.submit(self._process_single_code_static, i, pre_error,
                                code, self.config): i
                for i, pre_error, code in tasks
            }
            for future in as_completed(futures):
                i, code = future.result()
                results[i] = code

        final_results = [(i, results.get(i, '')) for i in range(len(segments))]

        if pre_error_mode:
            shutil.rmtree(self.code_fix_dir, ignore_errors=True)
        for (i, code) in final_results:
            manim_file = os.path.join(manim_code_dir, f'segment_{i + 1}.py')
            with open(manim_file, 'w') as f:
                f.write(code)

        return messages

    @staticmethod
    def _process_single_code_static(i, pre_error, code, config):
        """Static method for multiprocessing"""
        if not code:
            return i, ''

        llm = LLM.from_config(config)
        if pre_error is not None:
            logger.info(f'Try to fix pre defined error for segment {i+1}')
            if pre_error:
                logger.info(f'Fixing pre error of segment {i+1}: {pre_error}')
                code = FixManimCode._fix_code_impl(llm, pre_error, code)
                logger.info(f'Fix pre error of segment {i + 1} done')
        return i, code

    @staticmethod
    def _fix_code_impl(llm, fix_prompt, manim_code):
        fix_request = f"""
{fix_prompt}

**Original Code**:
```python
{manim_code}
```

- Please focus on solving the detected issues
- Keep the good parts, only fix problematic areas
- Ensure no new layout issues are introduced
- If some issues are difficult to solve, prioritize the most impactful ones
- Make minimal code changes to fix the issue while keeping the correct parts unchanged
- The code may contain images & image effects, such as glowing or frames - **don't remove them when making modifications**
- Do not use SVGMobject("magnifying_glass") or any other built-in SVG names that might not exist. If you need an icon, use a simple geometric shape (like a Circle with a Line handle) or check if an image file is provided.

Please precisely fix the detected issues while maintaining the richness and creativity of the animation.
""" # noqa
        inputs = [Message(role='user', content=fix_request)]
        _response_message = llm.generate(inputs)
        response = _response_message.content
        if '```python' in response:
            manim_code = response.split('```python')[1].split('```')[0]
        elif '```' in response:
            manim_code = response.split('```')[1].split('```')[0]
        else:
            manim_code = response

        return manim_code
