# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional

import json
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils.utils import file_lock


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


def _generate_note_id() -> str:
    """Generate a short unique ID for a note."""
    return uuid.uuid4().hex[:6]


def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    return re.sub(r'[^\w\-]', '_', name)[:64]


def _validate_source_tier(tier: str) -> str:
    allowed = {'official', 'primary', 'secondary', 'unknown'}
    if tier not in allowed:
        return 'unknown'
    return tier


def _render_note_card(note: Dict[str, Any]) -> str:
    """
    Render a note card as Markdown.

    Note structure:
    {
        "note_id": "abc123",
        "task_id": "task_1",  # optional, links to plan task
        "title": "Key finding about X",
        "claim": "The main claim or observation",
        "supports": "Evidence text supporting the claim...",
        "contradicts": "Evidence text contradicting the claim...",  # optional
        "sources": [
            {"url": "...", "published_at": "...", "source_tier": "primary"}
        ],
        "summary": "Brief summary of this evidence",
        "tags": ["tag1", "tag2"],
        "quality_score": 85 (0-100),
        "created_at": "2025-01-19T10:00:00"
    }
    """
    lines = []

    # Header
    lines.append(f"# {note.get('title', 'Untitled Note')}")
    lines.append('')

    # Metadata block
    lines.append('## Metadata')
    lines.append(f"- **Note ID**: `{note.get('note_id', '')}`")
    if note.get('task_id'):
        lines.append(f"- **Task ID**: `{note['task_id']}`")
    if note.get('tags'):
        tags_str = ', '.join(f'`{t}`' for t in note['tags'])
        lines.append(f'- **Tags**: {tags_str}')
    if note.get('quality_score') is not None:
        lines.append(f"- **Quality Score**: {note['quality_score']}/100")
    lines.append(f"- **Created**: {note.get('created_at', '')}")
    lines.append('')

    # Claim
    if note.get('claim'):
        lines.append('## Claim')
        lines.append(note['claim'])
        lines.append('')

    # Supporting evidence
    if note.get('supports'):
        lines.append('## Supporting Evidence')
        lines.append(note['supports'])
        lines.append('')

    # Contradicting evidence
    if note.get('contradicts'):
        lines.append('## Contradicting Evidence')
        lines.append(note['contradicts'])
        lines.append('')

    # Summary
    if note.get('summary'):
        lines.append('## Summary')
        lines.append(note['summary'])
        lines.append('')

    # Sources
    sources = note.get('sources', [])
    if sources:
        lines.append('## Sources')
        for src in sources:
            url = src.get('url', 'N/A')
            tier = src.get('source_tier', 'unknown')
            pub = src.get('published_at', '')
            pub_str = f' (published: {pub})' if pub else ''
            lines.append(f'- [{tier}] {url}{pub_str}')
        lines.append('')

    return '\n'.join(lines)


def _parse_note_from_md(content: str, note_id: str) -> Dict[str, Any]:
    """
    Parse a note card from Markdown back to dict.
    This is a best-effort parser for re-reading stored notes.
    """
    note: Dict[str, Any] = {'note_id': note_id}

    # Extract title from first H1
    title_match = re.search(r'^# (.+)$', content, re.MULTILINE)
    if title_match:
        note['title'] = title_match.group(1).strip()

    # Extract sections
    sections = re.split(r'^## ', content, flags=re.MULTILINE)
    for section in sections[1:]:  # Skip content before first ##
        lines = section.strip().split('\n', 1)
        if not lines:
            continue
        header = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ''

        if header == 'Claim':
            note['claim'] = body
        elif header == 'Supporting Evidence':
            note['supports'] = body
        elif header == 'Contradicting Evidence':
            note['contradicts'] = body
        elif header == 'Summary':
            note['summary'] = body
        elif header == 'Metadata':
            # Parse metadata lines
            for line in body.split('\n'):
                if '**Task ID**' in line:
                    match = re.search(r'`([^`]+)`', line)
                    if match:
                        note['task_id'] = match.group(1)
                elif '**Tags**' in line:
                    tags = re.findall(r'`([^`]+)`', line)
                    note['tags'] = tags
                elif '**Quality Score**' in line:
                    match = re.search(r'(\d+)/100', line)
                    if match:
                        note['quality_score'] = int(match.group(1))
                elif '**Created**' in line:
                    match = re.search(r'\*\*Created\*\*: (.+)$', line)
                    if match:
                        note['created_at'] = match.group(1).strip()
        elif header == 'Sources':
            sources = []
            for line in body.split('\n'):
                match = re.search(
                    r'- \[(\w+)\] (.+?)(?:\s+\(published: ([^)]+)\))?$', line)
                if match:
                    sources.append({
                        'url': match.group(2).strip(),
                        'source_tier': match.group(1),
                        'published_at': match.group(3) or ''
                    })
            note['sources'] = sources

    return note


class EvidenceTool(ToolBase):
    """
    Evidence management tool for DeepResearch agents.

    Provides structured storage and retrieval of evidence cards (notes).
    Each note represents a single piece of evidence (claim/observation)
    with supporting/contradicting text, sources, and metadata.

    Storage:
    - evidence/index.json: Global index for fast lookups
    - evidence/notes/note_{id}.md: Individual evidence cards
    - chunks/: Reserved for future chunk storage
    """

    SERVER_NAME = 'evidence_store'

    def __init__(self, config, **kwargs):
        super().__init__(config)
        tool_cfg = getattr(getattr(config, 'tools'), 'evidence_store')
        self.exclude_func(tool_cfg)

        # Configurable paths
        self._evidence_dir = getattr(tool_cfg, 'evidence_dir',
                                     'evidence') if tool_cfg else 'evidence'
        self._chunks_dir = getattr(tool_cfg, 'chunks_dir',
                                   'chunks') if tool_cfg else 'chunks'
        self._lock_subdir = getattr(tool_cfg, 'lock_subdir',
                                    '.locks') if tool_cfg else '.locks'

        # Feature flags
        self._enable_chunk_storage = bool(
            getattr(tool_cfg, 'enable_chunk_storage',
                    False)) if tool_cfg else False

    async def connect(self) -> None:
        """Initialize directory structure."""
        _ensure_dir(self.output_dir)
        _ensure_dir(os.path.join(self.output_dir, self._evidence_dir, 'notes'))
        _ensure_dir(os.path.join(self.output_dir, self._chunks_dir))
        _ensure_dir(os.path.join(self.output_dir, self._lock_subdir))

    def _paths(self) -> Dict[str, str]:
        return {
            'index':
            os.path.join(self.output_dir, self._evidence_dir, 'index.json'),
            'notes_dir':
            os.path.join(self.output_dir, self._evidence_dir, 'notes'),
            'chunks_dir':
            os.path.join(self.output_dir, self._chunks_dir),
            'lock_dir':
            os.path.join(self.output_dir, self._lock_subdir),
        }

    async def _get_tools_inner(self) -> Dict[str, Any]:
        tools: Dict[str, List[Tool]] = {
            self.SERVER_NAME: [
                Tool(
                    tool_name='write_note',
                    server_name=self.SERVER_NAME,
                    description=
                    ('Write a new evidence note (card) to the evidence store. '
                     'Each note represents ONE piece of evidence: a claim/observation with supporting text. '
                     'Returns the generated note_id.'),
                    parameters={
                        'type':
                        'object',
                        'properties': {
                            'title': {
                                'type':
                                'string',
                                'description':
                                'Brief title describing this evidence (e.g., "Tesla Q3 revenue growth").',
                            },
                            'claim': {
                                'type':
                                'string',
                                'description':
                                'The main claim or observation this note captures. '
                                'It should be as detailed and comprehensive as possible.',
                            },
                            'supports': {
                                'type':
                                'string',
                                'description':
                                ('Evidence text that supports this claim. '
                                 'This should be a detailed and comprehensive description '
                                 'of the evidence that supports the claim.'
                                 'Can include quotes, data, or reasoning. Multi-paragraph allowed.'
                                 ),
                            },
                            'contradicts': {
                                'type':
                                'string',
                                'description':
                                ('Optional: Evidence text that contradicts this claim. '
                                 'Include if there are conflicting sources or caveats.'
                                 ),
                            },
                            'sources': {
                                'type': 'array',
                                'description':
                                'List of source references for this evidence.',
                                'items': {
                                    'type': 'object',
                                    'properties': {
                                        'url': {
                                            'type': 'string',
                                            'description': 'Source URL'
                                        },
                                        'published_at': {
                                            'type':
                                            'string',
                                            'description':
                                            'Publication date (YYYY-MM-DD)'
                                        },
                                        'source_tier': {
                                            'type':
                                            'string',
                                            'enum': [
                                                'official', 'primary',
                                                'secondary', 'unknown'
                                            ],
                                            'description':
                                            ('Source credibility tier (for example, Official '
                                             'Documents/Papers/Standards > '
                                             'Primary News/Announcements > Secondary Blogs)'
                                             ),
                                        },
                                    },
                                    'required': ['url'],
                                },
                            },
                            'summary': {
                                'type':
                                'string',
                                'description':
                                'One-sentence summary of this evidence.',
                            },
                            'task_id': {
                                'type':
                                'string',
                                'description':
                                'The plan task this evidence relates to.',
                            },
                            'tags': {
                                'type': 'array',
                                'items': {
                                    'type': 'string'
                                },
                                'description': 'Tags for categorization.',
                            },
                            'quality_score': {
                                'type':
                                'integer',
                                'minimum':
                                0,
                                'maximum':
                                100,
                                'description':
                                'Optional: Confidence/quality score (0-100).',
                            },
                        },
                        'required': [
                            'title', 'claim', 'supports', 'sources', 'summary',
                            'task_id', 'tags'
                        ],
                        'additionalProperties':
                        False,
                    },
                ),
                Tool(
                    tool_name='get_note',
                    server_name=self.SERVER_NAME,
                    description='Retrieve a specific evidence note by its ID.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'note_id': {
                                'type': 'string',
                                'description':
                                'The ID of the note to retrieve.',
                            },
                        },
                        'required': ['note_id'],
                        'additionalProperties': False,
                    },
                ),
                Tool(
                    tool_name='list_notes',
                    server_name=self.SERVER_NAME,
                    description=
                    ('List all evidence notes, optionally filtered by task_id or tags. '
                     'Returns a summary list (not full content).'),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'task_id': {
                                'type': 'string',
                                'description': 'Optional: Filter by task ID.',
                            },
                            'tags': {
                                'type':
                                'array',
                                'items': {
                                    'type': 'string'
                                },
                                'description':
                                'Optional: Filter by tags (notes must have ALL specified tags).',
                            },
                            # 'min_quality': {
                            #     'type': 'integer',
                            #     'description': 'Optional: Minimum quality score to include.',
                            # },
                        },
                        'required': [],
                        'additionalProperties': False,
                    },
                ),
                Tool(
                    tool_name='search_notes',
                    server_name=self.SERVER_NAME,
                    description=
                    'Search notes by keyword in title, claim, or summary.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'keyword': {
                                'type': 'string',
                                'description': 'Keyword to search for.',
                            },
                        },
                        'required': ['keyword'],
                        'additionalProperties': False,
                    },
                ),
                Tool(
                    tool_name='delete_note',
                    server_name=self.SERVER_NAME,
                    description='Delete an evidence note by its ID.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'note_id': {
                                'type': 'string',
                                'description': 'The ID of the note to delete.',
                            },
                        },
                        'required': ['note_id'],
                        'additionalProperties': False,
                    },
                ),
                Tool(
                    tool_name='load_index',
                    server_name=self.SERVER_NAME,
                    description='Load the evidence index.',
                    parameters={
                        'type': 'object',
                        'properties': {},
                        'required': [],
                        'additionalProperties': False,
                    },
                )
            ]
        }
        return tools

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        return await getattr(self, tool_name)(**(tool_args or {}))

    def _load_index_locked(self, paths: Dict[str, str]) -> Dict[str, Any]:
        """Load index.json, creating empty structure if not exists."""
        data = _safe_read_json(paths['index'])
        if data is None or not isinstance(data, dict):
            return {
                'schema_version': 1,
                'updated_at': _now_iso(),
                'notes':
                {},  # note_id -> {title, task_id, summary, sources, tags, quality_score, created_at}
            }
        return data

    def _save_index_locked(self, paths: Dict[str, str],
                           index: Dict[str, Any]) -> None:
        """Save index.json."""
        index['updated_at'] = _now_iso()
        _write_text(paths['index'], _json_dumps(index))

    def _add_to_index(self, index: Dict[str, Any], note: Dict[str,
                                                              Any]) -> None:
        """Add a note's metadata to the index."""
        note_id = note['note_id']
        index['notes'][note_id] = {
            'title': note.get('title', ''),
            'task_id': note.get('task_id', ''),
            'summary': note.get('summary', ''),
            'sources': note.get('sources', []),
            'tags': note.get('tags', []),
            'quality_score': note.get('quality_score'),
            'created_at': note.get('created_at', ''),
        }

    def _remove_from_index(self, index: Dict[str, Any], note_id: str) -> bool:
        """Remove a note from the index. Returns True if found and removed."""
        if note_id in index.get('notes', {}):
            del index['notes'][note_id]
            return True
        return False

    def _store_chunk(self, chunk_id: str, content: str,
                     metadata: Dict[str, Any]) -> str:
        """
        Store a text chunk. Reserved for future implementation.

        Args:
            chunk_id: Unique identifier for the chunk
            content: The chunk text content
            metadata: Additional metadata (source_url, position, etc.)

        Returns:
            The chunk_id (or path) for reference
        """
        if not self._enable_chunk_storage:
            # Return chunk_id as-is when storage is disabled
            return chunk_id

        # TODO: Implement chunk storage when enabled
        # paths = self._paths()
        # chunk_path = os.path.join(paths['chunks_dir'], f'chunk_{chunk_id}.json')
        # chunk_data = {'chunk_id': chunk_id, 'content': content, 'metadata': metadata}
        # _write_text(chunk_path, _json_dumps(chunk_data))
        return chunk_id

    def _load_chunk(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """
        Load a chunk by ID. Reserved for future implementation.
        """
        if not self._enable_chunk_storage:
            return None

        # TODO: Implement chunk loading when enabled
        return None

    async def write_note(
        self,
        title: str,
        claim: str,
        supports: str,
        contradicts: Optional[str] = None,
        sources: Optional[List[Dict[str, Any]]] = None,
        summary: Optional[str] = None,
        task_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        quality_score: Optional[int] = None,
    ) -> str:
        """Write a new evidence note."""
        paths = self._paths()
        _ensure_dir(paths['notes_dir'])
        _ensure_dir(paths['lock_dir'])

        # Generate ID and build note
        note_id = _generate_note_id()
        note: Dict[str, Any] = {
            'note_id': note_id,
            'title': title.strip(),
            'claim': claim.strip(),
            'supports': supports.strip(),
            'created_at': _now_iso(),
        }

        if contradicts:
            note['contradicts'] = contradicts.strip()
        if sources:
            # Validate source tiers
            for src in sources:
                src['source_tier'] = _validate_source_tier(
                    src.get('source_tier', 'unknown'))
            note['sources'] = sources
        if summary:
            note['summary'] = summary.strip()
        if task_id:
            note['task_id'] = task_id.strip()
        if tags:
            note['tags'] = [t.strip() for t in tags if t.strip()]
        if quality_score is not None:
            note['quality_score'] = max(0, min(100, quality_score))

        # Write note file
        note_path = os.path.join(paths['notes_dir'], f'note_{note_id}.md')
        note_content = _render_note_card(note)

        with file_lock(paths['lock_dir'], 'evidence_index'):
            _write_text(note_path, note_content)

            # Update index
            index = self._load_index_locked(paths)
            self._add_to_index(index, note)
            self._save_index_locked(paths, index)

        return _json_dumps({
            'status': 'ok',
            'note_id': note_id,
            'path': os.path.relpath(note_path, self.output_dir),
        })

    async def get_note(self,
                       note_id: str,
                       parse_note: Optional[bool] = False) -> str:
        """Retrieve a note by ID."""
        paths = self._paths()
        note_path = os.path.join(paths['notes_dir'], f'note_{note_id}.md')

        if not os.path.exists(note_path):
            return _json_dumps({
                'status': 'error',
                'message': f'Note {note_id} not found.'
            })

        with open(note_path, 'r', encoding='utf-8') as f:
            content = f.read()

        if not parse_note:
            return _json_dumps({'status': 'ok', 'raw_content': content})
        else:
            note = _parse_note_from_md(content, note_id)
            return _json_dumps({
                'status': 'ok',
                'note_id': note_id,
                'note': note,
                'raw_content': content
            })

    async def list_notes(self,
                         task_id: Optional[str] = None,
                         tags: Optional[List[str]] = None,
                         min_quality: Optional[int] = None) -> str:
        """List notes with optional filters.

        Args:
            task_id: Optional: Filter by task ID.
            tags: Optional: Filter by tags (notes must have ALL specified tags).
            min_quality: Optional: Minimum quality score to include. (not supported yet)
        """
        paths = self._paths()
        _ensure_dir(paths['lock_dir'])

        with file_lock(paths['lock_dir'], 'evidence_index'):
            index = self._load_index_locked(paths)

        notes_meta = index.get('notes', {})
        results = []

        for nid, meta in notes_meta.items():
            # Apply filters
            if task_id and meta.get('task_id') != task_id:
                continue
            if tags:
                note_tags = set(meta.get('tags', []))
                if not all(t in note_tags for t in tags):
                    continue
            if min_quality is not None:
                score = meta.get('quality_score')
                if score is None or score < min_quality:
                    continue

            results.append({
                'note_id': nid,
                'title': meta.get('title', ''),
                'task_id': meta.get('task_id', ''),
                'summary': meta.get('summary', ''),
                'sources': meta.get('sources', []),
                'tags': meta.get('tags', []),
                'quality_score': meta.get('quality_score'),
                'created_at': meta.get('created_at', ''),
            })

        # Sort by created_at descending
        results.sort(key=lambda x: x.get('created_at', ''), reverse=True)

        return _json_dumps({
            'status': 'ok',
            'count': len(results),
            'notes': results,
        })

    async def search_notes(self, keyword: str) -> str:
        """Search notes by keyword."""
        paths = self._paths()
        _ensure_dir(paths['lock_dir'])

        keyword_lower = keyword.lower().strip()
        if not keyword_lower:
            return _json_dumps({
                'status': 'error',
                'message': 'Keyword is required.'
            })

        with file_lock(paths['lock_dir'], 'evidence_index'):
            index = self._load_index_locked(paths)

        notes_meta = index.get('notes', {})
        results = []

        for nid, meta in notes_meta.items():
            # Search in title, summary
            searchable = ' '.join([
                meta.get('title', ''),
                meta.get('summary', ''),
            ]).lower()
            tags = meta.get('tags', [])
            searchable += ' ' + ' '.join(tags).lower()

            if keyword_lower in searchable:
                results.append({
                    'note_id': nid,
                    'title': meta.get('title', ''),
                    'summary': meta.get('summary', ''),
                    'task_id': meta.get('task_id', ''),
                    'quality_score': meta.get('quality_score'),
                })

        return _json_dumps({
            'status': 'ok',
            'keyword': keyword,
            'count': len(results),
            'notes': results,
        })

    async def delete_note(self, note_id: str) -> str:
        """Delete a note by ID."""
        paths = self._paths()
        _ensure_dir(paths['lock_dir'])

        note_path = os.path.join(paths['notes_dir'], f'note_{note_id}.md')

        with file_lock(paths['lock_dir'], 'evidence_index'):
            # Remove from index
            index = self._load_index_locked(paths)
            removed = self._remove_from_index(index, note_id)

            if not removed and not os.path.exists(note_path):
                return _json_dumps({
                    'status': 'error',
                    'message': f'Note {note_id} not found.'
                })

            self._save_index_locked(paths, index)

            # Remove file
            if os.path.exists(note_path):
                os.remove(note_path)

        return _json_dumps({'status': 'ok', 'deleted': note_id})

    async def load_index(self) -> str:
        """
        Load and return the full evidence index.

        Returns the complete index containing metadata for all notes,
        useful for understanding the overall evidence coverage.
        """
        paths = self._paths()
        _ensure_dir(paths['lock_dir'])

        with file_lock(paths['lock_dir'], 'evidence_index'):
            index = self._load_index_locked(paths)

        notes = index.get('notes', {})
        return _json_dumps({
            'status': 'ok',
            'updated_at': index.get('updated_at', ''),
            'total_notes': len(notes),
            'notes': notes,
        })
