# Copyright (c) ModelScope Contributors. All rights reserved.
"""Offline regressions for Han keywords in the default skill retriever."""
from ms_agent.retriever.bm25 import BM25Retriever, _tokenize
from ms_agent.skill.catalog import SkillCatalog
from ms_agent.skill.search import SkillSearchEngine
from ms_agent.skill.sources import SkillSource, SkillSourceType


def test_chinese_keyword_inside_sentence():
    retriever = BM25Retriever()
    retriever.index(['用于分析销售数据并生成报表', '执行代码格式化'],
                    ['sales', 'format'])
    results = retriever.search('销售数据')
    assert results
    assert results[0].doc_id == 'sales'


def test_mixed_han_latin_boundaries():
    assert _tokenize('使用Python3处理CSV文件') == [
        '使', '用', 'python3', '处', '理', 'csv', '文', '件']
    retriever = BM25Retriever()
    retriever.index(['使用Python3处理CSV文件', '执行代码格式化'], ['csv', 'format'])
    assert retriever.search('CSV')[0].doc_id == 'csv'
    assert retriever.search('Python3')[0].doc_id == 'csv'


def test_latin_tokens_remain_whole_words():
    assert _tokenize('Python_3 CAFÉ naïve 123') == [
        'python_3', 'café', 'naïve', '123']
    retriever = BM25Retriever()
    retriever.index(['Python programming', 'JavaScript formatting'])
    assert retriever.search('python')[0].doc_id == '0'
    assert retriever.search('py') == []
    assert retriever.search('!?') == []


def test_default_skill_search_finds_chinese_description(tmp_path):
    for skill_id, description in [
            ('sales-report', '用于分析销售数据并生成报表'),
            ('code-format', '执行代码格式化')]:
        directory = tmp_path / skill_id
        directory.mkdir()
        (directory / 'SKILL.md').write_text(
            f'---\nname: {skill_id}\ndescription: {description}\n---\n',
            encoding='utf-8')
    catalog = SkillCatalog()
    catalog.load_from_sources([
        SkillSource(type=SkillSourceType.LOCAL_DIR, path=str(tmp_path))])
    engine = SkillSearchEngine(catalog)
    matches = engine.search('销售数据')
    assert matches
    assert matches[0][0] == 'sales-report'
    assert engine.search('苹果') == []


def test_chinese_keyword_ranks_above_shared_character_distractors():
    retriever = BM25Retriever()
    retriever.index([
        '用于分析销售数据并生成报表',
        '用于分析天气数据并生成报表',
        '生成销售合同并保存文件',
    ], ['sales-data', 'weather-data', 'sales-contract'])
    results = retriever.search('销售数据')
    assert results[0].doc_id == 'sales-data'
    assert results[0].score > results[1].score
