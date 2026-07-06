# Copyright (c) ModelScope Contributors. All rights reserved.
"""Backward-compatible re-exports for sirchmunk local search.

Implementation lives in :mod:`ms_agent.tools.search.sirchmunk_search`; prefer
importing ``SirchmunkSearch`` from there in new code.
"""

from ms_agent.tools.search.sirchmunk_search import SirchmunkSearch

__all__ = ['SirchmunkSearch']
