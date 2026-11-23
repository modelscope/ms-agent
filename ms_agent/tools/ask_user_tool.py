# Copyright (c) ModelScope Contributors. All rights reserved.
"""Model-facing user question tool."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import (SELF_MANAGED_OUTPUT, SELF_MANAGED_TIMEOUT,
                                 ToolBase)
from ms_agent.ui.interaction import (MAX_HEADER_CHARS, MAX_OPTIONS,
                                     MAX_QUESTIONS, MIN_OPTIONS, AnswerStatus,
                                     Question, QuestionOption)

TOOL_NAME = 'ask_user_question'

DESCRIPTION = """Use this tool when you need to ask the user questions during execution. This allows you to:
1. Gather user preferences or requirements.
2. Clarify ambiguous instructions.
3. Get decisions on implementation choices as you work.
4. Offer choices to the user about what direction to take.

Usage notes:
- Prefer this tool when a missing user decision blocks the CURRENT requested task. Ordinary conversational clarification can remain plain text; do not turn every question into a tool call.
- Respect the user's explicit scope and stopping point. For plan-only or research-only requests, clarify only what is needed to complete that deliverable; once it is complete, present it and stop. Do not ask to start implementation or another phase unless the user requested that transition.
- Ask only about choices that change the OUTCOME and that you cannot settle by reading the project or picking a reasonable default. An interruption the user could have avoided costs more than a decision you document.
- Users can always type their own answer, so do NOT add an "Other" / "None of these" option — one is provided automatically.
- Use multiSelect: true when the choices are not mutually exclusive.
- If you recommend a specific option, make it the FIRST one and append " (Recommended)" to its label.
- Do not use this tool for plan or tool authorization ("Shall I proceed?"); authorization is handled separately. Do not ask for passwords, tokens or other authentication secrets.
"""  # noqa: E501


class AskUserToolError(ValueError):
    """A malformed ask. Reported to the model as a tool error it can fix."""


def _parse_questions(raw: Any) -> List[Question]:
    """Validate questions and assign call-local question and option IDs."""
    if not isinstance(raw, list) or not raw:
        raise AskUserToolError(
            'questions must be a non-empty array of question objects.')
    if len(raw) > MAX_QUESTIONS:
        raise AskUserToolError(
            f'Too many questions ({len(raw)}); at most {MAX_QUESTIONS} may be '
            'asked at once. Ask about what blocks you now and leave the rest.')

    questions: List[Question] = []
    for q_index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise AskUserToolError(f'questions[{q_index}] must be an object.')
        text = str(item.get('question') or '').strip()
        if not text:
            raise AskUserToolError(
                f'questions[{q_index}].question is required.')
        if len(text) > 2000:
            raise AskUserToolError('Question text exceeds 2000 characters.')
        header = str(item.get('header') or '').strip()
        if not header:
            raise AskUserToolError(f'questions[{q_index}].header is required.')
        if len(header) > MAX_HEADER_CHARS:
            raise AskUserToolError(
                f'questions[{q_index}].header is {len(header)} characters; '
                f'keep it to {MAX_HEADER_CHARS} — it renders as a small chip.')
        raw_options = item.get('options')
        if not isinstance(raw_options, list):
            raise AskUserToolError(
                f'questions[{q_index}].options must be an array.')
        if not MIN_OPTIONS <= len(raw_options) <= MAX_OPTIONS:
            raise AskUserToolError(
                f'questions[{q_index}].options has {len(raw_options)} '
                f'entries; provide between {MIN_OPTIONS} and {MAX_OPTIONS}.')
        options: List[QuestionOption] = []
        for o_index, option in enumerate(raw_options):
            if not isinstance(option, dict):
                raise AskUserToolError(
                    f'questions[{q_index}].options[{o_index}] must be an '
                    'object with label and description.')
            label = str(option.get('label') or '').strip()
            if not label:
                raise AskUserToolError(
                    f'questions[{q_index}].options[{o_index}].label is '
                    'required.')
            description = str(option.get('description') or '').strip()
            if len(label) > 120 or len(description) > 1000:
                raise AskUserToolError(
                    'Option label or description is too long.')
            options.append(
                QuestionOption(
                    id=f'q{q_index}_o{o_index}',
                    label=label,
                    description=description,
                ))
        questions.append(
            Question(
                id=f'q{q_index}',
                header=header,
                question=text,
                options=options,
                multi_select=bool(item.get('multiSelect', False)),
            ))
    return questions


_PARAMETERS: Dict[str, Any] = {
    'type': 'object',
    'properties': {
        'questions': {
            'type': 'array',
            'description': f'Questions to ask the user (1-{MAX_QUESTIONS}).',
            'minItems': 1,
            'maxItems': MAX_QUESTIONS,
            'items': {
                'type': 'object',
                'properties': {
                    'question': {
                        'type':
                        'string',
                        'description':
                        ('The complete question, clear and specific, ending '
                         'with a question mark. Phrase it for multiple '
                         'answers when multiSelect is true.'),
                    },
                    'header': {
                        'type':
                        'string',
                        'description':
                        (f'Very short label shown as a chip (max '
                         f'{MAX_HEADER_CHARS} characters), e.g. "Output '
                         'format", "Library".'),
                    },
                    'options': {
                        'type':
                        'array',
                        'description':
                        (f'The available choices ({MIN_OPTIONS}-{MAX_OPTIONS}).'
                         ' Each must be a distinct choice, mutually exclusive '
                         'unless multiSelect is set. Do NOT include an '
                         '"Other" option — one is added automatically.'),
                        'minItems':
                        MIN_OPTIONS,
                        'maxItems':
                        MAX_OPTIONS,
                        'items': {
                            'type': 'object',
                            'properties': {
                                'label': {
                                    'type':
                                    'string',
                                    'description':
                                    ('Display text, concise (1-5 words).'),
                                },
                                'description': {
                                    'type':
                                    'string',
                                    'description':
                                    ('What this choice means or what happens '
                                     'if it is picked — the trade-off the '
                                     'user needs in order to decide.'),
                                },
                            },
                            'required': ['label', 'description'],
                        },
                    },
                    'multiSelect': {
                        'type':
                        'boolean',
                        'description':
                        ('Allow selecting several options. Use when the '
                         'choices are not mutually exclusive.'),
                        'default':
                        False,
                    },
                },
                'required': ['question', 'header', 'options'],
            },
        },
    },
    'required': ['questions'],
}

#: Returned when the tool is reachable but nobody can be asked. Phrased for a
#: SUB-AGENT, which is the case that actually gets here: the main agent's tool
#: is simply not registered when its handler cannot ask (see ToolManager), so
#: it never sees this text.
NO_HANDLER_RESULT = (
    'This agent cannot put questions to the user directly. Do not retry. '
    'Decide with the most reasonable default and report the open choice (and '
    'the assumption you made) in your result, so the main agent can raise it '
    'with the user if it matters.')


class AskUserTool(ToolBase):
    """Exposes ``ask_user_question`` over an injected QuestionHandler."""

    SERVER_NAME = 'ask_user'

    def __init__(self, config, question_handler=None, **kwargs):
        super().__init__(config)
        tool_cfg = getattr(getattr(config, 'tools', None), 'ask_user', None)
        self.exclude_func(tool_cfg)
        self._handler = question_handler

    @property
    def max_output_chars(self) -> Optional[float]:
        # A set of answers is short by construction, and the generic cut would
        # land in the middle of one.
        return SELF_MANAGED_OUTPUT

    @property
    def call_timeout(self) -> Optional[float]:
        # The wait belongs to a person, and the handler is what bounds it (by
        # default: not at all). See ToolBase.call_timeout.
        return SELF_MANAGED_TIMEOUT

    async def connect(self) -> None:
        pass

    async def cleanup(self) -> None:
        pass

    async def _get_tools_inner(self) -> Dict[str, Any]:
        return {
            self.SERVER_NAME: [
                Tool(
                    tool_name=TOOL_NAME,
                    server_name=self.SERVER_NAME,
                    description=DESCRIPTION,
                    parameters=_PARAMETERS,
                )
            ]
        }

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> Any:
        if tool_name != TOOL_NAME:
            return {
                'result': f'Unknown tool: {tool_name}',
                'is_error': True,
            }
        if not getattr(self._handler, 'supports_questions', False):
            return NO_HANDLER_RESULT
        args = tool_args or {}
        try:
            questions = _parse_questions(args.get('questions'))
        except AskUserToolError as exc:
            return {'result': str(exc), 'is_error': True}

        reply = await self._handler.ask(
            questions, call_id=str(args.get('__call_id') or ''))
        if reply.status is not AnswerStatus.ANSWERED:
            # Not an error: a person declining, or nobody being there, is a
            # legitimate outcome the model must reason about. Marking it
            # is_error would make the agent treat it as a broken tool and
            # retry the call, which asks the same unanswered question again.
            return reply.note or f'Question not answered ({reply.status.value}).'
        return self._format(questions, reply)

    @staticmethod
    def _format(questions: List[Question], reply) -> str:
        """Format answers under their original question headers."""
        by_id = {q.id: q for q in questions}
        lines: List[str] = []
        for answer in reply.answers:
            question = by_id.get(answer.question_id)
            if question is None:
                continue
            label = question.header or question.question
            lines.append(f'**{label}**: {", ".join(answer.labels)}')
        body = '\n'.join(lines) if lines else 'No answers were provided.'
        return (f'User answered your questions:\n{body}\n\n'
                'You can now continue with these answers in mind, '
                "within the user's requested scope.")
