from __future__ import annotations

# Copyright (c) ModelScope Contributors. All rights reserved.
import asyncio
import importlib
import inspect
import json
import os.path
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from omegaconf import DictConfig, OmegaConf
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, Union

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback, callbacks_mapping
from ms_agent.knowledge_search import SirchmunkSearch
from ms_agent.llm.llm import LLM
from ms_agent.llm.utils import Message, ToolResult
from ms_agent.memory import Memory, get_memory_meta_safe, memory_mapping
from ms_agent.memory.memory_manager import SharedMemoryManager
from ms_agent.personalization.injector import PersonalizationInjector
from ms_agent.personalization.profile import ProfileManager
from ms_agent.personalization.types import PersonalizationConfig
from ms_agent.rag.base import RAG
from ms_agent.rag.utils import rag_mapping
from ms_agent.session import ContextAssembler, SessionLog
from ms_agent.session.strategies import SummaryCompactor, ToolOutputPruner
from ms_agent.skill.catalog import SkillCatalog
from ms_agent.skill.prompt_injector import SkillPromptInjector
from ms_agent.skill.runtime import SkillRuntime
from ms_agent.skill.search import SkillSearchEngine
from ms_agent.skill.skill_tools import SkillToolSet
from ms_agent.tools import ToolManager
from ms_agent.ui.events import (ContentDelta, ContentEnd, ContextCompacted,
                                ErrorRaised, PlanEntry, PlanUpdated,
                                ReasoningDelta, ReasoningEnded,
                                ReasoningStarted, ToolCallCompleted,
                                ToolCallStarted, TurnCompleted, UsageInfo)
from ms_agent.utils import (async_retry, is_retryable_error, read_history,
                            save_history)
from ms_agent.utils.constants import DEFAULT_TAG, DEFAULT_USER
from ms_agent.utils.logger import get_logger
from ms_agent.utils.snapshot import take_snapshot
from ms_agent.utils.task_manager import TaskManager
from ..config.config import Config, ConfigLifecycleHandler
from .base import Agent

logger = get_logger()

_MISSING_ENABLE_SNAPSHOTS = object()

# Neutral, model-facing placeholder for an interrupted round that produced no
# visible content. UIs should render rows flagged ``interrupted`` from their
# metadata (not this literal), so the placeholder never needs localization.
INTERRUPTED_PLACEHOLDER = '[interrupted]'
_INTERRUPTED_TOOL_RESULT = '[Interrupted: tool execution was cancelled]'


def build_partial_round_records(
        rows: List[Dict[str, Any]],
        marker: str = 'interrupted') -> List[Dict[str, Any]]:
    """Turn an unfinished round's in-memory rows into protocol-valid log records.

    ``marker`` is the boolean key stamped on every produced record, naming *why*
    the round ended early: ``interrupted`` (user Stop / cancellation) or
    ``errored`` (the turn raised). UIs badge these differently, so an API
    failure must not be sealed as an interruption.

    ``rows`` are the ``_msg_to_dict`` serializations of ``messages[pre_step_len:]``
    at cancellation time. Rules (each keeps replay valid on BOTH transports):

    - assistant ``tool_calls`` are kept only when their ``arguments`` parse as
      JSON (an interrupted openai-compat stream can leave truncated argument
      deltas) and they carry an id; every kept call that has no real result row
      in the segment gets a synthesized ``role:"tool"`` error result — Anthropic
      rejects a replayed ``tool_use`` without a ``tool_result`` in the next user
      message, and OpenAI equally requires a tool row per call id.
    - partial ``reasoning_content`` without a ``reasoning_signature`` moves to
      ``interrupted_reasoning`` (display-only): Anthropic thinking replay
      rejects a thinking block whose signature is missing, and the signature is
      only assigned at message_stop — which an interrupt never reached.
    - an empty segment (cancelled before the first chunk) or an assistant row
      with no content and no kept calls gets the neutral placeholder content so
      the turn reads as closed (an empty assistant block would be rejected on
      Anthropic replay, and a dangling user row would be re-answered on resume).
    - every row is flagged ``<marker>: true`` — an extra key that survives in
      the log for UI replay but is filtered out of the LLM context rebuild.
    """
    present_results = {
        row.get('tool_call_id')
        for row in rows
        if row.get('role') == 'tool' and row.get('tool_call_id')
    }
    records: List[Dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        rec[marker] = True
        if rec.get('role') != 'assistant':
            records.append(rec)
            continue
        kept_calls = []
        for tc in rec.get('tool_calls') or []:
            if not isinstance(tc, dict) or not tc.get('id'):
                continue
            args = tc.get('arguments')
            if isinstance(args, dict):
                kept_calls.append(tc)
                continue
            try:
                json.loads(args or '')
            except (TypeError, ValueError):
                continue
            kept_calls.append(tc)
        if kept_calls:
            rec['tool_calls'] = kept_calls
        else:
            rec.pop('tool_calls', None)
        if rec.get('reasoning_content') and not rec.get('reasoning_signature'):
            rec['interrupted_reasoning'] = rec.pop('reasoning_content')
        if not rec.get('content') and not kept_calls:
            # Neutral filler so the round reads as closed on replay AND stays a
            # protocol-valid assistant message on resume (empty content is
            # rejected on Anthropic; a dangling user row would be re-answered).
            # ``content_placeholder`` lets UIs identify this as synthetic filler
            # by a structured flag rather than string-matching the literal.
            rec['content'] = INTERRUPTED_PLACEHOLDER
            rec['content_placeholder'] = True
        records.append(rec)
        for tc in kept_calls:
            if tc.get('id') in present_results:
                continue
            records.append({
                'role': 'tool',
                'content': _INTERRUPTED_TOOL_RESULT,
                'tool_call_id': tc.get('id'),
                'name': tc.get('tool_name', ''),
                'is_error': True,
                marker: True,
            })
    if not records:
        records.append({
            'role': 'assistant',
            'content': INTERRUPTED_PLACEHOLDER,
            'content_placeholder': True,
            marker: True,
        })
    return records


class LLMAgent(Agent):
    """
    An agent designed to run LLM-based tasks with support for tools, memory,
    planning, callbacks, and skill integration.

    This class provides a full lifecycle for running an LLM agent, including:
    - Prompt preparation
    - Chat history management
    - External tool calling
    - Memory retrieval and updating
    - Stream or non-stream response generation
    - Callback hooks at various stages of execution
    - Skill system: skill discovery (skills_list), viewing (skill_view),
      and management (skill_manage) as standard tools

    Args:
        config (DictConfig): Pre-loaded configuration object.
        tag (str): The name of this class defined by the user.
        trust_remote_code (bool): Whether to trust remote code if any.
        **kwargs: Additional keyword arguments passed to the parent Agent constructor.

    Skills Configuration (in config.skills):
        path: Path(s) to skill directories or ModelScope repo IDs.
        sources: Structured source list (type, path, repo_id, url, etc.).
        auto_discover: Auto-scan CWD/skills/ directory.
        enable_manage: Enable skill_manage tool for runtime CRUD.
        whitelist: Skill ID whitelist (null=all, []=none, [ids]=specific).
        disabled: List of disabled skill IDs.
    """

    AGENT_NAME = 'LLMAgent'

    DEFAULT_SYSTEM = 'You are a helpful assistant.'

    DEFAULT_MAX_CHAT_ROUND = 20

    @staticmethod
    def _coerce_enable_snapshots_value(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in ('1', 'true', 'yes', 'on')
        return bool(value)

    @staticmethod
    def resolve_enable_snapshots(config: Any) -> bool:
        """Resolve whether to take automatic pre-task snapshots.

        Tool-spawned sub-agents (``ms_agent_subagent`` in config) default to
        ``False``; all other agents default to ``True``. An explicit
        ``enable_snapshots`` in config always wins (including string forms
        like ``\"false\"`` coerced to boolean).
        """
        if OmegaConf.is_config(config):
            raw = OmegaConf.select(
                config, 'enable_snapshots', default=_MISSING_ENABLE_SNAPSHOTS)
            if raw is not _MISSING_ENABLE_SNAPSHOTS and raw is not None:
                return LLMAgent._coerce_enable_snapshots_value(raw)
            sub = bool(
                OmegaConf.select(config, 'ms_agent_subagent', default=False))
            return not sub
        if isinstance(config, dict):
            if 'enable_snapshots' in config and config[
                    'enable_snapshots'] is not None:
                return LLMAgent._coerce_enable_snapshots_value(
                    config['enable_snapshots'])
            return not bool(config.get('ms_agent_subagent'))
        return True

    TOTAL_PROMPT_TOKENS = 0
    TOTAL_COMPLETION_TOKENS = 0
    TOTAL_CACHED_TOKENS = 0
    TOTAL_CACHE_CREATION_INPUT_TOKENS = 0
    TOTAL_REASONING_TOKENS = 0
    LAST_PROMPT_TOKENS = 0
    LAST_COMPLETION_TOKENS = 0
    LAST_REASONING_TOKENS = 0
    TOKEN_LOCK = asyncio.Lock()

    def __init__(
        self,
        config: DictConfig = DictConfig({}),
        tag: str = DEFAULT_TAG,
        trust_remote_code: bool = False,
        **kwargs,
    ):
        if not hasattr(config, 'llm'):
            default_yaml = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 'agent.yaml')
            llm_config = Config.from_task(default_yaml)
            config = OmegaConf.merge(llm_config, config)
        super().__init__(config, tag, trust_remote_code)
        self.callbacks: List[Callback] = []
        self.tool_manager: Optional[ToolManager] = None
        self.task_manager: Optional[TaskManager] = None
        self.memory_tools: List[Memory] = []
        self.rag: Optional[RAG] = None
        self.knowledge_search: Optional[SirchmunkSearch] = None
        self.llm: Optional[LLM] = None
        self.runtime: Optional[Runtime] = None
        self.session_log: Optional[SessionLog] = None
        self.context_assembler: Optional[ContextAssembler] = None
        self.max_chat_round: int = 0
        self.load_cache = kwargs.get('load_cache', False)
        self.config.load_cache = self.load_cache
        self.mcp_server_file = kwargs.get('mcp_server_file', None)
        self.mcp_config: Dict[str, Any] = self.parse_mcp_servers(
            kwargs.get('mcp_config', {}))
        self.mcp_client = kwargs.get('mcp_client', None)
        self.mcp_runtime = kwargs.get('mcp_runtime', None)
        self.config_handler = self.register_config_handler()

        # Skill system (initialized in prepare_skills)
        self._skill_catalog = None
        self._skill_injector = None
        self._rollback_messages: Optional[List[Message]] = None

        # Skill runtime (initialized in prepare_skills)
        self._skill_runtime: Optional[SkillRuntime] = None
        self._plugin_runtime = None

        # Slash-command router for interactive input (lazily built)
        self._command_router = None

        # Whether this run is an interactive session (resolved in run_loop).
        # Gates both the initial >>> prompt and the mid-turn InputCallback.
        self._interactive = False

        # Optional injected PermissionHandler (TUI/WebUI/Server). When None,
        # _select_permission_handler() picks by mode + interactivity.
        self._permission_handler = kwargs.get('permission_handler', None)

        # Structured event sink — the UI-agnostic output seam (ms_agent.ui).
        # When set, the agent emits semantic AgentEvents (content / reasoning /
        # tool / ...) that a TUI renders and a WebUI backend forwards. When
        # None, output goes to stdout (current CLI behavior, byte-identical).
        # This is the seam that validates the WebUI contract.
        self._event_sink = kwargs.get('event_sink', None)

        # Async input source (awaitable read_prompt). When set, the interactive
        # loop reads the next prompt through it (TUI now, WebUI queue later),
        # so the read never blocks the event loop or fights the renderer for
        # the terminal — the enabling seam for the native (route-A) lifecycle.
        # When None, the legacy sync console_io / input() path is used.
        self._input_source = kwargs.get('input_source', None)

        # Personalization (lazy-loaded in _build_personalization_section)
        self._profile_manager = ProfileManager()

    async def prepare_skills(self):
        """Initialize the skill system from config.skills.

        Sets up SkillCatalog, SkillPromptInjector, and registers
        SkillToolSet into ToolManager.
        """
        if not hasattr(self.config, 'skills') or not self.config.skills:
            return

        skills_config = self.config.skills
        self._skill_catalog = SkillCatalog(config=skills_config)
        self._skill_catalog.load_from_config(skills_config)

        prompt_injection = getattr(skills_config, 'prompt_injection', 'all')
        update_notice = bool(getattr(skills_config, 'update_notice', False))
        self._skill_injector = SkillPromptInjector(
            self._skill_catalog,
            prompt_injection=prompt_injection,
            update_notice=update_notice)

        search_cfg = getattr(skills_config, 'search', None)
        search_backend = getattr(search_cfg, 'backend',
                                 'bm25') if search_cfg else 'bm25'
        search_kwargs = {}
        if search_cfg:
            if hasattr(search_cfg, 'embed_model'):
                search_kwargs['embed_model'] = search_cfg.embed_model
            if hasattr(search_cfg, 'fusion'):
                search_kwargs['fusion'] = search_cfg.fusion
        search_engine = SkillSearchEngine(
            self._skill_catalog, backend=search_backend, **search_kwargs)

        enable_manage = getattr(skills_config, 'enable_manage', False)
        skill_toolset = SkillToolSet(
            self.config,
            self._skill_catalog,
            enable_manage=enable_manage,
            tool_manager=self.tool_manager,
            search_engine=search_engine)
        await skill_toolset.connect()
        self.tool_manager.register_tool(skill_toolset)

        # Index just this newly added tool into the live registry; a full
        # reindex_tool() would re-touch already-indexed (and runtime-owned MCP)
        # tools.
        await self.tool_manager.index_extra_tool(skill_toolset)

        self._check_skill_tool_dependencies()

        self._skill_runtime = SkillRuntime(
            catalog=self._skill_catalog,
            injector=self._skill_injector,
        )
        # Notice mode: the host announces skill changes inside the
        # conversation, so the system prompt stays byte-stable per session
        # (tail-only updates; prefix cache never breaks).
        self._skill_runtime.head_refresh_enabled = not update_notice
        self._skill_runtime.set_system_content_builder(
            self._build_system_content)
        if getattr(self, '_plugin_runtime', None) is not None:
            self._plugin_runtime.skill_runtime = self._skill_runtime
            self._plugin_runtime._sync_skill_runtime(self.config)

        # Wire /skill-name slash commands. Without this the SkillCommandBridge
        # is never registered and `/skill-id args` falls through to the model as
        # raw text (only "works" when the skill happens to be in the system
        # prompt). Registering it makes `/skill-id` dispatch to SUBMIT_PROMPT,
        # including *disabled* skills (per meeting decision). The bridge is the
        # only router interceptor (plugins use register()), so reset first to
        # rebind to the current catalog across restarts without duplicates.
        from ms_agent.command.skill_bridge import SkillCommandBridge
        router = self._get_command_router()
        router._interceptors.clear()
        SkillCommandBridge(self._skill_catalog).register(router)

    def _build_system_content(self) -> str:
        """Build the full system prompt content.

        Assembly order: base prompt → personalization → skill injection.
        Used by create_messages() and SkillRuntime.maybe_refresh_system_prompt().
        """
        content = self.system or LLMAgent.DEFAULT_SYSTEM

        personalization = self._build_personalization_section()
        if personalization:
            content += '\n\n' + personalization

        if self._skill_injector:
            skill_section = self._skill_injector.build_skill_prompt_section()
            if skill_section:
                content += '\n\n' + skill_section

        return content

    def _check_skill_tool_dependencies(self):
        """Warn if skills are enabled but essential tools are missing."""
        if (not self._skill_catalog
                or not self._skill_catalog.get_enabled_skills()):
            return

        has_tools = hasattr(self.config, 'tools') and self.config.tools
        warnings = []

        if not has_tools or not hasattr(self.config.tools, 'file_system'):
            warnings.append('file_system (read_file, write_file) - needed for '
                            'reading skill scripts and writing outputs')

        if not has_tools or not hasattr(self.config.tools, 'code_executor'):
            warnings.append(
                'code_executor (python, shell execution) - needed for '
                'running skill scripts')

        if warnings:
            logger.warning(
                'Skills are configured but the following recommended tools '
                'are not enabled. Skills that depend on these tools may not '
                'work correctly:\n' + '\n'.join(f'  - {w}' for w in warnings)
                + "\nAdd them to your agent config under 'tools:' to enable.")

    def _clear_read_caches(self) -> None:
        """Clear FileSystemTool read dedup caches after disk state changes."""
        if self.tool_manager is None:
            return
        for tool in self.tool_manager.extra_tools:
            if hasattr(tool, '_read_cache'):
                tool._read_cache.clear()

    def consume_rollback_messages(self) -> Optional[List[Message]]:
        """Return and clear pending in-memory history after rollback."""
        messages = self._rollback_messages
        self._rollback_messages = None
        return messages

    def _apply_pending_rollback(self,
                                messages: List[Message]) -> List[Message]:
        pending = self.consume_rollback_messages()
        return pending if pending is not None else messages

    def rollback(self,
                 commit_hash: str) -> tuple[bool, Optional[List[Message]]]:
        """Restore output_dir to snapshot and truncate message history.

        Returns:
            (success, truncated_messages). On success, truncated_messages is
            the history that should drive the active run_loop; the next step
            will pick it up automatically via _apply_pending_rollback().
        """
        from ms_agent.utils.snapshot import restore_snapshot
        ok, message_count = restore_snapshot(self.output_dir, commit_hash)
        if not ok:
            return False, None
        # Truncate saved history to the message count at snapshot time
        _, saved_messages = read_history(self.output_dir, self.tag)
        if saved_messages and message_count < len(saved_messages):
            save_history(self.output_dir, self.tag, self.config,
                         saved_messages[:message_count])
        self._clear_read_caches()
        _, truncated = read_history(self.output_dir, self.tag)
        self._rollback_messages = truncated
        return True, truncated

    def register_callback(self, callback: Callback):
        """
        Register a new callback to be triggered during the agent's lifecycle.

        Args:
            callback (Callback): The callback instance to add.
        """
        self.callbacks.append(callback)

    def parse_mcp_servers(self, mcp_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse MCP server configurations from a file or dictionary.

        Args:
            mcp_config (Dict[str, Any]): Raw MCP configuration data.

        Returns:
            Dict[str, Any]: Merged configuration including file-based overrides.
        """
        mcp_config = mcp_config or {}
        if self.mcp_server_file is not None and os.path.isfile(
                self.mcp_server_file):
            with open(self.mcp_server_file, 'r') as f:
                config = json.load(f)
                config.update(mcp_config)
                return config
        return mcp_config

    @contextmanager
    def config_context(self):
        if self.config_handler is not None:
            self.config = self.config_handler.task_begin(self.config, self.tag)
        yield
        if self.config_handler is not None:
            self.config = self.config_handler.task_end(self.config, self.tag)

    def register_config_handler(self) -> Optional[ConfigLifecycleHandler]:
        """
        Registers a `ConfigLifecycleHandler` based on the configuration's `handler` field.

        This method dynamically imports and instantiates a subclass of `ConfigLifecycleHandler`
        defined in an external module. Requires `trust_remote_code=True` and a valid `local_dir`.

        Raises:
            AssertionError: If the handler cannot be found or loaded due to security restrictions or invalid paths.
        """
        handler_file = getattr(self.config, 'handler', None)
        if handler_file is not None:
            local_dir = self.config.local_dir
            assert self.config.trust_remote_code, (
                f'[External Code]A Config Lifecycle handler '
                f'registered in the config: {handler_file}. '
                f'\nThis is external code, if you trust this workflow, '
                f'please specify `--trust_remote_code true`')
            assert (
                local_dir is not None
            ), 'Using external py files, but local_dir cannot be found.'
            if local_dir not in sys.path:
                sys.path.insert(0, local_dir)

            handler_module = importlib.import_module(handler_file)
            module_classes = {
                name: cls
                for name, cls in inspect.getmembers(handler_module,
                                                    inspect.isclass)
            }
            handler = None
            for name, handler_cls in module_classes.items():
                if (handler_cls.__bases__[0] is ConfigLifecycleHandler
                        and handler_cls.__module__ == handler_file):
                    handler = handler_cls()
            assert (
                handler is not None
            ), f'Config Lifecycle handler class cannot be found in {handler_file}'
            return handler
        return None

    def register_callback_from_config(self):
        """
        Dynamically load and instantiate callbacks defined in the configuration.

        Raises:
            AssertionError: If untrusted external code is referenced without permission.
        """
        local_dir = self.config.local_dir if hasattr(self.config,
                                                     'local_dir') else None
        if hasattr(self.config, 'callbacks'):
            callbacks = self.config.callbacks or []
            for _callback in callbacks:
                subdir = os.path.dirname(_callback)
                assert (
                    local_dir is not None
                ), 'Using external py files, but local_dir cannot be found.'
                if subdir:
                    subdir = os.path.join(local_dir, str(subdir))
                _callback = os.path.basename(_callback)
                if _callback not in callbacks_mapping:
                    if not self.trust_remote_code:
                        raise AssertionError(
                            '[External Code Found] Your config file contains external code, '
                            'instantiate the code may be UNSAFE, if you trust the code, '
                            'please pass `trust_remote_code=True` or `--trust_remote_code true`'
                        )
                    if local_dir not in sys.path:
                        sys.path.insert(0, local_dir)
                    if subdir and subdir not in sys.path:
                        sys.path.insert(0, subdir)
                    if _callback.endswith('.py'):
                        _callback = _callback[:-3]
                    callback_file = importlib.import_module(_callback)
                    module_classes = {
                        name: cls
                        for name, cls in inspect.getmembers(
                            callback_file, inspect.isclass)
                    }
                    for name, cls in module_classes.items():
                        # Find cls which base class is `Callback`
                        if issubclass(
                                cls, Callback) and cls.__module__ == _callback:
                            self.callbacks.append(cls(self.config))  # noqa
                elif _callback == 'input_callback':
                    # Interactive input is gated by the resolved interactive
                    # mode (see _resolve_interactive), not by mere presence in
                    # `callbacks:`, and shares the agent's single router so the
                    # initial-prompt and mid-turn paths never diverge.
                    if self._interactive:
                        self.callbacks.append(callbacks_mapping[_callback](
                            self.config,
                            command_router=self._get_command_router(),
                            input_source=self._input_source,
                            event_sink=self._event_sink))
                else:
                    self.callbacks.append(callbacks_mapping[_callback](
                        self.config))

        # Ensure interactive input is available whenever this is an interactive
        # session, even if the config never listed `input_callback`.
        input_cls = callbacks_mapping.get('input_callback')
        if (self._interactive and input_cls is not None and
                not any(isinstance(cb, input_cls) for cb in self.callbacks)):
            self.callbacks.append(
                input_cls(
                    self.config,
                    command_router=self._get_command_router(),
                    input_source=self._input_source,
                    event_sink=self._event_sink))

    async def on_task_begin(self, messages: List[Message]):
        self.log_output(f'Agent {self.tag} task beginning.')
        if self.resolve_enable_snapshots(self.config):
            _user_content = next(
                ((getattr(m, 'content', '') or '')[:80]
                 for m in messages if getattr(m, 'role', '') == 'user'),
                '',
            )
            take_snapshot(
                self.output_dir,
                f'[pre] {_user_content}'
                if _user_content else '[pre] new task',
                message_count=len(messages),
            )
        await self.loop_callback('on_task_begin', messages)

    async def on_task_end(self, messages: List[Message]):
        self.log_output(f'Agent {self.tag} task finished.')
        await self.loop_callback('on_task_end', messages)

    async def on_generate_response(self, messages: List[Message]):
        await self.loop_callback('on_generate_response', messages)

    async def on_tool_call(self, messages: List[Message]):
        await self.loop_callback('on_tool_call', messages)

    async def after_tool_call(self, messages: List[Message]):
        assistant = messages[-1]
        would_stop = assistant.role == 'assistant' and not assistant.tool_calls

        hook_runtime = getattr(self, '_hook_runtime', None)
        if would_stop and hook_runtime is not None and not hook_runtime.is_empty:
            from ms_agent.hooks.context import (append_stop_blocking_feedback,
                                                apply_hook_result_to_messages)

            last_text = assistant.content if isinstance(
                assistant.content, str) else ''
            stop = await hook_runtime.run_stop(
                reason='no_tool_calls',
                last_assistant_message=last_text,
                stop_hook_active=getattr(self.runtime, 'stop_hook_active',
                                         False),
            )
            if stop.action in ('block', 'deny'):
                append_stop_blocking_feedback(messages, stop.reason)
                self.runtime.should_stop = False
                self.runtime.stop_hook_active = True
                await self.loop_callback('after_tool_call', messages)
                return
            apply_hook_result_to_messages(messages, stop, hook_event='Stop')

        if would_stop:
            self.runtime.should_stop = True
        await self.loop_callback('after_tool_call', messages)

    async def loop_callback(self, point, messages: List[Message]):
        """
        Trigger a specific callback hook across all registered callbacks.

        Args:
            point (str): Name of the callback method to call.
            messages (List[Message]): Current message history.
        """
        for callback in self.callbacks:
            await getattr(callback, point)(self.runtime, messages)

    async def parallel_tool_call(self,
                                 messages: List[Message]) -> List[Message]:
        """
        Execute multiple tool calls in parallel and append results to the message list.

        Each result is turned into its tool message and ANNOUNCED
        (``ToolCallCompleted``, plus ``PlanUpdated`` for todo tools) the moment
        that call returns — not once the whole batch has. A round can contain
        one call blocked on a human's approval next to calls that are already
        finished, and those must be able to report themselves as finished.
        The messages are still appended in call order, matching ``tool_calls``.

        Args:
            messages (List[Message]): Current conversation history.

        Returns:
            List[Message]: Updated message list including tool responses.
        """
        tool_calls = messages[-1].tool_calls
        results: Dict[int, Message] = {}

        def _on_result(index: int, tool_call, raw, duration_s: float) -> None:
            tool_call_result_format = ToolResult.from_raw(raw)
            _new_message = Message(
                role='tool',
                content=tool_call_result_format.text,
                tool_call_id=tool_call['id'],
                name=tool_call['tool_name'],
                resources=tool_call_result_format.resources,
                tool_detail=tool_call_result_format.tool_detail,
                hook_attachments=tool_call_result_format.hook_attachments,
                is_error=tool_call_result_format.is_error,
            )

            if _new_message.tool_call_id is None:
                # If tool call id is None, add a random one
                _new_message.tool_call_id = str(uuid.uuid4())[:8]
                tool_call['id'] = _new_message.tool_call_id
            # This call's OWN wall clock. It used to be the batch's span
            # attributed to every call in it, which over-reported every fast
            # tool that shared a round with a slow one.
            _new_message._duration_ms = int(duration_s * 1000)
            results[index] = _new_message
            self.log_output(_new_message.content)
            self._emit_tool_completed(_new_message, duration_s)

        await self.tool_manager.parallel_call_tool(
            tool_calls, on_result=_on_result)
        assert len(results) == len(tool_calls)
        for index in range(len(tool_calls)):
            messages.append(results[index])
        return messages

    def _emit_tool_completed(self, message: Message, duration_s: float) -> None:
        """Report one finished tool call to the UI (and the plan it may carry)."""
        if self._event_sink is None:
            return
        content = (
            message.content
            if isinstance(message.content, str) else str(message.content))
        is_error = bool(getattr(message, 'is_error', False))
        self._event_sink.emit(
            ToolCallCompleted(
                call_id=str(getattr(message, 'tool_call_id', '') or ''),
                name=str(getattr(message, 'name', '') or ''),
                result=content or '',
                error=(content or 'tool call failed') if is_error else None,
                duration_s=round(duration_s, 3)))
        # todo/split_task tool results drive the plan panel.
        plan = self._extract_plan_from_tool_result(message)
        if plan is not None:
            self._event_sink.emit(PlanUpdated(entries=plan))

    def _select_permission_handler(self, mode: str):
        """Pick the PermissionHandler by mode + runtime environment.

        - An explicitly injected handler (``set_permission_handler`` / the
          ``permission_handler`` kwarg) always wins — this is how the TUI /
          WebUI / Server supply their own confirmation UI.
        - ``interactive`` (alias ``restricted``) in an interactive terminal
          session -> ``CLIPermissionHandler`` (the ``[y/s/a/e/n]`` prompt),
          so non-whitelisted tools actually ask the user.
        - Everything else (``auto`` / ``strict`` / non-interactive) ->
          ``AutoPermissionHandler`` (SafetyGuard still enforces the floor).
        """
        if self._permission_handler is not None:
            return self._permission_handler
        from ms_agent.permission import (AutoPermissionHandler,
                                         CLIPermissionHandler)

        # ``PermissionConfig.from_dict`` already normalizes ``restricted`` ->
        # ``interactive``; accept both so a direct caller passing the raw alias
        # still gets the interactive prompt (not a silent AutoPermissionHandler).
        if mode in ('interactive', 'restricted') and self._interactive:
            return CLIPermissionHandler()
        return AutoPermissionHandler()

    def _build_permission_objects(self):
        """Create SafetyGuard and PermissionEnforcer from config if configured."""
        from ms_agent.permission import (PermissionConfig, PermissionEnforcer,
                                         PermissionMemory, SafetyGuard)

        raw = {}
        if hasattr(self.config, 'permission'):
            raw = dict(
                self.config.permission) if self.config.permission else {}

        from ms_agent.utils.workspace_context import resolve_workspace_root

        workspace_root = str(resolve_workspace_root(self.config))
        perm_config = PermissionConfig.from_dict(
            raw, project_root=workspace_root)

        allowed_dirs = [workspace_root]
        for directory in perm_config.safety.allowed_directories:
            if directory not in allowed_dirs:
                allowed_dirs.append(directory)
        read_only_dirs = list(perm_config.safety.read_only_directories)
        safety_guard = SafetyGuard(
            config=perm_config.safety,
            allowed_dirs=allowed_dirs,
            read_only_dirs=read_only_dirs,
            workspace_root=workspace_root,
        )

        handler = self._select_permission_handler(perm_config.mode)
        memory = PermissionMemory(project_path=workspace_root)
        enforcer = PermissionEnforcer(
            config=perm_config, handler=handler, memory=memory)

        return safety_guard, enforcer, perm_config

    def set_permission_handler(self, handler) -> None:
        """Inject a custom PermissionHandler (TUI/WebUI/Server) before run."""
        self._permission_handler = handler

    def set_permission_mode(self, mode: str) -> str:
        """Change the permission mode at runtime; returns the normalized mode.

        Mutates the live ToolManager + enforcer so the next tool call uses the
        new mode without rebuilding the agent (``PermissionConfig`` is frozen,
        so a replaced copy is swapped in). ``restricted`` normalizes to
        ``interactive`` (the canonical asking mode).
        """
        from dataclasses import replace
        mode = {'restricted': 'interactive'}.get(mode, mode)
        if mode not in ('auto', 'strict', 'interactive'):
            raise ValueError(f"Unknown permission mode '{mode}' "
                             '(auto | restricted | strict | interactive)')
        tm = self.tool_manager
        if tm is not None:
            tm._permission_mode = mode
            if getattr(tm, '_permission_config', None) is not None:
                tm._permission_config = replace(
                    tm._permission_config, mode=mode)
            enf = getattr(tm, '_permission_enforcer', None)
            if enf is not None and getattr(enf, '_config', None) is not None:
                enf._config = replace(enf._config, mode=mode)
        return mode

    async def prepare_tools(self):
        """Initialize and connect the tool manager."""
        import uuid

        from ms_agent.hooks.bridge import CallbackToHookBridge
        from ms_agent.hooks.factory import build_hook_runtime
        from ms_agent.plugins.runtime import PluginRuntime
        from ms_agent.utils.workspace_context import resolve_workspace_root

        self.task_manager = TaskManager()

        safety_guard, permission_enforcer, perm_config = self._build_permission_objects(
        )
        session_id = (
            self.runtime.session_id or getattr(self, 'tag', None)
            or str(uuid.uuid4()))
        raw_hooks = {}
        if hasattr(self.config, 'hooks') and self.config.hooks:
            raw_hooks = OmegaConf.to_container(
                self.config.hooks, resolve=True) or {}
        enabled_executors = frozenset(
            raw_hooks.get('enabled_executors', ['command']) or ['command'])
        self._plugin_runtime = PluginRuntime(
            skill_runtime=self._skill_runtime,
            mcp_runtime=self.mcp_runtime,
        )
        self._plugin_runtime.start_sync(
            str(resolve_workspace_root(self.config)),
            session_id,
            config=self.config,
            enabled_executors=enabled_executors,
        )
        self._register_plugin_commands()
        plugin_mcp_servers = self._plugin_runtime.load_result.mcp_servers
        if plugin_mcp_servers:
            from ms_agent.plugins.runtime import dedupe_mcp_server_names
            plugin_mcp_servers = dedupe_mcp_server_names(
                plugin_mcp_servers,
                set(self.mcp_config.setdefault('mcpServers', {}).keys()),
            )
            self._plugin_runtime.load_result.mcp_servers = plugin_mcp_servers
            self.mcp_config['mcpServers'].update(plugin_mcp_servers)
        hook_runtime = build_hook_runtime(
            self.config,
            session_id=session_id,
            plugin_hook_registries=self._plugin_runtime.load_result.
            hook_registries,
        )
        mcp_rt = self.mcp_runtime
        if mcp_rt is not None and plugin_mcp_servers:
            from ms_agent.config.mcp_schema import ResolvedMCPConfig
            merged_servers = {
                state.name: dict(state.config)
                for state in mcp_rt.list_servers()
            }
            merged_servers.update(plugin_mcp_servers)
            await mcp_rt.apply_config(
                ResolvedMCPConfig(mcp_servers=merged_servers))

        self.tool_manager = ToolManager(
            self.config,
            self.mcp_config if mcp_rt is None else {},
            self.mcp_client,
            permission_enforcer=permission_enforcer,
            safety_guard=safety_guard,
            permission_mode=perm_config.mode,
            read_policy=perm_config.safety.read_policy,
            hook_runtime=hook_runtime,
            permission_config=perm_config,
            trust_remote_code=self.trust_remote_code,
            mcp_callable_check=mcp_rt.is_callable if mcp_rt else None,
            mcp_failure_handler=mcp_rt.record_failure if mcp_rt else None,
            mcp_unavailable_detail=mcp_rt.unavailable_detail
            if mcp_rt else None,
            mcp_success_handler=mcp_rt.record_success if mcp_rt else None,
        )
        if mcp_rt is not None:
            self.tool_manager._skip_mcp_reindex = True
        if self._plugin_runtime.agent_registry.has_agents():
            self.tool_manager.ensure_plugin_agent_tools(
                self._plugin_runtime.agent_registry, )
        if hook_runtime.has_session_handlers:
            self.register_callback(
                CallbackToHookBridge(self.config, hook_runtime))
        self._hook_runtime = hook_runtime
        if not self.runtime.session_id:
            self.runtime.session_id = hook_runtime.session_id
        if mcp_rt is not None and not mcp_rt.is_started:
            await mcp_rt.start()
        await self.tool_manager.connect()
        if mcp_rt is not None:
            mcp_rt.bind_tool_manager(self.tool_manager)
            await mcp_rt.sync_tools()
        for tool in self.tool_manager.extra_tools:
            if hasattr(tool, 'set_task_manager'):
                tool.set_task_manager(self.task_manager)

    async def cleanup_tools(self):
        """Cleanup resources used by the tool manager."""
        if self.task_manager is not None:
            self.task_manager.kill_all()
        if self.mcp_runtime is not None:
            await self.mcp_runtime.stop()
        if self.tool_manager is not None:
            await self.tool_manager.cleanup()
        # Drain scheduled memory ingestion so a teardown right after the last
        # turn cannot lose its write. Flush only — memory instances are shared
        # across agents of the same store (SharedMemoryManager), so CLOSING
        # them here would yank the store out from under a sibling agent; the
        # owner of the shared instance decides when to close (e.g. via
        # SharedMemoryManager.close_matching).
        for tool in self.memory_tools:
            flush = getattr(tool, 'flush_pending', None)
            if flush is not None:
                try:
                    await flush(timeout=15)
                except Exception as e:  # noqa: BLE001 - cleanup is best-effort
                    logger.warning(f'memory flush on cleanup failed: {e}')

    @property
    def stream(self):
        generation_config = getattr(self.config, 'generation_config',
                                    DictConfig({}))
        return getattr(generation_config, 'stream', False)

    @property
    def stream_output(self) -> bool:
        """Whether stream mode should print generated tokens locally."""
        generation_config = getattr(self.config, 'generation_config',
                                    DictConfig({}))
        return bool(getattr(generation_config, 'stream_output', True))

    @property
    def show_reasoning(self) -> bool:
        """Whether to print model reasoning/thinking content in stream mode.

        Notes:
            - This only affects local console output.
            - Reasoning is carried by `Message.reasoning_content` (if the backend provides it).
        """
        generation_config = getattr(self.config, 'generation_config',
                                    DictConfig({}))
        return bool(getattr(generation_config, 'show_reasoning', False))

    @property
    def reasoning_output(self) -> str:
        """Where to print reasoning content when `show_reasoning=True`.

        Supported values:
            - "stderr" (default): keep stdout clean for assistant final text
            - "stdout": interleave reasoning with assistant output on stdout
        """
        generation_config = getattr(self.config, 'generation_config',
                                    DictConfig({}))
        return str(getattr(generation_config, 'reasoning_output', 'stdout'))

    _THINKING_SEP = '─' * 40

    def _reasoning_stream(self):
        if self.reasoning_output.lower() == 'stdout':
            return sys.stdout
        return sys.stderr

    def _write_reasoning(self, text: str, dim: bool = False):
        if not text:
            return
        stream = self._reasoning_stream()
        use_ansi = hasattr(stream, 'isatty') and stream.isatty()
        if dim and use_ansi:
            text = f'\033[2m{text}\033[0m'
        stream.write(text)
        stream.flush()

    def _write_thinking_header(self):
        stream = self._reasoning_stream()
        use_ansi = hasattr(stream, 'isatty') and stream.isatty()
        line = f'{self._THINKING_SEP[:15]} thinking {self._THINKING_SEP[25:]}'
        if use_ansi:
            stream.write(f'\033[2m{line}\033[0m\n')
        else:
            stream.write(line + '\n')
        stream.flush()

    def _write_thinking_footer(self):
        stream = self._reasoning_stream()
        use_ansi = hasattr(stream, 'isatty') and stream.isatty()
        if use_ansi:
            stream.write(f'\n\033[2m{self._THINKING_SEP}\033[0m\n')
        else:
            stream.write(f'\n{self._THINKING_SEP}\n')
        stream.flush()

    # ── output seam ────────────────────────────────────────────────────────
    # These route each output write to the structured event sink when one is
    # injected, else to stdout. The no-sink branch calls the exact same code as
    # before the seam existed, so CLI output stays byte-identical.

    def _emit_reasoning_start(self) -> None:
        # Wall-clock the reasoning stream so its elapsed time can be persisted
        # (display/replay only — see handle_new_response + _msg_to_dict).
        self._reasoning_started_at = time.monotonic()
        if self._event_sink is not None:
            self._event_sink.emit(ReasoningStarted())
        else:
            self._write_thinking_header()

    def _emit_reasoning_delta(self, text: str) -> None:
        if self._event_sink is not None:
            self._event_sink.emit(ReasoningDelta(text))
        else:
            self._write_reasoning(text, dim=True)

    def _emit_reasoning_end(self) -> None:
        started = getattr(self, '_reasoning_started_at', None)
        if started is not None:
            self._last_reasoning_duration = round(time.monotonic() - started)
            self._reasoning_started_at = None
        if self._event_sink is not None:
            self._event_sink.emit(ReasoningEnded())
        else:
            self._write_thinking_footer()

    def _emit_content(self, text: str) -> None:
        if self._event_sink is not None:
            self._event_sink.emit(ContentDelta(text))
        else:
            sys.stdout.write(text)
            sys.stdout.flush()

    def _emit_content_end(self) -> None:
        if self._event_sink is not None:
            self._event_sink.emit(ContentEnd())
        else:
            sys.stdout.write('\n')

    @staticmethod
    def _extract_plan_from_tool_result(msg):
        """Parse a todo / split_task tool result into a list of PlanEntry, or
        None. Feeds the WebUI plan/todo panel (and the TUI plan render). Mirrors
        the ACP server's plan extraction so both consumers agree."""
        name = getattr(msg, 'name', '') or ''
        short = name.split('---')[-1] if '---' in name else name
        if 'todo' not in short and short != 'split_task':
            return None
        content = msg.content if isinstance(msg.content, str) else str(
            msg.content)
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        todos = (
            data.get('todos') if isinstance(data, dict) else
            data if isinstance(data, list) else None)
        if not isinstance(todos, list):
            return None
        entries = []
        for it in todos:
            if isinstance(it, dict):
                entries.append(
                    PlanEntry(
                        content=str(
                            it.get('content') or it.get('description')
                            or it.get('task') or ''),
                        status=str(it.get('status') or 'pending')))
        return entries or None

    @property
    def system(self):
        return getattr(
            getattr(self.config, 'prompt', DictConfig({})), 'system', None)

    @property
    def query(self):
        query = getattr(
            getattr(self.config, 'prompt', DictConfig({})), 'query', None)
        if not query:
            query = input('>>>')
        return query

    def _get_command_router(self):
        """Lazily build the slash-command router (builtin commands)."""
        if self._command_router is None:
            from ms_agent.command import (CommandRouter,
                                          register_builtin_commands)

            router = CommandRouter()
            register_builtin_commands(router)
            self._command_router = router
            self._register_plugin_commands()
        return self._command_router

    def _register_plugin_commands(self) -> None:
        if self._command_router is None or self._plugin_runtime is None:
            return
        from ms_agent.plugins.commands import register_plugin_commands
        register_plugin_commands(
            self._command_router,
            self._plugin_runtime.load_result.command_defs,
        )

    def _resolve_interactive(self, messages) -> bool:
        """Decide whether this run is an interactive session.

        An explicit ``config.interactive`` (or ``--interactive`` propagated
        into config) wins. Otherwise interactivity is implicit: only when no
        task was supplied (``messages is None``) AND stdin is a TTY. This keeps
        piped/redirected input, SDK calls, and sub-agent invocations (which all
        pass explicit messages) from ever blocking on ``input()``.
        """
        explicit = getattr(self.config, 'interactive', None)
        if explicit is not None:
            return bool(explicit)
        if messages is not None:
            return False
        # A configured prompt.query is a preset single-shot task, not a session.
        configured = getattr(
            getattr(self.config, 'prompt', DictConfig({})), 'query', None)
        if configured:
            return False
        return sys.stdin.isatty()

    def _has_restorable_history(self) -> bool:
        """True when this run should resume from the session log rather than
        read an initial prompt.

        Guards against the prompt-then-discard on resume: without this, the
        interactive first ``>>>`` read happens *before* history restore, so the
        user's first line would be thrown away when the log is loaded. When a
        resumable log exists (``load_cache`` + non-empty ``SessionLog``), skip
        the initial prompt; restore seeds context and the loop then prompts for
        the next turn via ``InputCallback``.
        """
        if not self.load_cache or self.session_log is None:
            return False
        try:
            return bool(self.session_log.get_all_messages())
        except Exception:
            return False

    async def create_messages(
            self, messages: Union[List[Message], str]) -> List[Message]:
        """
        Convert input into a standardized list of messages.

        Args:
            messages (Union[List[Message], str]): Input prompt or existing message history.

        Returns:
            List[Message]: Standardized message history including system and user prompts.
        """
        if isinstance(messages, list):
            pass
        else:
            assert isinstance(
                messages, str
            ), f'inputs can be either a list or a string, but current is {type(messages)}'
            messages = [
                Message(role='system', content=''),
                Message(role='user', content=messages or self.query),
            ]

        messages[0].content = self._build_system_content()

        return messages

    def _build_personalization_section(self) -> str:
        p_config = getattr(self.config, 'personalization', None)
        config = PersonalizationConfig(
            global_instruction=(getattr(p_config, 'global_instruction', '')
                                or '') if p_config else '',
            project_instruction=(getattr(p_config, 'project_instruction', '')
                                 or '') if p_config else '',
            user_profile=self._profile_manager.read(),
        )
        return PersonalizationInjector.build(config)

    async def do_rag(self, messages: List[Message]):
        """Process RAG to enrich the user query with context.

        Args:
            messages (List[Message]): The message list to process.
        """
        user_message = messages[1] if len(messages) > 1 else None
        if user_message is None or user_message.role != 'user':
            return

        query = user_message.content

        # Handle traditional RAG
        if self.rag is not None:
            user_message.content = await self.rag.query(query)
        # Handle sirchmunk knowledge search
        if self.knowledge_search is not None:
            search_result = await self.knowledge_search.query(query)
            search_details = self.knowledge_search.get_search_details()

            user_message.searching_detail = search_details
            user_message.search_result = search_result

            if search_result:
                context = search_result
                user_message.content = (
                    f'Relevant context retrieved from codebase search:\n\n{context}\n\n'
                    f'User question: {query}')

    async def load_memory(self):
        """Initialize and append memory tool instances based on the configuration provided in the global config.

        For ``unified_memory``, this also:
        - Passes the agent's LLM instance to the orchestrator
        - Registers the ``memory`` / ``memory_read`` tools into ToolManager
        - Injects memory-usage guidance into the system prompt

        Raises:
            AssertionError: If a specified memory type in the config does not exist in memory_mapping.
        """
        self.config: DictConfig
        if hasattr(self.config, 'memory'):
            for mem_instance_type, _memory in self.config.memory.items():
                assert mem_instance_type in memory_mapping, (
                    f'{mem_instance_type} not in memory_mapping, '
                    f'which supports: {list(memory_mapping.keys())}')

                shared_memory = await SharedMemoryManager.get_shared_memory(
                    self.config, mem_instance_type)

                ignore_roles = getattr(_memory, 'ignore_roles', [])
                shared_memory.should_early_add_after_task = (
                    'assistant' in ignore_roles and 'tool' in ignore_roles)
                shared_memory.early_add_after_task_done = False

                self.memory_tools.append(shared_memory)

                # Wire unified_memory into the tool system
                if mem_instance_type == 'unified_memory':
                    await self._register_memory_tool(shared_memory)

    async def _register_memory_tool(self, orchestrator):
        """Register the memory tool into ToolManager and inject prompt guidance."""
        from ms_agent.memory.unified.memory_tool import (MEMORY_USAGE_PROMPT,
                                                         MemoryTool)

        if not hasattr(orchestrator, 'get_tool_schemas'):
            return

        # Pass the LLM to the orchestrator for consolidation / extraction.
        if self.llm is not None:
            orchestrator.set_llm(self.llm)
            orchestrator.init_update_queue()

        # Tool-less backends (e.g. mem0: ingestion via on_messages, retrieval
        # via inject) get neither the MemoryTool registration nor the usage
        # prompt — injecting "use the memory tools" guidance without tools
        # would mislead the model.
        try:
            has_tools = bool(orchestrator.get_tool_schemas())
        except Exception:
            has_tools = False
        if not has_tools:
            return

        # Register memory tool into the agent's tool system
        if self.tool_manager is not None:
            mem_tool = MemoryTool(self.config, orchestrator)
            self.tool_manager.register_tool(mem_tool)
            # Index only the new tool. A full reindex_tool() would re-list every
            # MCP server, duplicating the runtime-owned MCP index and possibly
            # resurfacing tools for disabled/degraded servers.
            await self.tool_manager.index_extra_tool(mem_tool)
            logger.info('[unified_memory] Memory tool registered')

        # Inject usage guidance into system prompt
        if hasattr(self.config, 'prompt') and hasattr(self.config.prompt,
                                                      'system'):
            current_prompt = self.config.prompt.system or ''
            if 'Long-term Memory' not in current_prompt:
                OmegaConf.update(
                    self.config,
                    'prompt.system',
                    current_prompt + '\n\n' + MEMORY_USAGE_PROMPT,
                    merge=True)

    def _schedule_add_memory_after_task(self, messages, timestamp=None):

        def _add_memory():
            asyncio.run(
                self.add_memory(
                    messages, add_type='add_after_task', timestamp=timestamp))

        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _add_memory)

    async def prepare_rag(self):
        """Load and initialize the RAG component from the config."""
        if hasattr(self.config, 'rag'):
            rag = self.config.rag
            if rag is not None:
                assert rag.name in rag_mapping, (
                    f'{rag.name} not in rag_mapping, '
                    f'which supports: {list(rag_mapping.keys())}')
                self.rag: RAG = rag_mapping(rag.name)(self.config)

    async def prepare_knowledge_search(self):
        """Load and initialize the knowledge search component from the config."""
        if self.knowledge_search is not None:
            return
        if hasattr(self.config, 'knowledge_search'):
            ks_config = self.config.knowledge_search
            if ks_config is not None:
                self.knowledge_search: SirchmunkSearch = SirchmunkSearch(
                    self.config)

    async def condense_memory(self, messages: List[Message]) -> List[Message]:
        """Inject long-term memory context into the message list.

        Runs every configured memory tool's ``run`` hook, which adds memory
        context (``<long-term-memory>`` blocks, MEMORY.md snapshot, facts,
        etc.).  It never trims or compresses messages — context compression is
        handled by :class:`ContextAssembler` before this method is called.
        """
        for memory_tool in self.memory_tools:
            messages = await memory_tool.run(messages)
        return messages

    def _init_session_log(self) -> None:
        """Create SessionLog and ContextAssembler if session logging is enabled.

        Both blocks are optional; sensible defaults apply when omitted.  Full
        YAML schema::

            # Append-only message log (source of truth for history).
            session_log:
              enabled: true            # default true; set false to disable
              dir: output/sessions     # default: <output_dir>/sessions
              session_key: my-session  # default: random session_<hex>
              # Token budget passed to the ContextAssembler:
              context_limit: 128000    # max tokens kept in the live window
              reserved_buffer: 20000   # headroom left for the next response
              prune_protect: 40000     # recent tokens never tool-pruned

            # Non-destructive context compaction (rebuilt every loop round).
            compaction:
              enabled: true            # default true; false -> no strategies
              context_limit: 128000    # overrides session_log.context_limit
              reserved_buffer: 20000
              strategies:              # default: both, in this order
                - name: tool_output_pruner
                  enabled: true
                  prune_protect: 40000 # recent tokens exempt from pruning
                - name: summary_compactor
                  enabled: true        # needs an LLM; summarizes old turns

        With ``compaction.enabled: false`` the assembler is created with an
        empty strategy list (history is still logged, just never compressed).
        """
        session_cfg = getattr(self.config, 'session_log', None)
        enabled = getattr(session_cfg, 'enabled',
                          True) if session_cfg else True
        if not enabled:
            return

        session_dir = getattr(session_cfg, 'dir',
                              None) if session_cfg else None
        if session_dir is None:
            # Sessions live globally, keyed by the work dir (Claude Code style),
            # decoupled from output_dir. An explicit session_log.dir (set by the
            # WebUI/Server per project) still wins. Legacy <output_dir>/sessions
            # is migrated forward if present.
            from ms_agent.project.paths import global_sessions_dir
            output_dir = getattr(self.config, 'output_dir', 'output')
            session_dir = str(global_sessions_dir(output_dir))
            legacy_dir = os.path.join(output_dir, 'sessions')
            if os.path.isdir(legacy_dir) and not os.path.isdir(session_dir):
                try:
                    import shutil
                    shutil.copytree(legacy_dir, session_dir)
                except Exception:
                    pass

        session_key = getattr(session_cfg, 'session_key',
                              None) if session_cfg else None
        self.session_log = SessionLog(session_dir, session_key=session_key)

        compaction_cfg = getattr(self.config, 'compaction', None)
        compaction_enabled = (
            getattr(compaction_cfg, 'enabled', True)
            if compaction_cfg else True)

        if not compaction_enabled:
            self.context_assembler = ContextAssembler(
                session_log=self.session_log,
                strategies=[],
                config={},
            )
            return

        strategies = self._build_compaction_strategies(compaction_cfg)
        assembler_config = self._build_assembler_config(
            compaction_cfg, session_cfg)
        flush_callback = self._make_memory_flush_callback()

        self.context_assembler = ContextAssembler(
            session_log=self.session_log,
            strategies=strategies,
            config=assembler_config,
            memory_flush_callback=flush_callback,
        )

    def _build_compaction_strategies(self, compaction_cfg):
        """Build the strategy list from YAML ``compaction.strategies``."""
        if compaction_cfg and hasattr(compaction_cfg, 'strategies'):
            strategies = []
            for s_cfg in compaction_cfg.strategies:
                name = getattr(s_cfg, 'name', '')
                if not getattr(s_cfg, 'enabled', True):
                    continue
                if name == 'tool_output_pruner':
                    strategies.append(ToolOutputPruner())
                elif name == 'summary_compactor':
                    strategies.append(SummaryCompactor(llm=self.llm))
                else:
                    logger.warning(f'Unknown compaction strategy: {name}')
            return strategies

        return [ToolOutputPruner(), SummaryCompactor(llm=self.llm)]

    def _build_assembler_config(self, compaction_cfg, session_cfg):
        """Merge compaction params from ``compaction`` and ``session_log``."""
        config: Dict[str, Any] = {}

        if session_cfg:
            for key in ('context_limit', 'reserved_buffer', 'prune_protect'):
                val = getattr(session_cfg, key, None)
                if val is not None:
                    config[key] = val

        if compaction_cfg:
            for key in ('context_limit', 'reserved_buffer'):
                val = getattr(compaction_cfg, key, None)
                if val is not None:
                    config[key] = val
            if hasattr(compaction_cfg, 'strategies'):
                for s_cfg in compaction_cfg.strategies:
                    if getattr(s_cfg, 'name', '') == 'tool_output_pruner':
                        pp = getattr(s_cfg, 'prune_protect', None)
                        if pp is not None:
                            config['prune_protect'] = pp

        config.setdefault('context_limit', 128000)
        config.setdefault('reserved_buffer', 20000)
        config.setdefault('prune_protect', 40000)
        return config

    def _make_memory_flush_callback(self):
        """Create a callback that flushes memory before context compaction."""

        def _flush(discarded_messages):
            for memory_tool in self.memory_tools:
                orchestrator = memory_tool
                if hasattr(orchestrator, 'flush'):
                    import asyncio

                    from ms_agent.llm.utils import Message as _Msg
                    msgs = [
                        _Msg(
                            role=m.get('role', 'user'),
                            content=m.get('content', ''),
                            tool_calls=m.get('tool_calls'),
                        ) for m in discarded_messages
                    ]
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(orchestrator.flush(msgs))
                    except RuntimeError:
                        asyncio.run(orchestrator.flush(msgs))

        return _flush

    def log_output(self, content: Union[str, list]):
        """
        Log formatted output with a tag prefix.

        Args:
            content (Union[str, list]): Content to log. Can be a string or a list (for multimodal content).
        """
        # Handle multimodal content (list type)
        if isinstance(content, list):
            # Extract text from multimodal content
            text_parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get('type') == 'text':
                        text_parts.append(item.get('text', ''))
                    elif item.get('type') == 'image_url':
                        img_url = item.get('image_url', {}).get('url', '')
                        text_parts.append(f'[Image: {img_url[:50]}...]')
            content = ' '.join(text_parts)

        # Ensure content is a string
        if not isinstance(content, str):
            content = str(content)

        if len(content) > 1024:
            content = content[:512] + '\n...\n' + content[-512:]
        for line in content.split('\n'):
            for _line in line.split('\\n'):
                logger.info(f'[{self.tag}] {_line}')

    def handle_new_response(self, messages: List[Message],
                            response_message: Message):
        assert response_message is not None, 'No response message generated from LLM.'
        if response_message.tool_calls:
            self.log_output('[tool_calling]:')
            for tool_call in response_message.tool_calls:
                tool_call = deepcopy(tool_call)
                if isinstance(tool_call['arguments'], str):
                    try:
                        tool_call['arguments'] = json.loads(
                            tool_call['arguments'])
                    except json.decoder.JSONDecodeError:
                        pass
                self.log_output(
                    json.dumps(tool_call, ensure_ascii=False, indent=4))

        if messages[-1] is not response_message:
            messages.append(response_message)

        # NOTE: a tool-call-only assistant turn is left with EMPTY content on
        # purpose. It used to be filled with a 'Let me do a tool calling.'
        # placeholder, but that leaked into both the session log and the model
        # context (a fake assistant utterance). An assistant message carrying
        # tool_calls needs no text on any supported transport — the provider
        # adapters serialize empty content as null/omitted (OpenAI family) or as
        # tool_use blocks with no text block (Anthropic). See _format_input_message.

        # Stamp the reasoning elapsed time onto the assistant message so it can
        # be persisted for replay (display only — never re-enters the LLM, see
        # _msg_to_dict; the attribute is not a dataclass field so to_dict_clean
        # skips it). Cleared after use so it doesn't leak to the next message.
        dur = getattr(self, '_last_reasoning_duration', None)
        if dur is not None and getattr(response_message, 'reasoning_content',
                                       ''):
            response_message._reasoning_duration = dur
        self._last_reasoning_duration = None

    def _append_task_notifications(self,
                                   messages: List[Message]) -> List[Message]:
        """Inject drained TaskManager completion notices as a user message."""
        if self.task_manager is None:
            return messages
        notes = self.task_manager.drain_notifications()
        if not notes:
            return messages
        body = '[Background task updates]\n' + '\n'.join(notes)
        messages.append(Message(role='user', content=body))
        return messages

    # retry_if: a hard 4xx (bad payload, content filter, auth) is a verdict on
    # the request, not a transient fault — retrying it 5× only adds ~40s of
    # backoff before the same failure surfaces.
    @async_retry(
        max_attempts=Agent.retry_count, delay=1.0, retry_if=is_retryable_error)
    async def step(
        self, messages: List[Message]
    ) -> AsyncGenerator[List[Message], Any]:  # type: ignore
        """
        Execute a single step in the agent's interaction loop.

        This method performs the following operations in sequence:
        1. Deep copies the current message history to avoid mutation issues.
        2. Refines memory based on the current conversation state.
        3. Triggers pre-response callbacks.
        5. Generates a response from the LLM using available tools.
        6. Optionally streams the response output to stdout.
        7. Triggers post-response callbacks.
        8. Handles parallel tool calls if needed.
        9. Triggers post-tool-call callbacks.
        10. Returns the updated message history.

        The step may be retried up to two times on failure due to the `@async_retry` decorator.

        Args:
            messages (List[Message]): Current message history.

        Returns:
            List[Message]: Updated message history after this step.
        """
        messages = deepcopy(messages)
        messages = self._append_task_notifications(messages)
        from ms_agent.hooks.context import (apply_hook_result_to_messages,
                                            condense_hook_attachments_for_llm,
                                            extract_latest_user_prompt)
        messages = condense_hook_attachments_for_llm(messages)

        # UserPromptSubmit for multi-turn user input (InputCallback path)
        hook_runtime = getattr(self, '_hook_runtime', None)
        if (hook_runtime is not None and not hook_runtime.is_empty and messages
                and messages[-1].role == 'user' and self.runtime.round > 0):
            prompt_text = extract_latest_user_prompt(messages)
            submit = await hook_runtime.run_user_prompt_submit(prompt_text)
            if submit.action in ('deny', 'block'):
                if messages and messages[-1].role == 'user':
                    messages.pop()
                messages.append(
                    Message(
                        role='system',
                        content=(
                            f'UserPromptSubmit operation blocked by hook:\n'
                            f'{submit.reason}\n\nOriginal prompt: {prompt_text}'
                        ),
                    ))
                self.runtime.should_stop = True
                yield messages
                return
            apply_hook_result_to_messages(
                messages, submit, hook_event='UserPromptSubmit')

        if (not self.load_cache) or messages[-1].role != 'assistant':
            await self.on_generate_response(messages)
            tools = await self.tool_manager.get_tools()

            if self.stream:
                if self.stream_output:
                    self.log_output('[assistant]:')
                _content = ''
                _reasoning = ''
                is_first = True
                _response_message = None
                _printed_reasoning_header = False
                _printed_reasoning_footer = False
                _gen = self.llm.generate(messages, tools=tools)
                _loop = asyncio.get_running_loop()
                _NO_MORE = object()

                def _next_chunk(_g=_gen):
                    # Step the BLOCKING sync LLM stream off the event loop, so
                    # each chunk flushes incrementally (SSE / UI) and the server
                    # stays responsive during generation. Awaited sequentially,
                    # so the generator is only ever touched by one thread at a
                    # time. (Without this the whole event loop is frozen for the
                    # entire generation and everything arrives at once.)
                    try:
                        return next(_g)
                    except StopIteration:
                        return _NO_MORE

                try:
                    while True:
                        _chunk = await _loop.run_in_executor(None, _next_chunk)
                        if _chunk is _NO_MORE:
                            break
                        _response_message = _chunk
                        if is_first:
                            messages.append(_response_message)
                            is_first = False

                        if self.stream_output and self.show_reasoning:
                            reasoning_text = (
                                getattr(_response_message, 'reasoning_content',
                                        '') or '')
                            # Some providers may reset / shorten content across chunks.
                            if len(reasoning_text) < len(_reasoning):
                                _reasoning = ''
                            new_reasoning = reasoning_text[len(_reasoning):]
                            if new_reasoning:
                                if not _printed_reasoning_header:
                                    self._emit_reasoning_start()
                                    _printed_reasoning_header = True
                                self._emit_reasoning_delta(new_reasoning)
                                _reasoning = reasoning_text

                        new_content = _response_message.content[len(_content):]
                        if self.stream_output and new_content:
                            if _printed_reasoning_header and not _printed_reasoning_footer:
                                self._emit_reasoning_end()
                                _printed_reasoning_footer = True
                            self._emit_content(new_content)
                        _content = _response_message.content
                        messages[-1] = _response_message
                        yield messages
                finally:
                    # Turn abandoned mid-stream (client disconnect / stop): ask
                    # the provider to close the live upstream response so the
                    # server stops generating, instead of leaving it to run to
                    # completion into a dropped connection. Only the data-driven
                    # provider layer implements interrupt(); the legacy LLM does
                    # not, so this is a no-op there (unchanged). Harmless on a
                    # normal finish (the stream is already exhausted).
                    _interrupt = getattr(self.llm, 'interrupt', None)
                    if callable(_interrupt):
                        try:
                            _interrupt()
                        except Exception:  # noqa: BLE001 - teardown never raises
                            pass
                if self.stream_output:
                    if _printed_reasoning_header and not _printed_reasoning_footer:
                        self._emit_reasoning_end()

                    # Handle reasoning summaries that arrive after content
                    if self.show_reasoning and _response_message is not None:
                        final_reasoning = getattr(
                            _response_message, 'reasoning_content', '') or ''
                        if final_reasoning and not _printed_reasoning_header:
                            self._emit_reasoning_start()
                            self._emit_reasoning_delta(final_reasoning)
                            self._emit_reasoning_end()

                    self._emit_content_end()
            else:
                _response_message = self.llm.generate(messages, tools=tools)
                if self.show_reasoning:
                    reasoning_text = (
                        getattr(_response_message, 'reasoning_content', '')
                        or '')
                    if reasoning_text:
                        self._emit_reasoning_start()
                        self._emit_reasoning_delta(reasoning_text)
                        self._emit_reasoning_end()
                if _response_message.content:
                    if self._event_sink is not None:
                        self._emit_content(_response_message.content)
                        self._emit_content_end()
                    self.log_output('[assistant]:')
                    self.log_output(_response_message.content)

            # Response generated
            self.handle_new_response(messages, _response_message)
            await self.on_tool_call(messages)
        else:
            # Set load_cache to `false` to avoid affect later operations
            self.load_cache = False
            # Meaning the latest message is `assistant`, this prevents a different response if there are sub-tasks.
            _response_message = messages[-1]
        self.save_history(messages)

        if _response_message.tool_calls:
            if self._event_sink is not None:
                for tc in _response_message.tool_calls:
                    self._event_sink.emit(
                        ToolCallStarted(
                            call_id=str(tc.get('id') or ''),
                            name=str(
                                tc.get('tool_name') or tc.get('name') or ''),
                            arguments=tc.get('arguments')))
            # Each call stamps its own ``_duration_ms`` (persistence/replay) and
            # emits its own ToolCallCompleted / PlanUpdated as it finishes —
            # inside parallel_tool_call, not after the batch, so one call held
            # up by an approval doesn't hold back its finished siblings.
            messages = await self.parallel_tool_call(messages)

        # usage
        # NOTE: token accounting must run BEFORE after_tool_call. The interactive
        # InputCallback fires inside after_tool_call and may read these counters
        # (e.g. /usage, /context); updating them first keeps those views current.
        prompt_tokens = _response_message.prompt_tokens
        completion_tokens = _response_message.completion_tokens
        cached_tokens = getattr(_response_message, 'cached_tokens', 0) or 0
        cache_creation_input_tokens = (
            getattr(_response_message, 'cache_creation_input_tokens', 0) or 0)
        reasoning_tokens = getattr(_response_message, 'reasoning_tokens',
                                   0) or 0

        async with LLMAgent.TOKEN_LOCK:
            LLMAgent.TOTAL_PROMPT_TOKENS += prompt_tokens
            LLMAgent.TOTAL_COMPLETION_TOKENS += completion_tokens
            LLMAgent.TOTAL_CACHED_TOKENS += cached_tokens
            LLMAgent.TOTAL_CACHE_CREATION_INPUT_TOKENS += cache_creation_input_tokens
            LLMAgent.TOTAL_REASONING_TOKENS += reasoning_tokens
            LLMAgent.LAST_PROMPT_TOKENS = prompt_tokens
            LLMAgent.LAST_COMPLETION_TOKENS = completion_tokens
            LLMAgent.LAST_REASONING_TOKENS = reasoning_tokens

        # after_tool_call() is invoked by run_loop AFTER this step yields (not
        # here): its interactive InputCallback blocks awaiting the next prompt,
        # and step() is under @async_retry, so a quit/EOF here would re-run the
        # step and re-generate/re-persist. Keeping it out of the retry scope lets
        # run_loop persist this turn's assistant reply *before* the blocking read
        # (fixes: last answer lost / resume re-answering the last user turn).

        # tokens in the current step
        self.log_output(
            f'[usage] prompt_tokens: {prompt_tokens}, completion_tokens: {completion_tokens}'
        )
        if reasoning_tokens:
            self.log_output(
                f'[usage_reasoning] reasoning_tokens: {reasoning_tokens}')
        if cached_tokens or cache_creation_input_tokens:
            self.log_output(
                f'[usage_cache] cache_hit: {cached_tokens}, cache_created: {cache_creation_input_tokens}'
            )
        # total tokens for the process so far
        self.log_output(
            f'[usage_total] total_prompt_tokens: {LLMAgent.TOTAL_PROMPT_TOKENS}, '
            f'total_completion_tokens: {LLMAgent.TOTAL_COMPLETION_TOKENS}')
        if LLMAgent.TOTAL_CACHED_TOKENS or LLMAgent.TOTAL_CACHE_CREATION_INPUT_TOKENS:
            self.log_output(
                f'[usage_cache_total] total_cache_hit: {LLMAgent.TOTAL_CACHED_TOKENS}, '
                f'total_cache_created: {LLMAgent.TOTAL_CACHE_CREATION_INPUT_TOKENS}'
            )

        if self._event_sink is not None:
            self._event_sink.emit(
                TurnCompleted(
                    usage=UsageInfo(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        reasoning_tokens=reasoning_tokens,
                        total_prompt_tokens=LLMAgent.TOTAL_PROMPT_TOKENS,
                        total_completion_tokens=LLMAgent.
                        TOTAL_COMPLETION_TOKENS)))

        yield messages

    def prepare_llm(self):
        """Initialize the LLM model from the configuration."""
        self.llm: LLM = LLM.from_config(self.config)

    def prepare_runtime(self):
        """Initialize the runtime context."""
        self.runtime: Runtime = Runtime(llm=self.llm)

    def read_history(self, messages: List[Message],
                     **kwargs) -> Tuple[DictConfig, Runtime, List[Message]]:
        """
        Load previous chat history from disk if available.

        Args:
            messages (List[Message]): Input message or history to resume from.

        Returns:
            Tuple[DictConfig, Runtime, List[Message]]: Updated config, runtime, and message history.
        """
        if isinstance(messages, str):
            query = messages
        else:
            query = messages[1].content
        if not query or not self.load_cache:
            return self.config, self.runtime, messages

        config, _messages = read_history(self.output_dir, self.tag)
        if config is not None and _messages is not None:
            if hasattr(config, 'runtime'):
                runtime = Runtime(llm=self.llm)
                runtime.from_dict(config.runtime)
                delattr(config, 'runtime')
            else:
                runtime = self.runtime
            if _messages[-1].role == 'tool':
                # Ignore and redo the last tool response
                # This is because it's the last calling, the unhandled error may be started from here
                _messages = _messages[:-1]
            return config, runtime, _messages
        else:
            return self.config, self.runtime, messages

    def get_user_id(self, default_user_id=DEFAULT_USER) -> Optional[str]:
        user_id = default_user_id
        if hasattr(self.config, 'memory') and self.config.memory:
            for memory_config in self.config.memory:
                if hasattr(memory_config, 'user_id') and memory_config.user_id:
                    user_id = memory_config.user_id
                    break
        return user_id

    def _get_step_memory_info(self, memory_config: DictConfig):
        user_id, agent_id, run_id, memory_type = get_memory_meta_safe(
            memory_config, 'add_after_step')
        if all(value is None
               for value in [user_id, agent_id, run_id, memory_type]):
            return None, None, None, None
        user_id = user_id or getattr(memory_config, 'user_id', None)
        return user_id, agent_id, run_id, memory_type

    def _get_run_memory_info(self, memory_config: DictConfig):
        user_id, agent_id, run_id, memory_type = get_memory_meta_safe(
            memory_config,
            'add_after_task',
            default_user_id=getattr(memory_config, 'user_id', None),
        )
        if all(value is None
               for value in [user_id, agent_id, run_id, memory_type]):
            return None, None, None, None
        user_id = user_id or getattr(memory_config, 'user_id', None)
        agent_id = agent_id or self.tag
        memory_type = memory_type or None
        return user_id, agent_id, run_id, memory_type

    async def add_memory(self, messages: List[Message], add_type, **kwargs):
        if hasattr(self.config, 'memory') and self.config.memory:
            for tool, (_, memory_config) in zip(self.memory_tools,
                                                self.config.memory.items()):
                timestamp = kwargs.get('timestamp', '')
                if add_type == 'add_after_task':
                    user_id, agent_id, run_id, memory_type = self._get_run_memory_info(
                        memory_config)
                    should_early = getattr(tool, 'should_early_add_after_task',
                                           False)
                    early_done = getattr(tool, 'early_add_after_task_done',
                                         False)

                    if timestamp == 'early':
                        if not (should_early and not early_done):
                            # pass memory tool.run
                            continue
                        tool.early_add_after_task_done = True
                    else:
                        if early_done:
                            # pass memory tool.run
                            continue

                else:
                    user_id, agent_id, run_id, memory_type = self._get_step_memory_info(
                        memory_config)

                if not any(v is not None
                           for v in [user_id, agent_id, run_id, memory_type]):
                    continue
                # Ingestion runs an extraction LLM + embeddings (seconds).
                # Backends that support it take the write off the turn's
                # critical path — schedule_add returns immediately and the
                # write serializes against retrieval on the store's own lock.
                # Others (legacy memory types) keep the awaited behaviour.
                if add_type == 'add_after_step' and hasattr(
                        tool, 'schedule_add'):
                    tool.schedule_add(
                        messages,
                        user_id=user_id,
                        agent_id=agent_id,
                        run_id=run_id,
                        memory_type=memory_type)
                    continue
                await tool.add(
                    messages,
                    user_id=user_id,
                    agent_id=agent_id,
                    run_id=run_id,
                    memory_type=memory_type)

    def save_history(self, messages: List[Message], **kwargs):
        """
        Save current chat history to disk for future resuming.

        Args:
            messages (List[Message]): Current message history to save.
        """
        query = None
        if len(messages) > 1 and messages[1].role == 'user':
            query = messages[1].content
        elif messages:
            query = messages[0].content
        if not query:
            return

        if not getattr(self.config, 'save_history', True):
            return

        config: DictConfig = deepcopy(self.config)
        config.runtime = self.runtime.to_dict()
        save_history(
            self.output_dir, task=self.tag, config=config, messages=messages)

    @staticmethod
    def _msg_to_dict(msg: Message) -> Dict[str, Any]:
        """Convert a Message to a plain dict for SessionLog.

        Preserves ``prompt_tokens`` and ``completion_tokens`` individually
        so that :class:`ContextAssembler` strategies can leverage API-reported
        usage data for accurate overflow detection.
        """
        d: Dict[str, Any] = {'role': msg.role, 'content': msg.content or ''}
        if msg.tool_calls:
            d['tool_calls'] = msg.tool_calls
        if hasattr(msg, 'tool_call_id') and msg.tool_call_id:
            d['tool_call_id'] = msg.tool_call_id
        if hasattr(msg, 'name') and msg.name:
            d['name'] = msg.name
        if getattr(msg, 'reasoning_content', ''):
            d['reasoning_content'] = msg.reasoning_content
            # Anthropic thinking blocks must be replayed verbatim (with their
            # signature) in a tool follow-up, so both round-trip. OpenAI-compat
            # transports drop reasoning via their input_msg allowlist, so this
            # never re-enters an OpenAI-style call.
            if getattr(msg, 'reasoning_signature', ''):
                d['reasoning_signature'] = msg.reasoning_signature
        # Display-only timings (stamped as plain attributes, not dataclass
        # fields, so to_dict_clean/asdict never send them to the model).
        if getattr(msg, '_reasoning_duration', None) is not None:
            d['reasoning_duration'] = msg._reasoning_duration
        if getattr(msg, '_duration_ms', None) is not None:
            d['duration_ms'] = msg._duration_ms
        if getattr(msg, 'is_error', False):
            d['is_error'] = True
        prompt_tokens = int(getattr(msg, 'prompt_tokens', 0) or 0)
        completion_tokens = int(getattr(msg, 'completion_tokens', 0) or 0)
        if prompt_tokens:
            d['prompt_tokens'] = prompt_tokens
        if completion_tokens:
            d['completion_tokens'] = completion_tokens
        if prompt_tokens or completion_tokens:
            d['tokens'] = prompt_tokens + completion_tokens
        return d

    def _persist_partial_round(self,
                               messages: List[Message],
                               pre_step_len: int,
                               marker: str = 'interrupted') -> None:
        """Seal an unfinished round into the SessionLog (best-effort).

        Called from run_loop's cancellation handler AND its exception handler,
        where the normal round-boundary persistence can no longer run.
        Serializes the round's in-memory rows and appends the protocol-repaired
        records built by :func:`build_partial_round_records`. Synchronous file
        I/O only (safe inside a cancelled task); never raises — sealing must not
        break the unwind.

        Sealing is not cosmetic: without it the log tail stays on a ``user`` or
        ``tool`` row, and the next resume rebuilds that same round and re-calls
        the model instead of reading the user's new prompt (see run_loop's
        ``load_cache`` guard). ``marker`` records why the round ended —
        ``interrupted`` for Stop, ``errored`` for a raised turn.
        """
        if self.session_log is None:
            return
        # Stamp the thinking elapsed onto the interrupted round's partial
        # reasoning message, else the row persists no `reasoning_duration` and
        # replay shows "thought 0s". Two cancel points need it:
        #  (a) cancelled MID-reasoning — `_emit_reasoning_end` never ran, so the
        #      elapsed was never computed; finalize it now from the start stamp;
        #  (b) reasoning already ended and cancel hit during BODY streaming — the
        #      elapsed is parked in `_last_reasoning_duration`, but
        #      `handle_new_response` (which normally stamps it) never ran.
        started = getattr(self, '_reasoning_started_at', None)
        if started is not None:
            dur = round(time.monotonic() - started)
            self._reasoning_started_at = None
        else:
            dur = getattr(self, '_last_reasoning_duration', None)
        if dur is not None:
            for msg in reversed(messages[pre_step_len:]):
                if (msg.role == 'assistant'
                        and getattr(msg, 'reasoning_content', '')
                        and getattr(msg, '_reasoning_duration', None) is None):
                    msg._reasoning_duration = dur
                    break
        try:
            rows = [
                self._msg_to_dict(msg) for msg in messages[pre_step_len:]
            ]
            for record in build_partial_round_records(rows, marker=marker):
                self.session_log.append(record)
        except Exception:
            logger.warning('persist partial round failed', exc_info=True)

    async def run_loop(self, messages: Union[List[Message], str],
                       **kwargs) -> AsyncGenerator[Any, Any]:
        """Run the agent loop (LLM generation + tool calling).

        Skills, when configured, are exposed as standard tools
        (skills_list, skill_view, skill_manage) and injected into
        the system prompt—no special routing needed.

        Args:
            messages: Input prompt string or list of Message objects.
        """
        # Bound BEFORE the try so the exception handler can always read it:
        # setup (agent/LLM construction, credential resolution) raises well
        # before the round loop, and an unbound local there would turn a clean
        # provider error into an UnboundLocalError. None = no round to seal.
        pre_step_len: Optional[int] = None
        try:
            self.max_chat_round = getattr(self.config, 'max_chat_round',
                                          LLMAgent.DEFAULT_MAX_CHAT_ROUND)
            # Resolve interactive mode once; it gates both the initial >>>
            # prompt below and InputCallback registration just after.
            self._interactive = self._resolve_interactive(messages)
            self.register_callback_from_config()
            self.prepare_llm()
            self.prepare_runtime()
            await self.prepare_tools()
            await self.prepare_skills()
            await self.load_memory()
            await self.prepare_rag()
            await self.prepare_knowledge_search()
            self._init_session_log()
            self.runtime.tag = self.tag

            self.task_manager = TaskManager()
            for tool in self.tool_manager.extra_tools:
                if hasattr(tool, 'set_task_manager'):
                    tool.set_task_manager(self.task_manager)

            if messages is None:
                configured = getattr(
                    getattr(self.config, 'prompt', DictConfig({})), 'query',
                    None)
                if configured:
                    messages = configured
                elif self._interactive:
                    # On resume (restorable history), skip the initial prompt:
                    # restore below seeds context and the loop then prompts for
                    # the next turn via InputCallback. Leaving messages None here
                    # lets the restore block fill it.
                    if not self._has_restorable_history():
                        from ms_agent.command.interactive import \
                            InteractiveSession
                        session = InteractiveSession(
                            self._get_command_router(),
                            source='tui'
                            if self._input_source is not None else 'cli',
                            input_source=self._input_source,
                            event_sink=self._event_sink)
                        turn = await session.run_turn(
                            messages=None, runtime=self.runtime)
                        if turn.action == 'quit':
                            # Exited at the interactive prompt without a task.
                            self.runtime.should_stop = True
                            await self.cleanup_tools()
                            return
                        messages = turn.text
                else:
                    # Non-interactive with no task: accept piped stdin as the
                    # query; otherwise fail clearly instead of blocking input().
                    piped = ('' if sys.stdin.isatty() else
                             sys.stdin.read().strip())
                    if not piped:
                        raise ValueError(
                            'No query provided. Pass --query, pipe input via '
                            'stdin, or run in an interactive terminal.')
                    messages = piped

            # Load history and restore state
            restored_from_log = False
            if self.session_log is not None:
                restored = self.session_log.get_all_messages()
                if restored and self.load_cache:
                    # Reuse the canonical dict->Message conversion so tool-use
                    # fields (tool_call_id, name) survive the round-trip.
                    from ms_agent.session.context_assembler import \
                        _dicts_to_messages
                    messages = _dicts_to_messages(restored)
                    # Resume: recover the round counter from the session log so
                    # we don't re-run new-task setup (skill routing,
                    # on_task_begin) or duplicate the seeded history.
                    self.runtime.round = self.session_log.round
                    restored_from_log = True
                else:
                    self.config, self.runtime, messages = self.read_history(
                        messages)
            else:
                self.config, self.runtime, messages = self.read_history(
                    messages)

            if self.runtime.round == 0 and not restored_from_log:
                # New task: create standardized messages first
                messages = await self.create_messages(messages)

                hook_runtime = getattr(self, '_hook_runtime', None)
                if hook_runtime is not None:
                    hook_runtime.session_id = self.runtime.session_id

                # SessionStart before UserPromptSubmit (§9.3)
                await self.on_task_begin(messages)

                # UserPromptSubmit — first user message
                if hook_runtime is not None and not hook_runtime.is_empty:
                    from ms_agent.hooks.context import (
                        apply_hook_result_to_messages,
                        extract_latest_user_prompt)
                    prompt_text = extract_latest_user_prompt(messages)
                    submit = await hook_runtime.run_user_prompt_submit(
                        prompt_text)
                    if submit.action in ('deny', 'block'):
                        messages.append(
                            Message(
                                role='system',
                                content=
                                (f'UserPromptSubmit operation blocked by hook:\n'
                                 f'{submit.reason}\n\nOriginal prompt: {prompt_text}'
                                 ),
                            ))
                        await self.on_task_end(messages)
                        yield messages
                        await self.cleanup_tools()
                        return
                    apply_hook_result_to_messages(
                        messages, submit, hook_event='UserPromptSubmit')

                await self.do_rag(messages)

                # Seed SessionLog with initial messages
                if self.session_log is not None:
                    for msg in messages:
                        self.session_log.append(self._msg_to_dict(msg))

            for message in messages:
                if message.role != 'system':
                    self.log_output('[' + message.role + ']:')
                    self.log_output(message.content)
            while not self.runtime.should_stop:
                # Rebuild context view from SessionLog (non-destructive
                # compression). This is the canonical history for the round, so
                # it must run before the per-round augmentations below.
                if self.context_assembler is not None and self.runtime.round > 0:
                    # Detect real compaction via last_consolidated advancing
                    # (assemble() only advances it when a strategy consolidated
                    # the window — see ContextAssembler.assemble).
                    _lc_before = (
                        self.session_log.last_consolidated
                        if self.session_log is not None else 0)
                    messages = self.context_assembler.assemble()
                    if (self._event_sink is not None
                            and self.session_log is not None and
                            self.session_log.last_consolidated > _lc_before):
                        self._event_sink.emit(ContextCompacted())

                messages = self._apply_pending_rollback(messages)
                if self.task_manager is not None:
                    notifications = self.task_manager.drain_notifications()
                    if notifications:
                        messages.append(
                            Message(
                                role='user', content='\n'.join(notifications)))
                if self._skill_runtime:
                    self._skill_runtime.maybe_refresh_system_prompt(messages)
                messages = await self.condense_memory(messages)
                # If assistant and tool content can be ignored, add memory earlier to reduce running time.
                self._schedule_add_memory_after_task(
                    messages, timestamp='early')

                # Captured right before step() so only genuine step outputs are
                # appended to the SessionLog (ephemeral injections are excluded).
                pre_step_len = len(messages)
                try:
                    async for messages in self.step(messages):
                        messages = self._apply_pending_rollback(messages)
                        yield messages
                except (asyncio.CancelledError, GeneratorExit):
                    # The turn was interrupted mid-round (task cancelled, or the
                    # consumer closed the generator). Round persistence below
                    # never runs, so faithfully seal what this round produced —
                    # partial assistant text/reasoning, validated tool_calls
                    # plus synthesized interrupted tool results — before the
                    # cancellation unwinds. Sync file I/O only; must re-raise.
                    self._persist_partial_round(messages, pre_step_len)
                    # An interrupted round is never ingested into long-term
                    # memory: a half-finished answer is not durable
                    # conversational truth. Advance the ingest ledger past it
                    # (sync, in-memory + small file write) so the next turn's
                    # delta does not sweep the partial content in either.
                    for _mem_tool in self.memory_tools:
                        if hasattr(_mem_tool, 'mark_ingested'):
                            try:
                                _mem_tool.mark_ingested(messages)
                            except Exception:  # noqa: E722 - never mask cancel
                                pass
                    raise

                # Persist THIS round's step output (assistant + any tool
                # messages) NOW — before after_tool_call below, whose interactive
                # InputCallback blocks awaiting the next prompt. Without this a
                # turn's assistant reply would only be persisted when the next
                # turn starts (so a session's last answer is lost and resume
                # re-answers the last user turn). after_tool_call runs here (not
                # inside step) to stay outside step()'s @async_retry scope.
                step_end_len = len(messages)
                if self.session_log is not None:
                    for msg in messages[pre_step_len:step_end_len]:
                        self.session_log.append(self._msg_to_dict(msg))

                # Ingest memory here — before after_tool_call, which blocks on
                # the next prompt in interactive mode (running afterwards made
                # 'add_after_step' mean "after the *next* step": round N was
                # only ingested once round N+1 arrived, a single-round session
                # never at all, and the ingested list already carried the next
                # user turn). Only on a CLOSING round — an assistant reply with
                # no tool calls, i.e. the turn is complete. Tool rounds are
                # intermediate state, not durable conversational truth, and
                # ingesting every round made memory cost O(rounds x history):
                # a 4-round tool-calling answer paid ~4 extraction-LLM calls
                # where one covers it (the closing ingest sees the whole turn).
                if (messages and messages[-1].role == 'assistant'
                        and not messages[-1].tool_calls):
                    await self.add_memory(
                        messages, add_type='add_after_step', **kwargs)

                await self.after_tool_call(messages)
                self.runtime.round += 1

                # Persist whatever after_tool_call appended (the next user
                # message) and the round counter, so a later resume picks up here.
                if self.session_log is not None:
                    for msg in messages[step_end_len:]:
                        self.session_log.append(self._msg_to_dict(msg))
                    self.session_log.round = self.runtime.round

                self.save_history(messages)

                # +1 means the next round the assistant may give a conclusion
                if self.runtime.round >= self.max_chat_round + 1:
                    if not self.runtime.should_stop:
                        cutoff_msg = Message(
                            role='assistant',
                            content=
                            f'Task {messages[1].content} was cutted off, because '
                            f'max round({self.max_chat_round}) exceeded.',
                        )
                        messages.append(cutoff_msg)
                        if self.session_log is not None:
                            self.session_log.append(
                                self._msg_to_dict(cutoff_msg))
                        self.save_history(messages)
                    self.runtime.should_stop = True
                    yield messages

            # save memory
            await self.on_task_end(messages)
            await self.cleanup_tools()
            yield messages

            self._schedule_add_memory_after_task(messages)

        except Exception as e:
            import traceback

            logger.warning(traceback.format_exc())
            # Seal the round FIRST. A raised turn leaves the log tail on a
            # `user`/`tool` row, and run_loop's resume guard only skips the
            # model call when the tail is `assistant` — so the next request
            # rebuilds this same round, re-sends the identical failing context,
            # and never reaches after_tool_call (which is what drains the queued
            # prompt). The user sees the turn "loop" while every resend is
            # silently discarded. Sealing closes the round, so the rebuilt agent
            # blocks on read_prompt and consumes the new message instead.
            if pre_step_len is not None:
                self._persist_partial_round(
                    messages, pre_step_len, marker='errored')
            if self._event_sink is not None:
                # A run_loop turn-abort is non-recoverable (the turn produced no
                # usable assistant output); mark it so live == persisted/replay.
                self._event_sink.emit(
                    ErrorRaised(
                        message=f'{type(e).__name__}: {e}', recoverable=False))
            # Persist the turn/API error as a display-only record. It is filtered
            # out of get_all_messages(), so it never re-enters the LLM context on
            # resume (unrecoverable), but history can replay that it happened.
            if self.session_log is not None:
                try:
                    self.session_log.record_error({
                        'message': f'{type(e).__name__}: {e}',
                        'error_type': type(e).__name__,
                        'recoverable': False,
                        'round': self.runtime.round,
                    })
                    self.session_log.set_metadata_field('status', 'error')
                except Exception:
                    pass
            if hasattr(self.config, 'help'):
                logger.error(
                    f'[{self.tag}] Runtime error, please follow the instructions:\n\n {self.config.help}'
                )
            raise e

    async def run(
            self, messages: Union[List[Message], str], **kwargs
    ) -> Union[List[Message], AsyncGenerator[List[Message], Any]]:
        stream = kwargs.get('stream', False)
        with self.config_context():
            if stream:
                OmegaConf.update(
                    self.config, 'generation_config.stream', True, merge=True)

                async def stream_generator():
                    async for _chunk in self.run_loop(
                            messages=messages, **kwargs):
                        yield _chunk

                return stream_generator()
            else:
                res = None
                async for chunk in self.run_loop(messages=messages, **kwargs):
                    res = chunk
                return res
