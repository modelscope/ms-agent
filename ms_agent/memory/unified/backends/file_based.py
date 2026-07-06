"""FileBasedBackend — the built-in file-first memory backend.

Composes internal modules (FileMemoryStorage, FactsStorage, extractors,
retrievers) behind the single ``MemoryBackend`` interface.  Those modules
are private implementation details — the Orchestrator never sees them.

Registered as ``"file"`` in the backend_registry.
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict, List, Optional

from ms_agent.utils.logger import get_logger

from ..config import MemoryConfig
from ..protocols import BaseMemoryBackend, MemoryEntry
from ..registry import backend_registry
from ..security import sanitize_for_injection, scan_content

# Private internal modules (not public API)
from ..storage.file_storage import FileMemoryStorage
from ..storage.facts_storage import FactsStorage
from ..extraction.tool_based import ToolBasedExtractor
from ..extraction.llm_merge import LLMMergeExtractor
from ..retrieval.full_dump import FullDumpRetriever
from ..retrieval.fts import FTSRetriever
from ..update_queue import MemoryUpdateQueue

logger = get_logger()

MEMORY_TOOL_DEF = {
    "tool_name": "memory",
    "description": (
        "管理长期记忆 (MEMORY.md)。用于跨会话记住用户偏好、项目上下文、"
        "关键决策和纠错记录。支持 add（添加）、replace（替换）、remove（删除）操作。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "replace", "remove"],
                "description": "操作类型：add=添加新条目，replace=替换已有条目，remove=删除条目",
            },
            "content": {
                "type": "string",
                "description": "要添加的内容 (add)，或要匹配的旧内容 (replace/remove)",
            },
            "new_content": {
                "type": "string",
                "description": "替换后的新内容（仅 replace 时需要）",
            },
        },
        "required": ["action", "content"],
    },
}

MEMORY_READ_TOOL_DEF = {
    "tool_name": "memory_read",
    "description": "读取当前长期记忆 (MEMORY.md) 的完整内容",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


class FileBasedBackend(BaseMemoryBackend):
    """Built-in file-first memory backend.

    Internally composes FileMemoryStorage, FactsStorage, ToolBasedExtractor /
    LLMMergeExtractor, FullDumpRetriever / FTSRetriever.  All hidden behind
    the MemoryBackend interface.
    """

    def __init__(self, config: MemoryConfig) -> None:
        self._config = config
        self._llm: Any = None

        self._file_storage = FileMemoryStorage(config)
        self._facts_storage = FactsStorage(config)
        self._retriever = self._build_retriever()
        self._extractor = self._build_extractor()
        self._update_queue: Optional[MemoryUpdateQueue] = None
        # Built lazily and reused across inject() calls — its constructor opens
        # a SQLite connection and runs schema init, which must not happen on
        # every agent-loop iteration.
        self._fts: Optional[FTSRetriever] = None

        self._prompt_snapshot: Optional[str] = None
        self._snapshot_dirty = True

    # -- Lifecycle ----------------------------------------------------

    async def start(self, **kwargs: Any) -> None:
        if "llm" in kwargs:
            self.set_llm(kwargs["llm"])

    async def close(self) -> None:
        if self._fts is not None:
            self._fts.close()
            self._fts = None

    # -- inject (core read path) --------------------------------------

    async def inject(
        self, messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        snapshot = self._get_or_build_snapshot()
        if snapshot:
            messages = self._inject_snapshot(messages, snapshot)

        if self._config.retrieval_strategy in ("fts", "hybrid"):
            messages = await self._inject_fts_context(messages)

        return messages

    # -- on_messages (post-step persistence) ---------------------------

    async def on_messages(
        self, messages: List[Dict[str, Any]], **kwargs: Any,
    ) -> None:
        if self._config.retrieval_strategy not in ("fts", "hybrid"):
            return
        if self._update_queue is None:
            return
        thread_id = kwargs.get("run_id") or "default"
        has_correction = _detect_correction(messages)
        await self._update_queue.add(
            thread_id, messages, correction=has_correction)

    # -- on_pre_compress (flush before compression) --------------------

    async def on_pre_compress(
        self, messages: List[Dict[str, Any]],
    ) -> None:
        if not self._config.pre_condense_flush:
            return
        if not self._llm:
            return

        logger.info("[file_backend] Pre-condense flush started")
        current = self._file_storage.get_content()
        entries = await self._extractor.extract(
            messages, current_memory=current, is_flush=True)
        if entries and entries[0].content.strip():
            self._file_storage.full_replace(entries[0].content)
            self._snapshot_dirty = True
            logger.info("[file_backend] Flush completed -> MEMORY.md updated")

        if self._update_queue:
            await self._update_queue.add_nowait("flush", messages)

    # -- consolidate ---------------------------------------------------

    async def consolidate(
        self, messages: List[Dict[str, Any]],
        target_remove_count: int = 0,
    ) -> List[Dict[str, Any]]:
        if not self._llm:
            return messages

        current_memory = self._file_storage.get_content()
        boundary = min(target_remove_count, len(messages))
        window = messages[:boundary]

        if not window:
            return messages

        failures = 0
        for attempt in range(self._config.max_consolidation_rounds):
            try:
                entries = await self._extractor.extract(
                    window, current_memory=current_memory)
                if entries and entries[0].content.strip():
                    self._file_storage.full_replace(entries[0].content)
                    current_memory = entries[0].content
                    logger.info(
                        f"[file_backend] Consolidation succeeded "
                        f"(attempt {attempt + 1})")
                    break
                else:
                    failures += 1
            except Exception as e:
                logger.warning(
                    f"[file_backend] Consolidation attempt {attempt + 1} "
                    f"failed: {e}")
                failures += 1

            if failures >= self._config.raw_archive_threshold:
                raw = "\n".join(
                    f"[{m.get('role', '?')}] {m.get('content', '')}"
                    for m in window if m.get("content"))
                self._file_storage.append_archive(raw)
                logger.warning(
                    "[file_backend] Consolidation failed -> raw archived")
                break

        trimmed = [messages[0]]  # keep system message
        trimmed.extend(
            messages[boundary + 1:] if boundary < len(messages) else [])
        self._snapshot_dirty = True
        self.invalidate()
        return trimmed if len(trimmed) > 1 else messages

    # -- Tools --------------------------------------------------------

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [MEMORY_TOOL_DEF, MEMORY_READ_TOOL_DEF]

    async def handle_tool_call(
        self, tool_name: str, arguments: Dict[str, Any],
    ) -> str:
        if tool_name == "memory_read":
            content = self._file_storage.get_content()
            return content if content.strip() else "(MEMORY.md is empty)"

        if tool_name != "memory":
            return json.dumps({"error": f"unknown tool: {tool_name}"})

        action = arguments.get("action", "")
        content = arguments.get("content", "")
        new_content = arguments.get("new_content")

        if action == "add":
            if self._config.security_scan:
                safe, reason = scan_content(content)
                if not safe:
                    return f"添加失败（安全检查）: {reason}"
            ok = self._file_storage._add_entry(content)
            result = "已记住" if ok else "添加失败（可能超出字符预算）"
        elif action == "replace":
            if not new_content:
                result = "replace 操作需要 new_content 参数"
            else:
                ok = self._file_storage.replace_entry(content, new_content)
                result = "已更新" if ok else "更新失败（未找到旧内容或超出字符预算）"
        elif action == "remove":
            ok = self._file_storage.remove_entry(content)
            result = "已删除" if ok else "删除失败"
        else:
            result = f"未知操作: {action}"

        self._snapshot_dirty = True
        return result

    # -- Search -------------------------------------------------------

    async def search(
        self, query: str, limit: int = 10,
    ) -> List[MemoryEntry]:
        return await self._retriever.search(query, limit)

    # -- Cache --------------------------------------------------------

    def invalidate(self) -> None:
        self._prompt_snapshot = None
        self._snapshot_dirty = True
        self._file_storage.invalidate_cache()

    # -- LLM injection (backend-specific) ------------------------------

    def set_llm(self, llm: Any) -> None:
        self._llm = llm
        if isinstance(self._extractor, (ToolBasedExtractor, LLMMergeExtractor)):
            self._extractor.set_llm(llm)

    def init_update_queue(self) -> None:
        if self._config.retrieval_strategy in ("fts", "hybrid"):
            merge_extractor = LLMMergeExtractor(self._config, self._llm)
            self._update_queue = MemoryUpdateQueue(
                self._config, merge_extractor, self._facts_storage)

    # -- Internal helpers ----------------------------------------------

    def _build_retriever(self) -> FullDumpRetriever:
        return FullDumpRetriever(self._config, self._file_storage)

    def _build_extractor(self) -> ToolBasedExtractor | LLMMergeExtractor:
        if self._config.extraction_strategy == "llm_merge":
            return LLMMergeExtractor(self._config, self._llm)
        return ToolBasedExtractor(self._config, self._llm)

    def _get_or_build_snapshot(self) -> str:
        if self._prompt_snapshot is not None and not self._snapshot_dirty:
            return self._prompt_snapshot

        parts: List[str] = []
        md_content = self._file_storage.get_content().strip()
        if md_content:
            parts.append(f"## 长期记忆\n\n{md_content}")

        if self._config.retrieval_strategy in ("fts", "hybrid"):
            facts_text = self._facts_storage.format_for_prompt(max_chars=800)
            if facts_text:
                parts.append(f"## 已知事实\n\n{facts_text}")

        self._prompt_snapshot = "\n\n".join(parts) if parts else ""
        self._snapshot_dirty = False
        return self._prompt_snapshot

    def _inject_snapshot(
        self, messages: List[Dict[str, Any]], snapshot: str,
    ) -> List[Dict[str, Any]]:
        messages = list(messages)
        if not messages or messages[0].get("role") != "system":
            return messages

        sys_msg = {**messages[0]}
        block = f"\n\n<long-term-memory>\n{snapshot}\n</long-term-memory>"
        if "<long-term-memory>" not in (sys_msg.get("content") or ""):
            sys_msg["content"] = (sys_msg.get("content") or "") + block
        messages[0] = sys_msg
        return messages

    async def _inject_fts_context(
        self, messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not self._config.auto_retrieve:
            return messages

        last_user_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                last_user_idx = i
                break
        if last_user_idx < 0:
            return messages

        query = (messages[last_user_idx].get("content") or "")
        if isinstance(query, list):
            query = " ".join(
                item.get("text", "") for item in query
                if isinstance(item, dict))
        query = query[:self._config.auto_retrieve_max_chars].strip()
        if not query:
            return messages

        try:
            if self._fts is None:
                self._fts = FTSRetriever(self._config)
            results = await self._fts.search(query, limit=5)
        except Exception:
            return messages

        if not results:
            return messages

        lines = [
            f"[{r.metadata.get('role', '?')}] {r.content[:200]}"
            for r in results[:5]
        ]
        context_text = "\n".join(lines)

        messages = list(messages)
        user_copy = {**messages[last_user_idx]}
        user_copy["content"] = (
            f"{user_copy['content']}\n\n"
            f"<memory-context>\n"
            f"[System note: 以下是从历史会话中检索到的相关上下文]\n"
            f"{context_text}\n"
            f"</memory-context>"
        )
        messages[last_user_idx] = user_copy
        return messages


def _detect_correction(messages: List[Dict[str, Any]]) -> bool:
    patterns = [
        "不对", "不是", "错了", "纠正", "应该是", "修正",
        "no,", "wrong", "incorrect", "actually", "correction",
    ]
    for m in messages[-3:]:
        content = (m.get("content") or "").lower()
        if any(p in content for p in patterns):
            return True
    return False


# -- Self-register ----------------------------------------------------

backend_registry.register("file", FileBasedBackend)
