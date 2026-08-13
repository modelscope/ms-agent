# Copyright (c) ModelScope Contributors. All rights reserved.
"""Hot-reload update notices: when a head file changes mid-conversation, the
next user turn carries a durable <system-reminder> naming the changed files —
the model gets the *event*, not just the silently-updated content.

Also pins the coexistence contract of the three user-turn attachments:
skill update notice (host prefix) + prompt-files notice (SDK prefix) +
memory recall (SDK append) — none may suppress another.
"""
import asyncio

import pytest
from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.llm.utils import Message
from ms_agent.prompting import builtin, workspace_files as wf


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path / 'home'))
    wf.reset_cache()
    yield tmp_path / 'home'
    wf.reset_cache()


def _agent(tmp_path, **cfg):
    base = {'output_dir': str(tmp_path / 'work')}
    base.update(cfg)
    return LLMAgent(config=OmegaConf.create(base))


def _user_turn(text='下一个问题'):
    return [
        Message(role='system', content='S'),
        Message(role='user', content='第一问'),
        Message(role='assistant', content='答'),
        Message(role='user', content=text),
    ]


# ── fingerprints ─────────────────────────────────────────────────────────────


def test_fingerprints_track_injected_body_only(home, tmp_path):
    wf.ensure_home_files()
    work = tmp_path / 'work'
    work.mkdir(parents=True, exist_ok=True)
    base = wf.head_source_fingerprints(str(work))
    assert set(base) == {
        '~/.ms_agent/SOUL.md', '~/.ms_agent/AGENTS.md',
        '~/.ms_agent/PROFILE.md', '<project>/AGENTS.md',
        '<project>/.ms_agent/AGENTS.md'
    }

    # A comment-only edit is invisible to the model -> no fingerprint change.
    with open(home / 'AGENTS.md', 'a', encoding='utf-8') as f:
        f.write('\n<!-- just a note to self -->\n')
    wf.reset_cache()
    assert wf.head_source_fingerprints(str(work)) == base

    # Real content changes the one fingerprint it belongs to.
    with open(home / 'AGENTS.md', 'a', encoding='utf-8') as f:
        f.write('\nAnswer in French.\n')
    wf.reset_cache()
    after = wf.head_source_fingerprints(str(work))
    changed = [k for k in base if after[k] != base[k]]
    assert changed == ['~/.ms_agent/AGENTS.md']

    # No project -> no project keys.
    assert set(wf.head_source_fingerprints(None)) == {
        '~/.ms_agent/SOUL.md', '~/.ms_agent/AGENTS.md',
        '~/.ms_agent/PROFILE.md'
    }


def test_render_update_notice_shape(home):
    text = wf.render_update_notice(
        ['~/.ms_agent/AGENTS.md', '<project>/.ms_agent/AGENTS.md'])
    assert text.startswith('<system-reminder>')
    assert text.endswith('</system-reminder>')
    assert wf.UPDATE_NOTICE_MARKER in text
    assert '~/.ms_agent/AGENTS.md, <project>/.ms_agent/AGENTS.md' in text
    assert 'did not misremember' in text


# ── agent attach flow ────────────────────────────────────────────────────────


def test_notice_fires_once_on_drift(home, tmp_path):
    agent = _agent(tmp_path, personalization={'enabled': True})
    agent._init_prompt_surface()

    # No drift -> no notice.
    messages = _user_turn()
    assert agent._attach_prompt_update_notice(messages) is None
    assert '<system-reminder>' not in messages[-1].content

    # Drift -> prefixed notice naming the file; baseline moves only on commit.
    with open(home / 'AGENTS.md', 'a', encoding='utf-8') as f:
        f.write('\nAnswer in French.\n')
    wf.reset_cache()
    commit = agent._attach_prompt_update_notice(messages)
    assert commit is not None
    content = messages[-1].content
    assert content.startswith('<system-reminder>')
    assert '~/.ms_agent/AGENTS.md' in content
    assert content.rstrip().endswith('下一个问题')

    # Un-committed (turn failed to persist): the next turn re-fires.
    retry = _user_turn('再问一次')
    assert agent._attach_prompt_update_notice(retry) is not None

    # Committed: quiet from here on.
    commit()
    clean = _user_turn('第三问')
    assert agent._attach_prompt_update_notice(clean) is None
    assert clean[-1].content == '第三问'


def test_notice_disabled_without_personalization(home, tmp_path):
    agent = _agent(tmp_path)  # gate off
    agent._init_prompt_surface()
    (home / 'AGENTS.md').parent.mkdir(parents=True, exist_ok=True)
    (home / 'AGENTS.md').write_text('New rules\n', encoding='utf-8')
    wf.reset_cache()
    messages = _user_turn()
    assert agent._attach_prompt_update_notice(messages) is None
    assert messages[-1].content == '下一个问题'


def test_sidecar_survives_process_restart(home, tmp_path):
    from ms_agent.session.session_log import SessionLog

    session_dir = tmp_path / 'sess'
    agent = _agent(tmp_path, personalization={'enabled': True})
    agent.session_log = SessionLog(session_dir, session_key='session_x')
    agent._init_prompt_surface()
    assert (session_dir / 'prompt_surface.json').exists()

    # "Restart": a fresh agent over the same session dir, file edited while
    # the process was down.
    with open(home / 'AGENTS.md', 'a', encoding='utf-8') as f:
        f.write('\nEdited while offline.\n')
    wf.reset_cache()
    agent2 = _agent(tmp_path, personalization={'enabled': True})
    agent2.session_log = SessionLog(session_dir, session_key='session_x')
    messages = _user_turn()
    commit = agent2._attach_prompt_update_notice(messages)
    assert commit is not None
    assert '~/.ms_agent/AGENTS.md' in messages[-1].content
    commit()

    # And a third agent sees no drift.
    agent3 = _agent(tmp_path, personalization={'enabled': True})
    agent3.session_log = SessionLog(session_dir, session_key='session_x')
    assert agent3._attach_prompt_update_notice(_user_turn()) is None


def test_legacy_session_without_sidecar_stays_silent(home, tmp_path):
    """Unknowable drift (session predates tracking): start tracking quietly
    instead of guessing."""
    agent = _agent(tmp_path, personalization={'enabled': True})
    messages = _user_turn()
    assert agent._attach_prompt_update_notice(messages) is None
    # ...but tracking has begun: real drift after this point does fire.
    with open(home / 'AGENTS.md', 'a', encoding='utf-8') as f:
        f.write('\nNow it changed.\n')
    wf.reset_cache()
    assert agent._attach_prompt_update_notice(_user_turn()) is not None


# ── coexistence: skill notice + prompt notice + recall ───────────────────────


def test_all_three_attachments_coexist(home, tmp_path):
    """A host-prefixed skill notice must not suppress the prompt-files notice
    nor the recall attach; the recall query sees only the user's words."""
    agent = _agent(tmp_path, personalization={'enabled': True})
    agent._init_prompt_surface()
    with open(home / 'AGENTS.md', 'a', encoding='utf-8') as f:
        f.write('\nDrifted.\n')
    wf.reset_cache()

    seen_queries = []

    class FakeOrchestrator:
        recall_marker = '- MEM:'

        async def recall_block(self, query):
            seen_queries.append(query)
            return '<system-reminder>\n- MEM: F1\n</system-reminder>'

    agent.memory_tools = [FakeOrchestrator()]

    skill_notice = ('<system-reminder>\nSkill inventory updated. CURRENT '
                    'full list: ...\n</system-reminder>')
    messages = _user_turn(f'{skill_notice}\n\n查一下我的偏好')

    commit = agent._attach_prompt_update_notice(messages)
    asyncio.run(agent._attach_memory_recall(messages))
    assert commit is not None

    content = messages[-1].content
    # prompt-files notice first, then the host's skill notice, then the words,
    # then recall — and the retrieval query carried none of the notices.
    assert content.index(wf.UPDATE_NOTICE_MARKER) < content.index(
        'Skill inventory updated')
    assert content.index('Skill inventory updated') < content.index('查一下我的偏好')
    assert content.rstrip().endswith('</system-reminder>')
    assert '- MEM: F1' in content
    assert seen_queries == ['查一下我的偏好']

    # Idempotent per mechanism: a second recall attach is a no-op.
    asyncio.run(agent._attach_memory_recall(messages))
    assert content == messages[-1].content


def test_recall_not_suppressed_by_skill_notice_alone(home, tmp_path):
    """Regression: the old guard skipped recall whenever ANY
    <system-reminder> was present — a skill-notice turn lost its memories."""
    agent = _agent(tmp_path)

    class FakeOrchestrator:
        recall_marker = '- MEM:'

        async def recall_block(self, query):
            assert query == '我的主题偏好？'
            return '<system-reminder>\n- MEM: 深色主题\n</system-reminder>'

    agent.memory_tools = [FakeOrchestrator()]
    messages = [
        Message(role='system', content='S'),
        Message(
            role='user',
            content=('<system-reminder>\nSkill inventory updated.\n'
                     '</system-reminder>\n\n我的主题偏好？')),
    ]
    asyncio.run(agent._attach_memory_recall(messages))
    assert '深色主题' in messages[-1].content


# ── static self-knowledge hint ───────────────────────────────────────────────


def test_live_files_hint_present_iff_personalized_content(home, tmp_path):
    wf.ensure_home_files()
    agent = _agent(tmp_path, personalization={'enabled': True})
    # Default SOUL template has real content -> hint present, with the
    # logical ~/.ms_agent labels resolved to the real home directory.
    content = agent._build_system_content()
    assert builtin.LIVE_FILES_HINT.format(home=str(home)) in content
    assert str(home) in content

    # Gate off -> no hint.
    agent2 = _agent(tmp_path)
    assert 'stay live during the conversation' not in \
        agent2._build_system_content()
