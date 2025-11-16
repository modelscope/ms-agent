# flake8: noqa
# isort: skip_file
# yapf: disable
import asyncio
import base64
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gradio as gr
import json
import markdown
from ms_agent.agent.loader import AgentLoader
from ms_agent.config import Config
from ms_agent.tools.search.search_base import SearchEngineType
from ms_agent.utils.logger import get_logger
from ms_agent.workflow.dag_workflow import DagWorkflow
from omegaconf import DictConfig

logger = get_logger()

PROJECT_ROOT = Path(__file__).resolve().parents[0]
REPO_ROOT = Path(__file__).resolve().parents[2]
FIN_RESEARCH_CONFIG_DIR = PROJECT_ROOT / 'projects' / 'fin_research'
if not FIN_RESEARCH_CONFIG_DIR.exists():
    FIN_RESEARCH_CONFIG_DIR = REPO_ROOT / 'projects' / 'fin_research'
BASE_WORKDIR = PROJECT_ROOT / 'temp_workspace'
GRADIO_DEFAULT_CONCURRENCY_LIMIT = int(
    os.environ.get('GRADIO_DEFAULT_CONCURRENCY_LIMIT', '2'))
LOCAL_MODE = os.environ.get('LOCAL_MODE', 'true').lower() == 'true'
SEARCH_ENGINE_OVERRIDE_ENV = 'FIN_RESEARCH_SEARCH_ENGINE'
FIN_STATUS_TIMER_SIGNAL_ID = 'fin-status-timer-signal'
DEFAULT_TIMER_SIGNAL = json.dumps({'start': 0, 'elapsed': 0})

AGENT_SEQUENCE = [
    'orchestrator', 'searcher', 'collector', 'analyst', 'aggregator'
]

AGENT_LABELS = {
    'orchestrator': 'Orchestrator - 解析任务并拆解计划',
    'searcher': 'Searcher - 舆情与资讯深度研究',
    'collector': 'Collector - 结构化数据采集',
    'analyst': 'Analyst - 量化与可视化分析',
    'aggregator': 'Aggregator - 汇总生成综合报告'
}

AGENT_DUTIES = {
    'orchestrator': '解析任务并创建研究计划',
    'searcher': '进行舆情/新闻/资料搜索与梳理',
    'collector': '采集并整理结构化数据',
    'analyst': '执行量化与可视化分析',
    'aggregator': '汇总并生成综合报告'
}


class UserStatusManager:
    """Thread-safe concurrency tracker for multi-user isolation."""

    def __init__(self):
        self.active_users: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()

    def get_user_status(self, user_id: str) -> Dict[str, Any]:
        with self.lock:
            if user_id in self.active_users:
                info = self.active_users[user_id]
                elapsed = time.time() - info['start_time']
                return {
                    'status': info['status'],
                    'elapsed_time': elapsed,
                    'is_active': True
                }
        return {'status': 'idle', 'elapsed_time': 0, 'is_active': False}

    def start_user_task(self, user_id: str, task_id: str = ''):
        with self.lock:
            self.active_users[user_id] = {
                'start_time': time.time(),
                'status': 'running',
                'task_id': task_id
            }
            logger.info(
                f'FinResearch task started - User: {user_id[:8]}***, Task: {task_id}, Active users: {len(self.active_users)}'
            )

    def finish_user_task(self, user_id: str):
        with self.lock:
            if user_id in self.active_users:
                del self.active_users[user_id]
                logger.info(
                    f'FinResearch task finished - User: {user_id[:8]}***, Remaining: {len(self.active_users)}'
                )

    def is_user_running(self, user_id: str) -> bool:
        """Check if user has an active task running."""
        with self.lock:
            return user_id in self.active_users


user_status_manager = UserStatusManager()


def get_user_id_from_request(request: gr.Request) -> str:
    if request and hasattr(request, 'headers'):
        user_id = request.headers.get('x-modelscope-router-id', '')
        return user_id.strip() if user_id else ''
    return ''


def check_user_auth(request: gr.Request) -> Tuple[bool, str]:
    user_id = get_user_id_from_request(request)
    if not user_id:
        return False, '请登录后使用 | Please log in to launch FinResearch.'
    return True, user_id


def create_user_workdir(user_id: str) -> str:
    base_dir = Path(BASE_WORKDIR) / f'user_{user_id}'
    base_dir.mkdir(parents=True, exist_ok=True)
    return str(base_dir)


def create_task_workdir(user_id: str) -> str:
    user_dir = Path(create_user_workdir(user_id))
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    task_id = str(uuid.uuid4())[:8]
    workdir = user_dir / f'task_{timestamp}_{task_id}'
    workdir.mkdir(parents=True, exist_ok=True)
    return str(workdir)


def build_fin_prompt(
        goal: str,
        primary_tickers: str,
        benchmark_tickers: str,
        time_horizon: str,
        markets: str,
        focus_areas: List[str],
        extra_notes: str,
        output_language: str,
        macro_view: str,
        analysis_depth: int,
        deliverable_style: str,
        include_sentiment: bool,
        sentiment_weight: int) -> str:
    goal = (goal or '').strip()
    if not goal:
        raise ValueError('请输入研究目标 | Research goal cannot be empty.')

    sections = [f'Primary research objective:\n{goal}']

    if primary_tickers.strip():
        sections.append(f'Target tickers or instruments: {primary_tickers.strip()}')
    if benchmark_tickers.strip():
        sections.append(
            f'Benchmark / peer set to reference: {benchmark_tickers.strip()}')
    if time_horizon.strip():
        sections.append(f'Analysis window / guidance horizon: {time_horizon.strip()}')
    if markets.strip():
        sections.append(f'Market / region focus: {markets.strip()}')
    if focus_areas:
        sections.append(
            f'Priority analytical pillars: {", ".join(focus_areas)}')
    if macro_view:
        sections.append(f'Macro sensitivity preference: {macro_view}')
    if extra_notes.strip():
        sections.append(f'Additional analyst notes:\n{extra_notes.strip()}')

    instructions = [
        f'Desired deliverable style: {deliverable_style or "Balanced"}',
        f'Analytical depth target (1-5): {analysis_depth}'
    ]
    if output_language:
        instructions.append(
            f'Write the full report in {output_language}, including tables and summaries.'
        )
    instructions.append(
        'Integrate sandboxed quantitative analysis with qualitative reasoning.')

    if include_sentiment:
        instructions.append(
            f'Include a multi-source sentiment & news deep dive; sentiment emphasis level: {sentiment_weight}/5.'
        )
    else:
        instructions.append(
            'Skip the public sentiment/searcher agent and rely only on structured financial data.'
        )

    prompt = (
        'Please conduct a comprehensive financial research project following the structured plan below.\n\n'
        + '\n\n'.join(sections) + '\n\nExecution directives:\n- ' +
        '\n- '.join(instructions))
    return prompt


def convert_markdown_images_to_base64(markdown_content: str,
                                      workdir: str) -> str:
    pattern = r'!\[([^\]]*)\]\(([^)]+)\)'

    def replace_image(match):
        alt_text = match.group(1)
        image_path = match.group(2)
        full_path = image_path
        if not os.path.isabs(image_path):
            full_path = os.path.join(workdir, image_path)

        if os.path.exists(full_path):
            try:
                ext = os.path.splitext(full_path)[1].lower()
                mime_types = {
                    '.png': 'image/png',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.gif': 'image/gif',
                    '.bmp': 'image/bmp',
                    '.webp': 'image/webp',
                    '.svg': 'image/svg+xml'
                }
                mime_type = mime_types.get(ext, 'image/png')
                file_size = os.path.getsize(full_path)
                if file_size > 5 * 1024 * 1024:
                    return (f'**🖼️ 图片过大: {alt_text or os.path.basename(image_path)}**\n'
                            f'- 路径: `{image_path}`\n'
                            f'- 大小: {file_size / (1024 * 1024):.2f} MB (>5MB)\n')
                with open(full_path, 'rb') as img_file:
                    base64_data = base64.b64encode(img_file.read()).decode('utf-8')
                data_url = f'data:{mime_type};base64,{base64_data}'
                return f'![{alt_text}]({data_url})'
            except Exception as e:
                logger.info(f'Unable to convert image {full_path}: {e}')
                return f'**❌ 图片处理失败: {alt_text or os.path.basename(image_path)}**\n'
        return f'**❌ 图片文件不存在: {alt_text or image_path}**\n'

    return re.sub(pattern, replace_image, markdown_content)


def convert_markdown_images_to_file_info(markdown_content: str,
                                         workdir: str) -> str:
    pattern = r'!\[([^\]]*)\]\(([^)]+)\)'

    def replace_image(match):
        alt_text = match.group(1)
        image_path = match.group(2)
        full_path = os.path.join(workdir, image_path) if not os.path.isabs(
            image_path) else image_path
        if os.path.exists(full_path):
            size_mb = os.path.getsize(full_path) / (1024 * 1024)
            ext = os.path.splitext(full_path)[1].upper()
            return (f'**🖼️ 图片文件: {alt_text or os.path.basename(image_path)}**\n'
                    f'- 路径: `{image_path}`\n'
                    f'- 大小: {size_mb:.2f} MB\n'
                    f'- 格式: {ext}\n')
        return f'**❌ 图片文件不存在: {alt_text or image_path}**\n'

    return re.sub(pattern, replace_image, markdown_content)


def convert_markdown_to_html(markdown_content: str) -> str:
    latex_placeholders = {}
    placeholder_counter = 0

    def protect_latex(match):
        nonlocal placeholder_counter
        placeholder = f'LATEX_PLACEHOLDER_{placeholder_counter}'
        latex_placeholders[placeholder] = match.group(0)
        placeholder_counter += 1
        return placeholder

    protected_content = markdown_content
    protected_content = re.sub(r'\$\$([^$]+?)\$\$', protect_latex,
                               protected_content, flags=re.DOTALL)
    protected_content = re.sub(r'(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)',
                               protect_latex, protected_content)
    protected_content = re.sub(r'\\\[([^\\]+?)\\\]', protect_latex,
                               protected_content, flags=re.DOTALL)
    protected_content = re.sub(r'\\\(([^\\]+?)\\\)', protect_latex,
                               protected_content, flags=re.DOTALL)

    extensions = [
        'markdown.extensions.extra', 'markdown.extensions.codehilite',
        'markdown.extensions.toc', 'markdown.extensions.tables',
        'markdown.extensions.fenced_code', 'markdown.extensions.nl2br'
    ]
    extension_configs = {
        'markdown.extensions.codehilite': {
            'css_class': 'highlight',
            'use_pygments': True
        },
        'markdown.extensions.toc': {
            'permalink': True
        }
    }
    md = markdown.Markdown(
        extensions=extensions, extension_configs=extension_configs)
    html_content = md.convert(protected_content)
    for placeholder, latex_formula in latex_placeholders.items():
        html_content = html_content.replace(placeholder, latex_formula)
    container_id = f'katex-content-{int(time.time() * 1_000_000)}'

    styled_html = f"""
    <div class="markdown-html-content" id="{container_id}">
        <link rel="stylesheet"
              href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css"
              integrity="sha384-n8MVd4RsNIU0tAv4ct0nTaAbDJwPJzDEaqSD1odI+WdtXRGWt2kTvGFasHpSy3SV"
              crossorigin="anonymous">
        <div class="content-area">
            {html_content}
        </div>
        <script defer
            src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"
            integrity="sha384-XjKyOOlGwcjNTAIQHIpVOOVA+CuTF5UvLqGSXPM6njWx5iNxN7jyVjNOq8Ks4pxy"
            crossorigin="anonymous"></script>
        <script defer
            src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"
            integrity="sha384-+VBxd3r6XgURycqtZ117nYw44OOcIax56Z4dCRWbxyPt0Koah1uHoK0o4+/RRE05"
            crossorigin="anonymous"></script>
        <script type="text/javascript">
            (function() {{
                const containerId = '{container_id}';
                function renderKaTeX() {{
                    if (typeof renderMathInElement !== 'undefined') {{
                        renderMathInElement(document.getElementById(containerId), {{
                            delimiters: [
                                {{left: '$$', right: '$$', display: true}},
                                {{left: '$', right: '$', display: false}},
                                {{left: '\\\\[', right: '\\\\]', display: true}},
                                {{left: '\\\\(', right: '\\\\)', display: false}}
                            ],
                            throwOnError: false
                        }});
                    }} else {{
                        setTimeout(renderKaTeX, 200);
                    }}
                }}
                setTimeout(renderKaTeX, 200);
            }})();
        </script>
    </div>
    """
    return styled_html


def read_plan_file(workdir: str) -> str:
    plan_path = Path(workdir) / 'plan.json'
    if not plan_path.exists():
        return '未找到 plan.json'
    try:
        with open(plan_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.info(f'Failed to read plan.json: {e}')
        return '⚠️ plan.json 读取失败'


def read_markdown_report(workdir: str,
                         filename: str) -> Tuple[str, str, str]:
    report_path = Path(workdir) / filename
    if not report_path.exists():
        return '', '', f'未找到 {filename}'
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()
        try:
            processed_markdown = convert_markdown_images_to_base64(
                markdown_content, workdir)
        except Exception as e:
            logger.info(f'Base64 conversion failed: {e}')
            processed_markdown = convert_markdown_images_to_file_info(
                markdown_content, workdir)

        if LOCAL_MODE:
            return processed_markdown, processed_markdown, ''
        try:
            processed_html = convert_markdown_to_html(processed_markdown)
        except Exception as e:
            logger.info(f'HTML conversion failed: {e}')
            processed_html = processed_markdown
        return processed_markdown, processed_html, ''
    except Exception as e:
        return '', '', f'读取 {filename} 失败: {str(e)}'


def list_output_files(workdir: str, limit: int = 200) -> str:
    base = Path(workdir)
    if not base.exists():
        return '未找到输出目录'
    entries = []
    for root, _, files in os.walk(base):
        for file in files:
            rel_path = Path(root, file).relative_to(base)
            size_kb = os.path.getsize(Path(root, file)) / 1024
            entries.append(f'{rel_path} ({size_kb:.1f} KB)')
    entries.sort()
    if not entries:
        return '📂 输出目录为空'
    if len(entries) > limit:
        displayed = entries[:limit]
        displayed.append(f'... 其余 {len(entries) - limit} 个文件已省略')
        entries = displayed
    return '📁 输出文件:\n' + '\n'.join(f'• {item}' for item in entries)


def ensure_workdir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


class FinResearchWorkflowRunner:
    def __init__(self,
                 workdir: str,
                 include_sentiment: bool = True,
                 search_depth: int = 1,
                 search_breadth: int = 3,
                 search_api_key: Optional[str] = None):
        self.workdir = workdir
        self.include_sentiment = include_sentiment
        self.search_depth = search_depth
        self.search_breadth = search_breadth
        self.search_api_key = search_api_key

    def _parse_search_api_overrides(self) -> Tuple[Dict[str, str], Optional[str]]:
        overrides: Dict[str, str] = {}
        preferred_engine: Optional[str] = None
        if not self.search_api_key:
            return overrides, preferred_engine

        raw_entries = re.split(r'[,\n;]+', self.search_api_key)
        for entry in raw_entries:
            entry = entry.strip()
            if not entry:
                continue
            if ':' in entry:
                engine, key_val = [p.strip() for p in entry.split(':', 1)]
                if not key_val:
                    continue
                engine_norm = engine.lower()
                if engine_norm == 'exa':
                    overrides['EXA_API_KEY'] = key_val
                    if preferred_engine is None:
                        preferred_engine = SearchEngineType.EXA.value
                elif engine_norm in ('serpapi', 'serp', 'searpapi'):
                    overrides['SERPAPI_API_KEY'] = key_val
                    if preferred_engine is None:
                        preferred_engine = SearchEngineType.SERPAPI.value
                else:
                    logger.warning(
                        f'Unsupported search engine prefix "{engine}" provided; ignoring entry.'
                    )
            else:
                # No prefix -> set both for backward compatibility
                overrides['EXA_API_KEY'] = entry
                overrides['SERPAPI_API_KEY'] = entry
        return overrides, preferred_engine

    @staticmethod
    def _apply_runtime_env(env_overrides: Dict[str, str]) -> Dict[str, Optional[str]]:
        """Apply environment overrides - returns snapshot for restoration.
        Note: In multi-user scenarios, env vars are shared globally.
        Use env dict passed to workflow instead where possible."""
        applied: Dict[str, Optional[str]] = {}
        if not env_overrides:
            return applied
        # Only apply non-conflicting environment variables
        # Critical settings like output_dir are passed via workflow env dict
        for key, value in env_overrides.items():
            if not key or value is None:
                continue
            if not key.isupper():
                continue
            # Skip applying certain vars globally to avoid cross-user conflicts
            if key in ['output_dir']:
                continue
            applied[key] = os.environ.get(key)
            os.environ[key] = str(value)
        return applied

    @staticmethod
    def _restore_runtime_env(snapshot: Dict[str, Optional[str]]):
        if not snapshot:
            return
        for key, prev in snapshot.items():
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

    def _prepare_config(self,
                        env_overrides: Dict[str, str]) -> Config:
        config = Config.from_task(str(FIN_RESEARCH_CONFIG_DIR), env_overrides)
        if not self.include_sentiment:
            if 'searcher' in config:
                del config['searcher']
            if hasattr(config.orchestrator, 'next'):
                config.orchestrator.next = ['collector']
        else:
            if 'searcher' in config:
                setattr(config.searcher, 'depth', self.search_depth)
                setattr(config.searcher, 'breadth', self.search_breadth)
        return config

    def run(self, user_prompt: str, status_callback=None):
        env_overrides = {'output_dir': self.workdir}

        key_overrides, preferred_engine = self._parse_search_api_overrides()
        env_overrides.update(key_overrides)
        if preferred_engine:
            env_overrides[SEARCH_ENGINE_OVERRIDE_ENV] = preferred_engine

        applied_env = self._apply_runtime_env(env_overrides)
        try:
            config = self._prepare_config(env_overrides)
            workflow = TrackedDagWorkflow(
                config=config,
                env=env_overrides,
                trust_remote_code=True,
                load_cache=False,
                status_callback=status_callback)

            async def _execute():
                return await workflow.run(user_prompt)

            try:
                return asyncio.run(_execute())
            except RuntimeError as exc:
                # Fallback if an event loop is already running
                logger.info(f'Fallback loop for FinResearch: {exc}')
                loop = asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(_execute())
                finally:
                    loop.close()
        finally:
            self._restore_runtime_env(applied_env)


def format_result_summary(workdir: str, include_sentiment: bool,
                          output_language: str,
                          focus_areas: List[str]) -> str:
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = [
        '✅ FinResearch 工作流执行完成！',
        f'- 完成时间: {timestamp}',
        f'- 工作目录: {workdir}',
        f'- 舆情深研模块: {"启用" if include_sentiment else "关闭"}',
        f'- 输出语言: {output_language or "依据输入自动匹配"}'
    ]
    if focus_areas:
        lines.append(f'- 关注领域: {", ".join(focus_areas)}')
    lines.append('请查阅研究计划、数据分析报告及最终综合报告。')
    return '\n'.join(lines)


def collect_fin_reports(workdir: str,
                        include_sentiment: bool) -> Dict[str, Dict[str, str]]:
    reports = {}
    plan_text = read_plan_file(workdir)
    plan_path = Path(workdir) / 'plan.json'
    reports['plan'] = {'content': plan_text, 'path': str(plan_path)}

    final_path = Path(workdir) / 'report.md'
    final_md, final_html, final_err = read_markdown_report(workdir, 'report.md')
    reports['final'] = {
        'markdown': final_md,
        'html': final_html,
        'error': final_err,
        'path': str(final_path) if final_path.exists() else ''
    }

    analysis_md, analysis_html, analysis_err = read_markdown_report(
        workdir, 'analysis_report.md')
    analysis_path = Path(workdir) / 'analysis_report.md'
    reports['analysis'] = {
        'markdown': analysis_md,
        'html': analysis_html,
        'error': analysis_err,
        'path': str(analysis_path) if analysis_path.exists() else ''
    }

    sentiment_md, sentiment_html, sentiment_err = ('', '', '')
    if include_sentiment:
        sentiment_md, sentiment_html, sentiment_err = read_markdown_report(
            workdir, 'sentiment_report.md')
        sentiment_path = Path(workdir) / 'sentiment_report.md'
    else:
        sentiment_md = '舆情模块已关闭，本次未执行搜索工作流。'
        sentiment_path = Path(workdir) / 'sentiment_report.md'
    reports['sentiment'] = {
        'markdown': sentiment_md,
        'html': sentiment_html,
        'error': sentiment_err,
        'path': str(sentiment_path) if sentiment_path.exists() else ''
    }
    reports['resources'] = list_output_files(workdir)
    return reports


def run_fin_research_workflow(
        research_goal,
        search_depth,
        search_breadth,
        search_api_key,
        request: gr.Request,
        progress=gr.Progress()):
    user_id = None
    task_workdir = None
    try:
        local_mode = LOCAL_MODE
        if not local_mode:
            is_auth, user_id_or_error = check_user_auth(request)
            if not is_auth:
                return (
                    DEFAULT_TIMER_SIGNAL,
                    f'❌ 认证失败：{user_id_or_error}',
                    '⚠️ Failed',
                    '',
                    '⚠️ Failed',
                    '',
                    '⚠️ Failed',
                    '',
                    '未能列出输出文件',
                    None,
                    None,
                    None)
            user_id = user_id_or_error
        else:
            # Generate unique user ID for local mode per session
            user_id = get_user_id_from_request(request) or f'local_user_{uuid.uuid4().hex[:12]}'

        progress(0.05, desc='验证输入...')
        if not research_goal or not research_goal.strip():
            return (
                DEFAULT_TIMER_SIGNAL,
                '❌ 输入错误：请填写研究目标。',
                '⚠️ Failed',
                '',
                '⚠️ Failed',
                '',
                '⚠️ Failed',
                '',
                '未能列出输出文件',
                None,
                None,
                None)

        search_depth = int(search_depth or 1)
        search_breadth = int(search_breadth or 3)
        search_api_key = (search_api_key or '').strip()
        extra_notes = (f'请按照以下舆情搜索参数执行深度研究：depth={search_depth}, '
                       f'breadth={search_breadth}。')
        fin_prompt = build_fin_prompt(
            research_goal,
            primary_tickers='',
            benchmark_tickers='',
            time_horizon='',
            markets='',
            focus_areas=[],
            extra_notes=extra_notes,
            output_language='',
            macro_view='Balanced',
            analysis_depth=4,
            deliverable_style='Balanced',
            include_sentiment=True,
            sentiment_weight=3)

        progress(0.1, desc='创建工作目录...')
        task_workdir = create_task_workdir(user_id)
        task_id = Path(task_workdir).name
        ensure_workdir(Path(task_workdir))
        progress(0.15, desc='启动 FinResearch 工作流...')
        user_status_manager.start_user_task(user_id, task_id)

        status_tracker = StatusTracker(include_searcher=True)

        def build_timer_signal(elapsed_seconds: Optional[int] = None) -> str:
            elapsed_val = (elapsed_seconds if elapsed_seconds is not None else
                           int(time.time() - status_tracker.start_time))
            return json.dumps({
                'start': int(status_tracker.start_time),
                'elapsed': max(0, elapsed_val)
            })

        runner = FinResearchWorkflowRunner(
            workdir=task_workdir,
            include_sentiment=True,
            search_depth=search_depth,
            search_breadth=search_breadth,
            search_api_key=search_api_key or None)
        # Run in background to stream status updates
        run_exc: List[Optional[BaseException]] = [None]
        def _bg_run():
            try:
                runner.run(fin_prompt, status_callback=status_tracker.update)
            except BaseException as e:
                run_exc[0] = e
        bg_thread = threading.Thread(target=_bg_run, daemon=True)
        bg_thread.start()

        # Stream status while running (only when state changes to avoid flicker)
        last_rev = -1
        last_emit_ts = 0.0
        while bg_thread.is_alive():
            now_ts = time.time()
            revision_changed = status_tracker.revision != last_rev
            if revision_changed or now_ts - last_emit_ts >= 1.0:
                if revision_changed:
                    last_rev = status_tracker.revision
                last_emit_ts = now_ts
                elapsed_now = int(now_ts - status_tracker.start_time)
                status_html = (
                    status_tracker.render(elapsed_seconds=elapsed_now)
                    if revision_changed else gr.update())
                yield (
                    build_timer_signal(elapsed_now),
                    status_html,
                    '⌛ Waiting...',
                    '',
                    '⌛ Waiting...',
                    '',
                    '⌛ Waiting...',
                    '',
                    '📂 正在生成输出文件，请稍候...',
                    None,
                    None,
                    None,
                )
            time.sleep(0.2)

        if run_exc[0] is not None:
            raise run_exc[0]

        progress(0.85, desc='整理输出结果...')

        reports = collect_fin_reports(task_workdir, include_sentiment=True)

        progress(0.95, desc='生成总结...')
        final_elapsed = int(time.time() - status_tracker.start_time)
        status_text = status_tracker.render(elapsed_seconds=final_elapsed)
        progress(1.0, desc='完成')

        if LOCAL_MODE:
            final_report_value = reports['final']['markdown'] or reports[
                'final']['error']
            analysis_value = reports['analysis']['markdown'] or reports[
                'analysis']['error']
            sentiment_value = reports['sentiment']['markdown'] or reports[
                'sentiment']['error']
        else:
            final_report_value = reports['final']['html'] or reports['final'][
                'error']
            analysis_value = reports['analysis']['html'] or reports[
                'analysis']['error']
            sentiment_value = reports['sentiment']['html'] or reports[
                'sentiment']['error']

        # Prepare download button values - only set if file exists
        final_download_path = reports['final']['path'] if reports['final']['path'] and Path(reports['final']['path']).exists() else None
        analysis_download_path = reports['analysis']['path'] if reports['analysis']['path'] and Path(reports['analysis']['path']).exists() else None
        sentiment_download_path = reports['sentiment']['path'] if reports['sentiment']['path'] and Path(reports['sentiment']['path']).exists() else None

        yield (
            build_timer_signal(final_elapsed),
            status_text,
            '✅ Ready' if final_download_path else '⌛ Waiting...',
            final_report_value,
            '✅ Ready' if analysis_download_path else '⌛ Waiting...',
            analysis_value,
            '✅ Ready' if sentiment_download_path else '⌛ Waiting...',
            sentiment_value,
            reports['resources'],
            final_download_path,
            analysis_download_path,
            sentiment_download_path,
        )
    except Exception as e:
        logger.exception('FinResearch workflow failed')
        final_elapsed = int(time.time() - status_tracker.start_time
                            ) if 'status_tracker' in locals() else 0
        timer_payload = (build_timer_signal(final_elapsed)
                         if 'status_tracker' in locals() else DEFAULT_TIMER_SIGNAL)
        return (
            timer_payload,
            f'❌ 执行失败：{str(e)}',
            '⚠️ Failed',
            '',
            '⚠️ Failed',
            '',
            '⚠️ Failed',
            '',
            '未能列出输出文件，请检查日志',
            None,
            None,
            None,
        )
    finally:
        user_status_manager.finish_user_task(user_id if 'user_id' in locals()
                                             else 'unknown')


def clear_user_workspace(request: gr.Request):
    try:
        if not LOCAL_MODE:
            is_auth, user_id_or_error = check_user_auth(request)
            if not is_auth:
                return (
                    DEFAULT_TIMER_SIGNAL,
                    f'❌ 认证失败：{user_id_or_error}',
                    '⚠️ Failed',
                    '',
                    '⚠️ Failed',
                    '',
                    '⚠️ Failed',
                    '',
                    '未能列出输出文件',
                    None,
                    None,
                    None)
            user_id = user_id_or_error
        else:
            # In LOCAL_MODE, use the same user_id logic as workflow
            user_id = get_user_id_from_request(request) or 'local_default'

        # Check if user has active tasks
        if user_status_manager.is_user_running(user_id):
            return (
                DEFAULT_TIMER_SIGNAL,
                '⚠️ 当前用户有正在运行的任务，无法清理工作空间。请等待任务完成后再试。\n\n⚠️ Cannot clear workspace: User has active task running. Please wait for completion.',
                '⚠️ Active Task',
                '',
                '⚠️ Active Task',
                '',
                '⚠️ Active Task',
                '',
                '无法清理：任务进行中',
                None,
                None,
                None)

        user_dir = Path(create_user_workdir(user_id))
        if user_dir.exists():
            shutil.rmtree(user_dir)
            logger.info(f'Workspace cleared for user: {user_id[:8]}***')
        return (
            DEFAULT_TIMER_SIGNAL,
            '✅ 工作空间已清理。准备好下一次任务。\n\n✅ Workspace cleared. Ready for next task.',
            '⌛ Waiting...',
            '',
            '⌛ Waiting...',
            '',
            '⌛ Waiting...',
            '',
            '📂 输出文件已清空',
            None,
            None,
            None)
    except Exception as e:
        logger.exception('Failed to clear workspace')
        return (
            DEFAULT_TIMER_SIGNAL,
            f'❌ 清理失败：{str(e)}\n\n❌ Clear failed: {str(e)}',
            '⚠️ Failed',
            '',
            '⚠️ Failed',
            '',
            '⚠️ Failed',
            '',
            '未能列出输出文件',
            None,
            None,
            None)


class StatusTracker:

    def __init__(self, include_searcher: bool = True):
        self.include_searcher = include_searcher
        self.messages: List[Dict[str, str]] = []
        self.current_agent: Optional[str] = None
        self.current_agent_key: Optional[str] = None
        self.start_time = time.time()
        self.revision = 0

    def update(self, agent: str, phase: str, output: str = ''):
        """Update status with agent name, phase, and optional output"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        label = AGENT_LABELS.get(agent, agent)

        if phase == 'start':
            self.current_agent = label
            self.current_agent_key = agent
            # Add a "working" message
            self.messages.append({
                'time': timestamp,
                'agent': label,
                'status': 'working',
                'content': AGENT_DUTIES.get(agent, '正在执行任务'),
                'raw': ''
            })
            self.revision += 1
        else:
            # Update the last message with completion status and output
            if self.messages and self.messages[-1]['agent'] == label:
                self.messages[-1]['status'] = 'completed'
                if output:
                    # Support "preview||RAW||full" protocol for rich display
                    preview = output
                    full_raw = ''
                    if '||RAW||' in output:
                        parts = output.split('||RAW||', 1)
                        preview = parts[0].strip()
                        full_raw = parts[1].strip()
                    # Truncate preview for bubble
                    max_len = 140
                    short_preview = preview[:max_len] + '...' if len(preview) > max_len else preview
                    self.messages[-1]['content'] = short_preview
                    self.messages[-1]['raw'] = full_raw or preview
                else:
                    self.messages[-1]['content'] = '✓ 任务完成'
            self.current_agent = None
            self.current_agent_key = None
            self.revision += 1

    @staticmethod
    def _format_elapsed(seconds: int) -> str:
        seconds = max(0, seconds)
        minutes, secs = divmod(seconds, 60)
        if minutes:
            return f'{minutes}分{secs}秒'
        return f'{secs}秒'

    def render(self, elapsed_seconds: Optional[int] = None) -> str:
        if elapsed_seconds is None:
            elapsed_seconds = int(time.time() - self.start_time)
        elapsed_seconds = max(0, elapsed_seconds)
        elapsed_label = self._format_elapsed(elapsed_seconds)
        # Build chat-like messages
        messages_html = []
        for idx, msg in enumerate(self.messages):
            agent_name = msg['agent'].split(' - ')[0]  # Get short name
            content = msg['content']
            raw_full = msg.get('raw', '')
            time_str_msg = msg['time']

            if msg['status'] == 'working':
                # Working status with animated dots
                msg_class = 'agent-message working'
                # Use a CSS spinner instead of animated dots for clearer progress indication
                content_html = f'<span class="working-text">{content}<span class="spinner"></span></span>'
            else:
                # Completed status
                msg_class = 'agent-message completed'
                details_block = f'''
                <details data-id="{idx}">
                    <summary class="agent-summary">查看完整工作结果（点击展开）</summary>
                    <div class="agent-details" style="margin-top:0.5rem;">
                        <pre style="white-space: pre-wrap; word-break: break-word;">{raw_full or content}</pre>
                    </div>
                </details>
                '''
                content_html = f'<div class="agent-preview">{content}</div>{details_block}'

            messages_html.append(f'''
            <div class="{msg_class}">
                <div class="agent-header">
                    <span class="agent-name">{agent_name}</span>
                    <span class="agent-time">{time_str_msg}</span>
                </div>
                <div class="agent-content">{content_html}</div>
            </div>
            ''')

        if not messages_html:
            messages_html.append('''
            <div class="agent-message waiting">
                <div class="agent-content">⏳ 等待执行...</div>
            </div>
            ''')

        auto_scroll_js = """
        <script>
        (function() {
            try {
                var c = document.querySelector('.status-messages');
                if (c) {
                    var nearBottom = (c.scrollHeight - (c.scrollTop + c.clientHeight)) < 60;
                    if (nearBottom) { c.scrollTop = c.scrollHeight; }
                }
                // Elapsed time ticker
                var t = document.querySelector('.status-header .status-time');
                if (t && !t.dataset.bound) {
                    t.dataset.bound = '1';
                    var startTs = __START_TS__;
                    var tick = function() {
                        var now = Math.floor(Date.now() / 1000);
                        var elapsed = Math.max(0, now - startTs);
                        var m = Math.floor(elapsed / 60);
                        var s = elapsed % 60;
                        t.textContent = '⏱️ ' + (m > 0 ? (m + '分' + s + '秒') : (s + '秒'));
                    };
                    tick();
                    setInterval(tick, 1000);
                }
                // Persist details open state
                var key = 'fin_status_open_map';
                var openMap = {};
                try { openMap = JSON.parse(localStorage.getItem(key) || '{}'); } catch(e) {}
                document.querySelectorAll('.status-messages details[data-id]').forEach(function(d) {
                    var id = d.getAttribute('data-id');
                    if (openMap[id]) d.setAttribute('open', '');
                    d.addEventListener('toggle', function() {
                        openMap[id] = d.open;
                        try { localStorage.setItem(key, JSON.stringify(openMap)); } catch(e) {}
                    });
                });
            } catch(e) {}
        })();
        </script>
        """
        auto_scroll_js = auto_scroll_js.replace('__START_TS__', str(int(self.start_time)))
        return f'''
        <div class="status-container">
            <div class="status-header">
                <span class="status-title">执行状态</span>
                <span class="status-time" data-start="{int(self.start_time)}" data-elapsed="{elapsed_seconds}">⏱️ {elapsed_label}</span>
            </div>
            <div class="status-messages">
                {''.join(messages_html)}
            </div>
        </div>
        {auto_scroll_js}
        '''


class TrackedDagWorkflow(DagWorkflow):

    def __init__(self, *args, status_callback=None, **kwargs):
        self.status_callback = status_callback
        super().__init__(*args, **kwargs)

    async def run(self, inputs, **kwargs):
        outputs: Dict[str, Any] = {}
        for task in self.topo_order:
            if task in self.roots:
                task_input = inputs
            else:
                parent_outs = [outputs[p] for p in self.parents[task]]
                task_input = parent_outs if len(parent_outs) > 1 else parent_outs[
                    0]

            if self.status_callback:
                self.status_callback(task, 'start', '')

            task_info = getattr(self.config, task)
            agent_cfg_path = os.path.join(self.config.local_dir,
                                          task_info.agent_config)
            if not hasattr(task_info, 'agent'):
                task_info.agent = DictConfig({})
            init_args = getattr(task_info.agent, 'kwargs', {})
            init_args['trust_remote_code'] = self.trust_remote_code
            init_args['mcp_server_file'] = self.mcp_server_file
            init_args['task'] = task
            init_args['load_cache'] = self.load_cache
            init_args['config_dir_or_id'] = agent_cfg_path
            init_args['env'] = self.env
            if 'tag' not in init_args:
                init_args['tag'] = task
            engine = AgentLoader.build(**init_args)
            result = await engine.run(task_input)
            outputs[task] = result

            if self.status_callback:
                # Agent-specific output extraction with preview/raw protocol
                def get_msg_content(x):
                    if isinstance(x, dict):
                        return str(x.get('content', ''))
                    return str(getattr(x, 'content', '') or x)

                def find_path_in_text(text: str) -> Optional[str]:
                    import re as _re
                    m = _re.search(r'([^\s\'"]+\.(?:md|json|txt|csv|html))', text or '')
                    return m.group(1) if m else None

                def read_text_safe(path_text: str) -> str:
                    try:
                        if not path_text:
                            return ''
                        path_abs = path_text
                        workdir = self.env.get('output_dir') if isinstance(self.env, dict) else None
                        if workdir and not os.path.isabs(path_abs):
                            path_abs = os.path.join(workdir, path_abs)
                        if os.path.exists(path_abs) and os.path.isfile(path_abs):
                            with open(path_abs, 'r', encoding='utf-8') as f:
                                data = f.read()
                            # limit to avoid huge payloads
                            return data[:8000]
                    except Exception:
                        return ''
                    return ''

                preview = ''
                raw_full = ''
                try:
                    # Normalize result to a messages list when possible
                    messages_list = None
                    if isinstance(result, list):
                        messages_list = result
                    elif isinstance(result, dict) and isinstance(result.get('messages'), list):
                        messages_list = result.get('messages')

                    if task == 'orchestrator' and messages_list and len(messages_list) >= 2:
                        last_msg = get_msg_content(messages_list[-1])
                        second_last = get_msg_content(messages_list[-2])
                        # order: last (path) first, then plan json
                        preview = f'{last_msg}\n\n{second_last}'
                        raw_full = preview
                    elif task == 'searcher':
                        if messages_list and len(messages_list) >= 1:
                            last_msg = get_msg_content(messages_list[-1])
                            report_path = find_path_in_text(last_msg)
                            report_content = read_text_safe(report_path) if report_path else ''
                            # Fallback: try default sentiment_report.md in workdir
                            if not report_content:
                                try:
                                    workdir = self.env.get('output_dir') if isinstance(self.env, dict) else None
                                    fallback_path = os.path.join(workdir, 'sentiment_report.md') if workdir else None
                                    report_content = read_text_safe(fallback_path)
                                    if not report_path and fallback_path:
                                        report_path = fallback_path
                                except Exception:
                                    pass
                            preview = last_msg if last_msg else (report_path or '')
                            raw_full = report_content or last_msg
                        else:
                            preview = str(result)
                            raw_full = preview
                    elif task == 'collector':
                        # last message summary text
                        if messages_list and len(messages_list) >= 1:
                            last_msg = get_msg_content(messages_list[-1])
                            preview = last_msg
                            raw_full = last_msg
                        else:
                            preview = str(result)
                            raw_full = preview
                    elif task == 'analyst':
                        if messages_list and len(messages_list) >= 2:
                            last_msg = get_msg_content(messages_list[-1])      # path to report
                            second_last = get_msg_content(messages_list[-2])   # report content (likely)
                            preview = f'{last_msg}\n\n{second_last}'
                            raw_full = preview
                        elif messages_list and len(messages_list) >= 1:
                            last_msg = get_msg_content(messages_list[-1])
                            preview = last_msg
                            raw_full = last_msg
                        else:
                            preview = str(result)
                            raw_full = preview
                    elif task == 'aggregator':
                        # final comprehensive report; show only first few lines in preview
                        if messages_list and len(messages_list) >= 1:
                            last_msg = get_msg_content(messages_list[-1])
                            lines = (last_msg or '').splitlines()
                            preview = '\n'.join(lines[:20])  # first few lines
                            raw_full = last_msg
                        else:
                            preview = str(result)
                            raw_full = preview
                    else:
                        # Fallback: last message content or str(result)
                        if messages_list and len(messages_list) >= 1:
                            preview = get_msg_content(messages_list[-1])
                            raw_full = preview
                        else:
                            preview = str(result)
                            raw_full = preview
                except Exception:
                    preview = str(result)
                    raw_full = preview

                self.status_callback(task, 'end', f'{preview}||RAW||{raw_full}')

        terminals = [
            t for t in self.config.keys() if t not in self.graph and t in self.nodes
        ]
        return {t: outputs[t] for t in terminals}


def create_interface():
    with gr.Blocks(
            title='FinResearch Workflow App',
            theme=gr.themes.Soft(),
            css="""
        /* Container optimization */
        .gradio-container {
            max-width: 1600px !important;
            margin: 0 auto !important;
            padding: 1rem 2rem !important;
        }

        @media (min-width: 1800px) {
            .gradio-container {
                max-width: 1800px !important;
                padding: 0 3rem !important;
            }
        }

        /* Main header styles */
        .main-header {
            text-align: center;
            margin-bottom: 2rem;
            padding: 1.5rem 0;
            background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
            border-radius: 1rem;
            color: white;
            box-shadow: 0 4px 6px rgba(59, 130, 246, 0.2);
        }

        .main-header h1 {
            font-size: clamp(1.8rem, 4vw, 2.5rem);
            margin-bottom: 0.5rem;
            font-weight: 700;
        }

        .main-header p {
            font-size: clamp(1rem, 1.5vw, 1.2rem);
            margin: 0;
            opacity: 0.95;
        }

        /* Section headers */
        .section-header {
            color: #2563eb;
            font-weight: 600;
            margin: 1rem 0 0.75rem 0;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid #e5e7eb;
            font-size: clamp(1rem, 1.5vw, 1.2rem);
        }

        /* Column styling */
        .input-column {
            padding-right: 1.5rem;
            border-right: 1px solid var(--border-color-primary);
        }

        .output-column {
            padding-left: 1.5rem;
        }

        /* Status container - chat style */
        .status-container {
            border: 1px solid #e5e7eb;
            border-radius: 0.75rem;
            background: #ffffff;
            margin-bottom: 1rem;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
            overflow: hidden;
        }

        .status-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem 1.25rem;
            background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
            color: white;
            font-weight: 600;
        }

        .status-title {
            font-size: 1.1rem;
        }

        .status-time {
            font-size: 0.9rem;
            opacity: 0.95;
        }

        .status-messages {
            padding: 1rem;
            max-height: 50vh;
            overflow-y: auto;
            background: #f9fafb;
        }

        /* Agent message bubbles */
        .agent-message {
            margin-bottom: 0.75rem;
            padding: 0.75rem 1rem;
            border-radius: 0.5rem;
            animation: slideIn 0.3s ease-out;
        }

        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        .agent-message.working {
            background: #dbeafe;
            border-left: 4px solid #3b82f6;
        }

        .agent-message.completed {
            background: #ffffff;
            border-left: 4px solid #10b981;
        }

        .agent-message.waiting {
            background: #fef3c7;
            border-left: 4px solid #f59e0b;
            text-align: center;
        }

        .agent-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }

        .agent-name {
            font-weight: 600;
            color: #1e40af;
            font-size: 0.95rem;
        }

        .agent-time {
            font-size: 0.8rem;
            color: #6b7280;
        }

        .agent-content {
            color: #374151;
            line-height: 1.5;
            font-size: 0.9rem;
        }
        /* Details/summary styling */
        .agent-content details {
            margin-top: 0.35rem;
        }
        .agent-summary {
            list-style: none;
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 0.25rem 0.4rem;
            border-radius: 0.375rem;
            color: #1f2937;
            font-weight: 500;
            cursor: pointer;
            user-select: none;
            transition: background 0.15s ease, color 0.15s ease;
        }
        .agent-summary::before {
            content: '▸';
            display: inline-block;
            color: #2563eb;
            transition: transform 0.2s ease;
        }
        details[open] > .agent-summary::before {
            transform: rotate(90deg);
        }
        .agent-summary:hover {
            background: #f3f4f6;
            color: #111827;
        }
        .agent-details {
            background: #f8fafc;
            border-left: 3px solid #60a5fa;
            padding: 0.75rem;
            border-radius: 0.375rem;
            animation: fadeIn 0.2s ease;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(4px); }
            to { opacity: 1; transform: translateY(0); }
        }
        /* Dark theme for instructions section */
        .dark #fin-instructions * {
            color: rgba(229, 231, 235, 0.95) !important;
        }
        .dark #fin-instructions .card {
            background: #1f2937 !important;
            border-color: #374151 !important;
        }
        .dark #fin-instructions .card h4 {
            color: #bfdbfe !important;
            border-bottom-color: #3b82f6 !important;
        }
        .dark #fin-instructions .card ul li strong {
            color: #93c5fd !important;
        }
        .dark #fin-instructions .tip-card {
            background: linear-gradient(135deg, #0b1220 0%, #0b172a 100%) !important;
            border-left-color: #3b82f6 !important;
        }
        /* Fallback attribute-based overrides if classes missing */
        .dark #fin-instructions div[style*="background: linear-gradient(135deg, #ffffff"] {
            background: #1f2937 !important;
            border-color: #374151 !important;
        }
        .dark #fin-instructions div[style*="background: linear-gradient(135deg, #fef3c7"] {
            background: #0b1220 !important;
            border-left-color: #3b82f6 !important;
        }
        .dark #fin-instructions h4 {
            color: #bfdbfe !important;
            border-bottom-color: #3b82f6 !important;
        }
        .dark #fin-instructions li strong {
            color: #93c5fd !important;
        }

        /* Animated dots for working status */
        .working-text {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
        }

        /* CSS spinner */
        .spinner {
            width: 0.8rem;
            height: 0.8rem;
            border: 2px solid #d1d5db; /* gray-300 */
            border-top-color: #3b82f6; /* blue-500 */
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
            to {
                transform: rotate(360deg);
            }
        }

        /* Report containers with increased height and scroll */
        .report-container {
            height: 700px;
            overflow-y: auto;
            border: 1px solid var(--border-color-primary);
            border-radius: 0.5rem;
            padding: 1rem;
            background: var(--background-fill-primary);
            margin-top: 0.5rem;
        }

        .scrollable-html-report {
            height: 700px;
            overflow-y: auto;
        }

        /* Fix double scrollbar issue for HTML reports */
        .scrollable-html-report .markdown-html-content {
            max-height: none !important;
            overflow: visible !important;
        }

        .scrollable-html-report .content-area {
            max-height: none !important;
            overflow: visible !important;
        }

        /* Status indicators */
        .status-badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 0.5rem;
            font-size: 0.875rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }

        .status-waiting {
            background-color: #fef3c7;
            color: #92400e;
        }

        .status-ready {
            background-color: #d1fae5;
            color: #065f46;
        }

        .status-failed {
            background-color: #fee2e2;
            color: #991b1b;
        }

        /* Button styling */
        .gr-button {
            font-size: clamp(0.9rem, 1.2vw, 1.05rem) !important;
            padding: 0.75rem 1.5rem !important;
            border-radius: 0.5rem !important;
            font-weight: 500 !important;
            transition: all 0.2s ease !important;
        }

        .gr-button-primary {
            background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%) !important;
            border: none !important;
        }

        .gr-button-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4) !important;
        }

        /* Tab styling */
        .gr-tab-nav {
            font-size: clamp(0.9rem, 1.1vw, 1rem) !important;
            font-weight: 500 !important;
        }

        /* Input component styling */
        .gr-textbox, .gr-number {
            font-size: clamp(0.9rem, 1vw, 1rem) !important;
        }

        /* Resources output styling */
        .resources-box {
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 0.85rem;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
        }

        /* Scrollbar styling */
        .report-container::-webkit-scrollbar,
        .scrollable-html-report::-webkit-scrollbar,
        .status-messages::-webkit-scrollbar,
        .gr-textbox textarea::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }

        .report-container::-webkit-scrollbar-track,
        .scrollable-html-report::-webkit-scrollbar-track,
        .status-messages::-webkit-scrollbar-track,
        .gr-textbox textarea::-webkit-scrollbar-track {
            background: #f1f5f9;
            border-radius: 4px;
        }

        .report-container::-webkit-scrollbar-thumb,
        .scrollable-html-report::-webkit-scrollbar-thumb,
        .status-messages::-webkit-scrollbar-thumb,
        .gr-textbox textarea::-webkit-scrollbar-thumb {
            background: #cbd5e1;
            border-radius: 4px;
        }

        .report-container::-webkit-scrollbar-thumb:hover,
        .scrollable-html-report::-webkit-scrollbar-thumb:hover,
        .status-messages::-webkit-scrollbar-thumb:hover,
        .gr-textbox textarea::-webkit-scrollbar-thumb:hover {
            background: #94a3b8;
        }

        /* Responsive layout */
        @media (max-width: 1024px) {
            .input-column {
                border-right: none;
                border-bottom: 1px solid var(--border-color-primary);
                padding-right: 0;
                padding-bottom: 1rem;
            }

            .output-column {
                padding-left: 0;
                padding-top: 1rem;
            }
        }

        /* Dark theme adaptation */
        .dark .main-header {
            background: linear-gradient(135deg, #1e40af 0%, #1e3a8a 100%);
        }

        .dark .status-container {
            background: #1e293b;
            border-color: #334155;
        }

        .dark .status-messages {
            background: #0f172a;
        }

        .dark .agent-message.working {
            background: #1e3a8a;
            border-left-color: #60a5fa;
        }

        .dark .agent-message.completed {
            background: #1e293b;
            border-left-color: #34d399;
        }

        .dark .agent-name {
            color: #60a5fa;
        }

        .dark .agent-content {
            color: #e5e7eb;
        }
        .dark .agent-summary {
            color: #e5e7eb;
        }
        .dark .agent-summary::before {
            color: #93c5fd;
        }
        .dark .agent-summary:hover {
            background: #0b1220;
            color: #ffffff;
        }
        .dark .agent-details {
            background: #0f172a;
            border-left-color: #60a5fa;
        }

        .dark .section-header {
            color: #60a5fa;
            border-bottom-color: #374151;
        }

        .dark .resources-box {
            background: #1e293b;
            border-color: #334155;
        }
    """) as demo:
        gr.HTML("""
        <div class="main-header">
            <h1>📊 FinResearch 金融深度研究</h1>
            <p>Multi-Agent Financial Research Workflow</p>
        </div>
        """)
        timer_script = """
        <script>
        (function() {
            if (window.__finStatusTimerBound) return;
            window.__finStatusTimerBound = true;

            function formatLabel(seconds) {
                seconds = Math.max(0, parseInt(seconds || 0, 10));
                var m = Math.floor(seconds / 60);
                var s = seconds % 60;
                if (m > 0) {
                    return m + '分' + s + '秒';
                }
                return s + '秒';
            }

            function updateTimer(label) {
                try {
                    var els = document.querySelectorAll('.status-header .status-time');
                    els.forEach(function(t) {
                        t.textContent = '⏱️ ' + label;
                    });
                } catch (e) {}
            }

            function applyPayload(payload) {
                if (!payload) {
                    return;
                }
                try {
                    var data = JSON.parse(payload);
                    var elapsed = data && typeof data.elapsed !== 'undefined' ? data.elapsed : 0;
                    updateTimer(formatLabel(elapsed));
                } catch (e) {}
            }

            function bindSignal() {
                var signal = document.getElementById('__TIMER_SIGNAL_ID__');
                if (!signal) {
                    setTimeout(bindSignal, 500);
                    return;
                }
                var observer = new MutationObserver(function() {
                    applyPayload(signal.textContent || signal.innerText || '');
                });
                observer.observe(signal, { childList: true, subtree: true, characterData: true });
                applyPayload(signal.textContent || signal.innerText || '');
            }

            bindSignal();
        })();
        </script>
        """
        gr.HTML(timer_script.replace('__TIMER_SIGNAL_ID__',
                                     FIN_STATUS_TIMER_SIGNAL_ID))

        with gr.Row():
            with gr.Column(scale=2, elem_classes=['input-column']):
                gr.HTML('<h3 class="section-header">📝 研究输入 | Research Input</h3>')

                research_goal = gr.Textbox(
                    label='研究目标 | Research Goal',
                    placeholder='例如：分析宁德时代近四个季度的盈利能力与行业政策影响...\n\nExample: Analyze the profitability and policy impact of CATL over the past four quarters...',
                    lines=8,
                    max_lines=12
                )

                gr.HTML('<h3 class="section-header">🔍 舆情搜索配置 | Search Settings</h3>')

                with gr.Row():
                    search_depth = gr.Number(
                        label='搜索深度 | Depth',
                        value=1,
                        precision=0,
                        minimum=1,
                        maximum=3
                    )
                    search_breadth = gr.Number(
                        label='搜索宽度 | Breadth',
                        value=3,
                        precision=0,
                        minimum=1,
                        maximum=6
                    )

                search_api_key = gr.Textbox(
                    label='搜索引擎 API Key (可选 | Optional)',
                    placeholder='支持 exa: <key> / serpapi: <key>，可多条逗号或换行分隔',
                    type='password'
                )

                gr.HTML('<div style="margin-top: 1.5rem;"></div>')

                run_btn = gr.Button(
                    '🚀 启动 FinResearch | Launch Research',
                    variant='primary',
                    size='lg'
                )

                clear_btn = gr.Button(
                    '🧹 清理工作区 | Clear Workspace',
                    variant='secondary'
                )

            with gr.Column(scale=3, elem_classes=['output-column']):
                gr.HTML('<h3 class="section-header">📡 执行状态 | Execution Status</h3>')

                status_output = gr.HTML(
                    value='''
                    <div class="status-container">
                        <div class="status-header">
                            <span class="status-title">执行状态</span>
                            <span class="status-time">⏱️ 0秒</span>
                        </div>
                        <div class="status-messages">
                            <div class="agent-message waiting">
                                <div class="agent-content">⏳ 等待执行... | Waiting for execution...</div>
                            </div>
                        </div>
                    </div>
                    '''
                )
                status_timer_signal = gr.HTML(
                    value=DEFAULT_TIMER_SIGNAL,
                    visible=False,
                    elem_id=FIN_STATUS_TIMER_SIGNAL_ID)

                gr.HTML('<h3 class="section-header">📑 研究报告 | Research Reports</h3>')

                with gr.Tabs():
                    with gr.Tab('📊 综合报告 | Final Report'):
                        final_status_output = gr.Markdown('⌛ Waiting...')
                        if LOCAL_MODE:
                            final_report_output = gr.Markdown(
                                elem_classes=['report-container']
                            )
                        else:
                            final_report_output = gr.HTML(
                                elem_classes=['scrollable-html-report']
                            )
                        final_download = gr.DownloadButton(
                            label='⬇️ 下载综合报告 | Download Final Report',
                            value=None,
                            interactive=False
                        )

                    with gr.Tab('📈 数据分析 | Quantitative Analysis'):
                        analysis_status_output = gr.Markdown('⌛ Waiting...')
                        if LOCAL_MODE:
                            analysis_report_output = gr.Markdown(
                                elem_classes=['report-container']
                            )
                        else:
                            analysis_report_output = gr.HTML(
                                elem_classes=['scrollable-html-report']
                            )
                        analysis_download = gr.DownloadButton(
                            label='⬇️ 下载数据分析报告 | Download Analysis Report',
                            value=None,
                            interactive=False
                        )

                    with gr.Tab('📰 舆情洞察 | Sentiment Insights'):
                        sentiment_status_output = gr.Markdown('⌛ Waiting...')
                        if LOCAL_MODE:
                            sentiment_report_output = gr.Markdown(
                                elem_classes=['report-container']
                            )
                        else:
                            sentiment_report_output = gr.HTML(
                                elem_classes=['scrollable-html-report']
                            )
                        sentiment_download = gr.DownloadButton(
                            label='⬇️ 下载舆情分析报告 | Download Sentiment Report',
                            value=None,
                            interactive=False
                        )

                    with gr.Tab('📁 输出文件 | Output Files'):
                        resources_output = gr.Textbox(
                            label='输出文件列表 | Output Files List',
                            lines=20,
                            max_lines=25,
                            interactive=False,
                            show_copy_button=True,
                            elem_classes=['resources-box']
                        )

        # 使用说明
        gr.HTML("""
        <div id="fin-instructions" style="margin-top: 2rem; padding: 0; background: transparent; border-radius: 1rem;">
            <div style="text-align: center; margin-bottom: 1.5rem;">
                <h3 style="color: #1e40af; font-size: 1.8rem; font-weight: 700; margin: 0;">
                    📖 使用说明 | User Guide
                </h3>
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 1.5rem;">
                <div class="card" style="background: linear-gradient(135deg, #ffffff 0%, #f0f9ff 100%); padding: 2rem; border-radius: 1rem; box-shadow: 0 4px 6px rgba(0,0,0,0.07); border: 1px solid #e0f2fe;">
                    <h4 style="color: #0369a1; margin-bottom: 1.25rem; font-size: 1.3rem; font-weight: 600; border-bottom: 2px solid #0ea5e9; padding-bottom: 0.5rem;">
                        🇨🇳 中文说明
                    </h4>
                    <ul style="line-height: 2; color: #1e293b; font-size: 0.95rem; padding-left: 1.5rem; margin: 0;">
                        <li style="margin-bottom: 0.75rem;"><strong style="color: #0369a1;">研究目标：</strong>详细描述您的金融研究需求，可以包括特定的公司、行业、时间段等</li>
                        <li style="margin-bottom: 0.75rem;"><strong style="color: #0369a1;">搜索深度：</strong>设置舆情搜索的递归深度（1-3），越大越深入但耗时越长</li>
                        <li style="margin-bottom: 0.75rem;"><strong style="color: #0369a1;">搜索宽度：</strong>设置舆情搜索的并发主题数量（1-6），越大覆盖面越广但耗时越长</li>
                        <li style="margin-bottom: 0.75rem;"><strong style="color: #0369a1;">多智能体协作：</strong>系统自动调度 5 个专业 Agent 协同工作</li>
                        <li style="margin-bottom: 0.75rem;"><strong style="color: #0369a1;">综合报告：</strong>完整的研究分析、结论和建议</li>
                        <li style="margin-bottom: 0.75rem;"><strong style="color: #0369a1;">数据分析：</strong>基于结构化数据的统计和可视化</li>
                        <li style="margin-bottom: 0;"><strong style="color: #0369a1;">舆情洞察：</strong>网络搜索的新闻、观点和情感分析</li>
                    </ul>
                </div>

                <div class="card" style="background: linear-gradient(135deg, #ffffff 0%, #f0f9ff 100%); padding: 2rem; border-radius: 1rem; box-shadow: 0 4px 6px rgba(0,0,0,0.07); border: 1px solid #e0f2fe;">
                    <h4 style="color: #0369a1; margin-bottom: 1.25rem; font-size: 1.3rem; font-weight: 600; border-bottom: 2px solid #0ea5e9; padding-bottom: 0.5rem;">
                        🇺🇸 English Guide
                    </h4>
                    <ul style="line-height: 2; color: #1e293b; font-size: 0.95rem; padding-left: 1.5rem; margin: 0;">
                        <li style="margin-bottom: 0.75rem;"><strong style="color: #0369a1;">Research Goal:</strong> Describe your financial research needs in detail</li>
                        <li style="margin-bottom: 0.75rem;"><strong style="color: #0369a1;">Search Depth:</strong> Set recursive depth (1-3), higher = deeper analysis</li>
                        <li style="margin-bottom: 0.75rem;"><strong style="color: #0369a1;">Search Breadth:</strong> Set concurrent topics (1-6), higher = broader coverage</li>
                        <li style="margin-bottom: 0.75rem;"><strong style="color: #0369a1;">Multi-Agent:</strong> 5 specialized agents work collaboratively</li>
                        <li style="margin-bottom: 0.75rem;"><strong style="color: #0369a1;">Final Report:</strong> Comprehensive analysis with conclusions</li>
                        <li style="margin-bottom: 0.75rem;"><strong style="color: #0369a1;">Quantitative:</strong> Statistical and visual data analysis</li>
                        <li style="margin-bottom: 0;"><strong style="color: #0369a1;">Sentiment:</strong> News, opinions and sentiment analysis</li>
                    </ul>
                </div>
            </div>

            <div class="tip-card" style="padding: 1.5rem; background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border-radius: 1rem; box-shadow: 0 4px 6px rgba(0,0,0,0.07); border-left: 5px solid #f59e0b;">
                <p style="margin: 0; color: #78350f; font-size: 1rem; line-height: 1.8;">
                    <strong style="font-size: 1.1rem;">💡 提示 | Tip</strong>
                    <br/><br/>
                    <span style="display: block; margin-bottom: 0.5rem;">
                        研究任务通常需要几分钟时间完成。您可以实时查看右侧的执行状态，了解当前是哪个 Agent 在工作。建议在研究目标中明确指定股票代码、时间范围和关注的分析维度，以获得更精准的结果。
                    </span>
                    <span style="display: block; opacity: 0.9;">
                        Research tasks typically take several minutes to complete. You can monitor the execution status on the right to see which agent is working. Specify stock tickers, time ranges, and analysis dimensions for more accurate results.
                    </span>
                </p>
            </div>
        </div>
        """)

        # 示例
        gr.Examples(
            examples=[
                [
                    '请分析宁德时代（300750.SZ）在过去四个季度的盈利能力变化，并与新能源板块的主要竞争对手（如比亚迪（002594.SZ）、国轩高科（002074.SZ））进行对比。同时，结合市场舆情与竞争格局，预测其未来两个季度的业绩走势。',
                    1,
                    3,
                ],
                [
                    'Please analyze the changes in the profitability of Contemporary Amperex Technology Co., Limited (CATL, 300750.SZ) over the past four quarters and compare its performance with major competitors in the new energy sector, such as BYD Company Limited (002594.SZ) and Gotion High-Tech Co., Ltd. (002074.SZ). Based on market sentiment and competitor analysis, please forecast CATL’s profitability trends for the next two quarters.',
                    1,
                    3,
                ],
            ],
            inputs=[research_goal, search_depth, search_breadth],
            label='📚 示例 | Examples'
        )

        run_btn.click(
            fn=run_fin_research_workflow,
            inputs=[research_goal, search_depth, search_breadth, search_api_key],
            outputs=[
                status_timer_signal, status_output, final_status_output, final_report_output,
                analysis_status_output, analysis_report_output,
                sentiment_status_output, sentiment_report_output,
                resources_output, final_download, analysis_download,
                sentiment_download
            ],
            show_progress=False)

        clear_btn.click(
            fn=clear_user_workspace,
            outputs=[
                status_timer_signal, status_output, final_status_output, final_report_output,
                analysis_status_output, analysis_report_output,
                sentiment_status_output, sentiment_report_output,
                resources_output, final_download, analysis_download,
                sentiment_download
            ])

    return demo


def launch_server(server_name: Optional[str] = '0.0.0.0',
                  server_port: Optional[int] = 7861,
                  share: bool = False):
    demo = create_interface()
    demo.queue(default_concurrency_limit=GRADIO_DEFAULT_CONCURRENCY_LIMIT)
    demo.launch(server_name=server_name, server_port=server_port, share=share)


if __name__ == '__main__':
    launch_server()
