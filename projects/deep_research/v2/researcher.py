# Copyright (c) Alibaba, Inc. and its affiliates.
from typing import Any, AsyncGenerator, List, Union

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from ms_agent.utils.constants import DEFAULT_TAG
from ms_agent.utils.stats import (append_stats, build_timing_record,
                                  get_stats_path, monotonic, now_iso,
                                  summarize_usage)
from omegaconf import DictConfig

logger = get_logger()


class ResearcherAgent(LLMAgent):
    """
    Researcher Agent that conducts deep research tasks using LLMs and various tools.
    """

    def __init__(self,
                 config: DictConfig = DictConfig({}),
                 tag: str = DEFAULT_TAG,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)

    async def run_loop(self, messages: Union[List[Message], str],
                       **kwargs) -> AsyncGenerator[Any, Any]:
        start_ts = now_iso()
        start_time = monotonic()
        last_messages: List[Message] = []
        status = 'completed'
        try:
            async for chunk in super().run_loop(messages=messages, **kwargs):
                last_messages = chunk
                yield chunk
        except Exception:
            status = 'error'
            raise
        finally:
            end_ts = now_iso()
            duration_s = monotonic() - start_time
            usage = summarize_usage(last_messages)
            record = build_timing_record(
                event='workflow',
                agent_tag=self.tag,
                agent_type=self.AGENT_NAME,
                started_at=start_ts,
                ended_at=end_ts,
                duration_s=duration_s,
                status=status,
                usage=usage,
                extra={
                    'rounds': getattr(self.runtime, 'round', None),
                },
            )
            try:
                await append_stats(get_stats_path(self.config), record)
            except Exception as exc:
                logger.warning(f'Failed to write workflow stats: {exc}')

    async def on_task_end(self, messages: List[Message]):
        # Keep default behavior (callbacks + agent finished log), then dump
        # process-wide web_search summarization usage (separate from LLMAgent usage).
        await super().on_task_end(messages)
        try:
            from ms_agent.tools.search.websearch_tool import WebSearchTool
            WebSearchTool.log_global_summarization_usage()
        except Exception as exc:
            logger.warning(
                f'Failed to log web search summarization usage: {exc}')
