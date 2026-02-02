# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import json
from ms_agent.llm.openai_llm import OpenAI
from ms_agent.llm.utils import Message
from ms_agent.utils.logger import get_logger
from ms_agent.utils.thread_util import DaemonThreadPoolExecutor
from omegaconf import DictConfig, OmegaConf

logger = get_logger()

SUMMARIZE_WEBPAGE_PROMPT = """  # noqa: E501
你是最专业的研究助手，负责总结网页的原始内容。你的目标是创建一个能够为下游研究代理保留最重要信息的摘要，因此必须在不丢失关键信息的前提下，尽可能保留关键细节。

以下是网页的原始内容：

<webpage_content>
{webpage_content}
</webpage_content>

请遵循以下指南创建你的摘要：

1. 识别并保留网页的主要主题或目的。
2. 保留内容核心信息中的关键事实、统计数据和数据点。
3. 保留来自可信来源或专家的重要引述/原话。
4. 若内容具有时效性或历史性，请保持事件的时间顺序。
5. 若存在列表或分步说明，请保留这些结构化信息。
6. 包含对理解内容至关重要的相关日期、姓名/机构、地点等信息。
7. 将冗长解释进行压缩，但必须保留核心信息与结论。

针对不同类型的内容：
- 新闻文章：关注谁（who）、什么（what）、何时（when）、何地（where）、为什么（why）、如何（how）。
- 科学内容：保留方法、结果与结论。
- 观点文章：保留主要论点与支撑论据。
- 产品页面：保留关键特性、规格参数与独特卖点。
- 学术论文：保留研究目标、方法、主要发现与结论。

你的摘要应显著短于原文，但必须足够完整，能够作为独立信息来源使用。除非原文已非常简洁，否则目标长度约为原文的 25–30%。
但如果网页信息密度很高，请不要过度压缩。相比严格追求长度比例，更应优先保留有价值的细节（关键事实、数字、定义、约束条件、步骤、注意事项、上下文）。在这种情况下，只要结构清晰且避免冗余，摘要长度可以超过 30%（甚至可达约 70–80%）。

输出格式（JSON）：

```json
{{
   "summary": "你的摘要内容，根据需要使用适当的段落或要点进行结构化",
   "key_excerpts": "第一段重要引用或摘录, 第二段重要引用或摘录, 第三段重要引用或摘录, ...（按需补充更多摘录）"
}}
```

下面是两个摘要的优秀示例：

示例 1（新闻文章）：
```json
{{
   "summary": "2023 年 7 月 15 日，NASA 在肯尼迪航天中心成功发射阿尔忒弥斯 II（Artemis II）任务。这是自 1972 年阿波罗 17 号以来首次载人重返月球相关任务。由指挥官 Jane Smith 率领的四人乘组将绕月飞行 10 天后返回地球。该任务被视为 NASA 计划在 2030 年前建立月球长期有人存在的重要一步。",
   "key_excerpts": "“阿尔忒弥斯 II 代表着太空探索的新时代，”NASA 局长 John Doe 表示。 “该任务将测试未来在月球进行长期停留所需的关键系统，”首席工程师 Sarah Johnson 解释道。 “我们不是回到月球，我们是在走向月球的未来，”指挥官 Jane Smith 在发射前新闻发布会上说。"
}}
```

示例 2（科学文章）：
```json
{{
   "summary": "《nature climate change》发表的一项新研究显示，全球海平面上升速度比此前认为的更快。研究人员分析了 1993–2022 年的卫星数据，发现过去三十年海平面上升速率以 0.08 mm/year² 的幅度加速。这一加速主要归因于格陵兰与南极冰盖融化。研究预测若当前趋势持续，全球海平面到 2100 年可能上升多达 2 米，将对全球沿海社区造成重大风险。",
   "key_excerpts": "“我们的发现表明海平面上升存在明确的加速趋势，这对沿海规划与适应策略具有重要意义，”第一作者 Emily Brown 博士表示。研究指出：“格陵兰和南极冰盖融化速率自 20 世纪 90 年代以来已增加到三倍。”共同作者 Michael Green 教授警告：“如果不立即并大幅减少温室气体排放，到本世纪末我们可能面临灾难性的海平面上升。”"
}}
```

请记住：你的目标是生成一个易于下游研究代理理解与使用、同时保留原文最关键细节的摘要。

今天的日期是 {date}。
"""

SUMMARIZE_WEBPAGE_PROMPT_EN = """  # noqa: E501
You are the best professional research assistant tasked with summarizing raw webpage content. Your goal is to create a summary that preserves the most important information for downstream research agents, so it's crucial to maintain the key details without losing essential information.

Here is the raw content of the webpage:

<webpage_content>
{webpage_content}
</webpage_content>

Please follow these guidelines to create your summary:

1. Identify and preserve the main topic or purpose of the webpage.
2. Retain key facts, statistics, and data points that are central to the content' message.
3. Keep important quotes from credible sources or experts.
4. Maintain the chronological order of events if the content is time-sensitive or historical.
5. Preserve any lists or step-by-step instructions if present.
6. Include relevant dates, names, and locations that are crucial to understanding the content.
7. Summarize lengthy explanations while keeping the core message intact.

When handling different types of content:

- For news articles: Focus on the who, what, when, where, why, and how.
- For scientific content: Preserve methodology, results, and conclusions.
- For opinion pieces: Maintain the main arguments and supporting points.
- For product pages: Keep key features, specifications, and unique selling points.
- For academic papers: Preserve research goals, methods, findings, and conclusions.

Your summary should be significantly shorter than the original content but comprehensive enough to stand alone as a source of information. Aim for about 25-30 percent of the original length, unless the content is already concise.
However, if the webpage is information-dense, do not over-compress. Prefer retaining valuable details (key facts, numbers, definitions, constraints, steps, caveats, and context) over hitting a strict length ratio. In such cases, it is acceptable for the summary to be longer than 30% (even up to ~70–80%) as long as it remains well-structured and avoids redundancy.

Output format (JSON):
```json
{{
   "summary": "Your summary here, structured with paragraphs or bullet points as needed",
   "key_excerpts": "First important quote or excerpt, Second important quote or excerpt, Third important quote or excerpt, ...Add more excerpts as needed."
}}
```

Here are two examples of good summaries:

Example 1 (for a news article):
```json
{{
   "summary": "On July 15, 2023, NASA successfully launched the Artemis II mission from Kennedy Space Center. This marks the first crewed mission to the Moon since Apollo 17 in 1972. The four-person crew, led by Commander Jane Smith, will orbit the Moon for 10 days before returning to Earth. This mission is a crucial step in NASA's plans to establish a permanent human presence on the Moon by 2030.",
   "key_excerpts": "Artemis II represents a new era in space exploration, said NASA Administrator John Doe. The mission will test critical systems for future long-duration stays on the Moon, explained Lead Engineer Sarah Johnson. We're not just going back to the Moon, we're going forward to the Moon, Commander Jane Smith stated during the pre-launch press conference."
}}
```

Example 2 (for a scientific article):
```json
{{
   "summary": "A new study published in Nature Climate Change reveals that global sea levels are rising faster than previously thought. Researchers analyzed satellite data from 1993 to 2022 and found that the rate of sea-level rise has accelerated by 0.08 mm/year² over the past three decades. This acceleration is primarily attributed to melting ice sheets in Greenland and Antarctica. The study projects that if current trends continue, global sea levels could rise by up to 2 meters by 2100, posing significant risks to coastal communities worldwide.",
   "key_excerpts": "Our findings indicate a clear acceleration in sea-level rise, which has significant implications for coastal planning and adaptation strategies, lead author Dr. Emily Brown stated. The rate of ice sheet melt in Greenland and Antarctica has tripled since the 1990s, the study reports. Without immediate and substantial reductions in greenhouse gas emissions, we are looking at potentially catastrophic sea-level rise by the end of this century, warned co-author Professor Michael Green."
}}
```

Remember, your goal is to create a summary that can be easily understood and utilized by a downstream research agent while preserving the most critical information from the original webpage.

Today's date is {date}.
"""


@dataclass
class SearchResultMeta:
    """Metadata for a search result used in reranking."""
    url: str
    title: str
    snippet: str = ''
    published_at: str = ''
    source_type: str = 'unknown'
    original_index: int = 0
    relevance_score: float = 0.0


@dataclass
class SummaryResult:
    """Result of content summarization."""
    summary: str
    key_excerpts: str
    original_length: int
    compressed_length: int
    compression_ratio: float
    success: bool = True
    error: str = ''
    # Usage tracking (for summarizer LLM calls)
    model: str = ''
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cache_creation_input_tokens: int = 0
    api_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return int(self.prompt_tokens or 0) + int(self.completion_tokens or 0)


@dataclass
class ContentOptimizerConfig:
    """Configuration for content optimization."""
    # Summarization settings
    summarizer_model: str = 'qwen-flash'
    summarizer_base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    summarizer_api_key: Optional[str] = None
    max_content_chars: int = 50000
    summarization_timeout: float = 90.0
    min_content_length_for_summary: int = 2000
    summarizer_max_workers: int = 5

    # Reranking settings
    enable_rerank: bool = True
    rerank_top_k: int = 3

    # Source type weights for reranking
    source_weights: Dict[str, float] = field(
        default_factory=lambda: {
            'official': 1.0,  # Official documentation, standards
            'paper': 0.95,  # Academic papers
            'news': 0.8,  # News sources
            'blog': 0.6,  # Technical blogs
            'forum': 0.4,  # Forums, Q&A sites
            'unknown': 0.5,
        })


# Domain patterns for source classification
OFFICIAL_DOMAINS = {
    'gov',
    'edu',
    'org',
    'int',  # TLDs
    'github.com',
    'gitlab.com',
    'bitbucket.org',  # Code repositories
    'docs.',
    'documentation.',
    'developer.',  # Documentation subdomains
}

PAPER_DOMAINS = {
    'arxiv.org',
    'doi.org',
    'sciencedirect.com',
    'springer.com',
    'nature.com',
    'science.org',
    'ieee.org',
    'acm.org',
    'ncbi.nlm.nih.gov',
    'pubmed',
    'researchgate.net',
    'semanticscholar.org',
    'openreview.net',
}

NEWS_DOMAINS = {
    'reuters.com',
    'bbc.com',
    'cnn.com',
    'nytimes.com',
    'theguardian.com',
    'wsj.com',
    'bloomberg.com',
    'techcrunch.com',
    'wired.com',
    'theverge.com',
    'arstechnica.com',
    'news.',
    'xinhua',
    'chinadaily',
    'sina.com',
    'sohu.com',
}

BLOG_DOMAINS = {
    'medium.com',
    'dev.to',
    'hashnode.com',
    'substack.com',
    'wordpress.com',
    'blogger.com',
    'csdn.net',
    'juejin.cn',
    'zhihu.com',
    'jianshu.com',
}

FORUM_DOMAINS = {
    'stackoverflow.com',
    'stackexchange.com',
    'reddit.com',
    'quora.com',
    'v2ex.com',
    'segmentfault.com',
}


def classify_source(url: str) -> str:
    """
    Classify a URL into source type categories.

    Args:
        url: The URL to classify

    Returns:
        Source type: 'official', 'paper', 'news', 'blog', 'forum', or 'unknown'
    """
    if not url:
        return 'unknown'

    try:
        parsed = urlparse(url.lower())
        domain = parsed.netloc
        path = parsed.path.lower()

        # Check TLD first
        parts = domain.split('.')
        tld = parts[-1] if parts else ''

        if tld in {'gov', 'edu', 'int'}:
            return 'official'

        # Check against domain patterns
        for paper_domain in PAPER_DOMAINS:
            if paper_domain in domain:
                return 'paper'

        # Check for documentation indicators
        if any(doc_pattern in domain
               for doc_pattern in ['docs.', 'documentation.', 'developer.']):
            return 'official'

        for news_domain in NEWS_DOMAINS:
            if news_domain in domain:
                return 'news'

        for blog_domain in BLOG_DOMAINS:
            if blog_domain in domain:
                return 'blog'

        for forum_domain in FORUM_DOMAINS:
            if forum_domain in domain:
                return 'forum'

        # Check path patterns
        if '/docs/' in path or '/documentation/' in path or '/api/' in path:
            return 'official'
        if '/paper/' in path or '/pdf/' in path or '/abstract/' in path:
            return 'paper'
        if '/blog/' in path or '/post/' in path or '/article/' in path:
            return 'blog'

        # GitHub/GitLab special handling
        if 'github.com' in domain or 'gitlab.com' in domain:
            return 'official'

        return 'unknown'

    except Exception:
        return 'unknown'


class ContentSummarizer:
    """
    Summarize webpage content using a fast LLM model.
    This class provides asynchronous content summarization with:
    - Timeout protection
    - Fallback to original content on failure
    - Structured output parsing
    - Compression ratio tracking

    Example usage:
        config = ContentOptimizerConfig(
            summarizer_model="qwen-turbo",
            max_content_chars=50000,
        )
        summarizer = ContentSummarizer(config)
        await summarizer.initialize()

        result = await summarizer.summarize(content, task_context="研究AI安全")
        print(result.summary)
    """

    def __init__(self, config: ContentOptimizerConfig):
        self.config = config
        self._llm: Optional[OpenAI] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._initialized = False

    def _build_llm_config(self) -> DictConfig:
        """Build a DictConfig for the OpenAI LLM class."""
        config_dict = {
            'llm': {
                'model': self.config.summarizer_model,
                'openai_base_url': self.config.summarizer_base_url,
                'openai_api_key': self.config.summarizer_api_key,
            },
            'generation_config': {},
        }
        return OmegaConf.create(config_dict)

    async def initialize(self) -> None:
        """Initialize the OpenAI LLM client for summarization."""
        if self._initialized:
            return

        try:
            llm_config = self._build_llm_config()
            self._llm = OpenAI(llm_config)
            self._executor = DaemonThreadPoolExecutor(
                max_workers=self.config.summarizer_max_workers,
                thread_name_prefix='content_summarizer_',
            )
            self._initialized = True
            logger.info(
                f'ContentSummarizer initialized with model: {self.config.summarizer_model}'
            )
        except Exception as e:
            logger.error(f'Failed to initialize ContentSummarizer: {e}')
            raise

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self._executor:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                self._executor.shutdown(wait=False)
            self._executor = None
        self._llm = None
        self._initialized = False

    def _get_today_str(self) -> str:
        """Get current date formatted for prompts."""
        now = datetime.now()
        return f'{now:%Y-%m-%d}'

    def _parse_summary_response(self, response_text: str) -> Tuple[str, str]:
        """
        Parse the LLM response to extract summary and key excerpts.

        Args:
            response_text: Raw LLM response text

        Returns:
            Tuple of (summary, key_excerpts)
        """
        # Try to find JSON in the response
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```',
                               response_text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                return data.get('summary', ''), data.get('key_excerpts', '')
            except json.JSONDecodeError:
                pass

        # Try direct JSON parsing
        try:
            # Find JSON object in the response
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}')
            if start_idx != -1 and end_idx != -1:
                json_str = response_text[start_idx:end_idx + 1]
                data = json.loads(json_str)
                return data.get('summary', ''), data.get('key_excerpts', '')
        except json.JSONDecodeError:
            pass

        # Fallback: return the whole response as summary
        return response_text.strip(), ''

    def _call_llm_sync(self, prompt: str) -> Message:
        """
        Synchronously call the LLM to generate a response.

        Args:
            prompt: The prompt to send to the LLM

        Returns:
            The generated response message (includes usage fields)
        """
        messages = [Message(role='user', content=prompt)]
        response = self._llm.generate(messages)
        return response

    async def summarize(self,
                        content: str,
                        task_context: str = '',
                        language: str = 'auto') -> SummaryResult:
        """
        Summarize webpage content using the configured LLM.

        Args:
            content: Raw webpage content to summarize
            task_context: Optional context about the research task
            language: Language for the summary ('auto', 'zh', 'en')

        Returns:
            SummaryResult with summary, key excerpts, and metadata
        """
        if not self._initialized:
            await self.initialize()

        original_length = len(content)

        # Skip summarization for short content
        if original_length < self.config.min_content_length_for_summary:
            return SummaryResult(
                summary=content,
                key_excerpts='',
                original_length=original_length,
                compressed_length=original_length,
                compression_ratio=1.0,
                success=True,
            )

        # Truncate content if too long
        content_to_summarize = content[:self.config.max_content_chars]

        # Detect language and select prompt
        if language == 'auto':
            # Simple heuristic: check for Chinese characters
            chinese_chars = len(
                re.findall(r'[\u4e00-\u9fff]', content_to_summarize[:1000]))
            language = 'zh' if chinese_chars > 30 else 'en'

        prompt_template = SUMMARIZE_WEBPAGE_PROMPT if language == 'zh' else SUMMARIZE_WEBPAGE_PROMPT_EN

        # Add task context if provided
        if task_context:
            prompt_template = f'研究任务背景：{task_context}\n\n' + prompt_template

        prompt = prompt_template.format(
            webpage_content=content_to_summarize,
            date=self._get_today_str(),
        )

        try:
            # Run synchronous LLM call in executor with timeout
            loop = asyncio.get_event_loop()
            response_msg: Message = await asyncio.wait_for(
                loop.run_in_executor(self._executor, self._call_llm_sync,
                                     prompt),
                timeout=self.config.summarization_timeout,
            )

            response_text = response_msg.content if response_msg.content else ''
            summary, key_excerpts = self._parse_summary_response(response_text)

            if not summary:
                # Parsing failed, use raw response
                summary = response_text

            compressed_length = len(summary)
            compression_ratio = compressed_length / original_length if original_length > 0 else 1.0

            logger.debug(
                f'Content summarized: {original_length} -> {compressed_length} chars '
                f'(ratio: {compression_ratio:.2%})')

            return SummaryResult(
                summary=summary,
                key_excerpts=key_excerpts,
                original_length=original_length,
                compressed_length=compressed_length,
                compression_ratio=compression_ratio,
                success=True,
                model=str(
                    getattr(self._llm, 'model', '')
                    or self.config.summarizer_model),
                prompt_tokens=int(
                    getattr(response_msg, 'prompt_tokens', 0) or 0),
                completion_tokens=int(
                    getattr(response_msg, 'completion_tokens', 0) or 0),
                cached_tokens=int(
                    getattr(response_msg, 'cached_tokens', 0) or 0),
                cache_creation_input_tokens=int(
                    getattr(response_msg, 'cache_creation_input_tokens', 0)
                    or 0),
                api_calls=int(getattr(response_msg, 'api_calls', 0) or 0),
            )

        except asyncio.TimeoutError:
            logger.warning(
                f'Summarization timed out after {self.config.summarization_timeout}s, '
                'returning truncated original content')
            # Return truncated original content
            truncated = content_to_summarize[:100000]
            return SummaryResult(
                summary=truncated,
                key_excerpts='',
                original_length=original_length,
                compressed_length=len(truncated),
                compression_ratio=len(truncated) / original_length,
                success=False,
                error='Timeout',
                model=self.config.summarizer_model,
            )

        except Exception as e:
            logger.warning(
                f'Summarization failed: {e}, returning truncated original content'
            )
            truncated = content_to_summarize[:100000]
            return SummaryResult(
                summary=truncated,
                key_excerpts='',
                original_length=original_length,
                compressed_length=len(truncated),
                compression_ratio=len(truncated) / original_length,
                success=False,
                error=str(e),
                model=self.config.summarizer_model,
            )

    async def summarize_batch(
        self,
        contents: List[Tuple[str, str]],  # List of (url, content) tuples
        task_context: str = '',
        max_concurrent: int = 5,
    ) -> Dict[str, SummaryResult]:
        """
        Summarize multiple pieces of content in parallel.

        Args:
            contents: List of (url, content) tuples
            task_context: Optional context about the research task
            max_concurrent: Maximum concurrent summarization tasks

        Returns:
            Dictionary mapping URL to SummaryResult
        """
        if not contents:
            return {}

        semaphore = asyncio.Semaphore(max_concurrent)

        async def _bounded_summarize(
                url: str, content: str) -> Tuple[str, SummaryResult]:
            async with semaphore:
                result = await self.summarize(content, task_context)
                return url, result

        tasks = [_bounded_summarize(url, content) for url, content in contents]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        summary_map = {}
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f'Batch summarization error: {result}')
                continue
            url, summary_result = result
            summary_map[url] = summary_result

        return summary_map


class SearchResultReranker:
    """
    Rerank and filter search results based on metadata relevance.

    This class provides:
    - Source type classification and weighting
    - Query-title relevance scoring
    - Recency scoring
    - Top-K filtering before content fetching

    Example usage:
        config = ContentOptimizerConfig(enable_rerank=True, rerank_top_k=3)
        reranker = SearchResultReranker(config)

        filtered_results = reranker.rerank(
            results=search_results,
            query="AI safety research methods",
            top_k=3,
        )
    """

    def __init__(self, config: ContentOptimizerConfig):
        self.config = config

    def _compute_title_relevance(self, query: str, title: str) -> float:
        """
        Compute relevance score between query and title.

        Args:
            query: Search query string
            title: Result title

        Returns:
            Relevance score between 0 and 1
        """
        if not query or not title:
            return 0.0

        # Normalize strings
        query_lower = query.lower()
        title_lower = title.lower()

        # Tokenize (simple word split)
        query_words = set(re.findall(r'\w+', query_lower))
        title_words = set(re.findall(r'\w+', title_lower))

        if not query_words:
            return 0.0

        # Calculate word overlap
        overlap = len(query_words & title_words)
        max_possible = len(query_words)

        # Jaccard-like score
        overlap_score = overlap / max_possible if max_possible > 0 else 0.0

        # Bonus for exact phrase match
        phrase_bonus = 0.2 if query_lower in title_lower else 0.0

        # Bonus for query at start of title
        start_bonus = 0.1 if title_lower.startswith(query_lower[:10]) else 0.0

        return min(1.0, overlap_score + phrase_bonus + start_bonus)

    def _compute_recency_score(self, published_at: str) -> float:
        """
        Compute recency score based on publication date.

        Args:
            published_at: Publication date string (various formats)

        Returns:
            Recency score between 0 and 1 (1 = very recent)
        """
        if not published_at:
            return 0.5  # Neutral score for unknown dates

        try:
            # Try common date formats
            date_patterns = [
                r'(\d{4})-(\d{2})-(\d{2})',  # 2024-01-15
                r'(\d{4})/(\d{2})/(\d{2})',  # 2024/01/15
                r'(\d{4})年(\d{1,2})月',  # 2024年1月
            ]

            year = None
            month = None

            for pattern in date_patterns:
                match = re.search(pattern, published_at)
                if match:
                    groups = match.groups()
                    year = int(groups[0])
                    if len(groups) > 1:
                        month = int(groups[1])
                    break

            if year:
                now = datetime.now()
                current_year = now.year
                current_month = now.month

                # Calculate months difference
                if month:
                    months_diff = (current_year - year) * 12 + (
                        current_month - month)
                else:
                    months_diff = (current_year - year) * 12

                # Decay function: full score for recent, decaying over time
                if months_diff <= 3:
                    return 1.0
                elif months_diff <= 12:
                    return 0.8
                elif months_diff <= 24:
                    return 0.6
                elif months_diff <= 60:
                    return 0.4
                else:
                    return 0.2

            return 0.5

        except Exception:
            return 0.5

    def _build_result_meta(
        self,
        result: Dict[str, Any],
        index: int,
        query: str,
    ) -> SearchResultMeta:
        """
        Build SearchResultMeta from a raw search result.

        Args:
            result: Raw search result dictionary
            index: Original index in search results
            query: Search query for relevance scoring

        Returns:
            SearchResultMeta with computed scores
        """
        url = result.get('url', '')
        title = result.get('title', '')
        snippet = result.get('summary', '') or result.get('snippet', '')
        published_at = result.get('published_date', '') or result.get(
            'published_at', '')

        source_type = classify_source(url)

        # Compute individual scores
        title_relevance = self._compute_title_relevance(query, title)
        snippet_relevance = self._compute_title_relevance(query, snippet) * 0.5
        source_weight = self.config.source_weights.get(source_type, 0.5)
        recency_score = self._compute_recency_score(published_at)

        # Weighted combination
        # Title relevance: 40%, Source type: 30%, Recency: 20%, Snippet: 10%
        relevance_score = (
            title_relevance * 0.4 + source_weight * 0.3 + recency_score * 0.2
            + snippet_relevance * 0.1)

        return SearchResultMeta(
            url=url,
            title=title,
            snippet=snippet,
            published_at=published_at,
            source_type=source_type,
            original_index=index,
            relevance_score=relevance_score,
        )

    def rerank(
        self,
        results: List[Dict[str, Any]],
        query: str,
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Rerank and filter search results by relevance.

        Args:
            results: List of search result dictionaries
            query: Search query for relevance scoring
            top_k: Number of top results to return (defaults to config.rerank_top_k)

        Returns:
            Reranked and filtered list of search results
        """
        if not results:
            return []

        if not self.config.enable_rerank:
            # Just return top_k without reranking
            k = top_k or self.config.rerank_top_k
            return results[:k]

        # Build metadata for all results
        metas = [
            self._build_result_meta(result, idx, query)
            for idx, result in enumerate(results)
        ]

        # Sort by relevance score (descending)
        sorted_pairs = sorted(
            zip(metas, results),
            key=lambda x: x[0].relevance_score,
            reverse=True,
        )

        # Apply top_k filter
        k = top_k or self.config.rerank_top_k
        top_results = [result for _, result in sorted_pairs[:k]]

        # Log reranking results
        if len(results) > k:
            original_top = [r.get('title', '')[:30] for r in results[:k]]
            new_top = [r.get('title', '')[:30] for r in top_results]
            logger.debug(
                f'Reranked {len(results)} results to top {k}: '
                f"original=[{', '.join(original_top)}] -> new=[{', '.join(new_top)}]"
            )

        return top_results

    @staticmethod
    def deduplicate_by_url(
            results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Remove duplicate results based on URL.

        Args:
            results: List of search result dictionaries

        Returns:
            Deduplicated list preserving first occurrence order
        """
        seen_urls = set()
        unique_results = []

        for result in results:
            url = result.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(result)

        return unique_results


class ContentOptimizer:
    """
    Integrated content optimization combining summarization and reranking.

    This is the main entry point for content optimization in the web search tool.

    Example usage:
        optimizer = ContentOptimizer(config)
        await optimizer.initialize()

        # Rerank results before fetching
        filtered_results = optimizer.rerank_results(results, query)

        # Summarize fetched content
        summaries = await optimizer.summarize_contents(contents, task_context)
    """

    def __init__(self, config: ContentOptimizerConfig):
        self.config = config
        self.summarizer = ContentSummarizer(config)
        self.reranker = SearchResultReranker(config)
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the optimizer (only summarizer needs initialization)."""
        if self._initialized:
            return
        await self.summarizer.initialize()
        self._initialized = True

    async def cleanup(self) -> None:
        """Cleanup resources."""
        await self.summarizer.cleanup()
        self._initialized = False

    def rerank_results(
        self,
        results: List[Dict[str, Any]],
        query: str,
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Rerank and filter search results.

        Args:
            results: Raw search results
            query: Search query
            top_k: Number of top results to keep

        Returns:
            Reranked and filtered results
        """
        # First deduplicate
        unique_results = self.reranker.deduplicate_by_url(results)
        # Then rerank
        return self.reranker.rerank(unique_results, query, top_k)

    async def summarize_content(
        self,
        content: str,
        task_context: str = '',
    ) -> str:
        """
        Summarize a single piece of content.

        Args:
            content: Raw content to summarize
            task_context: Optional research task context

        Returns:
            Summarized content string
        """
        if not self._initialized:
            await self.initialize()

        result = await self.summarizer.summarize(content, task_context)

        if result.key_excerpts:
            return f'<summary>\n{result.summary}\n</summary>\n\n<key_excerpts>\n{result.key_excerpts}\n</key_excerpts>'
        return result.summary

    async def summarize_contents(
        self,
        contents: List[Tuple[str, str]],
        task_context: str = '',
        max_concurrent: int = 5,
    ) -> Dict[str, str]:
        """

        Args:
            contents: List of (url, content) tuples
            task_context: Optional research task context
            max_concurrent: Maximum concurrent summarizations

        Returns:
            Dictionary mapping URL to summarized content
        """
        if not self._initialized:
            await self.initialize()

        results = await self.summarizer.summarize_batch(
            contents, task_context, max_concurrent)

        # Convert SummaryResult to formatted strings
        formatted = {}
        for url, result in results.items():
            if result.key_excerpts:
                formatted[url] = (
                    f'<summary>\n{result.summary}\n</summary>\n\n'
                    f'<key_excerpts>\n{result.key_excerpts}\n</key_excerpts>')
            else:
                formatted[url] = result.summary

        return formatted

    async def summarize_contents_with_usage(
        self,
        contents: List[Tuple[str, str]],
        task_context: str = '',
        max_concurrent: int = 5,
    ) -> Tuple[Dict[str, str], Dict[str, Any]]:
        """
        Summarize multiple pieces of content and also return token usage summary.

        Returns:
            (formatted_summaries, usage_report)
        """
        if not self._initialized:
            await self.initialize()

        results = await self.summarizer.summarize_batch(
            contents, task_context, max_concurrent)

        formatted: Dict[str, str] = {}
        # Aggregate usage across results (best-effort; failures may have 0 usage)
        usage_prompt = 0
        usage_completion = 0
        usage_cached = 0
        usage_cache_created = 0
        api_calls = 0
        model = self.config.summarizer_model

        for url, result in results.items():
            if result.key_excerpts:
                formatted[url] = (
                    f'<summary>\n{result.summary}\n</summary>\n\n'
                    f'<key_excerpts>\n{result.key_excerpts}\n</key_excerpts>')
            else:
                formatted[url] = result.summary

            # Prefer the per-result model if present
            if result.model:
                model = result.model
            usage_prompt += int(result.prompt_tokens or 0)
            usage_completion += int(result.completion_tokens or 0)
            usage_cached += int(result.cached_tokens or 0)
            usage_cache_created += int(result.cache_creation_input_tokens or 0)
            api_calls += int(result.api_calls or 0)

        usage_report: Dict[str, Any] = {
            'model': model,
            'pages': len(results),
            'api_calls': api_calls,
            'prompt_tokens': usage_prompt,
            'completion_tokens': usage_completion,
            'total_tokens': usage_prompt + usage_completion,
            'cached_tokens': usage_cached,
            'cache_creation_input_tokens': usage_cache_created,
        }

        return formatted, usage_report


def create_content_optimizer(
    summarizer_model: str = 'qwen-flash',
    summarizer_base_url:
    str = 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    summarizer_api_key: Optional[str] = None,
    max_content_chars: int = 500000,
    enable_rerank: bool = False,
    rerank_top_k: int = 3,
    **kwargs,
) -> ContentOptimizer:
    """
    Factory function to create a ContentOptimizer with common settings.

    Args:
        summarizer_model: Model name for summarization (default: qwen-flash)
        summarizer_base_url: API base URL
        summarizer_api_key: API key (falls back to environment variable)
        max_content_chars: Maximum content length for summarization
        enable_rerank: Whether to enable result reranking
        rerank_top_k: Number of top results to keep after reranking
        **kwargs: Additional config options

    Returns:
        Configured ContentOptimizer instance
    """
    config = ContentOptimizerConfig(
        summarizer_model=summarizer_model,
        summarizer_base_url=summarizer_base_url,
        summarizer_api_key=summarizer_api_key or os.getenv('OPENAI_API_KEY'),
        max_content_chars=max_content_chars,
        enable_rerank=enable_rerank,
        rerank_top_k=rerank_top_k,
        **kwargs,
    )

    return ContentOptimizer(config)
