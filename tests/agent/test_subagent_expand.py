# Copyright (c) Alibaba, Inc. and its affiliates.
from omegaconf import OmegaConf

from ms_agent.agent.templates.subagent_expand import expand_subagents


def test_expand_creates_definitions():
    cfg = OmegaConf.create({'subagents': ['explore', 'research'], 'tools': {}})
    expand_subagents(cfg)
    defs = cfg.tools.agent_tools.definitions
    names = [d.tool_name for d in defs]
    assert names == ['explore', 'research']
    assert all(d.config_path.startswith('template://') for d in defs)
    assert all(d.output_mode == 'final_message' for d in defs)
    # Standard {request: string} parameter schema is attached.
    assert defs[0].parameters['required'] == ['request']


def test_explicit_definition_wins():
    cfg = OmegaConf.create({
        'subagents': ['explore'],
        'tools': {
            'agent_tools': {
                'definitions': [{
                    'tool_name': 'explore',
                    'config_path': '/custom/path',
                    'description': 'mine',
                }]
            }
        },
    })
    expand_subagents(cfg)
    defs = cfg.tools.agent_tools.definitions
    assert len(defs) == 1
    assert defs[0].config_path == '/custom/path'  # not overwritten


def test_no_subagents_is_untouched():
    cfg = OmegaConf.create({'tools': {'file_system': {}}})
    expand_subagents(cfg)
    assert 'agent_tools' not in cfg.tools


def test_partial_overlap_merges():
    cfg = OmegaConf.create({
        'subagents': ['explore', 'build'],
        'tools': {
            'agent_tools': {
                'definitions': [{
                    'tool_name': 'explore',
                    'config_path': '/custom/explore',
                }]
            }
        },
    })
    expand_subagents(cfg)
    by_name = {
        d.tool_name: d.config_path
        for d in cfg.tools.agent_tools.definitions
    }
    assert by_name['explore'] == '/custom/explore'        # kept
    assert by_name['build'] == 'template://build'         # generated
