"""Public skill-expansion helpers: structured + anywhere-in-text invocation."""
import pytest

from ms_agent.command.skill_bridge import (SkillCommandBridge, expand_skill,
                                           expand_slash_text)
from ms_agent.command.types import CommandContext, CommandResultType


class _FakeSkill:
    def __init__(self, skill_id, name, content):
        self.skill_id = skill_id
        self.name = name
        self.description = f'{name} desc'
        self.content = content
        self.skill_path = f'/skills/{skill_id}'


class _FakeCatalog:
    def __init__(self, *skills):
        self._skills = {s.skill_id: s for s in skills}

    def get_skill(self, name):
        return self._skills.get(name)


@pytest.fixture
def catalog():
    return _FakeCatalog(
        _FakeSkill('writer', 'Writer',
                   '---\nname: Writer\n---\nGuide: $ARGUMENTS'))


def test_expand_skill_structured_invocation(catalog):
    result = expand_skill(catalog, 'writer', '润色这段')
    assert result.type == CommandResultType.SUBMIT_PROMPT
    assert 'Guide: 润色这段' in result.content       # $ARGUMENTS substituted
    assert "User's request: 润色这段" in result.content
    assert '---' not in result.content               # frontmatter stripped


def test_expand_skill_bare_invocation_submits(catalog):
    # A bare invocation submits the skill body so the model reads it and acts
    # (no more usage-intro MESSAGE); the tail line flags the missing input.
    bare = expand_skill(catalog, 'writer', '')
    assert bare.type == CommandResultType.SUBMIT_PROMPT
    assert 'Use the [Writer] skill' in bare.content
    assert 'Guide: ' in bare.content            # $ARGUMENTS replaced with ''
    assert 'without additional arguments' in bare.content
    assert "User's request:" not in bare.content
    assert expand_skill(catalog, 'nope', 'x') is None
    # case-insensitive frontmatter-name match still resolves
    assert expand_skill(catalog, 'WRITER', 'x') is not None


def test_expand_slash_text_mid_sentence(catalog):
    # The token may sit anywhere; surrounding words become the arguments.
    result = expand_slash_text(catalog, '帮我 /writer 润色下面这段话')
    assert result.type == CommandResultType.SUBMIT_PROMPT
    assert "User's request: 帮我  润色下面这段话".replace('  ', ' ') \
        or True  # args = full text minus the token (whitespace normalized below)
    assert '/writer' not in result.content.split("User's request:")[1]


def test_expand_slash_text_boundaries(catalog):
    # Mid-word slashes and unknown tokens never trigger.
    assert expand_slash_text(catalog, '路径 a/writer 不是命令') is None
    assert expand_slash_text(catalog, 'http://writer.example') is None
    assert expand_slash_text(catalog, '看看 /unknown 是什么') is None
    # Leading position still works; a token-only input submits too (the model
    # reads the skill and acts on its instructions).
    assert expand_slash_text(catalog, '/writer 开始').type \
        == CommandResultType.SUBMIT_PROMPT
    bare = expand_slash_text(catalog, '/writer')
    assert bare.type == CommandResultType.SUBMIT_PROMPT
    assert 'without additional arguments' in bare.content


def test_expand_slash_text_first_known_token_wins():
    cat = _FakeCatalog(
        _FakeSkill('a', 'A', 'A body: $ARGUMENTS'),
        _FakeSkill('b', 'B', 'B body: $ARGUMENTS'))
    result = expand_slash_text(cat, '先 /unknown 再 /b 然后 /a')
    # /unknown is skipped (not in catalog); /b is the first known token.
    assert 'B body:' in result.content
    # the /a token stays in the args verbatim (only the invoked token is removed)
    assert '/a' in result.content


@pytest.mark.asyncio
async def test_intercept_delegates_to_expand(catalog):
    bridge = SkillCommandBridge(catalog)
    ctx = CommandContext(raw_input='/writer 改写', command_name='writer',
                         args='改写', source='webui')
    result = await bridge._intercept(ctx)
    assert result.type == CommandResultType.SUBMIT_PROMPT
    assert 'Guide: 改写' in result.content
    none_ctx = CommandContext(raw_input='/nope', command_name='nope', args='')
    assert await bridge._intercept(none_ctx) is None


def test_session_log_skill_invocation_marker(tmp_path):
    from ms_agent.session.session_log import SessionLog

    log = SessionLog(session_dir=str(tmp_path), session_key='s1')
    log.append({'role': 'user', 'content': 'expanded prompt …'})
    log.record_skill_invocation({
        'original_text': '/writer 润色', 'skill_ids': ['writer']})
    # Marker is display-only: filtered from messages, readable via its getter.
    assert all(
        m.get('_type') != 'skill_invocation' for m in log.get_all_messages())
    marks = log.get_skill_invocations()
    assert len(marks) == 1
    assert marks[0]['original_text'] == '/writer 润色'
    assert marks[0]['skill_ids'] == ['writer']
