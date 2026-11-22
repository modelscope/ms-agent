"""Tests for ask_resolver: mode-based resolution of SafetyGuard ``ask`` decisions."""

import pytest

from ms_agent.permission.ask_resolver import resolve_ask
from ms_agent.permission.shell_validator import SafetyDecision


_CATEGORIES = [
    'process_input_sub',
    'process_output_sub',
    'parse_failure',
    'cd_write_compound',
    'command_validator',
    'shell_expansion',
    'read_outside_dirs',
]


class TestFullAccessMode:
    """full-access (and the old name strict): every uncertain call is allowed."""

    @pytest.mark.parametrize('category', _CATEGORIES)
    @pytest.mark.parametrize('mode', ['full-access', 'strict', 'full_access'])
    def test_uncertain_calls_pass(self, category: str, mode: str) -> None:
        decision = SafetyDecision(action='ask', reason='test', category=category)
        result = resolve_ask(decision, mode=mode)
        assert result.action == 'allow'
        assert 'full-access' in result.reason


class TestAskMode:
    """ask (and the old names interactive / restricted): leave the ask for the user."""

    @pytest.mark.parametrize('category', _CATEGORIES)
    @pytest.mark.parametrize('mode', ['ask', 'interactive', 'restricted'])
    def test_uncertain_calls_stay_asks(self, category: str, mode: str) -> None:
        decision = SafetyDecision(action='ask', reason='test reason', category=category)
        result = resolve_ask(decision, mode=mode)
        assert result.action == 'ask'
        assert result.reason == 'test reason'


class TestAutoMode:
    """auto keeps the ask so the model or agent provider can decide it."""

    @pytest.mark.parametrize('category', _CATEGORIES + ['something_new'])
    def test_uncertain_calls_stay_asks(self, category: str) -> None:
        decision = SafetyDecision(action='ask', reason='needs a decision', category=category)
        result = resolve_ask(decision, mode='auto', read_policy='strict')
        assert result.action == 'ask'
        assert result.reason == 'needs a decision'
        assert result.category == category


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
