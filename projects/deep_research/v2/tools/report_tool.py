# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional

import json
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils.utils import file_lock, render_markdown_todo

try:
    from evidence_tool import _parse_note_from_md  # type: ignore
except Exception:  # pragma: no cover
    from .evidence_tool import _parse_note_from_md  # type: ignore


def _now_iso() -> str:
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


def _render_outline_md(outline: Dict[str, Any]) -> str:
    """Render outline as Markdown."""
    lines = [f"# {outline.get('title', 'Report Outline')}", '']

    for ch in outline.get('chapters', []):
        status_icon = {
            'pending': '⏳',
            'in_progress': '🔄',
            'completed': '✅'
        }.get(ch.get('status', 'pending'), '⏳')

        lines.append(
            f"## Chapter {ch['chapter_id']}: {ch['title']} {status_icon}")

        if ch.get('goals'):
            lines.append('')
            lines.append('**Goals:**')
            for goal in ch['goals']:
                lines.append(f'- {goal}')

        if ch.get('sections_description'):
            lines.append('')
            lines.append('**Chapter structure:**')
            lines.append(ch['sections_description'])

        if ch.get('candidate_evidence'):
            lines.append('')
            lines.append(
                f"**Related evidence:** {', '.join(ch['candidate_evidence'])}")

        lines.append('')

    return '\n'.join(lines)


class ReportTool(ToolBase):
    """
    Report generation tool for DeepResearch Reporter agent.

    Provides structured workflow for generating reports:
    1. commit_outline - Generate chapter structure bound to evidence
    2. update_outline - Update chapter information
    3. get_status - Check progress
    4. prepare_chapter_bundle - Prepare evidence for chapter writing
    5. commit_chapter - Write chapter content
    6. commit_conflict - Record evidence conflicts
    7. finalize_report - Assemble final report

    Storage:
    - reports/outline.json: Chapter structure with evidence bindings
    - reports/outline.md: Markdown render of outline
    - reports/chapters/chapter_XX.md: Chapter content
    - reports/chapters/chapter_XX_meta.json: Chapter metadata
    - reports/conflict.json: Recorded conflicts
    - reports/report.md: Final assembled report
    """

    SERVER_NAME = 'report_generator'

    def __init__(self, config, **kwargs):
        super().__init__(config)
        tool_cfg = getattr(getattr(config, 'tools'), 'report_generator')
        self.exclude_func(tool_cfg)

        # Configurable paths
        self._reports_dir = getattr(tool_cfg, 'reports_dir',
                                    'reports') if tool_cfg else 'reports'
        self._evidence_dir = getattr(tool_cfg, 'evidence_dir',
                                     'evidence') if tool_cfg else 'evidence'
        self._lock_subdir = getattr(tool_cfg, 'lock_subdir',
                                    '.locks') if tool_cfg else '.locks'

    async def connect(self) -> None:
        """Initialize directory structure."""
        _ensure_dir(self.output_dir)
        _ensure_dir(
            os.path.join(self.output_dir, self._reports_dir, 'chapters'))
        _ensure_dir(os.path.join(self.output_dir, self._lock_subdir))

    def _paths(self) -> Dict[str, str]:
        return {
            'outline_json':
            os.path.join(self.output_dir, self._reports_dir, 'outline.json'),
            'outline_md':
            os.path.join(self.output_dir, self._reports_dir, 'outline.md'),
            'chapters_dir':
            os.path.join(self.output_dir, self._reports_dir, 'chapters'),
            'conflict_json':
            os.path.join(self.output_dir, self._reports_dir, 'conflict.json'),
            'draft_md':
            os.path.join(self.output_dir, self._reports_dir, 'draft.md'),
            'report_md':
            os.path.join(self.output_dir, self._reports_dir, 'report.md'),
            'evidence_index':
            os.path.join(self.output_dir, self._evidence_dir, 'index.json'),
            'evidence_notes_dir':
            os.path.join(self.output_dir, self._evidence_dir, 'notes'),
            'lock_dir':
            os.path.join(self.output_dir, self._lock_subdir),
        }

    async def _get_tools_inner(self) -> Dict[str, Any]:
        tools: Dict[str, List[Tool]] = {
            self.SERVER_NAME: [
                Tool(
                    tool_name='commit_outline',
                    server_name=self.SERVER_NAME,
                    description=
                    ('Generate the report outline with chapter structure. '
                     'Each chapter must be bound to relevant evidence (note_ids). '
                     'Ensures all evidence is covered by at least one chapter.'
                     ),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'title': {
                                'type': 'string',
                                'description': 'Title of the report.',
                            },
                            'chapters': {
                                'type': 'array',
                                'description': 'List of chapter definitions.',
                                'items': {
                                    'type': 'object',
                                    'properties': {
                                        'title': {
                                            'type': 'string',
                                            'description': 'Chapter title.',
                                        },
                                        'goals': {
                                            'type':
                                            'array',
                                            'items': {
                                                'type': 'string'
                                            },
                                            'description':
                                            'Main objectives of this chapter.',
                                        },
                                        'sections_description': {
                                            'type':
                                            'string',
                                            'description':
                                            'Description of the planned sections in this chapter.',
                                        },
                                        'candidate_evidence': {
                                            'type':
                                            'array',
                                            'items': {
                                                'type': 'string'
                                            },
                                            'description':
                                            'List of note_ids relevant to this chapter.',
                                        },
                                    },
                                    'required':
                                    ['title', 'candidate_evidence'],
                                },
                            },
                        },
                        'required': ['title', 'chapters'],
                        'additionalProperties': False,
                    },
                ),
                Tool(
                    tool_name='prepare_chapter_bundle',
                    server_name=self.SERVER_NAME,
                    description=
                    ('Prepare metadata and evidence content for writing a specific chapter. '
                     'Returns the chapter info with full evidence details for review. '
                     'Call this before commit_chapter to review evidence quality.'
                     ),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'chapter_id': {
                                'type': 'integer',
                                'description': 'The chapter number (1-based).',
                            },
                            'relevant_evidence': {
                                'type':
                                'array',
                                'items': {
                                    'type': 'string'
                                },
                                'description':
                                ('List of note_ids maybe used in this chapter. '
                                 'The note_ids in this list will be loaded for review.'
                                 ),
                            },
                            # 'need_raw_chunks': {
                            #     'type': 'boolean',
                            #     'description': 'Whether to load raw chunk content for deeper analysis.',
                            #     'default': False,
                            # },
                        },
                        'required': ['chapter_id', 'relevant_evidence'],
                        'additionalProperties': False,
                    },
                ),
                Tool(
                    tool_name='commit_chapter',
                    server_name=self.SERVER_NAME,
                    description=
                    ('Write the content of a specific chapter. '
                     'The chapter will be saved as chapter_XX.md and status updated to completed.'
                     ),
                    parameters={
                        'type':
                        'object',
                        'properties': {
                            'chapter_id': {
                                'type': 'integer',
                                'description': 'The chapter number (1-based).',
                            },
                            'reranked_evidence': {
                                'type':
                                'array',
                                'items': {
                                    'type': 'string'
                                },
                                'description':
                                'List of note_ids reranked and chosen for this chapter.',
                            },
                            'content': {
                                'type':
                                'string',
                                'description':
                                ('The markdown content of the chapter. '
                                 'The content should include citations to the resources used in this chapter.'
                                 'Make sure the content is based on the reranked evidence.'
                                 ),
                            },
                            'cited_urls': {
                                'type':
                                'array',
                                'items': {
                                    'type': 'string'
                                },
                                'description':
                                ('List of resource urls actually cited in this chapter.'
                                 'Keep the same order as cited in content.'),
                            },
                        },
                        # Keep schema consistent with Python signature (reranked_evidence has no default)
                        'required': [
                            'chapter_id', 'reranked_evidence', 'content',
                            'cited_urls'
                        ],
                        'additionalProperties':
                        False,
                    },
                ),
                Tool(
                    tool_name='load_chunk',
                    server_name=self.SERVER_NAME,
                    description=
                    ('Load raw chunk content when evidence summaries are insufficient. '
                     'Reserved for future implementation.'),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'chunk_ids': {
                                'type': 'array',
                                'items': {
                                    'type': 'string'
                                },
                                'description': 'List of chunk IDs to load.',
                            },
                        },
                        'required': ['chunk_ids'],
                        'additionalProperties': False,
                    },
                ),
                Tool(
                    tool_name='commit_conflict',
                    server_name=self.SERVER_NAME,
                    description=
                    'Record a conflict or contradiction between evidence.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'description': {
                                'type': 'string',
                                'description': 'Description of the conflict.',
                            },
                            'evidence_ids': {
                                'type':
                                'array',
                                'items': {
                                    'type': 'string'
                                },
                                'description':
                                'Note IDs involved in the conflict.',
                            },
                            'chapter_id': {
                                'type': 'integer',
                                'description':
                                'Optional: Related chapter number.',
                            },
                            'resolution': {
                                'type':
                                'string',
                                'description':
                                'Optional: How the conflict was resolved.',
                            },
                        },
                        'required': ['description', 'evidence_ids'],
                        'additionalProperties': False,
                    },
                ),
                Tool(
                    tool_name='update_outline',
                    server_name=self.SERVER_NAME,
                    description=
                    'Update a specific chapter in the outline (title, goals, or evidence bindings).',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'chapter_id': {
                                'type': 'integer',
                                'description': 'The chapter number to update.',
                            },
                            'updates': {
                                'type': 'object',
                                'description':
                                'Fields to update (title, goals, sections_description, candidate_evidence).',
                                'properties': {
                                    'title': {
                                        'type': 'string',
                                        'description': 'Title of the chapter.',
                                    },
                                    'goals': {
                                        'type':
                                        'array',
                                        'items': {
                                            'type': 'string'
                                        },
                                        'description':
                                        'Main objectives of this chapter.',
                                    },
                                    'sections_description': {
                                        'type':
                                        'string',
                                        'description':
                                        'Description of the planned sections in this chapter.',
                                    },
                                    'candidate_evidence': {
                                        'type':
                                        'array',
                                        'items': {
                                            'type': 'string'
                                        },
                                        'description':
                                        'List of note_ids relevant to this chapter.',
                                    },
                                },
                            },
                        },
                        'required': ['chapter_id', 'updates'],
                        'additionalProperties': False,
                    },
                ),
                Tool(
                    tool_name='assemble_draft',
                    server_name=self.SERVER_NAME,
                    description=
                    ('Assemble all chapters into a draft (draft.md) with TOC and references. '
                     'Returns the draft path along with a summary of recorded conflicts. '
                     'The model should then review the draft and conflicts to produce the final report.'
                     ),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'include_toc': {
                                'type': 'boolean',
                                'description':
                                'Whether to include table of contents.',
                                'default': True,
                            },
                            'include_references': {
                                'type': 'boolean',
                                'description':
                                'Whether to include references section.',
                                'default': True,
                            },
                        },
                        'required': [],
                        'additionalProperties': False,
                    },
                ),
                Tool(
                    tool_name='get_status',
                    server_name=self.SERVER_NAME,
                    description='Get current report generation progress.',
                    parameters={
                        'type': 'object',
                        'properties': {},
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

    def _load_outline(self, paths: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Load outline.json."""
        return _safe_read_json(paths['outline_json'])

    def _save_outline(self,
                      paths: Dict[str, str],
                      outline: Dict[str, Any],
                      render: bool = True) -> None:
        """Save outline.json and render outline.md."""
        outline['updated_at'] = _now_iso()
        _write_text(paths['outline_json'], _json_dumps(outline))
        _write_text(paths['outline_md'], _render_outline_md(outline))

        if render:
            render_markdown_todo(
                paths['outline_md'],
                title='CURRENT REPORT OUTLINE',
                use_pager=False)

    def _load_evidence_index(self, paths: Dict[str, str]) -> Dict[str, Any]:
        """Load evidence index."""
        data = _safe_read_json(paths['evidence_index'])
        if data is None:
            return {'notes': {}}
        return data

    def _load_note_content(self, paths: Dict[str, str],
                           note_id: str) -> Optional[Dict[str, Any]]:
        """Load a single note's full content from markdown file."""
        note_path = os.path.join(paths['evidence_notes_dir'],
                                 f'note_{note_id}.md')
        if not os.path.exists(note_path):
            return None

        with open(note_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Parse note from markdown
        note = _parse_note_from_md(content, note_id)
        note['raw_content'] = content
        return note

    def _load_conflict(self, paths: Dict[str, str]) -> Dict[str, Any]:
        """Load conflict.json."""
        data = _safe_read_json(paths['conflict_json'])
        if data is None:
            return {'updated_at': _now_iso(), 'conflicts': []}
        return data

    def _save_conflict(self, paths: Dict[str, str],
                       conflict: Dict[str, Any]) -> None:
        """Save conflict.json."""
        conflict['updated_at'] = _now_iso()
        _write_text(paths['conflict_json'], _json_dumps(conflict))

    async def commit_outline(
        self,
        title: str,
        chapters: List[Dict[str, Any]],
    ) -> str:
        """Generate report outline with chapter structure."""
        paths = self._paths()
        _ensure_dir(paths['chapters_dir'])
        _ensure_dir(paths['lock_dir'])

        # Load evidence index to validate coverage
        evidence_index = self._load_evidence_index(paths)
        all_note_ids = set(evidence_index.get('notes', {}).keys())

        # Build outline
        outline_chapters = []
        covered_evidence = set()

        for idx, ch in enumerate(chapters, start=1):
            candidate = ch.get('candidate_evidence', [])
            covered_evidence.update(candidate)

            outline_chapters.append({
                'chapter_id':
                idx,
                'title':
                ch.get('title', f'Chapter {idx}'),
                'goals':
                ch.get('goals', []),
                'sections_description':
                ch.get('sections_description', ''),
                'candidate_evidence':
                candidate,
                'status':
                'pending',
            })

        # Check coverage
        uncovered = all_note_ids - covered_evidence
        coverage_warning = None
        if uncovered:
            coverage_warning = (
                f'Warning: the following evidence is not covered by any chapter: {list(uncovered)}'
            )

        outline = {
            'title': title,
            'created_at': _now_iso(),
            'updated_at': _now_iso(),
            'chapters': outline_chapters,
        }

        with file_lock(paths['lock_dir'], 'report_outline'):
            self._save_outline(paths, outline)

        result = {
            'status': 'ok',
            'outline_path': os.path.relpath(paths['outline_json'],
                                            self.output_dir),
            'chapters_count': len(outline_chapters),
            'total_evidence': len(all_note_ids),
            'covered_evidence': len(covered_evidence),
        }

        if coverage_warning:
            result['warning'] = coverage_warning

        return _json_dumps(result)

    async def prepare_chapter_bundle(
        self,
        chapter_id: int,
        relevant_evidence: List[str],
        need_raw_chunks: bool = False,
    ) -> str:
        """Prepare chapter metadata and evidence content."""
        paths = self._paths()
        _ensure_dir(paths['lock_dir'])

        # Load outline
        outline = self._load_outline(paths)
        if outline is None:
            return _json_dumps({
                'status':
                'error',
                'message':
                'Outline not created yet. Please call commit_outline first.'
            })

        # Find chapter
        chapter = None
        for ch in outline.get('chapters', []):
            if ch['chapter_id'] == chapter_id:
                chapter = ch
                break

        if chapter is None:
            return _json_dumps({
                'status': 'error',
                'message': f'Chapter {chapter_id} not found.'
            })

        # Load evidence content
        evidence_index = self._load_evidence_index(paths)
        notes_meta = evidence_index.get('notes', {})

        notes_content = []
        seen_note_ids = set()
        for note_id in chapter.get('candidate_evidence', []):
            meta = notes_meta.get(note_id, {})
            note_data = self._load_note_content(paths, note_id)

            if note_data:
                notes_content.append({
                    'note_id':
                    note_id,
                    'title':
                    meta.get('title', note_data.get('title', '')),
                    'claim':
                    note_data.get('claim', ''),
                    'supports':
                    note_data.get('supports', ''),
                    'contradicts':
                    note_data.get('contradicts', ''),
                    'summary':
                    meta.get('summary', note_data.get('summary', '')),
                    'sources':
                    meta.get('sources', note_data.get('sources', [])),
                    'quality_score':
                    meta.get('quality_score', note_data.get('quality_score')),
                    'tags':
                    meta.get('tags', note_data.get('tags', [])),
                })
            else:
                # Note not found, include minimal info
                notes_content.append({
                    'note_id': note_id,
                    'error': f'Note {note_id} not found',
                    'title': meta.get('title', ''),
                    'summary': meta.get('summary', ''),
                })

            seen_note_ids.add(note_id)

        for note_id in relevant_evidence:
            if note_id not in seen_note_ids:
                meta = notes_meta.get(note_id, {})
                note_data = self._load_note_content(paths, note_id)

                if note_data:
                    notes_content.append({
                        'note_id':
                        note_id,
                        'title':
                        meta.get('title', note_data.get('title', '')),
                        'claim':
                        note_data.get('claim', ''),
                        'supports':
                        note_data.get('supports', ''),
                        'contradicts':
                        note_data.get('contradicts', ''),
                        'summary':
                        meta.get('summary', note_data.get('summary', '')),
                        'sources':
                        meta.get('sources', note_data.get('sources', [])),
                        'quality_score':
                        meta.get('quality_score',
                                 note_data.get('quality_score')),
                        'tags':
                        meta.get('tags', note_data.get('tags', [])),
                    })
                else:
                    notes_content.append({
                        'note_id': note_id,
                        'error': f'Note {note_id} not found',
                        'title': meta.get('title', ''),
                        'summary': meta.get('summary', ''),
                    })

        # Build meta
        candidate_evidence = list(
            dict.fromkeys(
                list(chapter.get('candidate_evidence', []))
                + list(relevant_evidence or [])))
        meta = {
            'chapter_id': chapter_id,
            'chapter_title': chapter['title'],
            'chapter_goals': chapter.get('goals', []),
            'sections_description': chapter.get('sections_description', ''),
            'candidate_evidence': candidate_evidence,
            'need_raw_chunks': need_raw_chunks,
            'loaded_chunks': [],
            'created_at': _now_iso(),
        }

        # Save meta.json
        meta_path = os.path.join(paths['chapters_dir'],
                                 f'chapter_{chapter_id:02d}_meta.json')
        with file_lock(paths['lock_dir'], f'chapter_{chapter_id}_meta'):
            _write_text(meta_path, _json_dumps(meta))

        # Update outline status
        chapter['status'] = 'in_progress'
        with file_lock(paths['lock_dir'], 'report_outline'):
            self._save_outline(paths, outline)

        return _json_dumps({
            'status':
            'ok',
            'chapter_id':
            chapter_id,
            'chapter_title':
            chapter['title'],
            'chapter_goals':
            chapter.get('goals', []),
            'evidence_count':
            len(notes_content),
            'meta_path':
            os.path.relpath(meta_path, self.output_dir),
            'notes_content':
            notes_content,
        })

    async def commit_chapter(
        self,
        chapter_id: int,
        reranked_evidence: List[str],
        content: str,
        cited_urls: Optional[List[str]] = None,
    ) -> str:
        """Write chapter content."""
        paths = self._paths()
        _ensure_dir(paths['lock_dir'])

        # Validate outline exists
        outline = self._load_outline(paths)
        if outline is None:
            return _json_dumps({
                'status': 'error',
                'message': 'Outline not created yet.'
            })

        # Find and update chapter
        chapter_found = False
        chapter_title = ''
        for ch in outline.get('chapters', []):
            if ch['chapter_id'] == chapter_id:
                ch['status'] = 'completed'
                if cited_urls:
                    ch['cited_urls'] = cited_urls
                chapter_found = True
                chapter_title = ch['title']
                break

        if not chapter_found:
            return _json_dumps({
                'status': 'error',
                'message': f'Chapter {chapter_id} not found.'
            })

        # Write chapter file
        chapter_path = os.path.join(paths['chapters_dir'],
                                    f'chapter_{chapter_id:02d}.md')

        with file_lock(paths['lock_dir'], f'chapter_{chapter_id}'):
            _write_text(chapter_path, content)

        with file_lock(paths['lock_dir'], 'report_outline'):
            self._save_outline(paths, outline)

        meta_path = os.path.join(paths['chapters_dir'],
                                 f'chapter_{chapter_id:02d}_meta.json')
        meta = _safe_read_json(meta_path)
        meta = meta if isinstance(meta, dict) else {}
        meta['reranked_evidence'] = list(reranked_evidence or [])
        meta['cited_urls'] = list(cited_urls or [])
        with file_lock(paths['lock_dir'], f'chapter_{chapter_id}_meta'):
            _write_text(meta_path, _json_dumps(meta))

        return _json_dumps({
            'status':
            'ok',
            'chapter_id':
            chapter_id,
            'chapter_title':
            chapter_title,
            'path':
            os.path.relpath(chapter_path, self.output_dir),
            'content_length':
            len(content),
            'reranked_evidence':
            reranked_evidence or [],
            'cited_urls':
            cited_urls or [],
        })

    async def load_chunk(self, chunk_ids: List[str]) -> str:
        """Load raw chunk content. Reserved for future implementation."""
        return _json_dumps({
            'status': 'not_implemented',
            'message':
            'Chunk storage not enabled in this version. Use evidence notes directly.',
            'chunk_ids': chunk_ids,
        })

    async def commit_conflict(
        self,
        description: str,
        evidence_ids: List[str],
        chapter_id: Optional[int] = None,
        resolution: Optional[str] = None,
    ) -> str:
        """Record evidence conflict."""
        paths = self._paths()
        _ensure_dir(paths['lock_dir'])

        conflict_id = f'conflict_{uuid.uuid4().hex[:6]}'

        conflict_entry = {
            'id': conflict_id,
            'description': description,
            'evidence_ids': evidence_ids,
            'chapter_id': chapter_id,
            'resolution': resolution,
            'created_at': _now_iso(),
        }

        with file_lock(paths['lock_dir'], 'conflict'):
            conflicts = self._load_conflict(paths)
            conflicts['conflicts'].append(conflict_entry)
            self._save_conflict(paths, conflicts)

        return _json_dumps({
            'status':
            'ok',
            'conflict_id':
            conflict_id,
            'total_conflicts':
            len(conflicts['conflicts']),
            'conflict_path':
            os.path.relpath(paths['conflict_json'], self.output_dir),
        })

    async def update_outline(
        self,
        chapter_id: int,
        updates: Dict[str, Any],
    ) -> str:
        """Update a chapter in the outline."""
        paths = self._paths()
        _ensure_dir(paths['lock_dir'])

        with file_lock(paths['lock_dir'], 'report_outline'):
            outline = self._load_outline(paths)
            if outline is None:
                return _json_dumps({
                    'status': 'error',
                    'message': 'Outline not created yet.'
                })

            chapter_found = False
            for ch in outline.get('chapters', []):
                if ch['chapter_id'] == chapter_id:
                    if 'title' in updates:
                        ch['title'] = updates['title']
                    if 'goals' in updates:
                        ch['goals'] = updates['goals']
                    if 'sections_description' in updates:
                        ch['sections_description'] = updates[
                            'sections_description']
                    if 'candidate_evidence' in updates:
                        ch['candidate_evidence'] = updates[
                            'candidate_evidence']
                    chapter_found = True
                    break

            if not chapter_found:
                return _json_dumps({
                    'status':
                    'error',
                    'message':
                    f'Chapter {chapter_id} not found.'
                })

            self._save_outline(paths, outline)

        return _json_dumps({
            'status': 'ok',
            'chapter_id': chapter_id,
            'updates_applied': list(updates.keys()),
        })

    async def assemble_draft(
        self,
        include_toc: bool = True,
        include_references: bool = True,
    ) -> str:
        """Assemble draft from all chapters."""
        paths = self._paths()

        outline = self._load_outline(paths)
        if outline is None:
            return _json_dumps({
                'status': 'error',
                'message': 'Outline not created yet.'
            })

        # Collect chapter contents
        chapters_content = []
        missing_chapters = []

        for ch in outline.get('chapters', []):
            chapter_path = os.path.join(paths['chapters_dir'],
                                        f"chapter_{ch['chapter_id']:02d}.md")
            if os.path.exists(chapter_path):
                with open(chapter_path, 'r', encoding='utf-8') as f:
                    chapters_content.append({
                        'id':
                        ch['chapter_id'],
                        'title':
                        ch['title'],
                        'content':
                        f.read(),
                        'reranked_evidence':
                        ch.get('reranked_evidence', []),
                        'cited_urls':
                        ch.get('cited_urls', []),
                    })
            else:
                missing_chapters.append(ch['chapter_id'])

        if missing_chapters:
            return _json_dumps({
                'status':
                'error',
                'message':
                f'The following chapters are not completed yet: {missing_chapters}',
            })

        # Build draft
        draft_lines = [
            f"# {outline.get('title', 'Research Report')} (Draft)", ''
        ]

        # Table of contents
        if include_toc:
            draft_lines.append('## Table of Contents')
            draft_lines.append('')
            for ch in chapters_content:
                anchor = ch['title'].replace(' ', '-').lower()
                draft_lines.append(
                    f"- [Chapter {ch['id']} {ch['title']}](#{anchor})")
            draft_lines.append('')

        # Chapters
        for ch in chapters_content:
            draft_lines.append(ch['content'])
            draft_lines.append('')

        # References
        if include_references:
            # evidence_index = self._load_evidence_index(paths)
            # notes_meta = evidence_index.get('notes', {})

            cited_urls = set()
            for ch in chapters_content:
                for url in (ch.get('cited_urls') or []):
                    cited_urls.add(url)

            all_cited = set()
            for ch in chapters_content:
                all_cited.update(ch.get('reranked_evidence', []))

            # Also include candidate evidence if no explicit citations
            if not all_cited:
                for ch in outline.get('chapters', []):
                    all_cited.update(ch.get('candidate_evidence', []))

            if cited_urls:
                draft_lines.append('## References')
                draft_lines.append('')

                ref_idx = 1
                for url in cited_urls:
                    draft_lines.append(f'{ref_idx}. {url}')
                    ref_idx += 1

                draft_lines.append('')

        # Write draft
        draft_content = '\n'.join(draft_lines)
        _write_text(paths['draft_md'], draft_content)

        # Load conflicts for summary
        conflicts_data = self._load_conflict(paths)
        conflicts_list = conflicts_data.get('conflicts', [])
        conflicts_summary = []
        for c in conflicts_list:
            conflicts_summary.append({
                'id': c.get('id'),
                'description': c.get('description'),
                'chapter_id': c.get('chapter_id'),
                'resolution': c.get('resolution'),
            })

        return _json_dumps({
            'status':
            'ok',
            'draft_path':
            os.path.relpath(paths['draft_md'], self.output_dir),
            'chapters_count':
            len(chapters_content),
            'content_length':
            len(draft_content),
            'conflicts_count':
            len(conflicts_list),
            'conflicts_summary':
            conflicts_summary,
            'next_step_reminder':
            ('Review the draft and conflicts, then you can try to generate the final report. '
             ),
        })

    async def get_status(self) -> str:
        """Get current report generation progress."""
        paths = self._paths()

        outline = self._load_outline(paths)
        conflicts = self._load_conflict(paths)

        if outline is None:
            return _json_dumps({
                'status':
                'not_started',
                'outline_exists':
                False,
                'chapters': [],
                'conflicts_count':
                len(conflicts.get('conflicts', [])),
            })

        chapters_status = []
        for ch in outline.get('chapters', []):
            chapter_path = os.path.join(paths['chapters_dir'],
                                        f"chapter_{ch['chapter_id']:02d}.md")
            chapters_status.append({
                'chapter_id':
                ch['chapter_id'],
                'title':
                ch['title'],
                'status':
                ch.get('status', 'pending'),
                'file_exists':
                os.path.exists(chapter_path),
                'candidate_evidence_count':
                len(ch.get('candidate_evidence', [])),
            })

        completed = sum(1 for ch in chapters_status
                        if ch['status'] == 'completed')
        total = len(chapters_status)

        return _json_dumps({
            'status':
            'in_progress' if completed < total else 'completed',
            'outline_exists':
            True,
            'report_title':
            outline.get('title', ''),
            'progress':
            f'{completed}/{total}',
            'chapters':
            chapters_status,
            'conflicts_count':
            len(conflicts.get('conflicts', [])),
            'draft_exists':
            os.path.exists(paths['draft_md']),
            'report_exists':
            os.path.exists(paths['report_md']),
        })
