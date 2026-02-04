# flake8: noqa
# isort: skip_file
# yapf: disable
import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Union

import json
from ms_agent.llm import LLM
from ms_agent.llm.utils import Message
from ms_agent.retriever.hybrid_retriever import HybridRetriever
from ms_agent.skill.container import (ExecutionInput, ExecutionOutput,
                                      ExecutorType, SkillContainer)
from ms_agent.skill.loader import load_skills
from ms_agent.skill.prompts import (PROMPT_ANALYZE_EXECUTION_ERROR,
                                    PROMPT_ANALYZE_QUERY_FOR_SKILLS,
                                    PROMPT_BUILD_SKILLS_DAG,
                                    PROMPT_DIRECT_SELECT_SKILLS,
                                    PROMPT_FILTER_SKILLS_DEEP,
                                    PROMPT_FILTER_SKILLS_FAST,
                                    PROMPT_SKILL_ANALYSIS_PLAN,
                                    PROMPT_SKILL_EXECUTION_COMMAND)
from ms_agent.skill.schema import SkillContext, SkillExecutionPlan, SkillSchema
from ms_agent.utils.logger import get_logger

logger = get_logger()


def _configure_logger_to_dir(log_dir: Path) -> None:
    """
    Configure the logger to output to a specific directory.

    Args:
        log_dir: Directory path for log files.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'ms_agent.log'

    # Check if file handler for this path already exists
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            if Path(handler.baseFilename).resolve() == log_file.resolve():
                return  # Already configured

    # Remove existing file handlers and add new one
    for handler in logger.handlers[:]:
        if isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)

    file_handler = logging.FileHandler(str(log_file), mode='a')
    file_handler.setFormatter(logging.Formatter('[%(levelname)s:%(name)s] %(message)s'))
    file_handler.setLevel(logger.level)
    logger.addHandler(file_handler)
    logger.info(f'Logger configured to output to: {log_file}')


@dataclass
class SkillExecutionResult:
    """
    Result of executing a single skill.

    Attributes:
        skill_id: Identifier of the executed skill.
        success: Whether execution was successful.
        output: ExecutionOutput from container.
        error: Error message if execution failed.
    """
    skill_id: str
    success: bool = False
    output: Optional[ExecutionOutput] = None
    error: Optional[str] = None


@dataclass
class DAGExecutionResult:
    """
    Result of executing the entire skill DAG.

    Attributes:
        success: Whether all skills executed successfully.
        results: Dict mapping skill_id to SkillExecutionResult.
        execution_order: Actual execution order (with parallel groups).
        total_duration_ms: Total execution duration in milliseconds.
    """
    success: bool = False
    results: Dict[str, SkillExecutionResult] = field(default_factory=dict)
    execution_order: List[Union[str, List[str]]] = field(default_factory=list)
    total_duration_ms: float = 0.0

    def get_skill_output(self, skill_id: str) -> Optional[ExecutionOutput]:
        """Get output from a specific skill execution."""
        result = self.results.get(skill_id)
        return result.output if result else None


class SkillAnalyzer:
    """
    Progressive skill analyzer for incremental context loading.

    Implements two-phase analysis:
    1. Plan Phase: Analyze skill metadata + content to create execution plan
    2. Load Phase: Load only required resources based on plan
    """

    def __init__(self, llm: 'LLM'):
        """
        Initialize skill analyzer.

        Args:
            llm: LLM instance for analysis.
        """
        self.llm = llm

    def _llm_generate(self, prompt: str) -> str:
        """Generate LLM response from prompt."""
        from ms_agent.llm.utils import Message
        messages = [Message(role='user', content=prompt)]
        response = self.llm.generate(messages=messages)
        return response.content if hasattr(response,
                                           'content') else str(response)

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from LLM response with robust extraction."""
        # Remove markdown code blocks if present
        response = re.sub(r'```json\s*', '', response)
        response = re.sub(r'```\s*$', '', response)
        response = response.strip()

        # Try direct parsing first
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON object from response
        try:
            # Find the outermost JSON object
            start = response.find('{')
            if start != -1:
                # Find matching closing brace
                depth = 0
                for i, char in enumerate(response[start:], start):
                    if char == '{':
                        depth += 1
                    elif char == '}':
                        depth -= 1
                        if depth == 0:
                            json_str = response[start:i + 1]
                            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        # Try regex extraction as fallback
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

        logger.warning(f'Failed to parse JSON: {response[:500]}...')
        return {}

    def analyze_skill_plan(self,
                           skill: SkillSchema,
                           query: str,
                           root_path: Path = None) -> SkillContext:
        """
        Phase 1: Analyze skill and create execution plan.

        Only loads skill metadata and content (SKILL.md), not scripts/resources.

        Args:
            skill: SkillSchema to analyze.
            query: User's query to fulfill.
            root_path: Root path for skill context.

        Returns:
            SkillContext with execution plan (resources not yet loaded).
        """
        # Create context with lazy loading
        context = SkillContext(
            skill=skill,
            query=query,
            root_path=root_path or skill.skill_path.parent)

        # Build prompt with skill overview (not full content)
        prompt = PROMPT_SKILL_ANALYSIS_PLAN.format(
            query=query,
            skill_id=skill.skill_id,
            skill_name=skill.name,
            skill_description=skill.description,
            skill_content=skill.content[:4000] if skill.content else '',
            scripts_list=', '.join(context.get_scripts_list()) or 'None',
            references_list=', '.join(context.get_references_list()) or 'None',
            resources_list=', '.join(context.get_resources_list()) or 'None')

        response = self._llm_generate(prompt)
        parsed = self._parse_json_response(response)

        # Build execution plan
        plan = SkillExecutionPlan(
            can_handle=parsed.get('can_handle', False),
            plan_summary=parsed.get('plan_summary', ''),
            steps=parsed.get('steps', []),
            required_scripts=parsed.get('required_scripts', []),
            required_references=parsed.get('required_references', []),
            required_resources=parsed.get('required_resources', []),
            required_packages=parsed.get('required_packages', []),
            parameters=parsed.get('parameters', {}),
            reasoning=parsed.get('reasoning', ''))

        context.plan = plan
        context.spec.plan = plan.plan_summary

        logger.info(
            f'Skill analysis plan: can_handle={plan.can_handle}, '
            f'scripts={plan.required_scripts}, refs={plan.required_references}, '
            f'packages={plan.required_packages}'
        )

        return context

    def load_skill_resources(self, context: SkillContext) -> SkillContext:
        """
        Phase 2: Load resources based on execution plan.

        Args:
            context: SkillContext with plan from Phase 1.

        Returns:
            SkillContext with loaded resources.
        """
        if not context.plan or not context.plan.can_handle:
            logger.warning('No valid plan, skipping resource loading')
            return context

        context.load_from_plan()
        logger.info(
            f'Loaded resources: scripts={len(context.scripts)}, '
            f'refs={len(context.references)}, res={len(context.resources)}')

        return context

    def generate_execution_commands(
            self, context: SkillContext) -> List[Dict[str, Any]]:
        """
        Generate execution commands from loaded context.

        Args:
            context: SkillContext with loaded resources.

        Returns:
            List of execution command dictionaries.
        """
        if not context.plan:
            return []

        prompt = PROMPT_SKILL_EXECUTION_COMMAND.format(
            query=context.query,
            skill_id=context.skill.skill_id,
            execution_plan=json.dumps(
                {
                    'plan_summary': context.plan.plan_summary,
                    'steps': context.plan.steps,
                    'parameters': context.plan.parameters,
                },
                indent=2),
            scripts_content=context.get_loaded_scripts_content(),
            references_content=context.get_loaded_references_content()[:2000],
            resources_content=context.get_loaded_resources_content()[:2000])

        response = self._llm_generate(prompt)
        parsed = self._parse_json_response(response)

        commands = parsed.get('commands', [])

        # Fallback: if no commands generated, try to use loaded scripts directly
        if not commands:
            # If no scripts loaded yet, try to load all available scripts
            if not context.scripts and context.skill.scripts:
                logger.info(
                    f'Loading all scripts as fallback: {[s.name for s in context.skill.scripts]}')
                context.load_scripts()  # Load all scripts

            if context.scripts:
                logger.warning(
                    f'No commands generated, using {len(context.scripts)} loaded scripts as fallback')
                # context.scripts is List[Dict] with keys: name, file, path, abs_path, content
                for script_info in context.scripts:
                    script_name = script_info.get('name', '')
                    script_content = script_info.get('content', '')
                    if script_name.endswith('.py') and script_content:
                        commands.append({
                            'type': 'python_code',
                            'code': script_content,
                            'requirements': context.plan.required_packages if context.plan else []
                        })
                    elif script_name.endswith('.sh') and script_content:
                        commands.append({
                            'type': 'shell',
                            'code': script_content
                        })

        context.spec.tasks = json.dumps(commands, indent=2)

        return commands

    async def analyze_and_prepare(
            self,
            skill: SkillSchema,
            query: str,
            root_path: Path = None
    ) -> Tuple[SkillContext, List[Dict[str, Any]]]:
        """
        Complete progressive analysis: plan -> load -> generate commands.

        Args:
            skill: SkillSchema to analyze.
            query: User's query.
            root_path: Root path for context.

        Returns:
            Tuple of (SkillContext, execution_commands).
        """
        # Phase 1: Create plan
        context = await asyncio.to_thread(self.analyze_skill_plan, skill,
                                          query, root_path)

        if not context.plan or not context.plan.can_handle:
            return context, []

        # Phase 2: Load resources
        await asyncio.to_thread(self.load_skill_resources, context)

        # Phase 3: Generate commands
        commands = await asyncio.to_thread(self.generate_execution_commands,
                                           context)

        return context, commands


@dataclass
class SkillDAGResult:
    """
    Result of AutoSkills run containing the skill execution DAG.

    Attributes:
        dag: Adjacency list representation of skill dependencies.
        execution_order: Topologically sorted list of skill_ids (sublists = parallel).
        selected_skills: Dict of selected SkillSchema objects.
        is_complete: Whether the skills are sufficient for the task.
        clarification: Optional clarification question if skills are insufficient.
        chat_response: Direct response if no skills needed (chat-only mode).
        execution_result: Result of DAG execution (populated after execute_dag).
    """
    dag: Dict[str, List[str]] = field(default_factory=dict)
    execution_order: List[Union[str, List[str]]] = field(default_factory=list)
    selected_skills: Dict[str, SkillSchema] = field(default_factory=dict)
    is_complete: bool = False
    clarification: Optional[str] = None
    chat_response: Optional[str] = None
    execution_result: Optional[DAGExecutionResult] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert SkillDAGResult to dictionary."""
        return {
            'dag':
            self.dag,
            'execution_order':
            self.execution_order,
            'selected_skills':
            {k: v.__dict__
             for k, v in self.selected_skills.items()},
            'is_complete':
            self.is_complete,
            'clarification':
            self.clarification,
            'chat_response':
            self.chat_response,
            'execution_result':
            self.execution_result.__dict__ if self.execution_result else None,
        }


class DAGExecutor:
    """
    Executor for skill DAG with dependency-aware parallel execution.

    Handles execution order parsing, input/output linking between skills,
    and parallel execution of independent skills.
    Supports progressive skill analysis for incremental context loading.
    """

    def __init__(self,
                 container: SkillContainer,
                 skills: Dict[str, SkillSchema],
                 workspace_dir: Optional[Path] = None,
                 llm: 'LLM' = None,
                 enable_progressive_analysis: bool = True,
                 enable_self_reflection: bool = True,
                 max_retries: int = 3):
        """
        Initialize DAG executor.

        Args:
            container: SkillContainer for executing skills.
            skills: Dict of skill_id to SkillSchema.
            workspace_dir: Optional workspace directory for skill execution.
            llm: LLM instance for progressive skill analysis.
            enable_progressive_analysis: Whether to use progressive analysis.
            enable_self_reflection: Whether to analyze errors and retry on failure.
            max_retries: Maximum retry attempts for failed executions.
        """
        self.container = container
        self.skills = skills
        self.workspace_dir = workspace_dir or container.workspace_dir
        self.llm = llm
        self.enable_progressive_analysis = enable_progressive_analysis and llm is not None
        self.enable_self_reflection = enable_self_reflection and llm is not None
        self.max_retries = max_retries

        # Skill analyzer for progressive analysis
        self._analyzer: Optional[SkillAnalyzer] = None
        if self.enable_progressive_analysis:
            self._analyzer = SkillAnalyzer(llm)

        # Execution state: stores outputs keyed by skill_id
        self._outputs: Dict[str, ExecutionOutput] = {}

        # Skill contexts from progressive analysis
        self._contexts: Dict[str, SkillContext] = {}

        # Track execution attempts for retry logging
        self._execution_attempts: Dict[str, int] = {}

    def _get_skill_dependencies(self, skill_id: str,
                                dag: Dict[str, List[str]]) -> List[str]:
        """
        Get direct dependencies of a skill from the DAG.

        Args:
            skill_id: The skill to get dependencies for.
            dag: Adjacency list where dag[A] = [B, C] means A depends on B, C.

        Returns:
            List of skill_ids that this skill depends on.
        """
        return dag.get(skill_id, [])

    def _build_execution_input(
            self,
            skill_id: str,
            dag: Dict[str, List[str]],
            execution_input: Optional[ExecutionInput] = None) -> ExecutionInput:
        """
        Build execution input for a skill, linking outputs from dependencies.

        Args:
            skill_id: The skill to build input for.
            dag: Skill dependency DAG.
            execution_input: Optional user-provided input.

        Returns:
            ExecutionInput with linked dependency outputs.
        """
        base_input = execution_input or ExecutionInput()

        # Get outputs from upstream dependencies
        dependencies = self._get_skill_dependencies(skill_id, dag)
        upstream_data: Dict[str, Any] = {}

        for dep_id in dependencies:
            if dep_id in self._outputs:
                dep_output = self._outputs[dep_id]
                # Pass stdout/return_value as upstream data
                upstream_data[dep_id] = {
                    'stdout': dep_output.stdout,
                    'stderr': dep_output.stderr,
                    'return_value': dep_output.return_value,
                    'exit_code': dep_output.exit_code,
                    'output_files':
                    {k: str(v)
                     for k, v in dep_output.output_files.items()},
                }

        # Inject upstream data into environment variables as JSON
        env_vars = base_input.env_vars.copy()
        if upstream_data:
            env_vars['UPSTREAM_OUTPUTS'] = json.dumps(upstream_data)
            # Also provide individual upstream references
            for dep_id, data in upstream_data.items():
                safe_key = dep_id.replace('-', '_').replace('.', '_').upper()
                if data.get('stdout'):
                    env_vars[f'UPSTREAM_{safe_key}_STDOUT'] = data[
                        'stdout'][:4096]

        return ExecutionInput(
            args=base_input.args,
            kwargs=base_input.kwargs,
            env_vars=env_vars,
            input_files=base_input.input_files,
            stdin=base_input.stdin,
            working_dir=base_input.working_dir,
            requirements=base_input.requirements,
        )

    def _determine_executor_type(self, skill: SkillSchema) -> ExecutorType:
        """
        Determine the executor type based on skill scripts.

        Args:
            skill: SkillSchema to analyze.

        Returns:
            ExecutorType for the skill's primary script.
        """
        if not skill.scripts:
            return ExecutorType.PYTHON_CODE

        # Check first script's extension
        primary_script = skill.scripts[0]
        ext = primary_script.type.lower()

        if ext in ['.py']:
            return ExecutorType.PYTHON_SCRIPT
        elif ext in ['.sh', '.bash']:
            return ExecutorType.SHELL
        elif ext in ['.js', '.mjs']:
            return ExecutorType.JAVASCRIPT
        else:
            return ExecutorType.PYTHON_CODE

    async def _execute_single_skill(
            self,
            skill_id: str,
            dag: Dict[str, List[str]],
            execution_input: Optional[ExecutionInput] = None,
            query: str = '') -> SkillExecutionResult:
        """
        Execute a single skill with dependency-linked input.

        Uses progressive analysis if enabled:
        1. Analyze skill to create execution plan
        2. Load only required resources
        3. Generate and execute commands

        Args:
            skill_id: ID of the skill to execute.
            dag: Skill dependency DAG.
            execution_input: Optional user-provided input.
            query: User query for progressive analysis.

        Returns:
            SkillExecutionResult with execution outcome.
        """
        skill = self.skills.get(skill_id)
        if not skill:
            return SkillExecutionResult(
                skill_id=skill_id,
                success=False,
                error=f'Skill not found: {skill_id}')

        try:
            # Build base input with upstream outputs
            exec_input = self._build_execution_input(skill_id, dag, execution_input)

            # Use progressive analysis if enabled
            if self.enable_progressive_analysis and self._analyzer:
                return await self._execute_with_progressive_analysis(
                    skill, skill_id, exec_input, query)

            # Fallback: direct execution without progressive analysis
            return await self._execute_direct(skill, skill_id, exec_input)

        except Exception as e:
            logger.error(f'Skill execution failed for {skill_id}: {e}')
            return SkillExecutionResult(
                skill_id=skill_id, success=False, error=str(e))

    async def _execute_with_progressive_analysis(
            self, skill: SkillSchema, skill_id: str,
            exec_input: ExecutionInput, query: str) -> SkillExecutionResult:
        """
        Execute skill using progressive analysis.

        Args:
            skill: SkillSchema to execute.
            skill_id: Skill identifier.
            exec_input: Execution input with upstream data.
            query: User query for context.

        Returns:
            SkillExecutionResult with execution outcome.
        """
        # Phase 1 & 2: Analyze and load resources
        # Use skill's directory as root_path for proper file resolution
        context, commands = await self._analyzer.analyze_and_prepare(
            skill, query, skill.skill_path)

        # Store context for reference
        self._contexts[skill_id] = context

        # Mount skill directory in container for sandbox access
        self.container.mount_skill_directory(skill_id, skill.skill_path)

        if not context.plan or not context.plan.can_handle:
            return SkillExecutionResult(
                skill_id=skill_id,
                success=False,
                error=
                f'Skill cannot handle query: {context.plan.reasoning if context.plan else "No plan"}'
            )

        if not commands:
            return SkillExecutionResult(
                skill_id=skill_id,
                success=False,
                error='No execution commands generated')

        # Phase 3: Execute commands with retry support for all types
        outputs: List[ExecutionOutput] = []
        for cmd in commands:
            cmd_type = cmd.get('type', 'python_code')

            # Use retry mechanism for all command types
            if self.enable_self_reflection:
                output = await self._execute_command_with_retry(
                    cmd=cmd,
                    cmd_type=cmd_type,
                    skill_id=skill_id,
                    exec_input=exec_input,
                    context=context,
                    skill=skill,
                    query=query)
            else:
                # Self-reflection disabled - execute without retry
                output = await self._execute_command(cmd, cmd_type, skill_id,
                                                     exec_input, context)
            outputs.append(output)

            if output.exit_code != 0:
                # Stop on first failure (after retries exhausted)
                break

        # Merge outputs
        final_output = self._merge_outputs(outputs)

        # Store output for downstream skills
        self._outputs[skill_id] = final_output
        self.container.spec.link_upstream(skill_id, final_output)

        return SkillExecutionResult(
            skill_id=skill_id,
            success=(final_output.exit_code == 0),
            output=final_output,
            error=final_output.stderr if final_output.exit_code != 0 else None)

    async def _execute_direct(
            self, skill: SkillSchema, skill_id: str,
            exec_input: ExecutionInput) -> SkillExecutionResult:
        """
        Execute skill directly without progressive analysis.

        Args:
            skill: SkillSchema to execute.
            skill_id: Skill identifier.
            exec_input: Execution input.

        Returns:
            SkillExecutionResult with execution outcome.
        """
        # Mount skill directory for sandbox access
        self.container.mount_skill_directory(skill_id, skill.skill_path)

        executor_type = self._determine_executor_type(skill)

        if skill.scripts:
            script_path = skill.scripts[0].path
            output = await self.container.execute(
                executor_type=executor_type,
                skill_id=skill_id,
                script_path=script_path,
                input_spec=exec_input)
        else:
            output = await self.container.execute_python_code(
                code=skill.content or '# No executable content',
                skill_id=skill_id,
                input_spec=exec_input)

        self._outputs[skill_id] = output
        self.container.spec.link_upstream(skill_id, output)

        return SkillExecutionResult(
            skill_id=skill_id,
            success=(output.exit_code == 0),
            output=output,
            error=output.stderr if output.exit_code != 0 else None)

    async def _execute_command(self, cmd: Dict[str, Any], cmd_type: str,
                               skill_id: str, exec_input: ExecutionInput,
                               context: SkillContext) -> ExecutionOutput:
        """
        Execute a single command from progressive analysis.

        Args:
            cmd: Command dictionary.
            cmd_type: Type of command (python_script, shell, etc.).
            skill_id: Skill identifier.
            exec_input: Base execution input.
            context: SkillContext with loaded resources.

        Returns:
            ExecutionOutput from command execution.
        """
        # Merge parameters into input
        params = cmd.get('parameters', {})
        # Use skill directory as working directory for proper file access
        working_dir = exec_input.working_dir or context.skill_dir

        # Collect all requirements: from plan, command, and input
        all_requirements = []
        if context.plan and context.plan.required_packages:
            all_requirements.extend(context.plan.required_packages)
        all_requirements.extend(cmd.get('requirements', []))
        all_requirements.extend(exec_input.requirements)
        # Deduplicate while preserving order
        seen = set()
        unique_requirements = []
        for req in all_requirements:
            if req not in seen:
                seen.add(req)
                unique_requirements.append(req)

        merged_input = ExecutionInput(
            args=exec_input.args + list(params.values()),
            kwargs={
                **exec_input.kwargs,
                **params
            },
            env_vars={
                **exec_input.env_vars,
                'SKILL_DIR': str(context.skill_dir),
                **{k.upper(): str(v)
                   for k, v in params.items()}
            },
            input_files=exec_input.input_files,
            stdin=exec_input.stdin,
            working_dir=working_dir,
            requirements=unique_requirements)

        if cmd_type == 'python_script':
            script_path = cmd.get('path')
            if script_path:
                # Resolve path relative to skill directory
                full_path = context.skill_dir / script_path
                if not full_path.exists():
                    full_path = context.root_path / script_path
                return await self.container.execute_python_script(
                    script_path=full_path,
                    skill_id=skill_id,
                    input_spec=merged_input)
            else:
                code = cmd.get('code', '')
                return await self.container.execute_python_code(
                    code=code, skill_id=skill_id, input_spec=merged_input)

        elif cmd_type == 'python_code':
            code = cmd.get('code', '')
            return await self.container.execute_python_code(
                code=code, skill_id=skill_id, input_spec=merged_input)

        elif cmd_type == 'shell':
            command = cmd.get('code') or cmd.get('command', '')
            return await self.container.execute_shell(
                command=command, skill_id=skill_id, input_spec=merged_input)

        elif cmd_type == 'javascript':
            code = cmd.get('code', '')
            return await self.container.execute_javascript(
                code=code, skill_id=skill_id, input_spec=merged_input)

        else:
            # Default to python code
            code = cmd.get('code', '')
            return await self.container.execute_python_code(
                code=code, skill_id=skill_id, input_spec=merged_input)

    async def _execute_command_with_retry(
            self, cmd: Dict[str, Any], cmd_type: str,
            skill_id: str, exec_input: ExecutionInput,
            context: SkillContext, skill: SkillSchema,
            query: str) -> ExecutionOutput:
        """
        Execute a command with retry logic for all execution types.

        Always retries up to max_retries times. Uses LLM analysis to improve
        the fix between retries when self-reflection is enabled.

        Args:
            cmd: Command dictionary.
            cmd_type: Type of command.
            skill_id: Skill identifier.
            exec_input: Base execution input.
            context: SkillContext.
            skill: SkillSchema for error analysis.
            query: User query for context.

        Returns:
            ExecutionOutput from command execution.
        """
        current_cmd = cmd.copy()
        last_output = None

        for attempt in range(1, self.max_retries + 1):
            self._execution_attempts[skill_id] = attempt
            logger.info(f'[{skill_id}] Execution attempt {attempt}/{self.max_retries}')

            # Execute the command
            output = await self._execute_command(
                current_cmd, cmd_type, skill_id, exec_input, context)
            last_output = output

            # Check if successful
            if output.exit_code == 0:
                if attempt > 1:
                    logger.info(
                        f'[{skill_id}] Execution succeeded after {attempt} attempts')
                return output

            # Collect error info
            error_msg = output.stderr[:500] if output.stderr else 'Unknown error'
            logger.warning(f'[{skill_id}] Attempt {attempt} failed: {error_msg[:200]}')

            # Last attempt - no need to analyze
            if attempt >= self.max_retries:
                logger.warning(
                    f'[{skill_id}] Max retries ({self.max_retries}) reached')
                continue

            # Try to analyze and fix if self-reflection is enabled
            if self.enable_self_reflection and cmd_type in ('python_code', 'python_script'):
                code = current_cmd.get('code', '')
                if code:
                    logger.info(f'[{skill_id}] Analyzing error for retry...')
                    analysis = self._analyze_execution_error(
                        skill=skill,
                        failed_code=code,
                        output=output,
                        query=query,
                        attempt=attempt)

                    error_info = analysis.get('error_analysis', {})
                    is_fixable = error_info.get('is_fixable', False)
                    fixed_code = analysis.get('fixed_code')
                    additional_reqs = analysis.get('additional_requirements', [])

                    logger.info(
                        f'[{skill_id}] Error analysis: type={error_info.get("error_type")}, '
                        f'fixable={is_fixable}')

                    # Apply fix if available
                    if is_fixable and fixed_code:
                        current_cmd = current_cmd.copy()
                        current_cmd['code'] = fixed_code
                        logger.info(f'[{skill_id}] Applying fix')

                    # Add additional requirements
                    if additional_reqs:
                        logger.info(f'[{skill_id}] Adding requirements: {additional_reqs}')
                        exec_input = ExecutionInput(
                            args=exec_input.args,
                            kwargs=exec_input.kwargs,
                            env_vars=exec_input.env_vars,
                            input_files=exec_input.input_files,
                            working_dir=exec_input.working_dir,
                            requirements=list(set(exec_input.requirements + additional_reqs)))
            else:
                logger.info(f'[{skill_id}] Retrying without code modification')

        logger.error(f'[{skill_id}] All {self.max_retries} attempts failed')
        return last_output

    def _merge_outputs(self,
                       outputs: List[ExecutionOutput]) -> ExecutionOutput:
        """Merge multiple execution outputs into one."""
        if not outputs:
            return ExecutionOutput()
        if len(outputs) == 1:
            return outputs[0]

        # Merge all outputs
        merged_stdout = '\n'.join(o.stdout for o in outputs if o.stdout)
        merged_stderr = '\n'.join(o.stderr for o in outputs if o.stderr)
        final_exit_code = next(
            (o.exit_code for o in outputs if o.exit_code != 0), 0)
        total_duration = sum(o.duration_ms for o in outputs)

        # Merge output files
        merged_files = {}
        for o in outputs:
            merged_files.update(o.output_files)

        return ExecutionOutput(
            stdout=merged_stdout,
            stderr=merged_stderr,
            exit_code=final_exit_code,
            output_files=merged_files,
            duration_ms=total_duration)

    def _analyze_execution_error(
            self,
            skill: SkillSchema,
            failed_code: str,
            output: ExecutionOutput,
            query: str,
            attempt: int) -> Dict[str, Any]:
        """
        Analyze failed execution and generate a fix using LLM.

        Args:
            skill: The skill that failed.
            failed_code: The code that failed.
            output: ExecutionOutput with error details.
            query: Original user query.
            attempt: Current retry attempt number.

        Returns:
            Dict with error analysis and fixed code.
        """
        if not self.llm:
            return {'error_analysis': {'is_fixable': False},
                    'fixed_code': None}

        prompt = PROMPT_ANALYZE_EXECUTION_ERROR.format(
            query=query,
            skill_id=skill.skill_id,
            skill_name=skill.name,
            failed_code=failed_code[:8000],  # Limit code length
            stderr=output.stderr[:3000] if output.stderr else '',
            stdout=output.stdout[:1000] if output.stdout else '',
            attempt=attempt,
            max_attempts=self.max_retries)

        try:
            response = self.llm.generate(
                messages=[Message(role='user', content=prompt)])
            # Parse JSON response - handle different response formats
            response_text = (response.content if hasattr(response, 'content')
                             else str(response)).strip()
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.warning(f'Error analyzing execution failure: {e}')

        return {'error_analysis': {'is_fixable': False}, 'fixed_code': None}

    async def _execute_parallel_group(
            self,
            skill_ids: List[str],
            dag: Dict[str, List[str]],
            execution_input: Optional[ExecutionInput] = None,
            query: str = '') -> List[SkillExecutionResult]:
        """
        Execute a group of skills in parallel.

        Args:
            skill_ids: List of skill_ids to execute concurrently.
            dag: Skill dependency DAG.
            execution_input: Optional user-provided input.
            query: User query for progressive analysis.

        Returns:
            List of SkillExecutionResult for each skill.
        """
        tasks = [
            self._execute_single_skill(sid, dag, execution_input, query)
            for sid in skill_ids
        ]
        return await asyncio.gather(*tasks)

    async def execute(self,
                      dag: Dict[str, List[str]],
                      execution_order: List[Union[str, List[str]]],
                      execution_input: Optional[ExecutionInput] = None,
                      stop_on_failure: bool = True,
                      query: str = '') -> DAGExecutionResult:
        """
        Execute the skill DAG according to execution order.

        Execution order format: [skill1, skill2, [skill3, skill4], skill5, ...]
        - Single string items are executed sequentially
        - List items (sublists) are executed in parallel

        Args:
            dag: Skill dependency DAG (adjacency list).
            execution_order: Ordered list with parallel groups as sublists.
            execution_input: Optional initial input for all skills.
            stop_on_failure: Whether to stop execution on first failure.
            query: User query for progressive skill analysis.

        Returns:
            DAGExecutionResult with all execution outcomes.
        """
        import time
        start_time = time.time()

        results: Dict[str, SkillExecutionResult] = {}
        actual_order: List[Union[str, List[str]]] = []
        all_success = True

        for item in execution_order:
            if isinstance(item, list):
                # Parallel execution group
                group_results = await self._execute_parallel_group(
                    item, dag, execution_input, query)
                for res in group_results:
                    results[res.skill_id] = res
                    if not res.success:
                        all_success = False
                actual_order.append(item)

                if not all_success and stop_on_failure:
                    logger.warning(
                        f'Stopping DAG execution due to failure in parallel group: {item}'
                    )
                    break
            else:
                # Sequential execution
                result = await self._execute_single_skill(
                    item, dag, execution_input, query)
                results[result.skill_id] = result
                actual_order.append(item)

                if not result.success:
                    all_success = False
                    if stop_on_failure:
                        logger.warning(
                            f'Stopping DAG execution due to failure: {item}')
                        break

        total_duration = (time.time() - start_time) * 1000

        return DAGExecutionResult(
            success=all_success,
            results=results,
            execution_order=actual_order,
            total_duration_ms=total_duration)

    def get_skill_context(self, skill_id: str) -> Optional[SkillContext]:
        """Get the skill context from progressive analysis."""
        return self._contexts.get(skill_id)

    def get_all_contexts(self) -> Dict[str, SkillContext]:
        """Get all skill contexts from progressive analysis."""
        return self._contexts.copy()

    def get_executed_skill_ids(self) -> List[str]:
        """Get list of skill_ids that have been executed with contexts."""
        return list(self._contexts.keys())


class AutoSkills:
    """
    Automatic skill retrieval and DAG construction for user queries.

    Uses hybrid retrieval (dense + sparse) to find relevant skills,
    with LLM-based analysis and reflection loop for completeness checking.
    Supports DAG-based skill execution with dependency management.
    """

    def __init__(self,
                 skills: Union[str, List[str], List[SkillSchema]],
                 llm: LLM,
                 enable_retrieve: Union[bool, None] = None,
                 retrieve_args: Dict[str, Any] = None,
                 max_candidate_skills: int = 10,
                 max_retries: int = 3,
                 work_dir: Optional[Union[str, Path]] = None,
                 use_sandbox: bool = True,
                 **kwargs):
        """
        Initialize AutoSkills with skills corpus and retriever.

        Args:
            skills: Path(s) to skill directories or list of SkillSchema.
                Alternatively, single repo_id or list of repo_ids from ModelScope.
                e.g. skills='ms-agent/claude_skills', refer to `https://modelscope.cn/models/ms-agent/claude_skills`
            llm: LLM instance for query analysis and evaluation.
            enable_retrieve: If True, use HybridRetriever for skill search.
                If False, put all skills into LLM context for direct selection.
                If None, enable search only if skills > 10 automatically.
            retrieve_args: Additional arguments for HybridRetriever.
                Attributes:
                    top_k: Number of top results to retrieve per query.
                    min_score: Minimum score threshold for retrieval.
            max_candidate_skills: Maximum number of candidate skills to consider.
            max_retries: Maximum retry attempts for failed executions for each skill.
            work_dir: Working directory for skill execution.
            use_sandbox: Whether to use Docker sandbox for execution.

        Examples:
            >>> from omegaconf import DictConfig
            >>> from ms_agent.llm.openai_llm import OpenAI
            >>> from ms_agent.skill.auto_skills import SkillDAGResult
            >>> config = DictConfig(
                {
                    'llm': {
                        'service': 'openai',
                        'model': 'gpt-4',
                        'openai_api_key': 'your-api-key',
                        'openai_base_url': 'your-base-url'
                        }
                    }
            >>> )
            >>> llm_instance = OpenAI.from_config(config)
            >>> auto_skills = AutoSkills(
                skills='/path/to/skills',
                llm=llm_instance,
                )
            >>> async def main():
                    result: SkillDAGResult = await auto_skills.run(query='Analyze sales data and generate mock report for Nvidia Q4 2025 in PDF format.')
                    print(result.execution_result)
            >>> import asyncio
            >>> asyncio.run(main())
        """
        # Dict of <skill_id, SkillSchema>
        self.all_skills: Dict[str, SkillSchema] = load_skills(skills=skills)
        logger.info(f'Loaded {len(self.all_skills)} skills from {skills}')

        self.llm = llm
        self.enable_retrieve = len(
            self.all_skills) > 10 if enable_retrieve is None else enable_retrieve
        retrieve_args = retrieve_args or {}
        self.top_k = retrieve_args.get('top_k', 3)
        self.min_score = retrieve_args.get('min_score', 0.8)
        self.max_candidate_skills = max_candidate_skills
        self.max_retries = max_retries
        self.work_dir = Path(work_dir) if work_dir else None
        self.use_sandbox = use_sandbox
        self.kwargs = kwargs

        if self.use_sandbox:
            from ms_agent.utils.docker_utils import is_docker_daemon_running
            if not is_docker_daemon_running():
                raise RuntimeError(
                    'Docker daemon is not running. Please start Docker to use sandbox mode.'
                )

        # Configure logger to output to work_dir/logs if work_dir is specified
        if self.work_dir:
            _configure_logger_to_dir(self.work_dir / 'logs')

        # Build corpus and skill_id mapping
        self.corpus: List[str] = []
        self.corpus_to_skill_id: Dict[str, str] = {}
        self._build_corpus()

        # Initialize retriever only if search is enabled
        self.retriever: Optional[HybridRetriever] = None
        if self.enable_retrieve and self.corpus:
            self.retriever = HybridRetriever(corpus=self.corpus, **kwargs)

        # Container and executor (lazy initialization)
        self._container: Optional[SkillContainer] = None
        self._executor: Optional[DAGExecutor] = None

    def _build_corpus(self):
        """Build corpus from skills for retriever indexing."""
        for skill_id, skill in self.all_skills.items():
            # Concatenate skill_id, name, description as corpus document
            doc = f'[{skill_id}] {skill.name}: {skill.description}'
            self.corpus.append(doc)
            self.corpus_to_skill_id[doc] = skill_id

    def _extract_skill_id_from_doc(self, doc: str) -> Optional[str]:
        """Extract skill_id from corpus document string."""
        # First try direct lookup
        if doc in self.corpus_to_skill_id:
            return self.corpus_to_skill_id[doc]
        # Fallback: extract from [skill_id] pattern
        match = re.match(r'\[([^\]]+)\]', doc)
        return match.group(1) if match else None

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from LLM response with robust extraction."""
        # Remove markdown code blocks if present
        response = re.sub(r'```json\s*', '', response)
        response = re.sub(r'```\s*$', '', response)
        response = response.strip()

        # Try direct parsing first
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON object from response
        try:
            # Find the outermost JSON object
            start = response.find('{')
            if start != -1:
                # Find matching closing brace
                depth = 0
                for i, char in enumerate(response[start:], start):
                    if char == '{':
                        depth += 1
                    elif char == '}':
                        depth -= 1
                        if depth == 0:
                            json_str = response[start:i + 1]
                            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        # Try regex extraction as fallback
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

        logger.warning(f'Failed to parse JSON response: {response[:300]}...')
        return {}

    def _get_skills_overview(self, limit: int = 20) -> str:
        """Generate a brief overview of all available skills."""
        lines = []
        for skill_id, skill in self.all_skills.items():
            lines.append(
                f'- [{skill_id}] {skill.name}: {skill.description[:200]}')
        return '\n'.join(lines[:limit])  # Limit to avoid token overflow

    def _get_all_skills_context(self) -> str:
        """Generate full context of all skills for direct LLM selection."""
        lines = []
        for skill_id, skill in self.all_skills.items():
            lines.append(f'- [{skill_id}] {skill.name}\n  {skill.description}')
        return '\n'.join(lines)

    def _format_retrieved_skills(self, skill_ids: Set[str]) -> str:
        """Format retrieved skills for LLM prompt."""
        lines = []
        for skill_id in skill_ids:
            if skill_id in self.all_skills:
                skill = self.all_skills[skill_id]
                lines.append(
                    f'- [{skill_id}] {skill.name}\n  {skill.description}\n Main Content: {skill.content[:3000]}')
        return '\n'.join(lines)

    def _llm_generate(self, prompt: str) -> str:
        """Generate LLM response from prompt."""
        messages = [Message(role='user', content=prompt)]
        response = self.llm.generate(messages=messages)
        return response.content if hasattr(response,
                                           'content') else str(response)

    async def _async_llm_generate(self, prompt: str) -> str:
        """Async wrapper for LLM generation."""
        return await asyncio.to_thread(self._llm_generate, prompt)

    def _analyze_query(
        self,
        query: str,
    ) -> Tuple[bool, str, List[str], Optional[str]]:
        """
        Analyze user query to determine if skills are needed.

        Args:
            query: User's original query.

        Returns:
            Tuple of (needs_skills, intent_summary, skill_queries, chat_response).
        """
        prompt = PROMPT_ANALYZE_QUERY_FOR_SKILLS.format(
            query=query, skills_overview=self._get_skills_overview())
        response = self._llm_generate(prompt)
        parsed = self._parse_json_response(response)

        needs_skills = parsed.get('needs_skills', True)
        intent = parsed.get('intent_summary', query)
        queries = parsed.get('skill_queries', [query])
        chat_response = parsed.get('chat_response')
        return needs_skills, intent, queries if queries else [query
                                                              ], chat_response

    async def _async_retrieve_skills(self, queries: List[str]) -> Set[str]:
        """
        Retrieve skills for multiple queries in parallel.

        Args:
            queries: List of search queries.

        Returns:
            Set of unique skill_ids from all queries.
        """
        if not self.retriever:
            return set()

        # Run parallel async searches
        tasks = [
            self.retriever.async_search(
                query=q, top_k=self.top_k, min_score=self.min_score)
            for q in queries
        ]
        results = await asyncio.gather(*tasks)

        # Collect unique skill_ids
        skill_ids = set()
        for result_list in results:
            for doc, score in result_list:
                skill_id = self._extract_skill_id_from_doc(doc)
                if skill_id:
                    skill_ids.add(skill_id)
        return skill_ids

    def _filter_skills(
            self,
            query: str,
            skill_ids: Set[str],
            mode: Literal['fast', 'deep'] = 'fast'
    ) -> Set[str]:
        """
        Filter skills based on relevance to the query.

        Args:
            query: User's query.
            skill_ids: Set of candidate skill_ids.
            mode: 'fast' for name+description only, 'deep' for full content analysis.

        Returns:
            Set of filtered skill_ids that are relevant.
        """
        if len(skill_ids) <= 1:
            return skill_ids

        # Format candidate skills based on mode
        if mode == 'deep':
            # Include name, description, and content (truncated)
            skill_entries = []
            for sid in skill_ids:
                if sid not in self.all_skills:
                    continue
                skill = self.all_skills[sid]
                content = skill.content[:3000] if skill.content else ''
                entry = (
                    f'### [{sid}] {skill.name}\n'
                    f'**Description**: {skill.description}\n'
                    f'**Content**: {content}'
                )
                skill_entries.append(entry)
            candidate_skills_text = '\n\n'.join(skill_entries)
            prompt = PROMPT_FILTER_SKILLS_DEEP.format(
                query=query,
                candidate_skills=candidate_skills_text)
        else:
            # Fast mode: name and description only
            candidate_skills_text = '\n'.join([
                f'- [{sid}] {self.all_skills[sid].name}: {self.all_skills[sid].description}'
                for sid in skill_ids if sid in self.all_skills
            ])
            prompt = PROMPT_FILTER_SKILLS_FAST.format(
                query=query,
                candidate_skills=candidate_skills_text)

        response = self._llm_generate(prompt)
        parsed = self._parse_json_response(response)

        filtered_ids = parsed.get('filtered_skill_ids', list(skill_ids))

        # For deep mode, also check skill_analysis for can_execute
        if mode == 'deep':
            skill_analysis = parsed.get('skill_analysis', {})
            final_ids = []
            for sid in filtered_ids:
                analysis = skill_analysis.get(sid, {})
                # Keep skill if can_execute is True or not specified
                if analysis.get('can_execute', True):
                    final_ids.append(sid)
                else:
                    logger.info(
                        f'Removing skill [{sid}]: cannot execute - '
                        f'{analysis.get("reason", "")[:200]}'
                    )
            filtered_ids = final_ids

        logger.info(
            f'Filter ({mode}): {len(skill_ids)} -> {len(filtered_ids)} skills. '
            f'Reason: {parsed.get("reasoning", "")[:1000]}'
        )

        return set(filtered_ids)

    def _build_dag(self, query: str, skill_ids: Set[str]) -> Dict[str, Any]:
        """
        Filter skills and build execution DAG.

        Performs deep filtering and DAG construction in one LLM call.

        Args:
            query: Original user query.
            skill_ids: Set of candidate skill_ids.

        Returns:
            Dict containing 'filtered_skill_ids', 'dag', and 'execution_order'.
        """
        skills_info = self._format_retrieved_skills(skill_ids)
        prompt = PROMPT_BUILD_SKILLS_DAG.format(
            query=query, selected_skills=skills_info)
        response = self._llm_generate(prompt)
        parsed = self._parse_json_response(response)

        # Get filtered skills and validate they exist in input
        raw_filtered = parsed.get('filtered_skill_ids', list(skill_ids))
        filtered_ids = set(sid for sid in raw_filtered if sid in skill_ids)

        # If no valid IDs returned, keep all input skills
        if not filtered_ids:
            logger.warning('No valid skill IDs in LLM response, keeping all input skills')
            filtered_ids = skill_ids

        logger.info(f'DAG filter: {len(skill_ids)} -> {len(filtered_ids)} skills')

        # Validate and clean DAG - only keep valid skill IDs
        raw_dag = parsed.get('dag', {})
        dag = {}
        for sid, deps in raw_dag.items():
            if sid in filtered_ids:
                # Filter dependencies to only valid skill IDs
                valid_deps = [d for d in deps if d in filtered_ids]
                dag[sid] = valid_deps

        # Ensure all filtered skills are in DAG
        for sid in filtered_ids:
            if sid not in dag:
                dag[sid] = []

        # Validate execution_order - only keep valid skill IDs
        raw_order = parsed.get('execution_order', [])
        order = self._validate_execution_order(raw_order, filtered_ids)

        # Fallback: derive execution_order from DAG using topological sort
        if not order and filtered_ids:
            order = self._topological_sort_dag(dag)
            logger.info(f'Derived execution_order from DAG: {order}')

        return {
            'filtered_skill_ids': filtered_ids,
            'dag': dag,
            'execution_order': order
        }

    def _validate_execution_order(
            self,
            raw_order: List[Union[str, List[str]]],
            valid_ids: Set[str]
    ) -> List[Union[str, List[str]]]:
        """
        Validate execution order, keeping only valid skill IDs.

        Args:
            raw_order: Raw execution order from LLM.
            valid_ids: Set of valid skill IDs.

        Returns:
            Validated execution order with only valid skill IDs.
        """
        result = []
        for item in raw_order:
            if isinstance(item, list):
                valid_group = [sid for sid in item if sid in valid_ids]
                if valid_group:
                    if len(valid_group) == 1:
                        result.append(valid_group[0])
                    else:
                        result.append(valid_group)
            elif item in valid_ids:
                result.append(item)
        return result

    def _topological_sort_dag(self, dag: Dict[str, List[str]]) -> List[str]:
        """
        Perform topological sort on DAG to get execution order.

        Args:
            dag: Adjacency list where dag[A] = [B, C] means A depends on B, C.

        Returns:
            Topologically sorted list of skill IDs (dependencies first).
        """
        if not dag:
            return []

        # Calculate in-degree for each node
        in_degree = {node: 0 for node in dag}
        for node, deps in dag.items():
            for dep in deps:
                if dep in in_degree:
                    pass  # dep is a dependency, node depends on it
            # Count how many nodes depend on this node
        for node, deps in dag.items():
            for dep in deps:
                if dep not in in_degree:
                    in_degree[dep] = 0

        # Recalculate: in dag[A] = [B], A depends on B, so B must come before A
        # We need to build reverse mapping
        in_degree = {node: 0 for node in dag}
        for dep in set(d for deps in dag.values() for d in deps):
            if dep not in in_degree:
                in_degree[dep] = 0

        for node, deps in dag.items():
            in_degree[node] = len(deps)

        # Start with nodes that have no dependencies
        queue = [node for node, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            # Sort for deterministic order
            queue.sort()
            node = queue.pop(0)
            result.append(node)

            # Reduce in-degree for nodes that depend on this node
            for other_node, deps in dag.items():
                if node in deps and other_node in in_degree:
                    in_degree[other_node] -= 1
                    if in_degree[other_node] == 0:
                        queue.append(other_node)

        # If not all nodes processed, there might be a cycle or disconnected nodes
        remaining = set(dag.keys()) - set(result)
        if remaining:
            logger.warning(f'Topological sort incomplete, adding remaining: {remaining}')
            result.extend(sorted(remaining))

        return result

    def _filter_execution_order(
            self,
            execution_order: List[Union[str, List[str]]],
            valid_skill_ids: Set[str]
    ) -> List[Union[str, List[str]]]:
        """
        Filter execution order to only include valid skill_ids.

        Args:
            execution_order: Original execution order (may contain parallel groups).
            valid_skill_ids: Set of skill_ids that should be kept.

        Returns:
            Filtered execution order with only valid skills.
        """
        filtered = []
        for item in execution_order:
            if isinstance(item, list):
                # Parallel group: filter and keep if any remain
                filtered_group = [sid for sid in item if sid in valid_skill_ids]
                if filtered_group:
                    if len(filtered_group) == 1:
                        filtered.append(filtered_group[0])
                    else:
                        filtered.append(filtered_group)
            elif item in valid_skill_ids:
                filtered.append(item)
        return filtered

    def _direct_select_skills(self, query: str) -> SkillDAGResult:
        """
        Directly select skills using LLM with all skills in context.

        Used when enable_retrieve=False. Puts all skills into LLM context
        and lets LLM select relevant skills and build DAG in one call.

        Args:
            query: User's task query.

        Returns:
            SkillDAGResult containing the skill execution DAG.
        """
        prompt = PROMPT_DIRECT_SELECT_SKILLS.format(
            query=query, all_skills=self._get_all_skills_context())
        response = self._llm_generate(prompt)
        parsed = self._parse_json_response(response)

        # Handle chat-only response
        needs_skills = parsed.get('needs_skills', True)
        chat_response = parsed.get('chat_response')

        if not needs_skills:
            logger.info('Chat-only query, no skills needed')
            if chat_response:
                print(f'\n[Chat Response]\n{chat_response}\n')
            return SkillDAGResult(
                is_complete=True, chat_response=chat_response)

        # Extract selected skills and DAG
        selected_ids = parsed.get('selected_skill_ids', [])
        dag = parsed.get('dag', {})
        order = parsed.get('execution_order', [])

        # Validate skill_ids exist
        valid_ids = {sid for sid in selected_ids if sid in self.all_skills}
        selected = {sid: self.all_skills[sid] for sid in valid_ids}

        logger.info(f'Direct selection: {valid_ids}')

        return SkillDAGResult(
            dag=dag,
            execution_order=order,
            selected_skills=selected,
            is_complete=bool(valid_ids),
            clarification=None if valid_ids else 'No relevant skills found.')

    async def get_skill_dag(self, query: str) -> SkillDAGResult:
        """
        Run the autonomous skill retrieval and DAG construction loop.

        Iteratively retrieves skills, evaluates completeness with reflection,
        and builds execution DAG. Loop terminates when:
        - Query is chat-only (no skills needed)
        - Max iterations reached
        - Skills are deemed complete for the task
        - Clarification from user is needed

        Args:
            query: User's task query.

        Returns:
            SkillDAGResult containing the skill execution DAG.
        """
        if not self.all_skills:
            logger.warning('No skills loaded, returning empty result')
            return SkillDAGResult()

        # Direct selection mode: put all skills into LLM context
        if not self.enable_retrieve:
            logger.info('Direct selection mode (enable_retrieve=False)')
            return self._direct_select_skills(query)

        # Search mode: use HybridRetriever
        if not self.retriever:
            logger.warning('Retriever not initialized, returning empty result')
            return SkillDAGResult()

        # Step 1: Analyze query to determine if skills are needed
        needs_skills, intent, skill_queries, chat_response = self._analyze_query(
            query)
        logger.info(f'Needs skills: {needs_skills}, Intent: {intent}')

        # If chat-only, return empty DAG with chat response
        if not needs_skills:
            logger.info('Chat-only query, no skills needed')
            if chat_response:
                print(f'\n[Chat Response]\n{chat_response}\n')
            return SkillDAGResult(
                is_complete=True, chat_response=chat_response)

        clarification: Optional[str] = None

        # Step 2: Retrieve skills
        collected_skills = await self._async_retrieve_skills(skill_queries)
        logger.info(f'Retrieved skills: {collected_skills}')

        if not collected_skills:
            clarification = 'No relevant skills found. Please provide more details.'
            return SkillDAGResult(
                is_complete=False, clarification=clarification)

        # Limit candidate skills to max_candidate_skills
        if len(collected_skills) > self.max_candidate_skills:
            logger.warning(
                f'Too many candidate skills ({len(collected_skills)}), '
                f'limiting to {self.max_candidate_skills}'
            )
            collected_skills = set(list(collected_skills)[:self.max_candidate_skills])

        # Step 3: Fast filter by name/description
        collected_skills = self._filter_skills(query, collected_skills, mode='fast')
        logger.info(f'After fast filter: {collected_skills}')

        if len(collected_skills) > 1:
            collected_skills = self._filter_skills(query, collected_skills, mode='deep')
            logger.info(f'After deep filter: {collected_skills}')

        if not collected_skills:
            clarification = 'No relevant skills found after filtering. Please refine your query.'
            return SkillDAGResult(
                is_complete=False, clarification=clarification)

        # Step 4: Build DAG with integrated deep filtering
        dag_result = self._build_dag(query, collected_skills)

        filtered_ids = dag_result.get('filtered_skill_ids', collected_skills)
        skills_dag: Dict[str, Any] = dag_result.get('dag', {})
        execution_order: List[str] = dag_result.get('execution_order', [])

        if not filtered_ids:
            clarification = 'No relevant skills found after filtering. Please refine your query.'
            return SkillDAGResult(
                is_complete=False, clarification=clarification)

        # Build selected skills dict from filtered results
        selected = {
            sid: self.all_skills[sid]
            for sid in filtered_ids if sid in self.all_skills
        }

        logger.info(
            f'Final DAG built with skills: {skills_dag}, execution order: {execution_order}'
        )

        return SkillDAGResult(
            dag=skills_dag,
            execution_order=execution_order,
            selected_skills=selected,
            is_complete=(clarification is None),
            clarification=clarification)

    def _get_container(self) -> SkillContainer:
        """Get or create SkillContainer instance."""
        if self._container is None:
            self._container = SkillContainer(
                workspace_dir=self.work_dir,
                use_sandbox=self.use_sandbox,
                **{
                    k: v
                    for k, v in self.kwargs.items() if k in [
                        'timeout', 'image', 'memory_limit',
                        'enable_security_check', 'network_enabled'
                    ]
                })
        return self._container

    def _get_executor(self) -> DAGExecutor:
        """Get or create DAGExecutor instance."""
        if self._executor is None:
            container = self._get_container()
            self._executor = DAGExecutor(
                container=container,
                skills=self.all_skills,
                workspace_dir=self.work_dir,
                llm=self.llm,
                enable_progressive_analysis=True,
                max_retries=self.max_retries)
        return self._executor

    async def execute_dag(self,
                          dag_result: SkillDAGResult,
                          execution_input: Optional[ExecutionInput] = None,
                          stop_on_failure: bool = True,
                          query: str = '') -> DAGExecutionResult:
        """
        Execute the skill DAG from a SkillDAGResult.

        Executes skills according to the execution_order, handling:
        - Sequential execution for single skill items
        - Parallel execution for skill groups (sublists)
        - Input/output linking between dependent skills
        - Progressive skill analysis (plan -> load -> execute)

        Args:
            dag_result: SkillDAGResult containing DAG and execution order.
            execution_input: Optional initial input for skills.
            stop_on_failure: Whether to stop on first failure.
            query: User query for progressive skill analysis.

        Returns:
            DAGExecutionResult with all execution outcomes.
        """
        if not dag_result.is_complete:
            logger.warning('DAG is not complete, execution may fail')

        if not dag_result.execution_order:
            logger.warning('Empty execution order, nothing to execute')
            return DAGExecutionResult(success=True)

        executor = self._get_executor()
        result = await executor.execute(
            dag=dag_result.dag,
            execution_order=dag_result.execution_order,
            execution_input=execution_input,
            stop_on_failure=stop_on_failure,
            query=query)

        # Attach result to dag_result for convenience
        dag_result.execution_result = result

        logger.info(f'DAG execution completed: success={result.success}, '
                    f'duration={result.total_duration_ms:.2f}ms')

        return result

    def get_execution_spec(self) -> Optional[str]:
        """Get the execution spec log as markdown string."""
        if self._container:
            return self._container.get_spec_log()
        return None

    def save_execution_spec(self,
                            output_path: Optional[Union[str, Path]] = None):
        """Save the execution spec to a markdown file."""
        if self._container:
            self._container.save_spec_log(output_path)

    def cleanup(self, keep_spec: bool = True):
        """Clean up container workspace."""
        if self._container:
            self._container.cleanup(keep_spec=keep_spec)

    def get_skill_context(self, skill_id: str) -> Optional[SkillContext]:
        """
        Get the skill context for an executed skill.

        Args:
            skill_id: The skill identifier (e.g., 'pdf@latest').

        Returns:
            SkillContext if the skill was executed, None otherwise.
        """
        if self._executor:
            return self._executor.get_skill_context(skill_id)
        return None

    def get_all_skill_contexts(self) -> Dict[str, SkillContext]:
        """
        Get all skill contexts from executed skills.

        Returns:
            Dict mapping skill_id to SkillContext.
        """
        if self._executor:
            return self._executor.get_all_contexts()
        return {}

    def get_executed_skill_ids(self) -> List[str]:
        """
        Get list of skill_ids that were executed.

        Returns:
            List of skill_ids with available contexts.
        """
        if self._executor:
            return self._executor.get_executed_skill_ids()
        return []

    async def run(
            self,
            query: str,
            execution_input: Optional[ExecutionInput] = None,
            stop_on_failure: bool = True
    ) -> SkillDAGResult:
        """
        Run skill retrieval and execute the resulting DAG in one call.

        Combines get_skill_dag() and execute_dag().
        Uses progressive skill analysis for each skill execution.

        Args:
            query: User's task query.
            execution_input: Optional initial input for skills.
            stop_on_failure: Whether to stop on first failure.

        Returns:
            SkillDAGResult with execution_result populated.
        """
        dag_result = await self.get_skill_dag(query)

        # Skip execution for chat-only results
        if dag_result.chat_response:
            logger.info('Chat-only response, skipping execution')
            return dag_result

        # Skip if skills are incomplete
        if not dag_result.is_complete:
            logger.warning(f'Skills incomplete: {dag_result.clarification}')
            return dag_result

        # Execute the DAG
        if dag_result.execution_order:
            await self.execute_dag(
                dag_result, execution_input, stop_on_failure, query=query)

        return dag_result
