# Copyright (c) ModelScope Contributors. All rights reserved.
"""Event model contract: serialization, discriminators, RecordingSink."""
from ms_agent.ui.events import (AgentEventSink, ContentDelta, ContentEnd,
                                ContextCompacted, ErrorRaised, Notice,
                                PermissionRequested, PlanEntry, PlanUpdated,
                                ReasoningDelta, RecordingSink, ToolCallCompleted,
                                ToolCallStarted, TurnCompleted, UsageInfo)


def test_content_delta_to_dict():
    assert ContentDelta('hi').to_dict() == {'type': 'content_delta', 'text': 'hi'}


def test_type_property_matches_dict():
    ev = ToolCallStarted(call_id='c1', name='read_file', arguments={'p': 'x'})
    assert ev.type == 'tool_call_started'
    assert ev.to_dict()['type'] == 'tool_call_started'
    assert ev.to_dict()['arguments'] == {'p': 'x'}


def test_frozen_events_are_immutable():
    ev = ContentDelta('x')
    try:
        ev.text = 'y'  # type: ignore[misc]
    except Exception as e:
        assert 'FrozenInstanceError' in type(e).__name__ or isinstance(
            e, AttributeError)
    else:
        raise AssertionError('event should be immutable')


def test_nested_usage_serializes():
    ev = TurnCompleted(
        turn_id='t1',
        usage=UsageInfo(prompt_tokens=10, completion_tokens=5))
    d = ev.to_dict()
    assert d['type'] == 'turn_completed'
    assert d['usage'] == {
        'prompt_tokens': 10, 'completion_tokens': 5, 'reasoning_tokens': 0,
        'total_prompt_tokens': 0, 'total_completion_tokens': 0}


def test_nested_plan_entries_serialize():
    ev = PlanUpdated(entries=[PlanEntry('step 1', 'completed'),
                             PlanEntry('step 2')])
    d = ev.to_dict()
    assert d['type'] == 'plan_updated'
    assert d['entries'] == [
        {'content': 'step 1', 'status': 'completed'},
        {'content': 'step 2', 'status': 'pending'}]


def test_discriminators_are_unique_and_stable():
    events = [ContentDelta(), ContentEnd(), ReasoningDelta(),
              ToolCallStarted(), ToolCallCompleted(), PlanUpdated(),
              PermissionRequested(), ContextCompacted(), Notice(),
              ErrorRaised(), TurnCompleted()]
    types = [e.type for e in events]
    assert len(types) == len(set(types)), 'event discriminators must be unique'
    # Stable wire names a WebUI front-end mirrors — guard against renames.
    assert ContentDelta().type == 'content_delta'
    assert ToolCallCompleted().type == 'tool_call_completed'
    assert PermissionRequested().type == 'permission_requested'


def test_recording_sink_collects_and_helpers():
    sink = RecordingSink()
    assert isinstance(sink, AgentEventSink)  # runtime_checkable protocol
    sink.emit(ContentDelta('hello '))
    sink.emit(ToolCallStarted(call_id='1', name='shell'))
    sink.emit(ContentDelta('world'))
    assert sink.types() == ['content_delta', 'tool_call_started', 'content_delta']
    assert sink.text() == 'hello world'
    assert len(sink.of_type('content_delta')) == 2
    assert sink.of_type('tool_call_started')[0].name == 'shell'
