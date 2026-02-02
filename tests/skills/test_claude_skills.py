"""
Unit tests for Claude Skills using AutoSkills.

These tests cover the 16 skills in projects/agent_skills/skills/claude_skills:
1. algorithmic-art - Generative art with p5.js
2. brand-guidelines - Anthropic brand styling
3. canvas-design - Visual art in PNG/PDF
4. doc-coauthoring - Documentation workflow
5. docx - Word document operations
6. frontend-design - Frontend UI design
7. internal-comms - Internal communications
8. mcp-builder - MCP server creation
9. pdf - PDF manipulation
10. pptx - PowerPoint operations
11. skill-creator - Skill creation guide
12. slack-gif-creator - Slack GIF creation
13. theme-factory - Theme styling
14. web-artifacts-builder - React/HTML artifacts
15. webapp-testing - Playwright testing
16. xlsx - Excel/spreadsheet operations

Usage:
    # Run all tests
    python -m unittest tests.skills.test_claude_skills -v

    # Run specific test class
    python -m unittest tests.skills.test_claude_skills.TestClaudeSkillsRetrieval -v

    # Run specific test method
    python -m unittest tests.skills.test_claude_skills.TestClaudeSkillsRetrieval.test_pdf_skill -v
"""
import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from ms_agent.llm.openai_llm import OpenAI
from ms_agent.skill.auto_skills import AutoSkills
from omegaconf import DictConfig


#### Prerequisites ####
# - ALL ENVs: # LLM_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL, SKILLS_PATH, WORK_DIR, IS_REMOVE_WORK_DIR, USE_SANDBOX
# - Get SKILLS_PATH: git clone https://github.com/anthropics/skills.git and set the path `skills/skills` directory.


IS_REMOVE_WORK_DIR: bool = os.getenv('IS_REMOVE_WORK_DIR',
                                     'true').lower() == 'true'

USE_SANDBOX: bool = os.getenv('USE_SANDBOX',
                                'false').lower() == 'true'


def get_llm_config() -> DictConfig:
    """Get LLM configuration from environment variables."""
    return DictConfig({
        'llm': {
            'service':
            'openai',
            'model':
            os.getenv('LLM_MODEL', 'qwen3-max'),
            'openai_api_key':
            os.getenv('OPENAI_API_KEY'),
            'openai_base_url':
            os.getenv('OPENAI_BASE_URL',
                      'https://dashscope.aliyuncs.com/compatible-mode/v1')
        }
    })


def get_skills_path() -> str:
    """Get the path to claude_skills directory."""
    skills_path = os.getenv('SKILLS_PATH')
    if skills_path:
        return skills_path
    # Default path relative to project root
    return str(
        Path(__file__).parent.parent.parent / 'projects' / 'agent_skills'
        / 'skills' / 'claude_skills')


def get_work_dir() -> str:
    """Get work directory from env or create temp directory."""
    work_dir = os.getenv('WORK_DIR')
    if work_dir:
        os.makedirs(work_dir, exist_ok=True)
        return work_dir
    return tempfile.mkdtemp(prefix='ms_agent_test_')


def run_async(coro):
    """Helper to run async coroutines in sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestClaudeSkillsRetrieval(unittest.TestCase):
    """Test skill retrieval and DAG building for each skill category."""

    def setUp(self):
        """Setup test fixtures before each test."""
        self.config = get_llm_config()
        self.skills_path = get_skills_path()
        self.work_dir = get_work_dir()

        # Skip test if no API key
        if not self.config.llm.openai_api_key:
            self.skipTest('OPENAI_API_KEY not set')

        # Create AutoSkills instance for this test
        self.auto_skills = AutoSkills(
            skills=self.skills_path,
            llm=OpenAI.from_config(self.config),
            use_sandbox=USE_SANDBOX,
            work_dir=self.work_dir,
        )

    def tearDown(self):
        """Cleanup after each test."""
        # Clean up the temporary work directory (only if not from env)
        if IS_REMOVE_WORK_DIR and hasattr(self, 'work_dir') and os.path.exists(
                self.work_dir) and not os.getenv('WORK_DIR'):
            try:
                shutil.rmtree(self.work_dir)
            except Exception as e:
                print(f'Warning: Failed to clean up work_dir: {e}')

        # Clean up AutoSkills instance
        if hasattr(self, 'auto_skills'):
            self.auto_skills = None

    def _run_skill_retrieval_test(self, queries: list, skill_name: str):
        """
        Helper method to run skill retrieval test.

        Args:
            queries: List of user queries to test.
            skill_name: Name of the skill being tested.
        """
        for query in queries:
            with self.subTest(query=query):
                result = run_async(self.auto_skills.get_skill_dag(query))
                self.assertIsNotNone(
                    result, f'Result should not be None for: {query}')

                # Assert skills_dag and execution_order are not empty
                self.assertTrue(
                    result.dag,
                    f'skills_dag should not be empty for: {query}')
                self.assertTrue(
                    result.execution_order,
                    f'execution_order should not be empty for: {query}')

                if result.selected_skills:
                    skill_ids = list(result.selected_skills.keys())
                    print(f'\n[{skill_name}] Query: {query}')
                    print(f'[{skill_name}] Retrieved skills: {skill_ids}')
                    print(f'[{skill_name}] Execution order: {result.execution_order}')

    def test_algorithmic_art_skill(self):
        """
        Test algorithmic-art skill retrieval.

        Skill: Creates generative art using p5.js with seeded randomness.
        Capabilities: Algorithmic philosophy creation, p5.js implementation,
                     flow fields, particle systems, interactive artifacts.
        """
        queries = [
            'Create a generative art piece with flowing particles that looks organic',
            'Make an algorithmic art using flow fields and Perlin noise',
            'I want to create interactive p5.js artwork with seeded randomness',
        ]
        self._run_skill_retrieval_test(queries, 'algorithmic-art')

    def test_brand_guidelines_skill(self):
        """
        Test brand-guidelines skill retrieval.

        Skill: Applies Anthropic's brand colors and typography.
        Capabilities: Brand color application, typography styling,
                     visual formatting, corporate identity.
        """
        queries = [
            'Apply Anthropic brand colors to my presentation',
            'Style this document with official brand guidelines',
            'Format this artifact using company design standards',
        ]
        self._run_skill_retrieval_test(queries, 'brand-guidelines')

    def test_canvas_design_skill(self):
        """
        Test canvas-design skill retrieval.

        Skill: Creates visual art in PNG and PDF documents.
        Capabilities: Design philosophy creation, poster design,
                     static visual art, composition, color theory.
        """
        queries = [
            'Create a beautiful minimalist poster design in PDF format',
            'Design an artistic visual piece using canvas with modern aesthetics',
            'Make a museum-quality art poster with geometric patterns',
        ]
        self._run_skill_retrieval_test(queries, 'canvas-design')

    def test_doc_coauthoring_skill(self):
        """
        Test doc-coauthoring skill retrieval.

        Skill: Guides users through documentation co-authoring workflow.
        Capabilities: Context gathering, section refinement,
                     reader testing, iterative document creation.
        """
        queries = [
            'Help me write a technical design document for a new API',
            'I need to create a product requirements document (PRD)',
            'Draft a decision doc for our architecture proposal',
        ]
        self._run_skill_retrieval_test(queries, 'doc-coauthoring')

    def test_docx_skill(self):
        """
        Test docx skill retrieval.

        Skill: Comprehensive Word document creation, editing, and analysis.
        Capabilities: Document creation, tracked changes, comments,
                     formatting preservation, text extraction.
        """
        queries = [
            'Create a professional Word document with headers and bullet points',
            'Edit this docx file and add tracked changes to section 3',
            'Extract text from this Word document and analyze its structure',
            'Add comments to this docx file for review',
        ]
        self._run_skill_retrieval_test(queries, 'docx')

    def test_frontend_design_skill(self):
        """
        Test frontend-design skill retrieval.

        Skill: Creates distinctive, production-grade frontend interfaces.
        Capabilities: Web components, landing pages, dashboards,
                     React components, HTML/CSS layouts, UI styling.
        """
        queries = [
            'Build a modern landing page with bold typography and animations',
            'Create a React dashboard component with distinctive styling',
            'Design a web interface that avoids generic AI aesthetics',
            'Make a beautiful HTML/CSS card component with hover effects',
        ]
        self._run_skill_retrieval_test(queries, 'frontend-design')

    def test_internal_comms_skill(self):
        """
        Test internal-comms skill retrieval.

        Skill: Writes internal communications in company formats.
        Capabilities: 3P updates (Progress/Plans/Problems), newsletters,
                     FAQs, status reports, incident reports.
        """
        queries = [
            'Write a 3P update for our weekly team meeting',
            'Draft a company newsletter about Q4 achievements',
            'Create FAQ responses for the new product launch',
            'Write an incident report for yesterday\'s outage',
        ]
        self._run_skill_retrieval_test(queries, 'internal-comms')

    def test_mcp_builder_skill(self):
        """
        Test mcp-builder skill retrieval.

        Skill: Creates MCP servers for LLM-external service interaction.
        Capabilities: MCP protocol implementation, tool design,
                     API integration, TypeScript/Python SDK usage.
        """
        queries = [
            'Build an MCP server to integrate with GitHub API',
            'Create an MCP tool that enables Claude to search databases',
            'Implement a Model Context Protocol server in TypeScript',
        ]
        self._run_skill_retrieval_test(queries, 'mcp-builder')

    def test_pdf_skill(self):
        """
        Test pdf skill retrieval.

        Skill: Comprehensive PDF manipulation toolkit.
        Capabilities: Text/table extraction, PDF creation,
                     merging/splitting, form filling, watermarks.
        """
        queries = [
            'Extract all tables from this PDF document',
            'Create a new PDF report with charts and formatted text',
            'Merge multiple PDF files into one document',
            'Fill out this PDF form with the provided data',
            'Split this large PDF into separate pages',
        ]
        self._run_skill_retrieval_test(queries, 'pdf')

    def test_pptx_skill(self):
        """
        Test pptx skill retrieval.

        Skill: PowerPoint creation, editing, and analysis.
        Capabilities: Presentation creation, template editing,
                     slide layouts, speaker notes, thumbnails.
        """
        queries = [
            'Create a PowerPoint presentation about machine learning',
            'Edit this pptx file to update the charts and styling',
            'Generate a slide deck using this template with new content',
            'Add speaker notes to all slides in this presentation',
        ]
        self._run_skill_retrieval_test(queries, 'pptx')

    def test_skill_creator_skill(self):
        """
        Test skill-creator skill retrieval.

        Skill: Guide for creating effective skills.
        Capabilities: Skill design, SKILL.md creation,
                     resource bundling, workflow definition.
        """
        queries = [
            'Create a new skill for image processing with Python',
            'Help me design a skill that extends Claude\'s capabilities',
            'Build a custom skill with scripts and reference documents',
        ]
        self._run_skill_retrieval_test(queries, 'skill-creator')

    def test_slack_gif_creator_skill(self):
        """
        Test slack-gif-creator skill retrieval.

        Skill: Creates animated GIFs optimized for Slack.
        Capabilities: GIF creation, animation (shake, pulse, bounce),
                     Slack emoji optimization, frame composition.
        """
        queries = [
            'Make a bouncing star GIF for Slack emoji',
            'Create an animated celebration GIF optimized for Slack',
            'Generate a pulsing heart animation for team chat',
        ]
        self._run_skill_retrieval_test(queries, 'slack-gif-creator')

    def test_theme_factory_skill(self):
        """
        Test theme-factory skill retrieval.

        Skill: Styles artifacts with pre-set or custom themes.
        Capabilities: Theme application, color palettes,
                     font pairings, visual consistency.
        """
        queries = [
            'Apply the Ocean Depths theme to my presentation',
            'Style this document with the Tech Innovation theme',
            'Create a custom theme with warm earth tones for my slides',
        ]
        self._run_skill_retrieval_test(queries, 'theme-factory')

    def test_web_artifacts_builder_skill(self):
        """
        Test web-artifacts-builder skill retrieval.

        Skill: Builds elaborate HTML artifacts using React/Tailwind.
        Capabilities: React components, shadcn/ui, Tailwind CSS,
                     single-file HTML bundling.
        """
        queries = [
            'Build a complex React dashboard with shadcn/ui components',
            'Create a multi-component HTML artifact with state management',
            'Develop an interactive web app with Tailwind CSS styling',
        ]
        self._run_skill_retrieval_test(queries, 'web-artifacts-builder')

    def test_webapp_testing_skill(self):
        """
        Test webapp-testing skill retrieval.

        Skill: Tests local web applications using Playwright.
        Capabilities: Browser automation, screenshot capture,
                     UI interaction, server lifecycle management.
        """
        queries = [
            'Test this web application using Playwright automation',
            'Capture screenshots of my local webapp running on port 3000',
            'Debug UI behavior by inspecting the rendered DOM',
            'Verify frontend functionality with automated browser tests',
        ]
        self._run_skill_retrieval_test(queries, 'webapp-testing')

    def test_xlsx_skill(self):
        """
        Test xlsx skill retrieval.

        Skill: Comprehensive Excel/spreadsheet operations.
        Capabilities: Spreadsheet creation, formulas, formatting,
                     data analysis, visualization, recalculation.
        """
        queries = [
            'Create an Excel financial model with formulas and formatting',
            'Analyze data in this spreadsheet and create summary charts',
            'Build a budget tracker spreadsheet with automatic calculations',
            'Modify this xlsx file to add new formulas and preserve formatting',
        ]
        self._run_skill_retrieval_test(queries, 'xlsx')


class TestSkillsCombination(unittest.TestCase):
    """Test skill retrieval for queries requiring multiple skills."""

    def setUp(self):
        """Setup test fixtures before each test."""
        self.config = get_llm_config()
        self.skills_path = get_skills_path()
        self.work_dir = get_work_dir()

        if not self.config.llm.openai_api_key:
            self.skipTest('OPENAI_API_KEY not set')

        self.auto_skills = AutoSkills(
            skills=self.skills_path,
            llm=OpenAI.from_config(self.config),
            use_sandbox=USE_SANDBOX,
            work_dir=self.work_dir,
        )

    def tearDown(self):
        """Cleanup after each test."""
        if IS_REMOVE_WORK_DIR and hasattr(self, 'work_dir') and os.path.exists(
                self.work_dir) and not os.getenv('WORK_DIR'):
            try:
                shutil.rmtree(self.work_dir)
            except Exception as e:
                print(f'Warning: Failed to clean up work_dir: {e}')

        if hasattr(self, 'auto_skills'):
            self.auto_skills = None

    def _assert_dag_result(self, result, query: str):
        """Assert common DAG result validations."""
        self.assertIsNotNone(result, f'Result should not be None for: {query}')
        self.assertTrue(
            result.dag,
            f'skills_dag should not be empty for: {query}')
        self.assertTrue(
            result.execution_order,
            f'execution_order should not be empty for: {query}')

    def test_document_with_theme(self):
        """
        Test combining document creation with theme styling.

        Expected: pptx + theme-factory or docx + brand-guidelines
        """
        query = 'Create a PowerPoint presentation about AI and apply Ocean Depths theme'
        result = run_async(self.auto_skills.get_skill_dag(query))

        self._assert_dag_result(result, query)
        if result.selected_skills:
            skill_ids = list(result.selected_skills.keys())
            print(f'\n[Combination] Query: {query}')
            print(f'[Combination] Retrieved skills: {skill_ids}')
            print(f'[Combination] Execution order: {result.execution_order}')

    def test_frontend_with_testing(self):
        """
        Test combining frontend design with webapp testing.

        Expected: frontend-design + webapp-testing
        """
        query = 'Build a React dashboard and test it with Playwright'
        result = run_async(self.auto_skills.get_skill_dag(query))

        self._assert_dag_result(result, query)
        if result.selected_skills:
            skill_ids = list(result.selected_skills.keys())
            print(f'\n[Combination] Query: {query}')
            print(f'[Combination] Retrieved skills: {skill_ids}')
            print(f'[Combination] Execution order: {result.execution_order}')

    def test_pdf_and_xlsx_data(self):
        """
        Test combining PDF and Excel operations.

        Expected: pdf + xlsx for data extraction and reporting
        """
        query = 'Extract data from PDF tables and create an Excel analysis report'
        result = run_async(self.auto_skills.get_skill_dag(query))

        self._assert_dag_result(result, query)
        if result.selected_skills:
            skill_ids = list(result.selected_skills.keys())
            print(f'\n[Combination] Query: {query}')
            print(f'[Combination] Retrieved skills: {skill_ids}')
            print(f'[Combination] Execution order: {result.execution_order}')

    def test_doc_with_brand_styling(self):
        """
        Test combining document creation with brand guidelines.

        Expected: docx + brand-guidelines
        """
        query = 'Create a Word document and apply Anthropic brand styling'
        result = run_async(self.auto_skills.get_skill_dag(query))

        self._assert_dag_result(result, query)
        if result.selected_skills:
            skill_ids = list(result.selected_skills.keys())
            print(f'\n[Combination] Query: {query}')
            print(f'[Combination] Retrieved skills: {skill_ids}')
            print(f'[Combination] Execution order: {result.execution_order}')


class TestSkillsExecution(unittest.TestCase):
    """
    Test full skill execution pipeline.

    Note: These tests require actual LLM API access and may take longer.
    """

    def setUp(self):
        """Setup test fixtures before each test."""
        self.config = get_llm_config()
        self.skills_path = get_skills_path()
        self.work_dir = get_work_dir()

        if not self.config.llm.openai_api_key:
            self.skipTest('OPENAI_API_KEY not set')

        self.auto_skills = AutoSkills(
            skills=self.skills_path,
            llm=OpenAI.from_config(self.config),
            use_sandbox=USE_SANDBOX,
            work_dir=self.work_dir,
            max_retries=3,
        )

    def tearDown(self):
        """Cleanup after each test."""
        # Clean up any output files generated during execution
        if IS_REMOVE_WORK_DIR and hasattr(self, 'work_dir') and os.path.exists(
                self.work_dir) and not os.getenv('WORK_DIR'):
            try:
                shutil.rmtree(self.work_dir)
            except Exception as e:
                print(f'Warning: Failed to clean up work_dir: {e}')

        if IS_REMOVE_WORK_DIR and hasattr(self, 'auto_skills'):
            # Clean up executor if exists
            if hasattr(self.auto_skills,
                       '_executor') and self.auto_skills._executor:
                try:
                    self.auto_skills.cleanup()
                except Exception as e:
                    print(f'Warning: Failed to cleanup auto_skills: {e}')
            self.auto_skills = None

    def test_execute_pdf_creation(self):
        """
        Test full execution of PDF creation skill.

        This test verifies end-to-end skill execution.
        """
        query = "Create a simple PDF report titled 'Test Report' with basic text content"
        result = run_async(self.auto_skills.run(query))

        self.assertIsNotNone(result, f'Result should not be None for: {query}')
        print(f'\n[Execution] Query: {query}')
        print(f'[Execution] Is complete: {result.is_complete}')

        # Assert execution_result even if None
        if result.execution_result:
            print(f'[Execution] Success: {result.execution_result.success}')
            print(
                f'[Execution] Skills executed: {list(result.execution_result.results.keys())}'
            )
            self.assertTrue(
                result.execution_result.success,
                f'Execution should succeed for: {query}')
        else:
            self.fail(f'execution_result should not be None for: {query}')

    def test_execute_xlsx_creation(self):
        """Test full execution of Excel creation skill."""
        query = 'Create an Excel spreadsheet with a simple budget table and SUM formula'
        result = run_async(self.auto_skills.run(query))

        self.assertIsNotNone(result, f'Result should not be None for: {query}')
        print(f'\n[Execution] Query: {query}')
        print(f'[Execution] Is complete: {result.is_complete}')

        if result.execution_result:
            print(f'[Execution] Success: {result.execution_result.success}')
            self.assertTrue(
                result.execution_result.success,
                f'Execution should succeed for: {query}')
        else:
            self.fail(f'execution_result should not be None for: {query}')

    def test_execute_slack_gif(self):
        """Test full execution of Slack GIF creation skill."""
        query = 'Create a simple bouncing dot animation GIF for Slack emoji'
        result = run_async(self.auto_skills.run(query))

        self.assertIsNotNone(result, f'Result should not be None for: {query}')
        print(f'\n[Execution] Query: {query}')
        print(f'[Execution] Is complete: {result.is_complete}')

        if result.execution_result:
            print(f'[Execution] Success: {result.execution_result.success}')
            self.assertTrue(
                result.execution_result.success,
                f'Execution should succeed for: {query}')
        else:
            self.fail(f'execution_result should not be None for: {query}')


class TestChatOnlyQueries(unittest.TestCase):
    """Test queries that should be handled as chat-only (no skill retrieval)."""

    def setUp(self):
        """Setup test fixtures before each test."""
        self.config = get_llm_config()
        self.skills_path = get_skills_path()
        self.work_dir = get_work_dir()

        if not self.config.llm.openai_api_key:
            self.skipTest('OPENAI_API_KEY not set')

        self.auto_skills = AutoSkills(
            skills=self.skills_path,
            llm=OpenAI.from_config(self.config),
            use_sandbox=USE_SANDBOX,
            work_dir=self.work_dir,
        )

    def tearDown(self):
        """Cleanup after each test."""
        if IS_REMOVE_WORK_DIR and hasattr(self, 'work_dir') and os.path.exists(
                self.work_dir) and not os.getenv('WORK_DIR'):
            try:
                shutil.rmtree(self.work_dir)
            except Exception as e:
                print(f'Warning: Failed to clean up work_dir: {e}')

        if hasattr(self, 'auto_skills'):
            self.auto_skills = None

    def test_general_chat_queries(self):
        """Test that general chat queries return chat-only response."""
        queries = [
            'What is the capital of France?',
            'Tell me a joke about programming',
            'Explain what machine learning is',
        ]

        for query in queries:
            with self.subTest(query=query):
                result = run_async(self.auto_skills.get_skill_dag(query))
                self.assertIsNotNone(result, f'Result should not be None for: {query}')

                print(f'\n[Chat] Query: {query}')
                print(
                    f'[Chat] Chat response: {result.chat_response is not None}'
                )
                print(
                    f'[Chat] Selected skills: {list(result.selected_skills.keys()) if result.selected_skills else "None"}'
                )

                # For chat-only queries, chat_response should be present
                # OR it should have empty skills (no execution needed)
                is_chat_only = (result.chat_response is not None or
                                not result.selected_skills)
                self.assertTrue(
                    is_chat_only,
                    f'Query should be handled as chat-only: {query}')


class TestSkillDAGStructure(unittest.TestCase):
    """Test the structure and validity of skill DAG results."""

    def setUp(self):
        """Setup test fixtures before each test."""
        self.config = get_llm_config()
        self.skills_path = get_skills_path()
        self.work_dir = get_work_dir()

        if not self.config.llm.openai_api_key:
            self.skipTest('OPENAI_API_KEY not set')

        self.auto_skills = AutoSkills(
            skills=self.skills_path,
            llm=OpenAI.from_config(self.config),
            use_sandbox=USE_SANDBOX,
            work_dir=self.work_dir,
        )

    def tearDown(self):
        """Cleanup after each test."""
        if IS_REMOVE_WORK_DIR and hasattr(self, 'work_dir') and os.path.exists(
                self.work_dir) and not os.getenv('WORK_DIR'):
            try:
                shutil.rmtree(self.work_dir)
            except Exception as e:
                print(f'Warning: Failed to clean up work_dir: {e}')

        if hasattr(self, 'auto_skills'):
            self.auto_skills = None

    def test_dag_result_has_required_fields(self):
        """Test that DAG result contains all required fields."""
        query = 'Create a PDF document'
        result = run_async(self.auto_skills.get_skill_dag(query))

        self.assertIsNotNone(result, f'Result should not be None for: {query}')

        # Check required attributes exist
        self.assertTrue(hasattr(result, 'is_complete'))
        self.assertTrue(hasattr(result, 'selected_skills'))
        self.assertTrue(hasattr(result, 'dag'))
        self.assertTrue(hasattr(result, 'execution_order'))
        self.assertTrue(hasattr(result, 'clarification'))
        self.assertTrue(hasattr(result, 'chat_response'))

        # Assert skills_dag and execution_order are not empty
        self.assertTrue(
            result.dag,
            f'skills_dag should not be empty for: {query}')
        self.assertTrue(
            result.execution_order,
            f'execution_order should not be empty for: {query}')

    def test_execution_order_contains_valid_skills(self):
        """Test that execution order only contains valid skill IDs."""
        query = 'Create a PowerPoint presentation and apply theme'
        result = run_async(self.auto_skills.get_skill_dag(query))

        self.assertIsNotNone(result, f'Result should not be None for: {query}')
        self.assertTrue(
            result.dag,
            f'skills_dag should not be empty for: {query}')
        self.assertTrue(
            result.execution_order,
            f'execution_order should not be empty for: {query}')

        if result.execution_order and result.selected_skills:
            # Flatten execution order (may contain nested lists for parallel execution)
            flat_order = []
            for item in result.execution_order:
                if isinstance(item, list):
                    flat_order.extend(item)
                else:
                    flat_order.append(item)

            # All skills in execution order should be in selected_skills
            for skill_id in flat_order:
                self.assertIn(
                    skill_id, result.selected_skills,
                    f'Skill {skill_id} in execution_order but not in selected_skills'
                )

    def test_skills_dag_structure(self):
        """Test that skills DAG has valid adjacency list structure."""
        query = 'Extract PDF data and create Excel report'
        result = run_async(self.auto_skills.get_skill_dag(query))

        self.assertIsNotNone(result, f'Result should not be None for: {query}')
        self.assertTrue(
            result.dag,
            f'skills_dag should not be empty for: {query}')
        self.assertTrue(
            result.execution_order,
            f'execution_order should not be empty for: {query}')

        if result.dag:
            # DAG should be a dict
            self.assertIsInstance(result.dag, dict)

            # Each value should be a list of dependencies
            for skill_id, deps in result.dag.items():
                self.assertIsInstance(
                    deps, list,
                    f'Dependencies for {skill_id} should be a list')


# Test suite for running all tests
def suite():
    """Create test suite with all test cases."""
    loader = unittest.TestLoader()
    test_suite = unittest.TestSuite()

    test_suite.addTests(
        loader.loadTestsFromTestCase(TestClaudeSkillsRetrieval))
    test_suite.addTests(loader.loadTestsFromTestCase(TestSkillsCombination))
    test_suite.addTests(loader.loadTestsFromTestCase(TestSkillsExecution))
    test_suite.addTests(loader.loadTestsFromTestCase(TestChatOnlyQueries))
    test_suite.addTests(loader.loadTestsFromTestCase(TestSkillDAGStructure))

    return test_suite


if __name__ == '__main__':
    # Run tests with verbosity
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite())
