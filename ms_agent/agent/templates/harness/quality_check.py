# Copyright (c) Alibaba, Inc. and its affiliates.
"""LLMQualityChecker -- a lightweight LLM-as-judge.

Generalized from deep_research v2 quality_checker.ModelQualityChecker. Returns a
short failure-reason string, or ``None`` when the content passes.
"""
from __future__ import annotations

import json
from typing import Optional

from omegaconf import OmegaConf

from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger

logger = get_logger()

_DEFAULT_SYSTEM = (
    'You are a strict quality auditor. Decide whether the supplied answer is '
    'acceptable. Flag it ONLY if it clearly contains any of: placeholder or '
    'abbreviation markers in place of real content (e.g. "...for brevity", '
    '"omitted for brevity", "remaining content follows the same pattern"); '
    'fabricated-looking URLs or citations; or a pointer to an external file '
    'instead of the actual content. Stylistic choices, structure and citation '
    'density are OUT OF SCOPE -- do not fail for those.\n'
    'Respond with EXACTLY one JSON object and nothing else: '
    '{"pass": true} or {"pass": false, "reason": "<= two sentences"}.')


class LLMQualityChecker:
    """Call a lightweight model to audit a piece of content.

    The client is built lazily and is independent of the agent's own LLM, so a
    cheaper/faster judge model can be used.
    """

    _MAX_CHARS = 80000

    def __init__(self,
                 model: str,
                 api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 system_prompt: Optional[str] = None):
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._system = system_prompt or _DEFAULT_SYSTEM
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return
        from ms_agent.llm.openai_llm import OpenAI as OpenAILLM
        self._client = OpenAILLM(
            OmegaConf.create({
                'llm': {
                    'model': self._model,
                    'openai_api_key': self._api_key,
                    'openai_base_url': self._base_url,
                },
                'generation_config': {},
            }))

    def check(self, content: str) -> Optional[str]:
        if not content or not content.strip():
            return None
        try:
            self._ensure_client()
            text = content[:self._MAX_CHARS]
            resp = self._client.generate(messages=[
                Message(role='system', content=self._system),
                Message(
                    role='user',
                    content='---BEGIN---\n' + text + '\n---END---'),
            ])
            raw = (resp.content or '').strip()
            logger.info('LLMQualityChecker (%s): %s', self._model, raw[:200])
            verdict = json.loads(raw)
            if verdict.get('pass', True):
                return None
            return verdict.get('reason', 'quality_check_failed')
        except json.JSONDecodeError:
            logger.warning('LLMQualityChecker: non-JSON response, treating as pass')
            return None
        except Exception as exc:  # pragma: no cover - network/runtime
            logger.warning('LLMQualityChecker: model call failed: %s', exc)
            return None
