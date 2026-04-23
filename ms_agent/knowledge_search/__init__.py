# Copyright (c) ModelScope Contributors. All rights reserved.
"""Backward-compatible re-exports for sirchmunk local search.

This module provides integration between sirchmunk's AgenticSearch
and the ms_agent framework, enabling intelligent local path search
capabilities.
"""

from ms_agent.tools.search.sirchmunk_search import SirchmunkSearch

__all__ = ['SirchmunkSearch']
