import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import json
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils.utils import file_lock, render_markdown_todo


def _now_iso() -> str:
    # Keep it simple; no timezone conversions required for tool logic.
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _safe_read_json(path: str) -> Optional[Any]:
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _write_text(path: str, content: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        _ensure_dir(parent)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def _validate_status(status: str) -> str:
    allowed = {'pending', 'in_progress', 'completed', 'cancelled'}
    if status not in allowed:
        raise ValueError(
            f'Invalid todo status "{status}", must be one of {sorted(allowed)}.'
        )
    return status


def _validate_priority(priority: str) -> str:
    allowed = {'high', 'medium', 'low'}
    if priority not in allowed:
        raise ValueError(
            f'Invalid todo priority "{priority}", must be one of {sorted(allowed)}.'
        )
    return priority


@dataclass
class _PlanPaths:
    plan_json: str
    plan_md: str
    lock_dir: str


class TodoListTool(ToolBase):
    """
    Todo list tool for ms-agent.

    Storage format:
    - {output_dir}/plan.json:
        {
          "schema_version": 1,
          "updated_at": "...",
          "todos": [ { "id": "...", "content": "...", "status": "...", "priority": "..." , ... } ]
        }
    """

    SERVER_NAME = 'todo_list'

    def __init__(self, config, **kwargs):
        super().__init__(config)
        tool_cfg = getattr(getattr(config, 'tools'), 'todo_list')
        self.exclude_func(tool_cfg)

        self._plan_filename = getattr(tool_cfg, 'plan_filename',
                                      'plan.json') if tool_cfg else 'plan.json'
        self._plan_md_filename = getattr(tool_cfg, 'plan_md_filename',
                                         'plan.md') if tool_cfg else 'plan.md'
        self._lock_subdir = getattr(tool_cfg, 'lock_subdir',
                                    '.locks') if tool_cfg else '.locks'
        self._auto_render_md = bool(getattr(tool_cfg, 'auto_render_md',
                                            True)) if tool_cfg else True

    async def connect(self) -> None:
        # Nothing to connect; file-based tool.
        _ensure_dir(self.output_dir)
        _ensure_dir(os.path.join(self.output_dir, self._lock_subdir))

    def _paths(self) -> _PlanPaths:
        return _PlanPaths(
            plan_json=os.path.join(self.output_dir, self._plan_filename),
            plan_md=os.path.join(self.output_dir, self._plan_md_filename),
            lock_dir=os.path.join(self.output_dir, self._lock_subdir),
        )

    async def _get_tools_inner(self) -> Dict[str, Any]:
        tools: Dict[str, List[Tool]] = {
            self.SERVER_NAME: [
                Tool(
                    tool_name='todo_write',
                    server_name=self.SERVER_NAME,
                    description=
                    ('Create or update the structured todo list (plan.json) for this session/workdir. '
                     'Use merge=true to merge by id; merge=false replaces the list.'
                     ),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'merge': {
                                'type':
                                'boolean',
                                'description':
                                ('If true, merge todo items into existing list by id (partial updates allowed). '
                                 'If false, replace the list entirely.'),
                                'default':
                                True,
                            },
                            'todos': {
                                'type': 'array',
                                'description':
                                'The updated/created todo list.',
                                'items': {
                                    'type': 'object',
                                    'properties': {
                                        'id': {
                                            'type':
                                            'string',
                                            'description':
                                            'Unique identifier for the todo item',
                                        },
                                        'content': {
                                            'type':
                                            'string',
                                            'description':
                                            'Brief description of the task',
                                        },
                                        'status': {
                                            'type':
                                            'string',
                                            'enum': [
                                                'pending', 'in_progress',
                                                'completed', 'cancelled'
                                            ],
                                            'description':
                                            'Current status of the task',
                                        },
                                        'priority': {
                                            'type': 'string',
                                            'enum': ['high', 'medium', 'low'],
                                            'description':
                                            'Priority level of the task',
                                            'default': 'medium',
                                        },
                                    },
                                    'required': ['id', 'content', 'status'],
                                    # Allow DeepResearch to attach extra structured fields:
                                    # e.g. evidence_ids, depends_on, acceptance, agent, etc.
                                    'additionalProperties': True,
                                },
                                'minItems': 0,
                            },
                        },
                        'required': ['todos'],
                        'additionalProperties': False,
                    },
                ),
                Tool(
                    tool_name='todo_read',
                    server_name=self.SERVER_NAME,
                    description=
                    'Read the current todo list for this session/workdir.',
                    parameters={
                        'type': 'object',
                        'properties': {},
                        'required': [],
                        'additionalProperties': False,
                    },
                ),
                Tool(
                    tool_name='todo_render_md',
                    server_name=self.SERVER_NAME,
                    description=
                    'Render plan.md from plan.json (checkbox view).',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'path': {
                                'type':
                                'string',
                                'description':
                                ('Optional relative output path for the markdown file. '
                                 'Defaults to plan.md in the workdir.'),
                            }
                        },
                        'required': [],
                        'additionalProperties': False,
                    },
                ),
            ]
        }
        return tools

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        return await getattr(self, tool_name)(**(tool_args or {}))

    def _load_plan_locked(self, paths: _PlanPaths) -> Dict[str, Any]:
        data = _safe_read_json(paths.plan_json)
        if data is None:
            return {
                'schema_version': 1,
                'updated_at': _now_iso(),
                'todos': [],
            }
        # Backward compatibility: allow plain list storage
        if isinstance(data, list):
            return {
                'schema_version': 1,
                'updated_at': _now_iso(),
                'todos': data,
            }
        if not isinstance(data, dict):
            return {
                'schema_version': 1,
                'updated_at': _now_iso(),
                'todos': [],
            }
        if 'todos' not in data or not isinstance(data.get('todos'), list):
            data['todos'] = []
        if 'schema_version' not in data:
            data['schema_version'] = 1
        if 'updated_at' not in data:
            data['updated_at'] = _now_iso()
        return data

    def _save_plan_locked(self, paths: _PlanPaths, plan: Dict[str,
                                                              Any]) -> None:
        plan = dict(plan or {})
        plan['schema_version'] = int(plan.get('schema_version', 1) or 1)
        plan['updated_at'] = _now_iso()
        _write_text(paths.plan_json, _json_dumps(plan))

    def _normalize_todos(self, todos: List[Dict[str,
                                                Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for idx, item in enumerate(todos or []):
            if not isinstance(item, dict):
                raise ValueError(f'todos[{idx}] must be an object.')
            todo_id = str(item.get('id', '')).strip()
            content = str(item.get('content', '')).strip()
            status = str(item.get('status', '')).strip()
            priority = str(item.get('priority', 'medium') or 'medium').strip()
            if not todo_id:
                raise ValueError(
                    f'todos[{idx}].id is required and must be non-empty.')
            if not content:
                raise ValueError(
                    f'todos[{idx}].content is required and must be non-empty.')
            _validate_status(status)
            _validate_priority(priority)
            # Keep extra fields as-is
            merged = dict(item)
            merged['id'] = todo_id
            merged['content'] = content
            merged['status'] = status
            merged['priority'] = priority
            normalized.append(merged)
        return normalized

    def _merge_todos(self, base: List[Dict[str, Any]],
                     updates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        base_by_id: Dict[str, Dict[str, Any]] = {
            str(t.get('id')): dict(t)
            for t in (base or []) if isinstance(t, dict) and t.get('id')
        }
        order: List[str] = [
            str(t.get('id')) for t in (base or [])
            if isinstance(t, dict) and t.get('id')
        ]
        for upd in updates or []:
            tid = str(upd.get('id'))
            if tid in base_by_id:
                base_by_id[tid].update(upd)
            else:
                base_by_id[tid] = dict(upd)
                order.append(tid)
        # Preserve order; drop ids that disappeared due to corruption
        merged_list: List[Dict[str, Any]] = []
        seen = set()
        for tid in order:
            if tid in seen:
                continue
            if tid in base_by_id:
                merged_list.append(base_by_id[tid])
                seen.add(tid)
        return merged_list

    def _render_plan_md_text(self, plan: Dict[str, Any]) -> str:
        todos = plan.get('todos', []) if isinstance(plan, dict) else []
        if not todos:
            return '# Plan\n\n(Empty)\n'
        lines: List[str] = ['# Plan', '']
        for t in todos:
            if not isinstance(t, dict):
                continue
            status = t.get('status', 'pending')
            checkbox = 'x' if status == 'completed' else ' '
            tid = t.get('id', '')
            content = t.get('content', '')
            prio = t.get('priority', 'medium')
            suffix = f'  _(id: {tid}, status: {status}, priority: {prio})_'
            lines.append(f'- [{checkbox}] {content}{suffix}')
        lines.append('')
        return '\n'.join(lines)

    async def todo_write(self,
                         todos: List[Dict[str, Any]],
                         merge: bool = True) -> str:
        paths = self._paths()
        _ensure_dir(self.output_dir)
        _ensure_dir(paths.lock_dir)
        normalized = self._normalize_todos(todos)

        with file_lock(paths.lock_dir, self._plan_filename):
            plan = self._load_plan_locked(paths)
            existing = plan.get('todos', [])
            if merge:
                merged = self._merge_todos(existing, normalized)
            else:
                merged = normalized
            plan['todos'] = merged
            self._save_plan_locked(paths, plan)

            if self._auto_render_md:
                md_text = self._render_plan_md_text(plan)
                _write_text(paths.plan_md, md_text)

                render_markdown_todo(
                    paths.plan_md, title='CURRENT PLAN', use_pager=False)

        # Return a JSON list (opencode-style) so the model can easily read it.
        return _json_dumps({
            'status':
            'ok',
            'plan_path':
            os.path.relpath(paths.plan_json, self.output_dir),
            'todos':
            plan.get('todos', []),
        })

    async def todo_read(self) -> str:
        paths = self._paths()
        _ensure_dir(self.output_dir)
        _ensure_dir(paths.lock_dir)
        with file_lock(paths.lock_dir, self._plan_filename):
            plan = self._load_plan_locked(paths)
            if self._auto_render_md:
                render_markdown_todo(
                    paths.plan_md, title='CURRENT PLAN', use_pager=False)

        return _json_dumps(plan.get('todos', []))

    async def todo_render_md(self, path: Optional[str] = None) -> str:
        paths = self._paths()
        _ensure_dir(self.output_dir)
        _ensure_dir(paths.lock_dir)
        out_path = paths.plan_md if not path else os.path.join(
            self.output_dir, path)

        with file_lock(paths.lock_dir, self._plan_filename):
            plan = self._load_plan_locked(paths)
            md_text = self._render_plan_md_text(plan)
            _write_text(out_path, md_text)
        return f'OK: rendered plan markdown to {os.path.relpath(out_path, self.output_dir)}'
