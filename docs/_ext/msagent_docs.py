"""双语文档共用的导航、语言切换和静态资源。"""
import json
import os
import shutil
from pathlib import Path
from sphinxcontrib.mermaid import mermaid
from urllib.parse import urlsplit

SECTIONS = [
    ('快速开始', 'Getting started', 'get-started',
     [('', '', 'introduction quick-start python-sdk')]),
    ('使用教程', 'User guide', 'user-guide',
     [('', '',
       'webui tui cli projects-sessions model-settings skills-mcp memory scheduled-tasks deployment troubleshooting'
       )]),
    ('核心模块', 'Core modules', 'core', [
        ('配置与执行', 'Configuration & execution',
         'configuration models messages-events agents multimodal'),
        ('工具能力', 'Tools & capabilities',
         'tools execution-environments mcp-client skills'),
        ('状态与知识', 'State & knowledge',
         'sessions context memory prompts personalization retrieval rag'),
        ('行为控制', 'Behavior & control', 'permissions callbacks hooks plugins'),
        ('协作与互通', 'Orchestration & integration',
         'subagents workflows scheduling acp a2a agent-hub capability-gateway')
    ]),
    ('领域应用', 'Domain applications', 'applications',
     [('', '',
       'deep-research code-genesis fin-research doc-research singularity-cinema skill-evolution'
       )]),
    ('开发与参考', 'Development & reference', 'development',
     [('', '',
       'configuration-reference cli-reference storage glossary architecture contributing'
       ),
      ('设计提案（RFC）', 'Design proposals (RFCs)',
       'rfcs/plugins rfcs/hooks-executors rfcs/mcp-runtime-api')]),
]
PAGES = {
    prefix + '/' + slug
    for _, _, prefix, groups in SECTIONS
    for _, _, slugs in groups
    for slug in slugs.split()
}

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
                    entries.append({
                        'doc': doc,
                        'title': title.astext() if title else slug
                    })
            children.append({
                'title':
                group_cn if zh else group_en,
                'entries':
                entries,
                'active':
                any(p['doc'] == pagename for p in entries)
            })
        nav.append({
            'title': cn if zh else en,
            'groups': children,
            'active': pagename.startswith(prefix + '/')
        })
    context['ms_nav'] = nav
    context['ms_zh'] = zh
    context['ms_language_url'], missing = language_link(app, pagename)
    context['ms_language_missing'] = (
        ('对应语言的版本或页面尚未提供' if zh else
         'This version or page is not available in the other language')
        if missing else '')


def canonical_page(pagename):
    # 规范页优先；只有旧路径才按迁移表对应到新页。
    return pagename if pagename in PAGES else LEGACY_DOCS.get(
        pagename.lower().replace('-', ''), pagename)


def language_link(app, pagename):
    """只链接部署方明确声明存在的版本和页面；缺失时不回退到 latest。"""
    other = 'en' if app.config.language.startswith('zh') else 'zh'
    page = canonical_page(pagename)
    if app.config.msagent_preview:
        root = Path(app.confdir).parent / other
        if page in {'search', 'genindex'} or any(
            (root / (page + suffix)).is_file() for suffix in ('.md', '.rst')):
            return '/' + other + '/' + page + '.html', False
        return None, True
    target = app.config.msagent_language_builds.get(
        app.config.msagent_docs_version, {}).get(other, {})
    base = target.get('base_url', '')
    parsed = urlsplit(base)
    if (page not in target.get('pages', [])
            or parsed.scheme not in ('http', 'https') or not parsed.netloc
            or parsed.username or parsed.password or parsed.query
            or parsed.fragment):
        return None, True
    return base.rstrip('/') + '/' + page + '.html', False


def prepare_search(app, doctree):
    # 搜索只收集说明文字；图表仍按原样渲染。
    for node in doctree.findall(mermaid):
        node['classes'].append('no-search')
    if app.env.docname == 'development/configuration-reference':
        from docutils import nodes
        for node in doctree.findall(nodes.table):
            node['classes'].append('ms-config-table')


def finish_build(app, exc):
    if exc is not None or app.builder.format != 'html':
        return
    copy_logo(app)
    indexer = getattr(app.builder, 'indexer', None)
    if indexer is not None:
        # 排除迁移占位页，保留其 HTML、旧锚点和新版入口。
        indexer.prune((PAGES | {'index'}) & app.env.found_docs)
        app.builder.dump_search_index()


def copy_logo(app):
    source = Path(app.confdir).parents[1] / 'asset/logo.png'
    target = Path(app.outdir) / '_static/images/ms-agent-logo.png'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    # 主题将暗色样式合入单文件，但新版Sphinx仍引用独立文件；同时支持手动主题切换。
    from pygments.formatters import HtmlFormatter
    light = HtmlFormatter(style=app.config.pygments_style
                          or 'default').get_style_defs('.highlight')
    dark = HtmlFormatter(style=app.config.pygments_style_dark
                         or 'monokai').get_style_defs('.dark .highlight')
    (Path(app.outdir) / '_static/pygments.css').write_text(
        light + '\n' + dark, encoding='utf-8')
    (Path(app.outdir) / '_static/pygments_dark.css').write_text(
        dark, encoding='utf-8')


def setup(app):
    app.add_config_value('msagent_preview', False, 'html', types=[bool])
    app.add_config_value(
        'msagent_docs_version',
        os.environ.get('READTHEDOCS_VERSION', 'local'),
        'html',
        types=[str])
    app.add_config_value(
        'msagent_language_builds',
        json.loads(os.environ.get('MSAGENT_LANGUAGE_BUILDS', '{}')),
        'html',
        types=[dict])
    app.connect('doctree-read', prepare_search)
    app.connect('html-page-context', page_context)
    app.connect('build-finished', finish_build)
    return {
        'version': '1.0',
        'parallel_read_safe': True,
        'parallel_write_safe': True
    }
