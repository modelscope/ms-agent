"""
Unit tests for Skill DAG upstream-downstream data passing.

=== Overview ===

This test module validates the core DAG execution mechanism in AutoSkills:
when multiple skills are chained in a Directed Acyclic Graph (DAG), the
outputs (stdout, return_value, output_files, etc.) from upstream skills
are correctly propagated to downstream skills via environment variables.

=== Features Tested ===

1. **Upstream output storage**: After a skill executes, its ExecutionOutput
   is stored in DAGExecutor._outputs and linked via container.spec.link_upstream().

2. **Environment variable injection**: DAGExecutor._build_execution_input()
   reads upstream outputs and injects them as:
   - UPSTREAM_OUTPUTS: Full JSON dict of all dependency outputs.
   - UPSTREAM_<SAFE_KEY>_STDOUT: Per-dependency stdout shortcut variable.

3. **Sequential data flow**: A → B → C chain where each skill reads and
   transforms data from its predecessor.

4. **Full DAGExecutor.execute() pipeline**: End-to-end test through the
   public execute() method, verifying internal wiring.

5. **Mixed parallel + sequential DAG**: A → [B, C] → D pattern where B and
   C run in parallel (both depending on A), then D merges both results.

6. **container.link_skills() API**: Verifies the SkillContainer helper that
   retrieves linked upstream outputs programmatically.

7. **output_files propagation**: Upstream output files (written to
   SKILL_OUTPUT_DIR) are captured and exposed in UPSTREAM_OUTPUTS JSON.

=== Workflow ===

Each test follows this pattern:
  1. Create mock SkillSchema objects backed by temporary directories.
  2. Instantiate SkillContainer (local mode, no sandbox) and DAGExecutor
     (no LLM, no progressive analysis).
  3. Execute Python code snippets as mock skill scripts.
  4. Verify upstream data is available in downstream environment variables.
  5. Assert correctness of data transformation across the DAG.

=== Working Directory Structure ===

All intermediate results are stored under a temporary directory:

    <temp_root>/
    ├── test_upstream_downstream/
    │   ├── skills/                     # Mock skill definitions
    │   │   ├── skill_a/SKILL.md
    │   │   ├── skill_b/SKILL.md
    │   │   └── skill_c/SKILL.md
    │   └── workspace/
    │       ├── outputs/                # Skill output files (e.g., data.json)
    │       ├── scripts/                # Generated temp execution scripts
    │       └── logs/                   # Execution spec logs
    ├── test_full_pipeline/
    │   ├── skills/
    │   └── workspace/
    └── test_parallel_mixed/
        ├── skills/
        └── workspace/

=== Prerequisites ===

- Python >= 3.10
- ms_agent package installed (editable mode: pip install -e .)
- No external LLM API key required (tests use mock code, no LLM calls).
- No sandbox/Docker required (tests run in local mode).

=== Usage ===

    # Run all tests in this module
    python -m unittest tests.skills.test_dag_upstream_downstream -v

    # Run a specific test class
    python -m unittest tests.skills.test_dag_upstream_downstream.TestDAGUpstreamDownstream -v

    # Run a specific test method
    python -m unittest tests.skills.test_dag_upstream_downstream.TestDAGFullPipeline.test_sequential_pipeline -v

=== Environment Variables ===

    KEEP_TEST_ARTIFACTS=true|false  (default: true)
        Whether to keep intermediate results after tests finish.
        Set to 'false' to auto-clean temp directories in tearDown.
"""
import asyncio
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional

from ms_agent.skill.auto_skills import DAGExecutor, SkillExecutionResult
from ms_agent.skill.container import (ExecutionInput, ExecutionOutput,
                                      SkillContainer)
from ms_agent.skill.schema import SkillFile, SkillSchema

# ---------------------------------------------------------------------------
# Global control: whether to keep intermediate artifacts after tests.
# Set KEEP_TEST_ARTIFACTS=false to auto-clean.
# ---------------------------------------------------------------------------
KEEP_TEST_ARTIFACTS: bool = os.getenv('KEEP_TEST_ARTIFACTS',
                                      'true').lower() == 'true'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_async(coro):
    """Run an async coroutine in a new event loop (sync context helper)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def create_mock_skill(skill_id: str, name: str, description: str,
                      skill_dir: Path) -> SkillSchema:
    """
    Create a minimal mock SkillSchema backed by a real directory.

    Args:
        skill_id: Unique skill identifier (e.g., 'skill_a@latest').
        name: Human-readable skill name.
        description: Short description of the skill.
        skill_dir: Filesystem path for the skill directory.

    Returns:
        A SkillSchema instance pointing to the created directory.
    """
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / 'SKILL.md'
    skill_md.write_text(
        f'---\nname: {name}\ndescription: {description}\n---\n'
        f'# {name}\n{description}\n')

    return SkillSchema(
        skill_id=skill_id,
        name=name,
        description=description,
        content=f'# {name}\n{description}',
        files=[SkillFile(name='SKILL.md', type='.md', path=skill_md)],
        skill_path=skill_dir,
        version='latest',
    )


# ============================================================================
# Test 1: Direct upstream-downstream data flow
# ============================================================================

class TestDAGUpstreamDownstream(unittest.TestCase):
    """
    Test upstream -> downstream data flow through DAGExecutor.

    Scenario: skill_a -> skill_b -> skill_c
    - skill_a generates JSON data and writes an output file.
    - skill_b reads skill_a's stdout via UPSTREAM_OUTPUTS env var.
    - skill_c aggregates outputs from both skill_a and skill_b.
    """

    def setUp(self):
        """Create temp directories, mock skills, container, and executor."""
        self.test_root = Path(
            tempfile.mkdtemp(prefix='test_dag_upstream_downstream_'))
        self.skills_dir = self.test_root / 'skills'
        self.workspace_dir = self.test_root / 'workspace'

        # Create mock skills
        self.skill_a = create_mock_skill(
            'skill_a@latest', 'Data Generator',
            'Generates data and outputs to stdout',
            self.skills_dir / 'skill_a')
        self.skill_b = create_mock_skill(
            'skill_b@latest', 'Data Processor',
            'Processes upstream data',
            self.skills_dir / 'skill_b')
        self.skill_c = create_mock_skill(
            'skill_c@latest', 'Report Builder',
            'Builds report from all upstream outputs',
            self.skills_dir / 'skill_c')

        self.skills = {
            'skill_a@latest': self.skill_a,
            'skill_b@latest': self.skill_b,
            'skill_c@latest': self.skill_c,
        }

        self.container = SkillContainer(
            workspace_dir=self.workspace_dir, use_sandbox=False)

        self.executor = DAGExecutor(
            container=self.container,
            skills=self.skills,
            workspace_dir=self.workspace_dir,
            llm=None,
            enable_progressive_analysis=False,
            enable_self_reflection=False,
        )

        # DAG: skill_a -> skill_b -> skill_c
        self.dag = {
            'skill_a@latest': [],
            'skill_b@latest': ['skill_a@latest'],
            'skill_c@latest': ['skill_a@latest', 'skill_b@latest'],
        }

    def tearDown(self):
        """Clean up temp directory unless KEEP_TEST_ARTIFACTS is set."""
        if not KEEP_TEST_ARTIFACTS and self.test_root.exists():
            try:
                shutil.rmtree(self.test_root)
            except Exception as e:
                print(f'Warning: Failed to clean up {self.test_root}: {e}')

        self.executor = None
        self.container = None

    def test_skill_a_output_stored(self):
        """After executing skill_a, its output is stored in executor._outputs."""
        code_a = (
            'import os, json\n'
            'output_dir = os.environ.get("SKILL_OUTPUT_DIR", "/tmp")\n'
            'data = {"revenue": 1000000, "quarter": "Q4", "year": 2024}\n'
            'print(json.dumps(data))\n'
            'output_file = os.path.join(output_dir, "data.json")\n'
            'with open(output_file, "w") as f:\n'
            '    json.dump(data, f)\n'
            'print(f"Output file: {output_file}")\n'
        )

        exec_input = self.executor._build_execution_input(
            'skill_a@latest', self.dag)
        output_a = run_async(self.container.execute_python_code(
            code=code_a, skill_id='skill_a@latest', input_spec=exec_input))

        self.executor._outputs['skill_a@latest'] = output_a
        self.container.spec.link_upstream('skill_a@latest', output_a)

        self.assertEqual(output_a.exit_code, 0,
                         f'skill_a should succeed, stderr: {output_a.stderr}')
        self.assertIn('revenue', output_a.stdout)
        self.assertIn('skill_a@latest', self.executor._outputs)

    def test_upstream_env_vars_injected(self):
        """skill_b's execution input contains UPSTREAM env vars from skill_a."""
        # Simulate skill_a output
        output_a = ExecutionOutput(
            stdout='{"revenue": 1000000}\n',
            stderr='',
            exit_code=0,
            output_files={'data.json': Path('/tmp/data.json')},
            duration_ms=100.0,
        )
        self.executor._outputs['skill_a@latest'] = output_a

        exec_input_b = self.executor._build_execution_input(
            'skill_b@latest', self.dag)

        # Verify UPSTREAM_OUTPUTS JSON
        self.assertIn('UPSTREAM_OUTPUTS', exec_input_b.env_vars,
                       'UPSTREAM_OUTPUTS should be set')
        upstream_json = json.loads(exec_input_b.env_vars['UPSTREAM_OUTPUTS'])
        self.assertIn('skill_a@latest', upstream_json)
        self.assertEqual(upstream_json['skill_a@latest']['exit_code'], 0)
        self.assertIn('revenue', upstream_json['skill_a@latest']['stdout'])

        # Verify individual upstream shortcut env var
        self.assertIn('UPSTREAM_SKILL_A_LATEST_STDOUT', exec_input_b.env_vars,
                       'Per-skill stdout shortcut should be set')

    def test_downstream_reads_upstream_data(self):
        """skill_b can parse skill_a's stdout from UPSTREAM_OUTPUTS."""
        # Execute skill_a
        code_a = (
            'import json\n'
            'print(json.dumps({"revenue": 1000000, "quarter": "Q4"}))\n'
        )
        exec_input_a = self.executor._build_execution_input(
            'skill_a@latest', self.dag)
        output_a = run_async(self.container.execute_python_code(
            code=code_a, skill_id='skill_a@latest', input_spec=exec_input_a))
        self.executor._outputs['skill_a@latest'] = output_a
        self.container.spec.link_upstream('skill_a@latest', output_a)

        # Execute skill_b
        code_b = (
            'import os, json\n'
            'upstream = json.loads(os.environ.get("UPSTREAM_OUTPUTS", "{}"))\n'
            'data = json.loads(upstream["skill_a@latest"]["stdout"].strip())\n'
            'result = {"processed_revenue": data["revenue"] * 1.1}\n'
            'print(json.dumps(result))\n'
        )
        exec_input_b = self.executor._build_execution_input(
            'skill_b@latest', self.dag)
        output_b = run_async(self.container.execute_python_code(
            code=code_b, skill_id='skill_b@latest', input_spec=exec_input_b))

        self.assertEqual(output_b.exit_code, 0,
                         f'skill_b failed: {output_b.stderr}')
        result_b = json.loads(output_b.stdout.strip())
        self.assertAlmostEqual(result_b['processed_revenue'], 1100000.0)

    def test_multi_upstream_aggregation(self):
        """skill_c receives outputs from both skill_a and skill_b."""
        # Simulate skill_a and skill_b outputs
        self.executor._outputs['skill_a@latest'] = ExecutionOutput(
            stdout='A_DATA\n', stderr='', exit_code=0, duration_ms=10)
        self.executor._outputs['skill_b@latest'] = ExecutionOutput(
            stdout='B_DATA\n', stderr='', exit_code=0, duration_ms=10)

        exec_input_c = self.executor._build_execution_input(
            'skill_c@latest', self.dag)
        upstream_json = json.loads(exec_input_c.env_vars['UPSTREAM_OUTPUTS'])

        self.assertIn('skill_a@latest', upstream_json,
                       'skill_a should be in upstream data')
        self.assertIn('skill_b@latest', upstream_json,
                       'skill_b should be in upstream data')
        self.assertEqual(len(upstream_json), 2,
                         'skill_c should see exactly 2 upstream skills')

    def test_output_files_propagated(self):
        """Upstream output_files paths are included in UPSTREAM_OUTPUTS JSON."""
        # Simulate skill_a with output files
        self.executor._outputs['skill_a@latest'] = ExecutionOutput(
            stdout='done\n',
            stderr='',
            exit_code=0,
            output_files={
                'report.pdf': Path('/workspace/outputs/report.pdf'),
                'data.csv': Path('/workspace/outputs/data.csv'),
            },
            duration_ms=50,
        )

        exec_input_b = self.executor._build_execution_input(
            'skill_b@latest', self.dag)
        upstream_json = json.loads(exec_input_b.env_vars['UPSTREAM_OUTPUTS'])
        output_files = upstream_json['skill_a@latest']['output_files']

        self.assertIn('report.pdf', output_files)
        self.assertIn('data.csv', output_files)

    def test_link_skills_api(self):
        """container.link_skills() returns correct upstream output."""
        output_a = ExecutionOutput(
            stdout='hello from A\n', stderr='', exit_code=0, duration_ms=10)
        self.container.spec.link_upstream('skill_a@latest', output_a)

        linked = self.container.link_skills(
            'skill_a@latest', 'input_data', 'stdout')
        self.assertEqual(linked, 'hello from A\n')

        # Non-existent upstream returns None
        missing = self.container.link_skills(
            'nonexistent@latest', 'input_data', 'stdout')
        self.assertIsNone(missing)

    def test_full_three_skill_chain(self):
        """End-to-end: skill_a -> skill_b -> skill_c with real execution."""
        # skill_a: generate data
        code_a = (
            'import os, json\n'
            'output_dir = os.environ.get("SKILL_OUTPUT_DIR", "/tmp")\n'
            'data = {"revenue": 1000000, "quarter": "Q4", "year": 2024}\n'
            'print(json.dumps(data))\n'
            'with open(os.path.join(output_dir, "data.json"), "w") as f:\n'
            '    json.dump(data, f)\n'
        )
        exec_input_a = self.executor._build_execution_input(
            'skill_a@latest', self.dag)
        output_a = run_async(self.container.execute_python_code(
            code=code_a, skill_id='skill_a@latest', input_spec=exec_input_a))
        self.executor._outputs['skill_a@latest'] = output_a
        self.container.spec.link_upstream('skill_a@latest', output_a)
        self.assertEqual(output_a.exit_code, 0)

        # skill_b: process skill_a output
        code_b = (
            'import os, json\n'
            'upstream = json.loads(os.environ.get("UPSTREAM_OUTPUTS", "{}"))\n'
            'a_stdout = upstream["skill_a@latest"]["stdout"].strip()\n'
            'data = json.loads(a_stdout)\n'
            'processed = {"processed_revenue": data["revenue"] * 1.1, "source": "skill_a"}\n'
            'print(json.dumps(processed))\n'
        )
        exec_input_b = self.executor._build_execution_input(
            'skill_b@latest', self.dag)
        output_b = run_async(self.container.execute_python_code(
            code=code_b, skill_id='skill_b@latest', input_spec=exec_input_b))
        self.executor._outputs['skill_b@latest'] = output_b
        self.container.spec.link_upstream('skill_b@latest', output_b)
        self.assertEqual(output_b.exit_code, 0,
                         f'skill_b failed: {output_b.stderr}')

        # skill_c: aggregate both
        code_c = (
            'import os, json\n'
            'upstream = json.loads(os.environ.get("UPSTREAM_OUTPUTS", "{}"))\n'
            'print(f"Total upstream skills: {len(upstream)}")\n'
            'for sid, data in upstream.items():\n'
            '    print(f"From {sid}: exit_code={data[\'exit_code\']}")\n'
        )
        exec_input_c = self.executor._build_execution_input(
            'skill_c@latest', self.dag)
        output_c = run_async(self.container.execute_python_code(
            code=code_c, skill_id='skill_c@latest', input_spec=exec_input_c))

        self.assertEqual(output_c.exit_code, 0,
                         f'skill_c failed: {output_c.stderr}')
        self.assertIn('Total upstream skills: 2', output_c.stdout)


# ============================================================================
# Test 2: Full DAGExecutor.execute() pipeline
# ============================================================================

class TestDAGFullPipeline(unittest.TestCase):
    """
    Test the full DAGExecutor.execute() method with sequential skills.

    Scenario: adder (outputs 42) -> doubler (reads 42, outputs 84)
    Verifies the complete internal wiring: execute() -> _execute_single_skill
    -> _build_execution_input -> env_vars propagation.
    """

    def setUp(self):
        """Create temp directories, mock skills, container, and executor."""
        self.test_root = Path(
            tempfile.mkdtemp(prefix='test_dag_full_pipeline_'))
        self.skills_dir = self.test_root / 'skills'
        self.workspace_dir = self.test_root / 'workspace'

        self.skill_a = create_mock_skill(
            'adder@latest', 'Adder', 'Generates a number',
            self.skills_dir / 'adder')
        self.skill_b = create_mock_skill(
            'doubler@latest', 'Doubler', 'Doubles upstream number',
            self.skills_dir / 'doubler')

        self.skills = {
            'adder@latest': self.skill_a,
            'doubler@latest': self.skill_b,
        }

        self.container = SkillContainer(
            workspace_dir=self.workspace_dir, use_sandbox=False)

        self.executor = DAGExecutor(
            container=self.container,
            skills=self.skills,
            workspace_dir=self.workspace_dir,
            llm=None,
            enable_progressive_analysis=False,
            enable_self_reflection=False,
        )

        self.dag = {
            'adder@latest': [],
            'doubler@latest': ['adder@latest'],
        }
        self.execution_order = ['adder@latest', 'doubler@latest']

    def tearDown(self):
        """Clean up temp directory unless KEEP_TEST_ARTIFACTS is set."""
        if not KEEP_TEST_ARTIFACTS and self.test_root.exists():
            try:
                shutil.rmtree(self.test_root)
            except Exception as e:
                print(f'Warning: Failed to clean up {self.test_root}: {e}')

        self.executor = None
        self.container = None

    def test_sequential_pipeline(self):
        """adder outputs 42, doubler reads it and outputs 84."""
        container = self.container
        executor = self.executor

        async def mock_execute_single(
                skill_id, dag, execution_input=None, query=''):
            exec_input = executor._build_execution_input(
                skill_id, dag, execution_input)

            if skill_id == 'adder@latest':
                code = 'print(42)'
            elif skill_id == 'doubler@latest':
                code = (
                    'import os, json\n'
                    'upstream = json.loads(os.environ.get("UPSTREAM_OUTPUTS", "{}"))\n'
                    'val = int(upstream["adder@latest"]["stdout"].strip())\n'
                    'print(val * 2)\n'
                )
            else:
                return SkillExecutionResult(
                    skill_id=skill_id, success=False, error='Unknown')

            output = await container.execute_python_code(
                code=code, skill_id=skill_id, input_spec=exec_input)
            executor._outputs[skill_id] = output
            container.spec.link_upstream(skill_id, output)
            return SkillExecutionResult(
                skill_id=skill_id,
                success=(output.exit_code == 0),
                output=output,
                error=output.stderr if output.exit_code != 0 else None)

        executor._execute_single_skill = mock_execute_single

        result = run_async(executor.execute(
            dag=self.dag,
            execution_order=self.execution_order,
            stop_on_failure=True,
            query='test'))

        self.assertTrue(result.success, 'DAG execution should succeed')

        adder_out = result.results['adder@latest'].output.stdout.strip()
        self.assertEqual(adder_out, '42', f'Expected 42, got: {adder_out}')

        doubler_out = result.results['doubler@latest'].output.stdout.strip()
        self.assertEqual(doubler_out, '84', f'Expected 84, got: {doubler_out}')

    def test_failure_stops_pipeline(self):
        """When upstream skill fails and stop_on_failure=True, pipeline stops."""
        container = self.container
        executor = self.executor

        async def mock_execute_single(
                skill_id, dag, execution_input=None, query=''):
            exec_input = executor._build_execution_input(
                skill_id, dag, execution_input)

            if skill_id == 'adder@latest':
                code = 'import sys; print("error", file=sys.stderr); sys.exit(1)'
            else:
                code = 'print("should not run")'

            output = await container.execute_python_code(
                code=code, skill_id=skill_id, input_spec=exec_input)
            executor._outputs[skill_id] = output
            return SkillExecutionResult(
                skill_id=skill_id,
                success=(output.exit_code == 0),
                output=output,
                error=output.stderr if output.exit_code != 0 else None)

        executor._execute_single_skill = mock_execute_single

        result = run_async(executor.execute(
            dag=self.dag,
            execution_order=self.execution_order,
            stop_on_failure=True,
            query='test'))

        self.assertFalse(result.success, 'DAG should fail')
        self.assertIn('adder@latest', result.results)
        # doubler should not have been executed
        self.assertNotIn('doubler@latest', result.results,
                         'doubler should not run when adder fails')


# ============================================================================
# Test 3: Parallel + Sequential mixed DAG
# ============================================================================

class TestDAGParallelMixed(unittest.TestCase):
    """
    Test a mixed DAG with parallel and sequential execution.

    Scenario: gen -> [proc_x, proc_y] -> merge
    - gen outputs BASE_VALUE=100
    - proc_x reads gen, outputs X_RESULT=110 (100+10)
    - proc_y reads gen, outputs Y_RESULT=200 (100*2)
    - merge reads both, outputs MERGED=310 (110+200)
    proc_x and proc_y run in parallel.
    """

    def setUp(self):
        """Create temp directories, mock skills, container, and executor."""
        self.test_root = Path(
            tempfile.mkdtemp(prefix='test_dag_parallel_mixed_'))
        self.skills_dir = self.test_root / 'skills'
        self.workspace_dir = self.test_root / 'workspace'

        skill_names = ['gen', 'proc_x', 'proc_y', 'merge']
        self.skills = {}
        for sname in skill_names:
            sid = f'{sname}@latest'
            sdir = self.skills_dir / sname
            self.skills[sid] = create_mock_skill(
                sid, sname, f'{sname} skill', sdir)

        self.container = SkillContainer(
            workspace_dir=self.workspace_dir, use_sandbox=False)

        self.executor = DAGExecutor(
            container=self.container,
            skills=self.skills,
            workspace_dir=self.workspace_dir,
            llm=None,
            enable_progressive_analysis=False,
            enable_self_reflection=False,
        )

        self.dag = {
            'gen@latest': [],
            'proc_x@latest': ['gen@latest'],
            'proc_y@latest': ['gen@latest'],
            'merge@latest': ['proc_x@latest', 'proc_y@latest'],
        }
        self.execution_order = [
            'gen@latest',
            ['proc_x@latest', 'proc_y@latest'],
            'merge@latest',
        ]

    def tearDown(self):
        """Clean up temp directory unless KEEP_TEST_ARTIFACTS is set."""
        if not KEEP_TEST_ARTIFACTS and self.test_root.exists():
            try:
                shutil.rmtree(self.test_root)
            except Exception as e:
                print(f'Warning: Failed to clean up {self.test_root}: {e}')

        self.executor = None
        self.container = None

    def test_parallel_then_merge(self):
        """gen=100 -> proc_x=110, proc_y=200 (parallel) -> merge=310."""
        container = self.container
        executor = self.executor

        codes = {
            'gen@latest': 'print("BASE_VALUE=100")',
            'proc_x@latest': (
                'import os, json\n'
                'upstream = json.loads(os.environ.get("UPSTREAM_OUTPUTS", "{}"))\n'
                'gen_stdout = upstream["gen@latest"]["stdout"].strip()\n'
                'val = int(gen_stdout.split("=")[1])\n'
                'print(f"X_RESULT={val + 10}")\n'
            ),
            'proc_y@latest': (
                'import os, json\n'
                'upstream = json.loads(os.environ.get("UPSTREAM_OUTPUTS", "{}"))\n'
                'gen_stdout = upstream["gen@latest"]["stdout"].strip()\n'
                'val = int(gen_stdout.split("=")[1])\n'
                'print(f"Y_RESULT={val * 2}")\n'
            ),
            'merge@latest': (
                'import os, json\n'
                'upstream = json.loads(os.environ.get("UPSTREAM_OUTPUTS", "{}"))\n'
                'x_stdout = upstream["proc_x@latest"]["stdout"].strip()\n'
                'y_stdout = upstream["proc_y@latest"]["stdout"].strip()\n'
                'x_val = int(x_stdout.split("=")[1])\n'
                'y_val = int(y_stdout.split("=")[1])\n'
                'print(f"MERGED={x_val + y_val}")\n'
            ),
        }

        async def mock_execute_single(
                skill_id, dag, execution_input=None, query=''):
            exec_input = executor._build_execution_input(
                skill_id, dag, execution_input)
            code = codes.get(skill_id, 'print("unknown")')
            output = await container.execute_python_code(
                code=code, skill_id=skill_id, input_spec=exec_input)
            executor._outputs[skill_id] = output
            container.spec.link_upstream(skill_id, output)
            return SkillExecutionResult(
                skill_id=skill_id,
                success=(output.exit_code == 0),
                output=output,
                error=output.stderr if output.exit_code != 0 else None)

        executor._execute_single_skill = mock_execute_single

        result = run_async(executor.execute(
            dag=self.dag,
            execution_order=self.execution_order,
            stop_on_failure=True,
            query='test parallel'))

        self.assertTrue(result.success, 'DAG should succeed')

        gen_out = result.results['gen@latest'].output.stdout.strip()
        self.assertEqual(gen_out, 'BASE_VALUE=100')

        x_out = result.results['proc_x@latest'].output.stdout.strip()
        self.assertEqual(x_out, 'X_RESULT=110',
                         f'proc_x should output 110, got: {x_out}')

        y_out = result.results['proc_y@latest'].output.stdout.strip()
        self.assertEqual(y_out, 'Y_RESULT=200',
                         f'proc_y should output 200, got: {y_out}')

        merge_out = result.results['merge@latest'].output.stdout.strip()
        self.assertEqual(merge_out, 'MERGED=310',
                         f'merge should output 310, got: {merge_out}')

    def test_parallel_skills_both_receive_upstream(self):
        """Both proc_x and proc_y independently receive gen's output."""
        # Simulate gen output
        self.executor._outputs['gen@latest'] = ExecutionOutput(
            stdout='BASE_VALUE=100\n', stderr='', exit_code=0, duration_ms=10)

        input_x = self.executor._build_execution_input(
            'proc_x@latest', self.dag)
        input_y = self.executor._build_execution_input(
            'proc_y@latest', self.dag)

        # Both should have UPSTREAM_OUTPUTS
        for label, inp in [('proc_x', input_x), ('proc_y', input_y)]:
            with self.subTest(skill=label):
                self.assertIn('UPSTREAM_OUTPUTS', inp.env_vars)
                upstream = json.loads(inp.env_vars['UPSTREAM_OUTPUTS'])
                self.assertIn('gen@latest', upstream)
                self.assertIn('BASE_VALUE=100',
                              upstream['gen@latest']['stdout'])

    def test_merge_receives_both_parallel_outputs(self):
        """merge skill receives outputs from both proc_x and proc_y."""
        self.executor._outputs['proc_x@latest'] = ExecutionOutput(
            stdout='X_RESULT=110\n', stderr='', exit_code=0, duration_ms=10)
        self.executor._outputs['proc_y@latest'] = ExecutionOutput(
            stdout='Y_RESULT=200\n', stderr='', exit_code=0, duration_ms=10)

        input_merge = self.executor._build_execution_input(
            'merge@latest', self.dag)
        upstream = json.loads(input_merge.env_vars['UPSTREAM_OUTPUTS'])

        self.assertIn('proc_x@latest', upstream)
        self.assertIn('proc_y@latest', upstream)
        self.assertIn('X_RESULT=110', upstream['proc_x@latest']['stdout'])
        self.assertIn('Y_RESULT=200', upstream['proc_y@latest']['stdout'])


# ============================================================================
# Test 4: Edge cases and robustness
# ============================================================================

class TestDAGEdgeCases(unittest.TestCase):
    """Test edge cases in DAG upstream-downstream data passing."""

    def setUp(self):
        """Create temp directories and basic infrastructure."""
        self.test_root = Path(
            tempfile.mkdtemp(prefix='test_dag_edge_cases_'))
        self.skills_dir = self.test_root / 'skills'
        self.workspace_dir = self.test_root / 'workspace'

        self.skill_a = create_mock_skill(
            'solo@latest', 'Solo', 'Standalone skill',
            self.skills_dir / 'solo')
        self.skills = {'solo@latest': self.skill_a}

        self.container = SkillContainer(
            workspace_dir=self.workspace_dir, use_sandbox=False)

        self.executor = DAGExecutor(
            container=self.container,
            skills=self.skills,
            workspace_dir=self.workspace_dir,
            llm=None,
            enable_progressive_analysis=False,
            enable_self_reflection=False,
        )

    def tearDown(self):
        """Clean up temp directory unless KEEP_TEST_ARTIFACTS is set."""
        if not KEEP_TEST_ARTIFACTS and self.test_root.exists():
            try:
                shutil.rmtree(self.test_root)
            except Exception as e:
                print(f'Warning: Failed to clean up {self.test_root}: {e}')

        self.executor = None
        self.container = None

    def test_no_upstream_no_env_vars(self):
        """Skill with no dependencies has no UPSTREAM env vars."""
        dag = {'solo@latest': []}
        exec_input = self.executor._build_execution_input(
            'solo@latest', dag)

        self.assertNotIn('UPSTREAM_OUTPUTS', exec_input.env_vars,
                         'No UPSTREAM_OUTPUTS for skill without deps')

    def test_upstream_with_empty_stdout(self):
        """Upstream with empty stdout still appears in UPSTREAM_OUTPUTS."""
        # Add a second skill that depends on solo
        dep_skill = create_mock_skill(
            'dep@latest', 'Dep', 'Depends on solo',
            self.skills_dir / 'dep')
        self.skills['dep@latest'] = dep_skill

        self.executor._outputs['solo@latest'] = ExecutionOutput(
            stdout='', stderr='', exit_code=0, duration_ms=10)

        dag = {
            'solo@latest': [],
            'dep@latest': ['solo@latest'],
        }
        exec_input = self.executor._build_execution_input(
            'dep@latest', dag)
        upstream = json.loads(exec_input.env_vars['UPSTREAM_OUTPUTS'])

        self.assertIn('solo@latest', upstream)
        self.assertEqual(upstream['solo@latest']['stdout'], '')
        # No individual STDOUT shortcut since stdout is empty
        self.assertNotIn('UPSTREAM_SOLO_LATEST_STDOUT', exec_input.env_vars)

    def test_upstream_with_failed_exit_code(self):
        """Upstream failure data is still passed to downstream."""
        dep_skill = create_mock_skill(
            'dep@latest', 'Dep', 'Depends on solo',
            self.skills_dir / 'dep')
        self.skills['dep@latest'] = dep_skill

        self.executor._outputs['solo@latest'] = ExecutionOutput(
            stdout='partial output\n',
            stderr='something went wrong\n',
            exit_code=1,
            duration_ms=10,
        )

        dag = {
            'solo@latest': [],
            'dep@latest': ['solo@latest'],
        }
        exec_input = self.executor._build_execution_input(
            'dep@latest', dag)
        upstream = json.loads(exec_input.env_vars['UPSTREAM_OUTPUTS'])

        self.assertEqual(upstream['solo@latest']['exit_code'], 1)
        self.assertIn('something went wrong',
                       upstream['solo@latest']['stderr'])

    def test_safe_key_special_characters(self):
        """Skill IDs with @, -, . are sanitized in env var names."""
        special_skill = create_mock_skill(
            'my-tool.v2@latest', 'MyTool', 'Tool with special chars',
            self.skills_dir / 'my_tool')
        self.skills['my-tool.v2@latest'] = special_skill

        dep_skill = create_mock_skill(
            'consumer@latest', 'Consumer', 'Depends on special',
            self.skills_dir / 'consumer')
        self.skills['consumer@latest'] = dep_skill

        self.executor._outputs['my-tool.v2@latest'] = ExecutionOutput(
            stdout='special output\n', stderr='', exit_code=0, duration_ms=10)

        dag = {
            'my-tool.v2@latest': [],
            'consumer@latest': ['my-tool.v2@latest'],
        }
        exec_input = self.executor._build_execution_input(
            'consumer@latest', dag)

        # Safe key: my-tool.v2@latest -> MY_TOOL_V2_LATEST
        expected_key = 'UPSTREAM_MY_TOOL_V2_LATEST_STDOUT'
        self.assertIn(expected_key, exec_input.env_vars,
                       f'{expected_key} should be in env_vars, '
                       f'got keys: {list(exec_input.env_vars.keys())}')


# ============================================================================
# Test suite
# ============================================================================

def suite():
    """Create test suite with all test cases."""
    loader = unittest.TestLoader()
    test_suite = unittest.TestSuite()
    test_suite.addTests(
        loader.loadTestsFromTestCase(TestDAGUpstreamDownstream))
    test_suite.addTests(
        loader.loadTestsFromTestCase(TestDAGFullPipeline))
    test_suite.addTests(
        loader.loadTestsFromTestCase(TestDAGParallelMixed))
    test_suite.addTests(
        loader.loadTestsFromTestCase(TestDAGEdgeCases))
    return test_suite


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite())
