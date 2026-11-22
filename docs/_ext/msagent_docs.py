"""双语文档共用的导航、语言切换和静态资源。"""
from pathlib import Path
import shutil

SECTIONS = [
    ('快速开始', 'Getting started', 'get-started', [
        ('', '', 'introduction quick-start python-sdk')]),
    ('使用教程', 'User guide', 'user-guide', [
        ('', '', 'webui tui cli projects-sessions model-settings skills-mcp memory scheduled-tasks deployment troubleshooting')]),
    ('核心模块', 'Core modules', 'core', [
        ('配置与执行', 'Configuration & execution', 'configuration models messages-events agents multimodal'),
        ('工具能力', 'Tools & capabilities', 'tools execution-environments mcp-client skills'),
        ('状态与知识', 'State & knowledge', 'sessions context memory prompts personalization retrieval rag'),
        ('行为控制', 'Behavior & control', 'permissions callbacks hooks plugins'),
        ('协作与互通', 'Orchestration & integration', 'subagents workflows scheduling acp a2a agent-hub capability-gateway')]),
    ('领域应用', 'Domain applications', 'applications', [
        ('', '', 'deep-research code-genesis fin-research doc-research singularity-cinema skill-evolution')]),
    ('开发与参考', 'Development & reference', 'development', [
        ('', '', 'configuration-reference cli-reference storage glossary architecture contributing'),
        ('设计提案（RFC）', 'Design proposals (RFCs)', 'rfcs/plugins rfcs/hooks-executors rfcs/mcp-runtime-api')]),
]
PAGES = {prefix + '/' + slug for _, _, prefix, groups in SECTIONS
         for _, _, slugs in groups for slug in slugs.split()}


LEGACY_DOCS = {
    'getstarted/installation': 'get-started/quick-start',
    'getstarted/introduction': 'get-started/quick-start',
    'getstarted/quickstart': 'get-started/quick-start',
    'getstarted/cli': 'development/cli-reference',
    'components/config': 'development/configuration-reference',
    'components/supportedmodels': 'core/models',
    'components/modelcatalog': 'core/models',
    'components/llmagent': 'core/agents',
    'components/tools': 'core/tools',
    'components/workflow': 'core/workflows',
    'components/agentskills': 'core/skills',
    'components/multimodalsupport': 'core/multimodal',
    'components/contributorguide': 'development/contributing',
    'components/capabilitygateway': 'core/capability-gateway',
    'interfaces/webui': 'user-guide/webui',
    'projects/deepresearch': 'applications/deep-research',
    'projects/codegenesis': 'applications/code-genesis',
    'projects/finresearch': 'applications/fin-research',
    'projects/videogeneration': 'applications/singularity-cinema',
    'architecture/architecture': 'development/architecture',
    'architecture/roadmap': 'development/architecture',
    'architecture/rfcs/plugins': 'development/rfcs/plugins',
    'architecture/rfcs/hooksexecutors': 'development/rfcs/hooks-executors',
    'architecture/rfcs/mcpruntimeapi': 'development/rfcs/mcp-runtime-api',
    'design/webuiinsessioninput': 'core/messages-events',
    'design/hooksdesign': 'core/hooks',
    'design/permissiondesign': 'core/permissions',
    'design/pluginsdesign': 'core/plugins',
    'design/mcp_runtime_management': 'core/mcp-client',
}


def page_context(app, pagename, templatename, context, doctree):
    zh = app.config.language.startswith('zh')
    nav = []
    for cn, en, prefix, groups in SECTIONS:
        children = []
        for group_cn, group_en, slugs in groups:
            entries = []
            for slug in slugs.split():
                doc = prefix + '/' + slug
                title = app.env.titles.get(doc)
                if doc in app.env.found_docs:
                    entries.append({'doc': doc, 'title': title.astext() if title else slug})
            children.append({'title': group_cn if zh else group_en,
                             'entries': entries,
                             'active': any(p['doc'] == pagename for p in entries)})
        nav.append({'title': cn if zh else en, 'groups': children,
                    'active': pagename.startswith(prefix + '/')})
    context['ms_nav'] = nav
    context['ms_zh'] = zh
    other = 'en' if zh else 'zh'
    # 规范页优先；只有旧路径才按迁移表对应到新页。
    canonical = pagename if pagename in PAGES else LEGACY_DOCS.get(pagename.lower().replace('-', ''), pagename)
    relative = canonical if (Path(app.confdir).parent / other / (canonical + '.md')).exists() else 'index'
    local = app.config.msagent_preview
    if local:
        context['ms_language_url'] = '/' + other + '/' + relative + '.html'
    else:
        base = 'https://ms-agent-en.readthedocs.io/en/latest/' if zh else 'https://ms-agent.readthedocs.io/zh-cn/latest/'
        context['ms_language_url'] = base + relative + '.html'


def copy_logo(app):
    source = Path(app.confdir).parents[1] / 'asset/logo.png'
    target = Path(app.outdir) / '_static/images/ms-agent-logo.png'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    # 主题将暗色样式合入单文件，但新版Sphinx仍引用独立文件；同时支持手动主题切换。
    from pygments.formatters import HtmlFormatter
    light = HtmlFormatter(style=app.config.pygments_style or 'default').get_style_defs('.highlight')
    dark = HtmlFormatter(style=app.config.pygments_style_dark or 'monokai').get_style_defs('.dark .highlight')
    (Path(app.outdir) / '_static/pygments.css').write_text(light + '\n' + dark, encoding='utf-8')
    (Path(app.outdir) / '_static/pygments_dark.css').write_text(dark, encoding='utf-8')


def setup(app):
    app.add_config_value('msagent_preview', False, 'html', types=[bool])
    app.connect('html-page-context', page_context)
    app.connect('build-finished', lambda app, exc: copy_logo(app) if exc is None else None)
    return {'version': '1.0', 'parallel_read_safe': True, 'parallel_write_safe': True}
