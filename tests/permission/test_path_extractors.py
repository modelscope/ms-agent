"""Tests for PATH_EXTRACTORS registry."""

import pytest

from ms_agent.permission.path_extractors import (
    build_extractor_registry,
    extract_cd,
    extract_find,
    extract_find_exec_commands,
    extract_git,
    extract_jq,
    extract_sed,
    extract_tr,
    filter_out_flags,
    find_uses_delete,
    parse_pattern_command,
)


class TestFilterOutFlags:
    def test_basic(self):
        assert filter_out_flags(['-la', 'file1', 'file2']) == ['file1', 'file2']

    def test_double_dash(self):
        assert filter_out_flags(['--', '-file']) == ['-file']

    def test_mixed(self):
        assert filter_out_flags(['-r', 'src', '--force', '--', '-tricky']) == ['src', '-tricky']

    def test_no_flags(self):
        assert filter_out_flags(['a', 'b', 'c']) == ['a', 'b', 'c']

    def test_empty(self):
        assert filter_out_flags([]) == []


class TestExtractCd:
    def test_no_args(self):
        import os
        assert extract_cd([]) == [os.path.expanduser('~')]

    def test_single_dir(self):
        assert extract_cd(['/tmp']) == ['/tmp']

    def test_space_in_dir(self):
        assert extract_cd(['/my', 'dir']) == ['/my dir']


class TestExtractFind:
    def test_basic(self):
        assert extract_find(['.', '-name', '*.py']) == ['.']

    def test_multiple_paths(self):
        assert extract_find(['dir1', 'dir2', '-name', '*.py']) == ['dir1', 'dir2']

    def test_no_args(self):
        assert extract_find([]) == ['.']

    def test_path_flag(self):
        paths = extract_find(['.', '-newer', '/ref/file', '-name', '*.txt'])
        assert '/ref/file' in paths

    def test_global_options(self):
        assert extract_find(['-L', '/src', '-name', '*.py']) == ['/src']


class TestFindExecExtraction:
    def test_exec_rm(self):
        cmds = extract_find_exec_commands([
            '.', '-name', '*.log', '-exec', 'rm', '-rf', '/etc/important', '{}', ';',
        ])
        assert cmds == ['rm -rf /etc/important']

    def test_execdir(self):
        cmds = extract_find_exec_commands([
            '/tmp', '-execdir', 'chmod', '777', '{}', '+',
        ])
        assert cmds == ['chmod 777']

    def test_delete_flag(self):
        assert find_uses_delete(['.', '-delete']) is True
        assert find_uses_delete(['.', '-name', '*.tmp']) is False


class TestParsePatternCommand:
    def test_grep_basic(self):
        flags = {'-e', '--regexp', '-f', '--file', '-A', '-B', '-C', '-m', '--max-count'}
        paths = parse_pattern_command(['pattern', 'file1', 'file2'], flags)
        assert paths == ['file1', 'file2']

    def test_grep_with_e_flag(self):
        flags = {'-e', '--regexp'}
        paths = parse_pattern_command(['-e', 'pattern', 'file1'], flags)
        assert paths == ['file1']

    def test_grep_no_files(self):
        flags = {'-e', '--regexp'}
        paths = parse_pattern_command(['pattern'], flags, defaults=['.'])
        assert paths == ['.']


class TestExtractSed:
    def test_inline_expression(self):
        assert extract_sed(['s/a/b/', 'file.txt']) == ['file.txt']

    def test_e_flag(self):
        assert extract_sed(['-e', 's/a/b/', 'file.txt']) == ['file.txt']

    def test_f_flag(self):
        paths = extract_sed(['-f', 'script.sed', 'file.txt'])
        assert 'script.sed' in paths
        assert 'file.txt' in paths

    def test_multiple_expressions(self):
        assert extract_sed(['-e', 's/a/b/', '-e', 's/c/d/', 'file.txt']) == ['file.txt']


class TestExtractJq:
    def test_basic(self):
        assert extract_jq(['.data', 'file.json']) == ['file.json']

    def test_no_files(self):
        assert extract_jq(['.data']) == []

    def test_with_flags(self):
        assert extract_jq(['-r', '.data', 'file.json']) == ['file.json']


class TestExtractGit:
    def test_diff_no_index(self):
        assert extract_git(['diff', '--no-index', 'a.txt', 'b.txt']) == ['a.txt', 'b.txt']

    def test_other_subcommand(self):
        assert extract_git(['status']) == []

    def test_regular_diff(self):
        assert extract_git(['diff', 'HEAD']) == []


class TestExtractTr:
    def test_basic(self):
        assert extract_tr(['a-z', 'A-Z']) == []

    def test_with_delete(self):
        assert extract_tr(['-d', 'set1']) == []

    def test_with_file(self):
        assert extract_tr(['a-z', 'A-Z', 'file.txt']) == ['file.txt']


class TestRegistry:
    def test_registry_size(self):
        reg = build_extractor_registry()
        assert len(reg) >= 34

    def test_all_commands_have_op_type(self):
        reg = build_extractor_registry()
        for cmd, entry in reg.items():
            assert entry.op_type in ('read', 'write', 'create'), f'{cmd} has invalid op_type'

    def test_rm_is_write(self):
        reg = build_extractor_registry()
        assert reg['rm'].op_type == 'write'

    def test_cat_is_read(self):
        reg = build_extractor_registry()
        assert reg['cat'].op_type == 'read'

    def test_mkdir_is_create(self):
        reg = build_extractor_registry()
        assert reg['mkdir'].op_type == 'create'

    def test_mv_has_validator(self):
        reg = build_extractor_registry()
        assert reg['mv'].command_validator is not None
        assert reg['mv'].command_validator(['-t', '/dst', 'file']) is not None  # should warn

    def test_mv_no_flags_ok(self):
        reg = build_extractor_registry()
        assert reg['mv'].command_validator(['src', 'dst']) is None

    def test_find_has_validator(self):
        reg = build_extractor_registry()
        assert reg['find'].command_validator is not None
        assert reg['find'].command_validator(['.', '-fprintf', '/tmp/out', '%p\n']) is not None
