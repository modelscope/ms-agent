# Copyright (c) ModelScope Contributors. All rights reserved.
"""Discover chat model ids from a provider's standard /models endpoint.

Best-effort: missing key, network error, non-2xx, or a non-standard payload
all degrade to ``[]``. Image/video/embedding/audio ids are filtered out for
TUI listing — the endpoint itself usually returns every product on the key.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Tuple

import httpx

# Name heuristics only: OpenAI-compatible /models rarely carries a modality
# field. Vision-understanding ids (qwen-vl, gpt-4o, glm-4v) are kept.
_NON_CHAT_RE = re.compile(
    r'(embedding|rerank|moderation|whisper|transcribe|'
    r'(?:^|[-_./])(?:tts|asr|video|speech)(?:$|[-_./])|'
    r'wanx|wan[-_.]?2|(?:^|[-_./])wan\d|'
    r't2i|t2v|i2v|i2i|ti2v|'
    r'dall-?e|dalle|gpt-image|flux|stable-?diff|imagen|'
    r'image-gen|qwen-image|'
    r'kling|sora|veo[-_.]|cogview|cogvideox|'
    r'sambert|paraformer|cosyvoice|qwen-audio|qwen2-audio|'
    r'realtime)',
    re.IGNORECASE,
)


def parse_model_ids(payload: object) -> List[str]:
    """Extract ids from a standard OpenAI/Anthropic ``{"data":[{"id":...}]}``."""
    ids: List[str] = []
    if isinstance(payload, dict):
        data = payload.get('data')
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    mid = item.get('id')
                    if isinstance(mid, str) and mid:
                        ids.append(mid)
    return sorted(set(ids))


def is_non_chat_model(model_id: str) -> bool:
    return bool(model_id) and bool(_NON_CHAT_RE.search(model_id))


def filter_chat_model_ids(ids: Sequence[str]) -> Tuple[List[str], int]:
    """Return (chat-oriented ids, number dropped)."""
    kept: List[str] = []
    dropped = 0
    for mid in ids:
        if is_non_chat_model(mid):
            dropped += 1
        else:
            kept.append(mid)
    return kept, dropped


def wire_protocol(protocol_or_transport: str) -> str:
    p = (protocol_or_transport or '').lower()
    if p in ('anthropic', 'anthropic_messages'):
        return 'anthropic'
    return 'openai'


def fetch_model_ids(base_url: str, protocol: str, api_key: str) -> List[str]:
    """Return available model ids, or [] on any failure."""
    if not base_url:
        return []
    base = base_url.rstrip('/')
    try:
        if wire_protocol(protocol) == 'anthropic':
            if not base.endswith('/v1'):
                base = f'{base}/v1'
            url = f'{base}/models'
            headers = {'anthropic-version': '2023-06-01'}
            if api_key:
                headers['x-api-key'] = api_key
        else:
            url = f'{base}/models'
            headers = {}
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'
        with httpx.Client(timeout=8) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code // 100 != 2:
                return []
            return parse_model_ids(resp.json())
    except Exception:
        return []


def format_id_list(ids: Iterable[str], *, limit: int = 40) -> str:
    shown = list(ids)
    extra = 0
    if limit and len(shown) > limit:
        extra = len(shown) - limit
        shown = shown[:limit]
    text = ', '.join(shown) if shown else '(none)'
    if extra:
        text += f'  … +{extra} more'
    return text


def group_model_ids(
        ids: Sequence[str]
) -> Tuple[List[Tuple[str, List[str]]], List[str]]:
    """Bucket ids the way the WebUI model picker does.

    ``owner/rest`` ids become a named group. Prefixless ids that share a
    leading letter run (qwen-plus, qwen3.8-flash) share a family group when
    there are at least two. Leftover singletons stay ungrouped.
    """
    ungrouped: List[str] = []
    slash_groups: dict[str, List[str]] = {}
    for mid in ids:
        cut = mid.find('/')
        owner = mid[:cut] if cut > 0 else ''
        rest = mid[cut + 1:] if cut > 0 else ''
        if owner and rest:
            slash_groups.setdefault(owner, []).append(mid)
        else:
            ungrouped.append(mid)

    families: dict[str, List[str]] = {}
    singles: List[str] = []
    by_family: dict[str, List[str]] = {}
    for mid in ungrouped:
        match = re.match(r'[A-Za-z]+', mid)
        key = match.group(0) if match else mid
        by_family.setdefault(key, []).append(mid)
    for key, members in by_family.items():
        if len(members) >= 2:
            families[key] = members
        else:
            singles.extend(members)

    grouped: List[Tuple[str, List[str]]] = []
    for key in sorted(families):
        grouped.append((key, families[key]))
    for owner in slash_groups:
        grouped.append((f'{owner}/', slash_groups[owner]))
    return grouped, singles


def format_live_model_lines(ids: Sequence[str],
                            *,
                            indent: str = '      ') -> List[str]:
    """One model id per line; family / owner headers for scannable TUI output."""
    if not ids:
        return [f'{indent}(none)']
    grouped, singles = group_model_ids(ids)
    lines: List[str] = []
    for title, members in grouped:
        lines.append(f'{indent}{title}  ({len(members)})')
        for mid in members:
            lines.append(f'{indent}  {mid}')
    for mid in singles:
        lines.append(f'{indent}{mid}')
    return lines
