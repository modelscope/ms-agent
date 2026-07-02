"""Write-time security scanner — blocks injection, data exfiltration, and
invisible Unicode tricks before anything is persisted to memory.

Inspired by hermes-agent ``_scan_memory_content``.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from ms_agent.utils.logger import get_logger

logger = get_logger()

# ---------------------------------------------------------------------------
# Pattern groups
# ---------------------------------------------------------------------------

_INVISIBLE_UNICODE = re.compile(
    r"[\u200b-\u200f\u2028-\u202f\u2060-\u2069\ufeff]"
)

_INJECTION_PATTERNS: List[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in (
        r"ignore\s+(all\s+)?previous",
        r"disregard\s+(all\s+)?previous",
        r"you\s+are\s+now",
        r"new\s+instructions?\s*:",
        r"system\s*:\s*you",
        r"forget\s+(everything|all)",
        r"override\s+(system|instructions?)",
        r"act\s+as\s+(a\s+)?different",
        r"pretend\s+you\s+are",
    )
]

_EXFIL_PATTERNS: List[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in (
        r"curl\s+",
        r"wget\s+",
        r"fetch\s*\(",
        r"requests?\.(get|post|put|delete)",
        r"\.env\b",
        r"credentials?\.(json|yaml|yml)",
        r"ssh\s+",
        r"scp\s+",
        r"api[_-]?key\s*[=:]",
        r"secret[_-]?key\s*[=:]",
    )
]


def scan_content(text: str) -> Tuple[bool, str]:
    """Return ``(is_safe, reason)`` — *True* means content is safe to persist."""
    if not text or not text.strip():
        return True, ""

    if _INVISIBLE_UNICODE.search(text):
        reason = "Blocked: invisible Unicode characters detected"
        logger.warning(f"[security] {reason}")
        return False, reason

    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            reason = f"Blocked: prompt injection pattern '{pat.pattern}'"
            logger.warning(f"[security] {reason}")
            return False, reason

    for pat in _EXFIL_PATTERNS:
        if pat.search(text):
            reason = f"Blocked: data exfiltration pattern '{pat.pattern}'"
            logger.warning(f"[security] {reason}")
            return False, reason

    return True, ""


def sanitize_for_injection(text: str) -> str:
    """Strip leaked ``<memory-context>`` tags that may have been persisted."""
    return re.sub(
        r"</?memory-context[^>]*>", "", text, flags=re.IGNORECASE
    ).strip()
