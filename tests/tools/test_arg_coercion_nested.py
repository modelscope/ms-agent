"""Nested conversions must not disappear because int and float compare equal."""
import pytest

from ms_agent.tools.arg_coercion import coerce_arguments


@pytest.mark.parametrize('containers', [
    ('object',),
    ('array',),
    ('object', 'array', 'object'),
    ('array', 'object', 'array'),
])
def test_nested_number_widening_preserves_types_without_mutating_input(containers):
    value = 3
    schema = {'type': 'number'}
    for container in containers:
        if container == 'object':
            value = {'value': value}
            schema = {'type': 'object', 'properties': {'value': schema}}
        else:
            value = [value]
            schema = {'type': 'array', 'items': schema}
    arguments = {'payload': value}
    schema = {'type': 'object', 'properties': {'payload': schema}}

    result = coerce_arguments(arguments, schema)

    assert result is not arguments
    actual, original = result['payload'], arguments['payload']
    for container in reversed(containers):
        assert actual is not original
        key = 'value' if container == 'object' else 0
        actual, original = actual[key], original[key]
    assert type(actual) is float
    assert actual == 3.0
    assert type(original) is int
    assert coerce_arguments(result, schema) is result


@pytest.mark.parametrize('value', [3.0, True, None, 'not a number'])
def test_unchanged_nested_values_preserve_argument_identity(value):
    arguments = {'payload': {'values': [value]}, 'unknown': {'n': 3}}
    schema = {
        'type': 'object',
        'properties': {
            'payload': {
                'type': 'object',
                'properties': {
                    'values': {'type': 'array', 'items': {'type': 'number'}},
                },
            },
        },
    }
    assert coerce_arguments(arguments, schema) is arguments


def test_nested_integer_union_remains_integer():
    arguments = {'payload': [3]}
    schema = {'properties': {'payload': {
        'type': 'array', 'items': {'type': ['integer', 'number']},
    }}}
    assert coerce_arguments(arguments, schema) is arguments
    assert type(arguments['payload'][0]) is int


@pytest.mark.asyncio
async def test_manager_dispatches_nested_numbers_to_strict_tool():
    from omegaconf import OmegaConf
    from pydantic.v1 import BaseModel, StrictFloat

    from ms_agent.tools.base import ToolBase
    from ms_agent.tools.tool_manager import ToolManager

    class Payload(BaseModel):
        values: list[StrictFloat]

    class Arguments(BaseModel):
        payload: Payload

    class StrictTool(ToolBase):
        async def call_tool(self, server_name, *, tool_name, tool_args):
            # Pydantic v1 StrictFloat rejects ints, although JSON Schema
            # considers them valid numbers. Coercion supports such tools.
            Arguments.parse_obj(tool_args)
            self.received = tool_args
            return 'validated'

    manager = ToolManager(OmegaConf.create({}))
    tool = StrictTool(OmegaConf.create({}))
    schema = {'type': 'object', 'properties': {'payload': {
        'type': 'object', 'properties': {'values': {
            'type': 'array', 'items': {'type': 'number'},
        }},
    }}}
    manager._tool_index['strict---validate'] = (
        tool, 'strict', {'parameters': schema})
    arguments = {'payload': {'values': [3]}}
    call = {'tool_name': 'strict---validate', 'arguments': arguments}

    assert await manager.single_call_tool(call) == 'validated'
    assert type(tool.received['payload']['values'][0]) is float
    assert type(arguments['payload']['values'][0]) is int
    assert call['arguments'] is not arguments
