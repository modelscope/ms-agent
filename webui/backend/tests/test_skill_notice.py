"""Real WebUI input scheduling and SDK persistence, with only the model stubbed."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.backends.ms_agent import chat, common, conversations, model_link, projects, sessions
from app.backends.ms_agent.runtime import registry
from app.schemas.chat import ChatMessage, ChatRequest
from app.schemas.project import ProjectCreate
from app.schemas.session import SessionCreate


@pytest.fixture
async def flow(tmp_path, monkeypatch):
    from ms_agent.agent.llm_agent import LLMAgent
    from ms_agent.config.skills_manager import SkillsConfigManager

    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path / 'home'))
    model_link._save({'llm': {'provider': 'openai', 'model': 'notice-fixture',
                             'api_key': 'test', 'base_url': 'http://127.0.0.1:1/v1'},
                      'providers': {'openai': {'api_key': 'test', 'models': ['notice-fixture']}}})
    common.pm().initialize()
    project = projects.create_project(ProjectCreate(name='notice-test', memory_enabled=False))
    session = sessions.create_session(SessionCreate(title='notice test', project_id=project.id))
    project_path = common.pm().get(project.id).path
    tree = SkillsConfigManager(common.home()).project_skills_tree(project_path)
    skill = tree / 'notice-fixture'
    skill.mkdir(parents=True)
    state = SimpleNamespace(project=project, session=session, tree=tree, skill=skill,
                            observed=[], entered=asyncio.Event(), release=asyncio.Event(), block=False)

    def write(version):
        (skill / 'SKILL.md').write_text(
            '---\nname: notice-fixture\ndescription: Test skill\n---\n'
            f'Use marker READING_{version}.\n', encoding='utf-8')
        from app.backends.ms_agent.skill_management import _changed
        _changed(f'project:{project.id}')
    state.write = write
    write('V1')

    async def generate(self, messages, tools):
        from ms_agent.llm.utils import Message
        state.observed.append([(m.role, m.content) for m in messages])
        state.entered.set()
        if state.block:
            await state.release.wait()
        return iter([Message(role='assistant', content='answer')])
    monkeypatch.setattr(LLMAgent, '_generate_response', generate)

    def request(text):
        return ChatRequest(session_id=session.id, project_id=project.id,
                           message=ChatMessage(role='user', content=text))
    state.request = request

    async def turn(text, transport='session'):
        if transport == 'legacy':
            frames = [json.loads(frame['data']) async for frame in chat.stream(request(text))]
            assert not any(f.get('type') == 'error' for f in frames), frames
        else:
            from app.api.chat import submit_input
            c = conversations.get(session.id)
            previous = c.sequence
            await submit_input(request(text))
            await asyncio.wait_for(c.worker, 20)
            events = [e for e in c.events if int(e['cursor'].rsplit(':', 1)[1]) > previous]
            assert not any(e['type'] == 'failure' or (
                e['type'] == 'chunk' and e['chunk']['type'] == 'error') for e in events), events
        return [content for role, content in state.observed[-1] if role == 'user'][-1]
    state.turn = turn
    state.log = common.sm_for(common.pm().get(project.id)).get_session_log(
        common.sm_for(common.pm().get(project.id)).get(session.id))
    state.surface = state.log.directory / 'skill_surface.json'
    try:
        yield state
    finally:
        state.release.set()
        await conversations.discard(session.id)
        await registry.close(session.id)
        projects.delete_project(project.id)


@pytest.mark.parametrize('transport', ['legacy', 'session'])
async def test_notice_reaches_model_once_and_stays_out_of_bubbles(flow, transport):
    assert await flow.turn('first question', transport) == 'first question'
    assert flow.surface.exists()
    old_head = flow.observed[-1][0]
    flow.write('V2')
    changed = await flow.turn('continue', transport)
    assert 'Content updated since last known state: notice-fixture' in changed
    assert 're-read it via skill_view' in changed
    assert changed.endswith('continue')
    assert flow.observed[-1][0] == old_head
    assert await flow.turn('another question', transport) == 'another question'
    # Persisted history contains the reminder, while the UI keeps typed text.
    from ms_agent.session.session_log import SessionLog
    log_rows = SessionLog(flow.log.directory, flow.log.session_key).get_all_messages()
    assert any('Content updated since last known state' in str(m.get('content')) for m in log_rows)
    visible = [m.content for m in sessions.list_messages(flow.session.id) if m.role == 'user']
    assert visible == ['first question', 'continue', 'another question']
    # An idle runtime eviction uses the existing baseline, not a new one.
    await registry.close(flow.session.id)
    flow.write('V3')
    assert 'Content updated since last known state' in await flow.turn('after restart', transport)


@pytest.mark.parametrize('change', ['reference', 'add', 'remove', 'disable'])
async def test_original_skill_changes_still_notify(flow, change):
    await flow.turn('first')
    from app.backends.ms_agent import skills
    from app.backends.ms_agent.skill_management import _changed
    from app.schemas.skill import SkillUpdate
    scope = f'project:{flow.project.id}'
    row = next(s for s in skills.list_skills(scope) if s.name == 'notice-fixture')
    if change == 'reference':
        (flow.skill / 'references').mkdir()
        (flow.skill / 'references/guide.md').write_text('changed reference')
        _changed(scope)
        expected = 'Content updated since last known state: notice-fixture'
    elif change == 'add':
        extra = flow.tree / 'extra-skill'
        extra.mkdir()
        (extra / 'SKILL.md').write_text('---\nname: extra-skill\ndescription: Extra\n---\nNew skill\n')
        _changed(scope)
        expected = 'Newly added since last known state: extra-skill'
    elif change == 'remove':
        skills.delete_skill(row.id)
        expected = 'Removed or disabled since last known state: notice-fixture'
    else:
        skills.update_skill(row.id, SkillUpdate(enabled=False))
        expected = 'Removed or disabled since last known state: notice-fixture'
    assert expected in await flow.turn('next question')


async def test_stopped_queued_skill_uses_current_content_on_resume(flow):
    from app.api.chat import submit_input
    from ms_agent.skill.management.usage import skill_mutation
    from ms_agent.skill.management.models import SkillManagementError
    flow.block = True
    await submit_input(flow.request('first'))
    await asyncio.wait_for(flow.entered.wait(), 20)
    c = conversations.get(flow.session.id)
    await submit_input(flow.request('/notice-fixture'))
    pending = c.controller.pending()
    assert 'READING_V1' in pending[0]['prepared']['prompt']
    with pytest.raises(SkillManagementError, match='Task running'):
        with skill_mutation(flow.tree):
            pass
    await conversations.interrupt(flow.session.id, c.controller.active_turn)
    with skill_mutation(flow.tree):
        flow.write('V2')
    flow.block = False
    c.controller.resume()
    c.kick()
    await asyncio.wait_for(c.worker, 20)
    delivered = [text for role, text in flow.observed[-1] if role == 'user'][-1]
    assert 'READING_V2' in delivered and 'READING_V1' not in delivered
    assert 'Content updated since last known state: notice-fixture' in delivered
    assert sessions.list_messages(flow.session.id)[-2].content == '/notice-fixture'


async def test_cancel_before_persistence_does_not_consume_notice(flow, monkeypatch):
    from app.api.chat import submit_input
    from ms_agent.agent.llm_agent import LLMAgent
    await flow.turn('first')
    original = flow.surface.read_bytes()
    flow.write('V2')
    entered = asyncio.Event()
    recall = LLMAgent._attach_memory_recall
    async def hold_before_log(self, messages):
        if messages[-1].content.endswith('pending delivery'):
            assert 'Content updated since last known state' in messages[-1].content
            entered.set()
            await asyncio.Event().wait()
        await recall(self, messages)
    monkeypatch.setattr(LLMAgent, '_attach_memory_recall', hold_before_log)
    await submit_input(flow.request('pending delivery'))
    await asyncio.wait_for(entered.wait(), 20)
    c = conversations.get(flow.session.id)
    await conversations.interrupt(flow.session.id, c.controller.active_turn)
    assert flow.surface.read_bytes() == original
    monkeypatch.setattr(LLMAgent, '_attach_memory_recall', recall)
    c.controller.resume()
    c.kick()
    await asyncio.wait_for(c.worker, 20)
    delivered = [text for role, text in flow.observed[-1] if role == 'user'][-1]
    assert 'Content updated since last known state' in delivered
    assert flow.surface.read_bytes() != original


async def test_continuous_queue_has_no_mutation_gap(flow, monkeypatch):
    from app.api.chat import submit_input
    from ms_agent.skill.management.usage import skill_mutation
    from ms_agent.skill.management.models import SkillManagementError
    flow.block = True
    await submit_input(flow.request('first'))
    await asyncio.wait_for(flow.entered.wait(), 20)
    c = conversations.get(flow.session.id)
    await submit_input(flow.request('queued'))
    start_next = c.controller.start_next
    checked = []

    def next_with_mutation_probe():
        # At this point run_turn has released the previous runtime lock.
        assert not registry.peek_exact(flow.session.id).turn_lock.locked()
        with pytest.raises(SkillManagementError, match='Task running'):
            with skill_mutation(flow.tree):
                pass
        checked.append(True)
        return start_next()

    monkeypatch.setattr(c.controller, 'start_next', next_with_mutation_probe)
    flow.block = False
    flow.release.set()
    await asyncio.wait_for(c.worker, 20)
    assert checked and len(flow.observed) == 2
    with skill_mutation(flow.tree):
        pass  # Finished queues release the lease.


async def test_failed_message_write_keeps_notice_for_retry(flow, monkeypatch):
    from app.api.chat import submit_input
    from ms_agent.session.session_log import SessionLog
    await flow.turn('first')
    original = flow.surface.read_bytes()
    flow.write('V2')
    append = SessionLog.append
    failed = []

    def fail_user_write(self, row):
        if (row.get('role') == 'user' and not failed
                and str(row.get('content', '')).endswith('write failure')):
            failed.append(True)
            raise OSError('simulated session write failure')
        return append(self, row)

    monkeypatch.setattr(SessionLog, 'append', fail_user_write)
    await submit_input(flow.request('write failure'))
    c = conversations.get(flow.session.id)
    await asyncio.wait_for(c.worker, 20)
    assert failed and flow.surface.read_bytes() == original
    assert 'Content updated since last known state' in await flow.turn('retry')


async def test_steering_keeps_current_skill_until_next_task(flow):
    from app.api.chat import submit_input
    from ms_agent.config.interaction_settings import InteractionSettings
    await flow.turn('first')
    flow.block = True
    flow.entered.clear()
    await submit_input(flow.request('running'))
    await asyncio.wait_for(flow.entered.wait(), 20)
    c = conversations.get(flow.session.id)
    InteractionSettings(common.home()).update('steer')
    # Simulate an external editor; managed updates are blocked during a task.
    flow.write('V2')
    req = flow.request('/notice-fixture').model_copy(update={'expected_turn_id': c.controller.active_turn})
    await submit_input(req)
    flow.block = False
    flow.release.set()
    await asyncio.wait_for(c.worker, 20)
    steered = [text for role, text in flow.observed[-1] if role == 'user'][-1]
    assert 'READING_V1' in steered and 'Content updated since last known state' not in steered
    assert 'Content updated since last known state' in await flow.turn('next task')
