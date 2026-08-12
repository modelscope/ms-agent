"""Agent-side session titling + topic classification.

On a session's first user message the chat stream asks the LLM to summarize the
message into a short title and pick one topic category (see ``CATEGORIES``).
Both are cheap (one small completion) and best-effort: any failure returns None
so the caller keeps the cheap first-line fallback title and an empty category.

Credentials/model come from the SDK's seeded ``<home>/settings.json`` ``llm``
block, falling back to the exported OPENAI_* env. Uses the OpenAI-compatible
``/chat/completions`` endpoint directly (httpx) — no agent runtime needed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path

import httpx

from app.backends.ms_agent.common import home

logger = logging.getLogger("app.ms_agent.titler")

# Fixed topic taxonomy. Kept in sync with the frontend category→icon map
# (ProjectOverviewView). "general" is the fallback for anything uncategorized.
CATEGORIES: tuple[str, ...] = (
    "coding",
    "writing",
    "research",
    "planning",
    "data",
    "creative",
    "media",
    "general",
)

_SYSTEM = (
    "You name a chat and classify its topic from the user's first message. "
    'Reply with ONLY a compact JSON object: {"title": "...", "category": "..."}.\n'
    "- title: a short, specific title in the SAME language as the message; no "
    "quotes, no ending punctuation; at most ~6 words (or ~16 Chinese characters).\n"
    "- category: exactly one of:\n"
    "  coding (programming, debugging, code), writing (writing or editing text/docs), "
    "research (searching or browsing the web for information), planning (plans, todos, "
    "scheduling, multi-step tasks), data (data analysis, spreadsheets, charts), "
    "creative (brainstorming, ideas, design), media (images, audio, video, or file "
    "handling), general (casual chat, Q&A, anything else).\n"
    "No prose, no code fences."
)


def _llm_config() -> tuple[str, str, str, str]:
    """(model, api_key, base_url, protocol) from settings.json llm — plus the
    active provider's ``protocol`` override — then OPENAI_* env.

    ``protocol == "anthropic"`` means the active provider speaks the Anthropic
    Messages API (e.g. DeepSeek's ``/anthropic`` gateway): posting to
    ``/chat/completions`` there 404s, which would silently disable titling."""
    cfg: dict = {}
    providers: dict = {}
    try:
        data = json.loads((Path(home()) / "settings.json").read_text(encoding="utf-8"))
        if isinstance(data.get("llm"), dict):
            cfg = data["llm"]
        if isinstance(data.get("providers"), dict):
            providers = data["providers"]
    except (OSError, ValueError):
        cfg = {}
    model = cfg.get("model") or os.environ.get("MS_AGENT_LLM_MODEL") or ""
    api_key = cfg.get("api_key") or os.environ.get("OPENAI_API_KEY") or ""
    base_url = cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL") or ""
    entry = providers.get(str(cfg.get("provider") or ""))
    protocol = str(entry.get("protocol") or "") if isinstance(entry, dict) else ""
    return str(model), str(api_key), str(base_url), protocol.lower()


def _parse(content: str) -> tuple[str, str] | None:
    """Extract (title, category) from the model's JSON reply, leniently."""
    if not content:
        return None
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    title = str(obj.get("title") or "").strip().strip("\"'").strip()
    title = title.splitlines()[0][:60] if title else ""
    category = str(obj.get("category") or "").strip().lower()
    if category not in CATEGORIES:
        category = "general"
    if not title:
        return None
    return title, category


def _anthropic_text(data: dict) -> str:
    """The first text block of an Anthropic Messages response (a thinking-mode
    gateway may put a thinking block before it)."""
    for block in data.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            return str(block.get("text") or "")
    return ""


async def generate_title_and_category(text: str) -> tuple[str, str] | None:
    """Summarize the first user message into (title, category), or None on any
    failure (missing creds/model, network error, unparseable reply). Speaks the
    active provider's wire protocol: Anthropic Messages when its ``protocol``
    override says so, OpenAI-compatible chat/completions otherwise."""
    text = (text or "").strip()
    if not text:
        return None
    model, api_key, base_url, protocol = _llm_config()
    if not (model and api_key and base_url):
        return None
    if protocol == "anthropic":
        url = base_url.rstrip("/") + "/v1/messages"
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        payload = {
            "model": model,
            "system": _SYSTEM,
            "messages": [{"role": "user", "content": text[:2000]}],
            "temperature": 0.2,
            "max_tokens": 600,
            # Thinking-default gateways (DeepSeek /anthropic) otherwise spend
            # the whole budget on a thinking block for a long first message and
            # return no text block at all — the observed intermittent-title
            # failure. Explicitly off; standard Anthropic accepts this too.
            "thinking": {"type": "disabled"},
        }
    else:
        url = base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": text[:2000]},
            ],
            "temperature": 0.2,
            "max_tokens": 160,
            # Qwen thinking models require thinking off for non-streaming calls;
            # OpenAI-compatible servers ignore the extra field.
            "enable_thinking": False,
        }
    # One retry after a beat: transient gateway hiccups were observed live.
    # Credentials/config problems returned above never reach this loop, so
    # the retry only spends time when a real request was attempted.
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                if protocol == "anthropic":
                    content = _anthropic_text(data)
                else:
                    content = data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
            logger.warning("titler request failed (attempt %d, %s %s): %s",
                           attempt, protocol, model, exc)
            content = ""
        if content:
            parsed = _parse(str(content))
            if parsed is not None:
                return parsed
            logger.warning("titler reply unparseable (attempt %d, %s %s): %r",
                           attempt, protocol, model, str(content)[:120])
        if attempt == 1:
            await asyncio.sleep(2)
    return None
