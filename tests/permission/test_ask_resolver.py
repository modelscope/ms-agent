"""Tests for ask_resolver: mode-based resolution of SafetyGuard ``ask`` decisions."""

import pytest

from ms_agent.permission.ask_resolver import resolve_ask
from ms_agent.permission.shell_validator import SafetyDecision


class TestStrictMode:
    """strict mode: all ask → deny."""

    @pytest.mark.parametrize('category', [
        'process_input_sub',
        'process_output_sub',
        'parse_failure',
        'cd_write_compound',
        'command_validator',
        'shell_expansion',
        'read_outside_dirs',
    ])
    def test_all_ask_denied(self, category: str) -> None:
        decision = SafetyDecision(action='ask', reason='test', category=category)
        result = resolve_ask(decision, mode='strict')
        assert result.action == 'deny'
        assert 'strict mode' in result.reason


class TestInteractiveMode:
    """interactive mode: ask unchanged."""

    @pytest.mark.parametrize('category', [
        'process_input_sub',
        'process_output_sub',
        'parse_failure',
        'cd_write_compound',
        'command_validator',
        'shell_expansion',
        'read_outside_dirs',
    ])
    def test_all_ask_preserved(self, category: str) -> None:
        decision = SafetyDecision(action='ask', reason='test reason', category=category)
        result = resolve_ask(decision, mode='interactive')
        assert result.action == 'ask'
        assert result.reason == 'test reason'


class TestAutoMode:
    """auto mode: per-category resolution."""

    def test_process_input_sub_allowed(self) -> None:
        decision = SafetyDecision(action='ask', reason='input sub', category='process_input_sub')
        result = resolve_ask(decision, mode='auto')
        assert result.action == 'allow'

    def test_process_output_sub_denied(self) -> None:
        decision = SafetyDecision(action='ask', reason='output sub', category='process_output_sub')
        result = resolve_ask(decision, mode='auto')
        assert result.action == 'deny'

    def test_parse_failure_denied(self) -> None:
        decision = SafetyDecision(action='ask', reason='bad parse', category='parse_failure')
        result = resolve_ask(decision, mode='auto')
        assert result.action == 'deny'

    def test_cd_write_compound_denied(self) -> None:
        decision = SafetyDecision(action='ask', reason='cd+write', category='cd_write_compound')
        result = resolve_ask(decision, mode='auto')
        assert result.action == 'deny'

    def test_command_validator_denied(self) -> None:
        decision = SafetyDecision(action='ask', reason='suspicious', category='command_validator')
        result = resolve_ask(decision, mode='auto')
        assert result.action == 'deny'

    def test_shell_expansion_denied(self) -> None:
        decision = SafetyDecision(action='ask', reason='$VAR', category='shell_expansion')
        result = resolve_ask(decision, mode='auto')
        assert result.action == 'deny'

    def test_unknown_category_denied(self) -> None:
        decision = SafetyDecision(action='ask', reason='unknown', category='something_new')
        result = resolve_ask(decision, mode='auto')
        assert result.action == 'deny'


class TestReadPolicy:
    """read_outside_dirs resolved by read_policy in auto mode."""

    def test_loose_allows_read_outside(self) -> None:
        decision = SafetyDecision(action='ask', reason='outside', category='read_outside_dirs')
        result = resolve_ask(decision, mode='auto', read_policy='loose')
        assert result.action == 'allow'

    def test_strict_denies_read_outside(self) -> None:
        decision = SafetyDecision(action='ask', reason='outside', category='read_outside_dirs')
        result = resolve_ask(decision, mode='auto', read_policy='strict')
        assert result.action == 'deny'


class TestPassthrough:
    """Non-ask decisions pass through unchanged."""

    def test_allow_unchanged(self) -> None:
        decision = SafetyDecision(action='allow', reason='ok')
        result = resolve_ask(decision, mode='strict')
        assert result is decision

    def test_deny_unchanged(self) -> None:
        decision = SafetyDecision(action='deny', reason='blocked')
        result = resolve_ask(decision, mode='auto')
        assert result is decision
