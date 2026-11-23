# Copyright (c) ModelScope Contributors. All rights reserved.
"""Question tool validation, replies and model guidance."""
import asyncio

import pytest
from ms_agent.tools.ask_user_tool import (NO_HANDLER_RESULT, TOOL_NAME,
                                          AskUserTool, AskUserToolError,
                                          _parse_questions)
from ms_agent.tools.base import SELF_MANAGED_OUTPUT, SELF_MANAGED_TIMEOUT
from ms_agent.ui.interaction import (CUSTOM_OPTION_ID, Answer, AnswerStatus,
                                     QuestionReply)
from omegaconf import OmegaConf


def _config():
    return OmegaConf.create({'tools': {'ask_user': {'mcp': False}}})


def _args(*, header='Format', options=None, multi=False):
    # Preserve empty options for validation tests.
    if options is None:
        options = [
            {'label': 'CSV', 'description': 'comma separated'},
            {'label': 'Excel', 'description': 'xlsx workbook'},
        ]
    return {'questions': [{
        'question': 'Which format?',
        'header': header,
        'options': options,
        'multiSelect': multi,
    }]}


class _Handler:
    """Return a configured reply and record its call ID."""

    supports_questions = True

    def __init__(self, reply):
        self._reply = reply
        self.call_id = None

    async def ask(self, questions, call_id=''):
        self.call_id = call_id
        return self._reply


def _call(handler, args):
    tool = AskUserTool(_config(), question_handler=handler)
    return asyncio.run(
        tool.call_tool('ask_user', tool_name=TOOL_NAME, tool_args=args))


# ── parameter validation ──────────────────────────────────────────────────


def test_ids_are_minted_for_questions_and_options():
    """IDs associate answers independently of display labels."""
    questions = _parse_questions(_args()['questions'])
    assert questions[0].id == 'q0'
    assert [o.id for o in questions[0].options] == ['q0_o0', 'q0_o1']
    assert [o.label for o in questions[0].options] == ['CSV', 'Excel']


@pytest.mark.parametrize('raw', [None, [], 'nope', {}])
def test_a_missing_question_list_is_reported_not_guessed(raw):
    with pytest.raises(AskUserToolError):
        _parse_questions(raw)


def test_more_than_four_questions_is_refused():
    with pytest.raises(AskUserToolError) as exc:
        _parse_questions(_args()['questions'] * 5)
    # Oversized asks must return actionable feedback.
    assert 'at most 4' in str(exc.value)


@pytest.mark.parametrize('count', [0, 1, 5])
def test_a_question_needs_between_two_and_four_options(count):
    options = [{'label': f'o{i}', 'description': ''} for i in range(count)]
    with pytest.raises(AskUserToolError):
        _parse_questions(_args(options=options)['questions'])


def test_an_overlong_header_is_refused():
    with pytest.raises(AskUserToolError) as exc:
        _parse_questions(_args(header='a header far too long')['questions'])
    assert 'chip' in str(exc.value)


@pytest.mark.parametrize('missing', ['question', 'header', 'options'])
def test_every_required_field_is_named_when_absent(missing):
    raw = _args()['questions']
    del raw[0][missing]
    with pytest.raises(AskUserToolError) as exc:
        _parse_questions(raw)
    assert missing in str(exc.value)


def test_a_malformed_ask_is_an_error_the_model_can_fix():
    result = _call(_Handler(QuestionReply(status=AnswerStatus.ANSWERED)),
                   {'questions': []})
    assert result['is_error'] is True
    assert 'questions' in result['result']


# ── the answered path ─────────────────────────────────────────────────────


@pytest.mark.parametrize('answer,multi,expected', [
    (Answer('q0', ['q0_o1'], labels=['Excel']), False, 'Excel'),
    (Answer('q0', ['q0_o0', 'q0_o1'], labels=['CSV', 'Excel']), True, 'CSV, Excel'),
    (Answer('q0', [CUSTOM_OPTION_ID], labels=['Parquet'], custom_text='Parquet'),
     False, 'Parquet'),
])
def test_answers_reach_the_model_with_headers_and_scope(answer, multi, expected):
    handler = _Handler(QuestionReply(status=AnswerStatus.ANSWERED, answers=[answer]))
    result = _call(handler, _args(multi=multi))
    assert f'**Format**: {expected}' in result
    assert 'continue with these answers' in result
    assert "within the user's requested scope" in result


def test_the_gating_call_id_is_handed_to_the_handler():
    # Associate the reply with its originating tool call.
    handler = _Handler(QuestionReply(status=AnswerStatus.ANSWERED))
    args = _args()
    args['__call_id'] = 'call-7'
    _call(handler, args)
    assert handler.call_id == 'call-7'


# ── the non-answers ───────────────────────────────────────────────────────


@pytest.mark.parametrize('status', [
    AnswerStatus.SKIPPED,
    AnswerStatus.CANCELLED,
    AnswerStatus.TIMEOUT,
    AnswerStatus.UNAVAILABLE,
])
def test_a_non_answer_is_not_reported_as_a_tool_failure(status):
    """Non-answers are outcomes, not retryable tool failures."""
    handler = _Handler(QuestionReply(status=status, note='the note'))
    result = _call(handler, _args())
    assert result == 'the note'
    assert not isinstance(result, dict)


def test_an_agent_with_no_way_to_ask_is_told_to_decide_and_report():
    class _NoChannel:
        supports_questions = False

        async def ask(self, questions, call_id=''):  # pragma: no cover
            raise AssertionError('must not be consulted')

    assert _call(_NoChannel(), _args()) == NO_HANDLER_RESULT
    assert _call(None, _args()) == NO_HANDLER_RESULT


def test_an_unknown_leaf_name_is_refused():
    result = asyncio.run(
        AskUserTool(_config(), question_handler=_Handler(None)).call_tool(
            'ask_user', tool_name='something_else', tool_args={}))
    assert result['is_error'] is True


# ── declared host behaviour ───────────────────────────────────────────────


def test_wait_and_output_limits_are_self_managed():
    tool = AskUserTool(_config(), question_handler=_Handler(None))
    assert tool.call_timeout == SELF_MANAGED_TIMEOUT
    assert tool.max_output_chars == SELF_MANAGED_OUTPUT


def test_the_description_preserves_question_policy():
    tool = AskUserTool(_config(), question_handler=_Handler(None))
    description = asyncio.run(tool.get_tools())['ask_user'][0]['description']
    for rule in (
            'do NOT add an "Other"', 'Shall I proceed?',
            'missing user decision blocks the CURRENT requested task',
            'Ordinary conversational clarification can remain plain text',
            'plan-only or research-only',
            'once it is complete, present it and stop',
            'unless the user requested that transition',
    ):
        assert rule in description


def test_the_schema_advertises_the_same_bounds_the_parser_enforces():
    from ms_agent.tools.ask_user_tool import _PARAMETERS
    questions = _PARAMETERS['properties']['questions']
    assert questions['maxItems'] == 4
    options = questions['items']['properties']['options']
    assert (options['minItems'], options['maxItems']) == (2, 4)
