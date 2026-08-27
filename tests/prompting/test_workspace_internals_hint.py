"""The section that tells the agent which directories under its working
directory are the framework's own records."""
from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent


def _agent_for(workspace, session_id='abc123', log_dir=None):
    agent = LLMAgent.__new__(LLMAgent)
    agent.config = OmegaConf.create({'output_dir': str(workspace)})

    class _Runtime:
        pass

    runtime = _Runtime()
    runtime.session_id = session_id
    agent.runtime = runtime

    if log_dir is not None:

        class _Log:
            directory = log_dir

        agent.session_log = _Log()
    return agent


def test_section_is_absent_when_records_live_elsewhere(tmp_path):
    """A project opened from an existing folder keeps its transcripts outside
    the working directory; there is nothing to warn about."""
    workspace = tmp_path / 'plain-project'
    workspace.mkdir()
    assert _agent_for(workspace)._build_workspace_internals_section() == ''


def test_section_names_the_directories_and_this_session(tmp_path):
    workspace = tmp_path / 'managed-project'
    (workspace / 'sessions' / 'abc123').mkdir(parents=True)
    (workspace / '.ms_agent').mkdir()

    section = _agent_for(workspace)._build_workspace_internals_section()

    assert 'sessions/' in section
    assert '.ms_agent/' in section
    assert 'sessions/abc123/' in section
    # The reason the agent needs this at all: its own prompt is already on
    # disk, so searching for a phrase from the request matches the transcript.
    assert 'searching' in section


def test_the_named_directory_is_the_one_being_written_to(tmp_path):
    """The agent's tag is not its session directory; sending the model after
    `sessions/Agent-default/` would send it somewhere that does not exist."""
    workspace = tmp_path / 'managed-project'
    real = workspace / 'sessions' / 'de43058dc0b1'
    real.mkdir(parents=True)

    agent = _agent_for(workspace, session_id='Agent-default', log_dir=real)
    section = agent._build_workspace_internals_section()
    assert 'sessions/de43058dc0b1/' in section
    assert 'Agent-default' not in section


def test_it_reaches_the_system_prompt(tmp_path):
    """Guards the wiring, not just the builder."""
    workspace = tmp_path / 'managed-project'
    (workspace / 'sessions' / 'sid').mkdir(parents=True)

    agent = _agent_for(workspace, session_id='sid')
    # ``system`` reads through the config; set it where it actually comes from.
    agent.config = OmegaConf.create({
        'output_dir': str(workspace),
        'prompt': {
            'system': 'BASE PROMPT'
        },
    })
    agent._memory_guidance = None
    agent._skill_injector = None
    agent._skill_runtime = None
    agent._personalization_enabled = lambda: False

    content = agent._build_system_content()
    assert content.startswith('BASE PROMPT')
    assert 'sessions/sid/' in content
