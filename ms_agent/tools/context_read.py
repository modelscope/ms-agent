"""Read original session evidence without arbitrary filesystem access."""
import json
import re

from ms_agent.tools.base import SELF_MANAGED_OUTPUT, ToolBase


class ContextReadTool(ToolBase):

    def __init__(self, config, log):
        super().__init__(config)
        self.log = log

    @property
    def max_output_chars(self):
        return SELF_MANAGED_OUTPUT

    async def connect(self):
        pass

    async def _get_tools_inner(self):
        from ms_agent.llm.utils import Tool
        return {
            'context': [
                Tool(
                    tool_name='context_read',
                    server_name='context',
                    description=
                    'Read a page of original tool output referenced by a context preview.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'ref': {
                                'type': 'string'
                            },
                            'offset': {
                                'type': 'integer',
                                'minimum': 0
                            },
                            'limit': {
                                'type': 'integer',
                                'minimum': 1,
                                'maximum': 8000
                            }
                        },
                        'required': ['ref']
                    })
            ]
        }

    async def call_tool(self, server_name, *, tool_name, tool_args):
        if tool_name != 'context_read':
            raise ValueError('Unknown context tool')
        ref = tool_args.get('ref', '')
        match = re.fullmatch(r'ctx:(\d+):([^\s:]+)', ref)
        offset, limit = tool_args.get('offset',
                                      0), tool_args.get('limit', 2000)
        if (not match or type(offset) is not int or type(limit) is not int
                or offset < 0 or not 1 <= limit <= 8000):
            raise ValueError('Invalid context reference or page range')
        seq, call_id = int(match[1]), match[2]
        row = next(
            (r for r in self.log.records()
             if r.get('seq') == seq and r.get('_source') != 'compaction'
             and r.get('role') == 'tool' and r.get('tool_call_id') == call_id),
            None)
        if row is None or not isinstance(row.get('content'), str):
            return json.dumps({'status': 'unavailable', 'ref': ref})
        body = row['content']
        return json.dumps(
            {
                'ref': ref,
                'offset': offset,
                'total_chars': len(body),
                'next_offset':
                offset + limit if offset + limit < len(body) else None,
                'content': body[offset:offset + limit]
            },
            ensure_ascii=False)
