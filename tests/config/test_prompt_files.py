# Copyright (c) ModelScope Contributors. All rights reserved.
import os
import tempfile
import unittest

from ms_agent.config import Config


class TestPromptFiles(unittest.TestCase):

    def _write(self, path: str, content: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

    def test_inline_system_not_overridden(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = os.path.join(td, 'agent.yaml')
            self._write(
                cfg_path,
                """llm:
  service: openai
  model: qwen3-max
code_file: researcher
prompt:
  system: |
    INLINE_SYSTEM
  lang: zh
  family: qwen-3
""",
            )
            # Create prompt file that would match if resolver ran
            self._write(
                os.path.join(td, 'prompts', 'researcher', 'zh', 'qwen-3.md'),
                "FILE_SYSTEM",
            )
            config = Config.from_task(td)
            self.assertIn('INLINE_SYSTEM', config.prompt.system)

    def test_load_family_prompt_file(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(
                os.path.join(td, 'agent.yaml'),
                """llm:
  service: openai
  model: qwen3-max
code_file: researcher
prompt:
  lang: zh
  family: qwen-3
""",
            )
            self._write(
                os.path.join(td, 'prompts', 'researcher', 'zh', 'qwen-3.md'),
                "QWEN3_SYSTEM",
            )
            self._write(
                os.path.join(td, 'prompts', 'researcher', 'zh', 'base.md'),
                "BASE_SYSTEM",
            )
            config = Config.from_task(td)
            self.assertEqual(config.prompt.system.strip(), 'QWEN3_SYSTEM')

    def test_fallback_to_base_when_family_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(
                os.path.join(td, 'agent.yaml'),
                """llm:
  service: openai
  model: qwen3-max
code_file: researcher
prompt:
  lang: zh
  family: qwen-3
""",
            )
            self._write(
                os.path.join(td, 'prompts', 'researcher', 'zh', 'base.md'),
                "BASE_ONLY",
            )
            config = Config.from_task(td)
            self.assertEqual(config.prompt.system.strip(), 'BASE_ONLY')

    def test_custom_prompt_root_relative(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(
                os.path.join(td, 'agent.yaml'),
                """llm:
  service: openai
  model: claude-3-5-sonnet
code_file: reporter
prompt:
  lang: en
  family: claude
  root: my_prompts
""",
            )
            self._write(
                os.path.join(td, 'my_prompts', 'reporter', 'en', 'claude.md'),
                "CLAUDE_REPORTER",
            )
            config = Config.from_task(td)
            self.assertEqual(config.prompt.system.strip(), 'CLAUDE_REPORTER')

    def test_lang_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(
                os.path.join(td, 'agent.yaml'),
                """llm:
  service: openai
  model: gpt-4.1
code_file: searcher
prompt:
  lang: en
  family: gpt
""",
            )
            # en missing, fallback to zh
            self._write(
                os.path.join(td, 'prompts', 'searcher', 'zh', 'gpt.md'),
                "GPT_ZH",
            )
            config = Config.from_task(td)
            self.assertEqual(config.prompt.system.strip(), 'GPT_ZH')


if __name__ == '__main__':
    unittest.main()

