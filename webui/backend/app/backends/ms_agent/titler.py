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
    from ms_agent.config.model_settings import resolve_model_settings
    from ms_agent.config.secrets import resolve_secret
    provider = cfg.get("provider")
    if provider and model:
        cfg = resolve_model_settings({"llm": cfg, "providers": providers}, provider, model)
    api_key = resolve_secret(cfg.get("api_key"), home=home()) or os.environ.get("OPENAI_API_KEY") or ""
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


#: Enough room for a one-line JSON title. Deliberately NOT tight: on a model
#: whose thinking cannot be switched off, a tight budget is spent on reasoning
#: and the reply never reaches the title.
_MAX_TOKENS = 600

#: Budget once we know reasoning is unavoidable — it has to cover a full
#: thinking pass plus the title (measured: grok-4.5 spends ~70 reasoning tokens
#: on this prompt before writing anything).
_MAX_TOKENS_THINKING = 2000

#: Phrases an endpoint uses to say thinking cannot be switched off. Shared with
#: the SDK so the two paths recognise the same condition.
def _is_mandatory_thinking(resp: httpx.Response) -> bool:
    from ms_agent.llm.thinking import is_thinking_mandatory

    if resp.status_code != 400:
        return False
    # `is_thinking_mandatory` reads an exception's text; hand it the body.
    return is_thinking_mandatory(RuntimeError(f"400 - {resp.text}"))


def _thinking_off(base_url: str) -> dict:
    """The wire params that switch thinking off on THIS endpoint.

    Every vendor spells it differently — `enable_thinking` on DashScope,
    `thinking: {type: disabled}` on Zhipu and DeepSeek, `reasoning_effort:
    none` on Moonshot, `reasoning: {enabled: false}` on OpenRouter — and the
    titler used to hardcode the Qwen one, which the others silently ignore. So
    reuse the SDK's lowering table, flattening `extra_body` into the raw JSON
    body (that is exactly what the OpenAI client does with it).
    """
    from ms_agent.llm.thinking import plan

    params = plan("off", base_url=base_url)["params"]
    body = {k: v for k, v in params.items() if k != "extra_body"}
    body.update(params.get("extra_body") or {})
    return body


def _without_thinking(payload: dict) -> dict:
    from ms_agent.llm.thinking import THINKING_PARAM_KEYS

    return {k: v for k, v in payload.items() if k not in THINKING_PARAM_KEYS}


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
            "max_tokens": _MAX_TOKENS,
            # Thinking-default gateways (DeepSeek /anthropic) otherwise spend
            # the whole budget on a thinking block for a long first message and
            # return no text block at all — the observed intermittent-title
            # failure. This is the Messages-API spelling; the OpenAI-compatible
            # branch gets its own from the SDK below.
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
            "max_tokens": _MAX_TOKENS,
            **_thinking_off(base_url),
        }
    # One retry after a beat: transient gateway hiccups were observed live.
    # Credentials/config problems returned above never reach this loop, so
    # the retry only spends time when a real request was attempted.
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if _is_mandatory_thinking(resp):
                    # This model cannot stop thinking (OpenRouter answers
                    # "Reasoning is mandatory for this endpoint and cannot be
                    # disabled" for the Grok family). Stop asking, and pay for
                    # the reasoning we now cannot avoid: at the normal budget it
                    # eats the whole allowance and the model answers the user's
                    # question instead of titling it.
                    payload = _without_thinking(payload)
                    payload["max_tokens"] = _MAX_TOKENS_THINKING
                    resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                if protocol == "anthropic":
                    content = _anthropic_text(data)
                else:
                    content = data["choices"][0]["message"]["content"]
        # TypeError belongs here: a 200 response is not a promise of a body in
        # the documented shape. ModelScope intermittently answers 200 with
        # `choices: null` (seen right after a 429), and the subscript then
        # raises out of this coroutine instead of degrading to "no title".
        except (httpx.HTTPError, KeyError, ValueError, IndexError,
                TypeError) as exc:
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
