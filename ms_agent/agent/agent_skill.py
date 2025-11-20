# Copyright (c) Alibaba, Inc. and its affiliates.
import os.path
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import json
from ms_agent.llm import Message
from ms_agent.llm.openai_llm import OpenAI as OpenAILLM
from ms_agent.skill.loader import load_skills
from ms_agent.skill.prompts import (PROMPT_SKILL_PLAN, PROMPT_SKILL_TASKS,
                                    PROMPT_TASKS_IMPLEMENTATION,
                                    SCRIPTS_IMPLEMENTATION_FORMAT)
from ms_agent.skill.retrieve import create_retriever
from ms_agent.skill.schema import ExecutionResult, SkillContext, SkillSchema
from ms_agent.skill.skill_utils import (copy_with_exec_if_script,
                                        extract_cmd_from_code_blocks,
                                        extract_implementation,
                                        extract_packages_from_code_blocks,
                                        find_skill_dir)
from ms_agent.utils.logger import logger
from ms_agent.utils.utils import install_package, str_to_md5, valid_repo_id
from omegaconf import DictConfig, OmegaConf


class AgentSkill:
    """
    LLM Agent with progressive skill loading mechanism.

    Implements a multi-level progressive context loading and processing mechanism:
        1. Level 1 (Metadata): Load all skill names and descriptions
        2. Level 2 (Retrieval): Retrieve and load SKILL.md when relevant with the query
        3. Level 3 (Resources): Load additional files (references, scripts, resources) only when referenced in SKILL.md
        4. Level 4 (Analysis and Execution): Analyze the loaded skill context and execute scripts as needed
    """

    def __init__(self,
                 skills: Union[str, List[str], List[SkillSchema]],
                 model: str,
                 api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 stream: Optional[bool] = True,
                 enable_thinking: Optional[bool] = False,
                 max_tokens: Optional[int] = 8192,
                 work_dir: str = None,
                 use_sandbox: bool = True,
                 **kwargs):
        """
        Initialize Agent Skills.

        Args:
            skills: Path(s) to skill directories,
                the root path of skill directories, list of SkillSchema, or skill IDs on the hub.
                If using skill IDs on the hub, refer to `https://modelscope.cn/models/ms-agent/skill_examples`
            api_key: OpenAI API key
            base_url: Custom API base URL
            model: LLM model name
            stream: Whether to stream responses
            work_dir: Working directory.
            use_sandbox: Whether to use sandbox environment for script execution.
                If True, scripts will be executed in the `ms-enclave` sandbox environment.
                If False, scripts will be executed directly in the local environment.
        """
        self.work_dir: Path = Path(work_dir) if work_dir else Path.cwd()
        os.makedirs(self.work_dir, exist_ok=True)

        self.stream: bool = stream
        self.use_sandbox: bool = use_sandbox
        self.kwargs = kwargs

        if not self.use_sandbox:
            logger.warning(
                'The `use_sandbox` is False, scripts will be executed in the local environment. '
                'Make sure to trust the skills being executed!')

        # Preprocess skills
        skills = self._preprocess_skills(skills=skills)

        # Pre-load all skills, the key is "skill_id@version"
        self.all_skills: Dict[str, SkillSchema] = load_skills(skills=skills)
        logger.info(f'Loaded {len(self.all_skills)} skills from {skills}')

        # Initialize retriever
        self.retriever = create_retriever(skills=self.all_skills, )

        # Initialize OpenAI client
        api_key = api_key or os.getenv('OPENAI_API_KEY')
        base_url = base_url or os.getenv('OPENAI_BASE_URL')
        _conf: DictConfig = OmegaConf.create({
            'llm': {
                'model': model,
                'openai_base_url': base_url,
                'openai_api_key': api_key,
            },
            'generation_config': {
                'stream': stream,
                'extra_body': {
                    'enable_thinking': enable_thinking,
                },
                'max_tokens': max_tokens,
            }
        })

        self.llm = OpenAILLM(_conf)

        # Initialize sandbox environment
        if self.use_sandbox:
            self.sandbox, self.work_dir_in_sandbox = self._init_sandbox()

        logger.info('Agent Skills initialized successfully')

    def _preprocess_skills(
        self, skills: Union[str, List[str], List[SkillSchema]]
    ) -> Union[str, List[str], List[SkillSchema]]:
        """
        Preprocess skills by copying them to the working directory.

        Args:
            skills: Path(s) to skill directories,
                the root path of skill directories, list of SkillSchema, or skill IDs on the hub

        Returns:
            Processed skills in the working directory.
        """
        results: Union[str, List[str], List[SkillSchema]] = []

        if isinstance(skills, str):
            skills = [skills]

        if skills is None or len(skills) == 0:
            return results

        if isinstance(skills[0], SkillSchema):
            return skills

        # Process skill IDs on the hub
        if isinstance(skills[0], str) and valid_repo_id(
                skills[0]) and not os.path.exists(skills[0]):
            from modelscope import snapshot_download

            skill_cache_dirs: List[str] = []
            for skill_id in skills:
                skill_id_parts: List[str] = skill_id.split('/')
                subfolder = skill_id_parts[-1] if len(
                    skill_id_parts) == 3 else None
                allow_pattern: str = f'{subfolder}/*' if subfolder else None
                skill_id = '/'.join(
                    skill_id_parts[:2]) if subfolder else skill_id

                skill_dir: str = snapshot_download(
                    repo_id=skill_id,
                    allow_patterns=allow_pattern,
                )
                logger.info(
                    f'Downloaded skill from hub: {skill_id} to {skill_dir}')
                skill_cache_dirs.append(skill_dir)

            skills = skill_cache_dirs

        skill_paths: List[str] = find_skill_dir(skills)

        for skill_path in skill_paths:
            path_in_workdir = os.path.join(
                str(self.work_dir),
                Path(skill_path).name)
            if os.path.exists(path_in_workdir):
                shutil.rmtree(path_in_workdir, ignore_errors=True)
            os.makedirs(path_in_workdir, exist_ok=True)
            shutil.copytree(
                skill_path,
                path_in_workdir,
                copy_function=copy_with_exec_if_script,
                dirs_exist_ok=True)

            results.append(path_in_workdir)

        return results

    def _init_sandbox(self):
        """
        Initialize the sandbox environment.

        Returns:
            Tuple of (sandbox_instance, work_dir_in_sandbox)
        """
        from ms_agent.sandbox import EnclaveSandbox

        work_dir_in_sandbox = '/sandbox'
        mode: str = 'rw'

        sandbox = EnclaveSandbox(
            image=self.kwargs.pop('sandbox_image', None) or 'python:3.11-slim',
            memory_limit=self.kwargs.pop('sandbox_memory_limit', None)
            or '512m',
            volumes=[
                (self.work_dir, work_dir_in_sandbox, mode),
            ])

        return sandbox, work_dir_in_sandbox

    def _build_skill_context(self, skill: SkillSchema) -> SkillContext:

        skill_context: SkillContext = SkillContext(
            skill=skill,
            root_path=self.work_dir,
        )

        return skill_context

    def _call_llm(self,
                  user_prompt: str,
                  system_prompt: str = None,
                  stream: bool = True) -> str:

        default_system: str = 'You are an intelligent assistant that can help users by leveraging specialized skills.'
        system_prompt = system_prompt or default_system

        messages = [
            Message(role='assistant', content=system_prompt),
            Message(role='user', content=user_prompt),
        ]
        resp = self.llm.generate(
            messages=messages,
            stream=stream,
        )

        _content = ''
        is_first = True
        _response_message = None
        for _response_message in resp:
            if is_first:
                messages.append(_response_message)
                is_first = False
            new_content = _response_message.content[len(_content):]
            sys.stdout.write(new_content)
            sys.stdout.flush()
            _content = _response_message.content
            messages[-1] = _response_message
        sys.stdout.write('\n')

        return _content

    def run(self, query: str) -> str:
        """
        Run the agent skill with the given query.

        Args:
            query: User query string

        Returns:
            Agent response string
        """
        logger.info(
            f'Received user query: {query}, starting skill retrieval...')
        # Retrieve relevant skills
        relevant_skills = self.retriever.retrieve(
            query=query,
            method='semantic',
            top_k=5,
        )
        logger.debug(
            f'Retrieved {len(relevant_skills)} relevant skills for query')

        if not relevant_skills:
            logger.warning('No relevant skills found')
            logger.error(
                "I couldn't find any relevant skills for your query. Could you please rephrase or provide more details?"
            )
            return ''

        # Use the most relevant skill
        # TODO: Support multiple skills collaboration
        top_skill_key, top_skill, score = relevant_skills[0]
        logger.info(f'Using skill: {top_skill_key} (score: {score:.2f})')
        skill: SkillSchema = top_skill

        # Build skill context
        skill_context: SkillContext = self._build_skill_context(skill)
        skill_md_context: str = '\n\n<!-- SKILL_MD_CONTEXT -->\n' + skill_context.skill.content.strip(
        )
        reference_context: str = '\n\n<!-- REFERENCE_CONTEXT -->\n' + '\n'.join(
            [
                json.dumps(
                    {
                        'name': ref.get('name', ''),
                        'path': ref.get('path', ''),
                        'description': ref.get('description', ''),
                    },
                    ensure_ascii=False) for ref in skill_context.references
            ])
        script_context: str = '\n\n<!-- SCRIPT_CONTEXT -->\n' + '\n'.join([
            json.dumps(
                {
                    'name': script.get('name', ''),
                    'path': script.get('path', ''),
                    'description': script.get('description', ''),
                },
                ensure_ascii=False) for script in skill_context.scripts
        ])
        resource_context: str = '\n\n<!-- RESOURCE_CONTEXT -->\n' + '\n'.join([
            json.dumps(
                {
                    'name': res.get('name', ''),
                    'path': res.get('path', ''),
                    'description': res.get('description', ''),
                },
                ensure_ascii=False) for res in skill_context.resources
        ])

        # PLAN: Analyse the SKILL.md, references, and scripts.
        prompt_skill_plan: str = PROMPT_SKILL_PLAN.format(
            query=query,
            skill_md_context=skill_md_context,
            reference_context=reference_context,
            script_context=script_context,
            resource_context=resource_context,
        )

        response_skill_plan = self._call_llm(
            user_prompt=prompt_skill_plan,
            stream=self.stream,
        )
        skill_context.spec.plan = response_skill_plan
        logger.info('\n======== Completed Skill Plan Response ========\n')

        # TASKS: Get solutions and tasks based on analysis.
        prompt_skill_tasks: str = PROMPT_SKILL_TASKS.format(
            skill_plan_context=response_skill_plan, )

        response_skill_tasks = self._call_llm(
            user_prompt=prompt_skill_tasks,
            stream=self.stream,
        )
        skill_context.spec.tasks = response_skill_tasks
        logger.info('\n======== Completed Skill Tasks Response ========\n')

        # IMPLEMENTATION & EXECUTION
        script_contents: str = '\n\n'.join([
            '<!-- ' + script.get('path', '') + ' -->\n'
            + script.get('content', '') for script in skill_context.scripts
            if script.get('name', '') in response_skill_tasks
        ])
        reference_contents: str = '\n\n'.join([
            '<!-- ' + ref.get('path', '') + ' -->\n' + ref.get('content', '')
            for ref in skill_context.references
            if ref.get('name', '') in response_skill_tasks
        ])
        resource_contents: str = '\n\n'.join([
            '<!-- ' + res.get('path', '') + ' -->\n' + res.get('content', '')
            for res in skill_context.resources
            if res.get('name', '') in response_skill_tasks
        ])

        prompt_tasks_implementation: str = PROMPT_TASKS_IMPLEMENTATION.format(
            script_contents=script_contents,
            reference_contents=reference_contents,
            resource_contents=resource_contents,
            skill_tasks_context=response_skill_tasks,
            scripts_implementation_format=SCRIPTS_IMPLEMENTATION_FORMAT,
        )

        response_tasks_implementation = self._call_llm(
            user_prompt=prompt_tasks_implementation,
            stream=self.stream,
        )
        skill_context.spec.implementation = response_tasks_implementation

        # Dump the spec files
        spec_output_path = skill_context.spec.dump(
            output_dir=str(self.work_dir))
        logger.info(f'Spec files dumped to: {spec_output_path}')

        # Extract IMPLEMENTATION content and determine execution scenario
        _, implementation_content = extract_implementation(
            content=response_tasks_implementation)

        if not implementation_content or len(implementation_content) == 0:
            logger.error('No IMPLEMENTATION content extracted from response')
            return 'I was unable to determine the implementation steps required to complete your request.'

        else:
            if isinstance(implementation_content[0], dict):
                execute_results: List[dict] = []
                for _code_block in implementation_content:
                    execute_result: ExecutionResult = self.execute(
                        code_block=_code_block,
                        skill_context=skill_context,
                    )
                    execute_results.append(execute_result.to_dict())

                return json.dumps(
                    execute_results, ensure_ascii=False, indent=2)
            elif isinstance(implementation_content[0], tuple):
                # Dump the generated code content to files
                for _lang, _code in implementation_content:
                    if _lang == 'html':
                        file_ext = 'html'
                    elif _lang == 'javascript':
                        file_ext = 'js'
                    else:
                        file_ext = 'md'

                    output_file_path = self.work_dir / f'{str_to_md5(_code)}.{file_ext}'
                    with open(output_file_path, 'w', encoding='utf-8') as f:
                        f.write(_code)
                    logger.info(
                        f'Generated {_lang} file saved to: {output_file_path}')
                return f'Generated files have been saved to the working directory: {self.work_dir}'
            elif isinstance(implementation_content[0], str):
                return '\n\n'.join(implementation_content)
            else:
                logger.error('Unknown IMPLEMENTATION content format')
                return 'I encountered an unexpected format in the implementation steps.'

    def _analyse_code_block(self, code_block: dict,
                            skill_context: SkillContext) -> Dict[str, str]:
        """
        Analyse a code block from a skill context to extract executable command.

        Args:
            code_block: Code block dictionary containing 'script' or 'function' key
                e.g. {{'script': '<script_path>', 'parameters': {{'param1': 'value1', 'param2': 'value2', ...}}}}
            skill_context: SkillContext object

        Returns:
            Dictionary containing:
                'type': 'script' or 'function'
                'code': Executable command string or code block
                'packages': List of required packages
        """
        # type - script or function
        res = {'type': '', 'code': '', 'packages': []}

        # Get the script path
        if 'script' in code_block:
            script_str: str = code_block.get('script')
            parameters: Dict[str, Any] = code_block.get('parameters', {})

            # Get real script absolute path
            script_path: Path = skill_context.root_path / script_str
            if not script_path.exists():
                script_path: Path = skill_context.root_path / 'scripts' / script_str
            if not script_path.exists():
                raise FileNotFoundError(f'Script not found: {script_str}')

            # Read the content of script
            try:
                with open(script_path, 'r', encoding='utf-8') as f:
                    script_content = f.read()

                script_content = script_content.strip()
                if not script_content:
                    raise RuntimeError(f'Script is empty: {script_str}')

                # Build command to execute the script with parameters
                prompt: str = (
                    f'According to following script content and parameters, '
                    f'find the usage for script and output the shell command in the form of: '
                    f'```shell\npython {script_str} ...\n``` with python interpreter. '
                    f'\nExtract the packages required by the script and output them in the form of: ```packages\npackage1\npackage2\n...```. '  # noqa
                    f'Note that you need to exclude the build-in standard library packages, and determine the specific PyPI package name according to the import statements in the script. '  # noqa
                    f'you must output the result very concisely and clearly without any extra explanation.'
                    f'\n\nSCRIPT CONTENT:\n{script_content}'
                    f'\n\nPARAMETERS:\n{json.dumps(parameters, ensure_ascii=False)}'
                )
                response: str = self._call_llm(
                    user_prompt=prompt,
                    system_prompt=
                    'You are a helpful assistant that extracts the shell command from code blocks.',
                    stream=self.stream,
                )

                cmd_blocks = extract_cmd_from_code_blocks(response)
                if len(cmd_blocks) == 0:
                    raise RuntimeError(
                        f'No shell command found in LLM response for script {script_str}'
                    )
                cmd_str = cmd_blocks[0]  # TODO: NOTE

                packages = extract_packages_from_code_blocks(response)

                res['type'] = 'script'
                res['code'] = cmd_str
                res['packages'] = packages

            except Exception as e:
                raise RuntimeError(
                    f'Failed to read script {script_str}: {str(e)}')

        elif 'function' in code_block:
            res['type'] = 'function'
            res['code'] = code_block.get('function')

        else:
            raise ValueError(
                "Code block must contain either 'script' or 'function' key")

        return res

    def execute(self, code_block: Dict[str, Any],
                skill_context: SkillContext) -> ExecutionResult:
        """
        Execute a code block from a skill context.

        Args:
            code_block: Code block dictionary containing 'script' or 'function' key
                e.g. {{'script': '<script_path>', 'parameters': {{'param1': 'value1', 'param2': 'value2', ...}}}}
            skill_context: SkillContext object

        Returns:
            (ExecutionResult) Dictionary containing execution results
        """
        exec_result = ExecutionResult()
        try:
            executable_code: Dict[str, str] = self._analyse_code_block(
                code_block=code_block,
                skill_context=skill_context,
            )
            code_type: str = executable_code.get('type')
            code_str: str = executable_code.get('code')
            packages: list = executable_code.get('packages', [])

            if not code_str:
                raise RuntimeError(
                    'No command to execute extracted from code block')
        except Exception as e:
            logger.error(f'Error analyzing code block: {str(e)}')
            exec_result.success = False
            exec_result.messages = str(e)

            return exec_result

        try:
            if self.use_sandbox:
                if 'script' == code_type:

                    code_split = shlex.split(code_str)
                    new_code_split: List[str] = []
                    for item in code_split[1:]:
                        # All paths should be relative to `self.work_dir`
                        item = os.path.join(
                            str(self.work_dir_in_sandbox),
                            Path(item).as_posix())
                        new_code_split.append(item)
                    code_str = ' '.join(code_split[:1] + new_code_split)

                    results: Dict[str, Any] = self.sandbox.execute(
                        shell_command=code_str,
                        requirements=packages,
                    )
                    return ExecutionResult(
                        success=True,
                        output=results.get('shell_executor', []),
                        messages='Executed in sandbox successfully for script.',
                    )
                elif 'function' == code_type:
                    results: Dict[str, Any] = self.sandbox.execute(
                        python_code=code_str,
                        requirements=packages,
                    )
                    return ExecutionResult(
                        success=True,
                        output=results.get('python_executor', []),
                        messages=
                        'Executed in sandbox successfully for function.',
                    )
                else:
                    raise ValueError(f'Unknown code type: {code_type}')

            else:
                # TODO: Add `confirm manually`
                logger.warning('Executing code block in local environment!')

                # Prepare execution environment
                logger.info(f'Installing required packages: {packages}')
                for pack in packages:
                    install_package(package_name=pack)

                if 'script' == code_type:
                    code_split: List[str] = shlex.split(code_str)
                    new_code_split: List[str] = []
                    for item in code_split[1:]:
                        # All paths should be relative to `self.work_dir`
                        item = os.path.join(
                            str(self.work_dir),
                            Path(item).as_posix())
                        new_code_split.append(item)
                    new_code_split = code_split[:1] + new_code_split
                    code_str = ' '.join(new_code_split)
                    return self._execute_cmd(cmd_str=code_str)

                elif 'function' == code_type:
                    return self._execute_code_block(code=code_str)

                else:
                    raise ValueError(f'Unknown code type: {code_type}')

        except Exception as e:
            logger.error(f'Error executing code block: {str(e)}')
            exec_result.success = False
            exec_result.messages = str(e)

            return exec_result

    @staticmethod
    def _execute_code_block(code: str):
        """
        Execute a Python code block.

        Args:
            code: Python code string to execute

        Returns:
            ExecutionResult containing execution results
        """
        code = code or ''

        try:
            exec(code)
            return ExecutionResult(
                success=True,
                messages='Code executed successfully.',
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                messages=str(e),
            )

    @staticmethod
    def _execute_cmd(
        cmd_str: str,
        timeout: int = 180,
        work_dir: str = None,
    ) -> ExecutionResult:
        """
        Execute a Python script command in a subprocess.

        Args:
            cmd_str: Command string to execute, e.g. "python script.py --arg1 val1"
            timeout: Execution timeout in seconds
            work_dir: Working directory for execution

        Returns:
            ExecutionResult containing execution results
        """
        try:
            # Build command
            cmd_parts = shlex.split(cmd_str)
            cmd: list = [sys.executable] + cmd_parts[1:]

            # Execute subprocess
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=work_dir)

            return ExecutionResult(
                success=result.returncode == 0,
                output=result.stdout,
                messages=result.stderr,
            )

        except Exception as e:
            return ExecutionResult(
                success=False,
                messages=str(e),
            )


def create_agent_skill(skills: Union[str, List[str], List[SkillSchema]],
                       model: str,
                       api_key: Optional[str] = None,
                       base_url: Optional[str] = None,
                       stream: Optional[bool] = True,
                       enable_thinking: Optional[bool] = False,
                       max_tokens: Optional[int] = 8192,
                       work_dir: str = None,
                       use_sandbox: bool = True,
                       **kwargs) -> AgentSkill:
    """
    Create an AgentSkill instance.

    Args:
        skills: Path(s) to skill directories,
            the root path of skill directories, list of SkillSchema, or skill IDs on the hub.
            If using skill IDs on the hub, refer to `https://modelscope.cn/models/ms-agent/skill_examples`
        api_key: OpenAI API key
        base_url: Custom API base URL
        model: LLM model name
        stream: Whether to stream responses
        enable_thinking: Whether to enable thinking process in LLM generation
        max_tokens: Maximum tokens for LLM generation, default is 8192
        work_dir: Working directory.
        use_sandbox: Whether to use sandbox environment for script execution.
            If True, scripts will be executed in the `ms-enclave` sandbox environment.
            If False, scripts will be executed directly in the local environment.
    """
    return AgentSkill(
        skills=skills,
        model=model,
        api_key=api_key,
        base_url=base_url,
        stream=stream,
        enable_thinking=enable_thinking,
        max_tokens=max_tokens,
        work_dir=work_dir,
        use_sandbox=use_sandbox,
        **kwargs)
