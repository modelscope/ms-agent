# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Union

import json
from ms_agent.agent import CodeAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class FixRemotionCode(CodeAgent):

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
        logger.info('Fixing remotion code.')
        with open(os.path.join(self.work_dir, 'segments.txt'), 'r') as f:
            segments = json.load(f)

        remotion_code_dir = os.path.join(self.work_dir, 'remotion_code')
        remotion_code = []
        pre_errors = []
        pre_error_mode = False
        for i in range(len(segments)):
            file_path = os.path.join(remotion_code_dir, f'Segment{i+1}.tsx')
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    remotion_code.append(f.read())
            else:
                remotion_code.append('')

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

        if pre_error_mode:
            pre_errors = [e or '' for e in pre_errors]
        else:
            pre_errors = [None] * len(segments)

        tasks = [
            (i, pre_error, code)
            for i, (code,
                    pre_error) in enumerate(zip(remotion_code, pre_errors))
            if code
        ]
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
            if code:
                remotion_file = os.path.join(remotion_code_dir,
                                             f'Segment{i + 1}.tsx')
                with open(remotion_file, 'w', encoding='utf-8') as f:
                    f.write(code)

        return messages

    @staticmethod
    def _process_single_code_static(i, pre_error, code, config):
        """Static method for multiprocessing"""
        if not code:
            return i, ''
        # First, attempt a fast deterministic auto-fix for common template/parens issues
        fixed_code = FixRemotionCode._auto_fix_template_parens(code)
        fixed_code = FixRemotionCode._auto_fix_common_concat_syntax(fixed_code)
        if fixed_code != code:
            logger.info(
                f'Auto-fixed template parenthesis issues for segment {i+1}')
            # If we could auto-fix, return the fixed code and skip LLM to save cost
            return i, fixed_code

        llm = LLM.from_config(config)
        if pre_error is not None:
            logger.info(f'Try to fix pre defined error for segment {i+1}')
            if pre_error:
                logger.info(f'Fixing pre error of segment {i+1}: {pre_error}')
                code = FixRemotionCode._fix_code_impl(llm, pre_error, code)
                logger.info(f'Fix pre error of segment {i + 1} done')
        return i, code

    @staticmethod
    def _auto_fix_template_parens(code: str) -> str:
        """
        Auto-fix mismatched parentheses and convert template literals to avoid build errors.
        """

        # 1. Fix mismatched parentheses.
        def _repair(match):
            inner = match.group(1)
            open_parens = inner.count('(')
            close_parens = inner.count(')')
            if open_parens > close_parens:
                inner = inner + (')' * (open_parens - close_parens))
            return '${' + inner + '}'

        try:
            code = re.sub(r'\$\{([^}]*)\}', _repair, code)
        except Exception:
            pass

        # 2. Convert transform template literals to string concatenation.
        # This replaces `transform: ...${...}...` with simple string concatenation.

        def _replace_transform(match):
            # match.group(0) is the whole line or block
            # We want to extract the interpolate call and the surrounding text
            full_str = match.group(0)
            if 'interpolate' in full_str and 'transform' in full_str:
                # Replace backticks and template expressions.

                # Check if it's a backtick string
                if '`' in full_str:
                    # Replace backticks with single quotes
                    fixed = full_str.replace('`', "'")
                    # Replace ${ with ' + ( to handle ternary operators safely
                    fixed = fixed.replace('${', "' + (")
                    # Replace } with ) + '
                    fixed = fixed.replace('}', ") + '")
                    # Clean up empty strings: ' + ' -> +
                    fixed = fixed.replace("'' + ", '')
                    fixed = fixed.replace(" + ''", '')
                    return fixed
            return full_str

        # Regex to find transform properties with backticks
        # transform:\s*`[^`]*`
        try:
            code = re.sub(r'transform:\s*`[^`]*`', _replace_transform, code)
        except Exception:
            pass

        return code

    @staticmethod
    def _auto_fix_common_concat_syntax(code: str) -> str:
        """
        Auto-fix common malformed string concatenations that break esbuild.
        """

        # 1. Fix interpolate(..., { ... )) -> interpolate(..., { ... })
        # Removed aggressive auto-repair.
        # try:
        #     code = re.sub(r'(interpolate\s*\([^)]*\{[^})]*)\)', r'\1})', code)
        # except Exception:
        #     pass

        def _extract_balanced_parens(s: str, start_idx: int) -> str:
            """Return substring from start_idx to matching closing ')' (inclusive)."""
            depth = 0
            in_single = False
            in_double = False
            escaped = False
            for j in range(start_idx, len(s)):
                ch = s[j]
                if escaped:
                    escaped = False
                    continue
                if ch == '\\':
                    escaped = True
                    continue
                if ch == "'" and not in_double:
                    in_single = not in_single
                    continue
                if ch == '"' and not in_single:
                    in_double = not in_double
                    continue
                if in_single or in_double:
                    continue
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0:
                        return s[start_idx:j + 1]
            return ''

        def _fix_transform_line(line: str) -> str:
            if 'transform' not in line or 'interpolate(' not in line:
                return line

            # Only target already-string-based transforms (not template literals handled elsewhere)
            if '`' in line:
                return line

            func = None
            unit = None
            if "'translateY('" in line:
                func = 'translateY'
                unit = 'px'
            elif "'translateX('" in line:
                func = 'translateX'
                unit = 'px'
            elif "'rotate('" in line:
                func = 'rotate'
                unit = 'deg'

            if not func or not unit:
                return line

            idx = line.find('interpolate(')
            call = _extract_balanced_parens(line, idx)
            if not call:
                return line

            indent = re.match(r'^\s*', line).group(0)
            trailing_comma = ',' if line.rstrip().endswith(',') else ''
            return f"{indent}transform: '{func}(' + {call} + '{unit})'{trailing_comma}"

        try:
            lines = code.splitlines()
            lines = [_fix_transform_line(ln) for ln in lines]
            code = '\n'.join(lines)
        except Exception:
            pass

        # Fix common fps typo introduced by LLM
        # `useVideoConfig()` returns `fps`, not `FPS`.
        try:
            code = re.sub(r'\bfps\s*:\s*FPS\b', 'fps: fps', code)
        except Exception:
            pass

        return code

    @staticmethod
    def _fix_code_impl(llm, fix_prompt, code):
        fix_request = f"""
{fix_prompt}

**Original Code**:
```typescript
{code}
```

- Please focus on solving the detected issues
- Keep the good parts, only fix problematic areas
- Ensure no new layout issues are introduced
- Make minimal code changes to fix the issue while keeping the correct parts unchanged
- The output must be a valid React Functional Component.

**CRITICAL FIXING RULES**:
1. **React Error #130 (Objects as children)**: If the error mentions "Objects are not valid as a React child",
   check for variables being rendered directly (e.g. `<div>{{style}}</div>`).
   Change them to render properties (e.g. `<div>{{style.width}}</div>`).
2. **Remotion Interpolate Error**: If the error mentions "outputRange must contain only numbers",
   check your `interpolate` calls.
   Ensure `outputRange` has consistent types (all numbers OR all strings with same unit).
3. **Black Screen / Missing Assets**: If the error mentions "Visual Check Failed" or "Missing Assets", ensure:
    - `opacity` is 1.
    - `zIndex` is high enough.
    - Images are actually used (`<Img src={{staticFile(...)}} />`).

Please precisely fix the detected issues.
"""
        inputs = [Message(role='user', content=fix_request)]
        _response_message = llm.generate(inputs)
        response = _response_message.content

        # Robust code extraction using regex
        code_match = re.search(
            r'```(?:typescript|tsx|js|javascript)?\s*(.*?)```', response,
            re.DOTALL)
        if code_match:
            code = code_match.group(1)
        else:
            code = response
            if 'import React' in code:
                idx = code.find('import React')
                code = code[idx:]

        return code.strip()
