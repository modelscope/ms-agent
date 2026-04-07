# Copyright (c) ModelScope Contributors. All rights reserved.
"""Knowledge search module based on sirchmunk.

This module provides integration between sirchmunk's AgenticSearch
and the ms_agent framework, enabling intelligent codebase search
capabilities similar to RAG.
"""

from .sirchmunk_search import SirchmunkSearch

__all__ = ['SirchmunkSearch']
