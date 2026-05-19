"""Unified memory configuration.

Core fields are used by all backends.  Backend-specific settings live in
``backend_options[backend_name]`` so that adding a new backend never
changes the top-level schema.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from omegaconf import DictConfig, OmegaConf


@dataclass
class MemoryConfig:
    # --- Core (all backends) ---
    enabled: bool = True
    storage_backend: str = "file"
    base_dir: str = "."

    # Namespace
    user_id: str = "default"
    agent_id: str = "default"
    tenant_id: str = "local"

    # LLM for extraction (reuses agent LLM if None)
    llm_config: Optional[Dict[str, Any]] = None

    # Backend-specific options keyed by backend name
    backend_options: Dict[str, Any] = field(default_factory=dict)

    # --- File backend defaults (kept top-level for backward compat) ---
    memory_path: str = "MEMORY.md"
    facts_path: str = "facts.json"
    char_limit: int = 2200
    retrieval_strategy: str = "full_dump"
    extraction_strategy: str = "tool_based"
    pre_condense_flush: bool = True
    security_scan: bool = True
    raw_archive_threshold: int = 3
    auto_retrieve: bool = True
    auto_retrieve_max_chars: int = 100
    max_search_results: int = 50
    summary_model: Optional[str] = None

    # Session
    context_window_tokens: int = 65536
    max_completion_tokens: int = 4096
    safety_buffer: int = 1024
    max_consolidation_rounds: int = 5
    consolidation_target_ratio: float = 0.5

    # Facts (Phase 2)
    max_facts: int = 100
    confidence_threshold: float = 0.7
    debounce_seconds: float = 30.0
    update_model: Optional[str] = None

    @classmethod
    def from_dict_config(cls, cfg: DictConfig) -> "MemoryConfig":
        """Build from an OmegaConf node (the ``unified_memory`` sub-tree)."""
        if cfg is None:
            return cls()
        raw = OmegaConf.to_container(cfg, resolve=True) if isinstance(
            cfg, DictConfig) else cfg
        if not isinstance(raw, dict):
            return cls()

        flat: Dict[str, Any] = {}

        # Flatten nested YAML into dataclass fields
        storage = raw.get("storage", {}) or {}
        flat["storage_backend"] = storage.get("backend", cls.storage_backend)
        file_cfg = storage.get("file", {}) or {}
        for k in ("memory_path", "facts_path", "char_limit"):
            if k in file_cfg:
                flat[k] = file_cfg[k]

        retrieval = raw.get("retrieval", {}) or {}
        flat["retrieval_strategy"] = retrieval.get(
            "strategy", cls.retrieval_strategy)
        fts_cfg = retrieval.get("fts", {}) or {}
        for k in ("auto_retrieve", "auto_retrieve_max_chars",
                   "max_search_results", "summary_model"):
            if k in fts_cfg:
                flat[k] = fts_cfg[k]

        extraction = raw.get("extraction", {}) or {}
        flat["extraction_strategy"] = extraction.get(
            "strategy", cls.extraction_strategy)

        session = raw.get("session", {}) or {}
        for k in ("context_window_tokens", "max_completion_tokens",
                   "safety_buffer", "max_consolidation_rounds",
                   "consolidation_target_ratio"):
            if k in session:
                flat[k] = session[k]

        facts = raw.get("facts", {}) or {}
        for k in ("max_facts", "confidence_threshold",
                   "debounce_seconds", "update_model"):
            if k in facts:
                flat[k] = facts[k]

        lifecycle = raw.get("lifecycle", {}) or {}
        for k in ("pre_condense_flush", "security_scan",
                   "raw_archive_threshold"):
            if k in lifecycle:
                flat[k] = lifecycle[k]

        ns = raw.get("namespace", {}) or {}
        for k in ("user_id", "agent_id", "tenant_id"):
            if k in ns:
                flat[k] = ns[k]

        for k in ("enabled", "base_dir", "llm_config"):
            if k in raw:
                flat[k] = raw[k]

        # Collect backend-specific sub-trees
        backend_options: Dict[str, Any] = {}
        for bk in ("reme", "mempalace", "mem0", "byterover", "supermemory", "file"):
            if bk in raw:
                backend_options[bk] = raw[bk]
        if backend_options:
            flat["backend_options"] = backend_options

        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in flat.items() if k in known})
