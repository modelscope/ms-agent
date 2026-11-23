"""文档构建、检索和语言链接回归；不依赖模型或真实部署。"""
import importlib.util
import json
import pytest
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
pytest.importorskip('sphinxcontrib.mermaid')
SPEC = importlib.util.spec_from_file_location(
    'msagent_docs', ROOT / 'docs/_ext/msagent_docs.py')
SITE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SITE)


def application(version='latest',
                language='zh_CN',
                preview=False,
                builds=None):
    return SimpleNamespace(
        confdir=ROOT / 'docs' / ('zh' if language.startswith('zh') else 'en'),
        config=SimpleNamespace(
            language=language,
            msagent_preview=preview,
            msagent_docs_version=version,
            msagent_language_builds=builds or {}),
    )


@pytest.mark.parametrize('version', ['latest', 'v1.7.0', 'preview-1063'])
@pytest.mark.parametrize('language,other', [('zh_CN', 'en'), ('en', 'zh')])
def test_explicit_language_build(version, language, other):
    base = f'https://docs.example.com/{other}/{version}/'
    app = application(
        version,
        language,
        builds={
            version: {
                other: {
                    'base_url': base,
                    'pages': ['index', 'core/context'],
                }
            }
        })
    assert SITE.language_link(app,
                              'core/context') == (base + 'core/context.html',
                                                  False)


@pytest.mark.parametrize('page', ['core/context', 'search', 'index'])
def test_local_same_page(page):
    assert SITE.language_link(application(preview=True),
                              page) == ('/en/' + page + '.html', False)


def test_local_legacy_normalizes():
    assert SITE.language_link(
        application(preview=True), 'Components/Config') == (
            '/en/development/configuration-reference.html', False)


@pytest.mark.parametrize('target', [
    None, {}, {
        'base_url': 'https://docs.example.com/en/tag/',
        'pages': ['index']
    }
])
def test_missing_version_or_page_disables(target):
    builds = {'latest': {'en': target or {}}}
    assert SITE.language_link(
        application('tag', builds=builds), 'core/context') == (None, True)
    assert SITE.language_link(application(builds=builds),
                              'core/context') == (None, True)


def test_deployed_legacy_normalizes():
    builds = {
        'release': {
            'zh': {
                'base_url': 'https://docs.example.com/zh/release/',
                'pages': ['development/configuration-reference'],
            }
        }
    }
    assert SITE.language_link(
        application('release', 'en', builds=builds), 'Components/Config'
    ) == (
        'https://docs.example.com/zh/release/development/configuration-reference.html',
        False)


@pytest.mark.parametrize('base', [
    'javascript:alert(1)', 'https://user:password@example.com/en/',
    'https://docs.example.com/?token=x'
])
def test_unsafe_deployment_base_disabled(base):
    app = application(builds={
        'latest': {
            'en': {
                'base_url': base,
                'pages': ['core/context']
            }
        }
    })
    assert SITE.language_link(app, 'core/context') == (None, True)


@pytest.fixture(scope='module', params=['zh', 'en'])
def built_site(request, tmp_path_factory):
    lang = request.param
    output = tmp_path_factory.mktemp('html-' + lang)
    command = [
        sys.executable,
        '-m',
        'sphinx',
        '-q',
        '-E',
        '-a',
        '-b',
        'html',
        '-W',
        '--keep-going',
        '-D',
        'msagent_preview=1',
        str(ROOT / 'docs' / lang),
        str(output),
    ]
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'design.card_legacy' not in result.stderr
    raw = (output / 'searchindex.js').read_text()
    index = json.loads(raw[len('Search.setIndex('):-1])
    return lang, output, index


def test_no_migration_results(built_site):
    _, _, index = built_site
    assert set(index['docnames']) == SITE.PAGES | {'index'}
    assert all(
        title not in ('Page moved', '页面已迁移') for title in index['titles'])
    assert 'flowchart' not in index['terms']


def test_search_words_are_indexed(built_site):
    lang, _, index = built_site
    if lang == 'zh':
        from sphinx.search.zh import SearchChinese
        language = SearchChinese({})
        words = ['安装', '快速开始', '记忆', '权限', '模型', 'MCP']
    else:
        from sphinx.search.en import SearchEnglish
        language = SearchEnglish({})
        words = ['installation', 'memory']
    for word in words:
        terms = [
            language.stem(term) for term in language.split(word)
            if language.word_filter(term)
        ]
        assert terms, word
        assert all(term in index['terms'] or term in index['titleterms']
                   for term in terms), word


def test_logo_footer_and_config_identifiers(built_site):
    from bs4 import BeautifulSoup
    _, output, _ = built_site
    intro = BeautifulSoup(
        (output / 'get-started/introduction.html').read_text(), 'html.parser')
    assert len(intro.select('.ms-feature .sd-card-footer')) == 6
    assert len(intro.select('.ms-sidebar-brand img')) == 1
    assert not intro.select('.ms-sidebar-brand span')
    assert (output / '_static/images/ms-agent-logo.png').read_bytes() == (
        ROOT / 'asset/logo.png').read_bytes()
    table = BeautifulSoup(
        (output / 'development/configuration-reference.html').read_text(),
        'html.parser')
    assert table.select('.ms-config-table code')
    assert table.find(id='config_handler')
    first_cells = table.select('.ms-config-table tbody tr td:first-child')
    assert any(cell.get_text().strip() == 'handler' for cell in first_cells)
    assert not any(cell.get_text().strip() == 'config_handler'
                   for cell in first_cells)
    assert next(cell for cell in first_cells
                if cell.get_text().strip() == 'code_file').find('code')


def test_old_url_and_anchors_preserved(built_site):
    from bs4 import BeautifulSoup
    lang, output, _ = built_site
    path = 'Components/config.html' if lang == 'zh' else 'Components/Config.html'
    doc = BeautifulSoup((output / path).read_text(), 'html.parser')
    assert doc.find(id='config_handler')
    assert doc.find(id='callbacks')
    assert doc.select('a[href*="configuration-reference.html"]')
