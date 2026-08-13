# Copyright (c) ModelScope Contributors. All rights reserved.
"""The work-dir project patch must be merged exactly once (golden scenario 9).

Before the fix, ConfigResolver.resolve() merged <project>/.ms_agent/config.yaml
as layer 4 and BaseAgent.__init__ merged it AGAIN on top of every caller-side
override applied between resolve() and agent construction — silently making the
project patch the highest-priority layer (the WebUI's shaping lost to it).
"""
from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.config.resolver import ConfigResolver


def _project_with_patch(tmp_path, yaml_text):
    project = tmp_path / 'proj'
    (project / '.ms_agent').mkdir(parents=True)
    (project / '.ms_agent' / 'config.yaml').write_text(yaml_text)
    return project


def test_resolve_marks_patch_applied(tmp_path):
    project = _project_with_patch(tmp_path, 'llm:\n  model: patched-model\n')
    resolver = ConfigResolver(global_dir=str(tmp_path / 'home'))
    cfg = resolver.resolve(project_path=str(project))
    assert cfg._project_patch_applied is True
    assert cfg.llm.model == 'patched-model'


def test_caller_override_survives_agent_init(tmp_path):
    project = _project_with_patch(tmp_path, 'llm:\n  model: patched-model\n')
    resolver = ConfigResolver(global_dir=str(tmp_path / 'home'))
    cfg = resolver.resolve(project_path=str(project))
    # caller-side shaping AFTER resolve (what the WebUI does)
    OmegaConf.update(cfg, 'llm.model', 'shaped-model', merge=True)
    OmegaConf.update(cfg, 'output_dir', str(project), merge=True)
    agent = LLMAgent(config=cfg)
    assert agent.config.llm.model == 'shaped-model'  # not re-clobbered


def test_from_task_path_still_merges_patch(tmp_path):
    """Configs that did NOT go through resolve() keep the old behavior."""
    project = _project_with_patch(tmp_path, 'llm:\n  model: patched-model\n')
    cfg = OmegaConf.create({'output_dir': str(project),
                            'llm': {'model': 'yaml-model'}})
    agent = LLMAgent(config=cfg)
    assert agent.config.llm.model == 'patched-model'
