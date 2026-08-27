"""Commands the policy used to refuse although they touch nothing outside the
workspace. Each case here is one that was reported from a real session."""
import pytest

from ms_agent.permission.config import SafetyConfig
from ms_agent.permission.shell_validator import (PathSafetyConfig,
                                                 ShellPathValidator)

WS = '/tmp/ms-agent-policy-tests'


def _validator(**safety_kwargs) -> ShellPathValidator:
    cfg = SafetyConfig(**safety_kwargs)
    allowed = list(cfg.effective_allowed_directories(WS))
    return ShellPathValidator(
        allowed_dirs=allowed,
        safety_config=PathSafetyConfig(
            workspace_root=WS,
            allowed_directories=tuple(allowed),
            dangerous_removal_paths=cfg.dangerous_removal_paths,
        ))


HEREDOC_WITH_GLOB_CHARS = """python3 - <<EOF
data = [1, 2, 3]
result = [x * 2 for x in data if x > 1]
print(result)
EOF"""

HEREDOC_QUOTED_DELIMITER = """python3 - <<'PY'
with open('out_*.json', 'w') as f:
    f.write('a > b')
PY"""

HEREDOC_TAB_STRIPPED = """cat <<-END
\tbody containing > and [brackets]
\tEND"""


@pytest.mark.parametrize(
    'command',
    [
        # The redirect target used to be read with \S+, so the subshell's
        # closing paren became part of the filename: "/dev/null)".
        'rg -F -n "ORANGE-RIVER-731" . 2>/dev/null',
        'echo hi 2>/dev/null)',
        '(ls >> /dev/null)',
        'make build > log.txt 2>&1',
        # A '>' inside a quoted argument is not a redirection.
        'git commit -m "perf: speed > /etc of before"',
        # Heredoc bodies are data, not commands.
        HEREDOC_TAB_STRIPPED,
    ],
)
def test_allows_commands_that_touch_nothing_outside_the_workspace(command):
    assert _validator().check(command).action == 'allow', command


@pytest.mark.parametrize('command',
                         [HEREDOC_WITH_GLOB_CHARS, HEREDOC_QUOTED_DELIMITER])
def test_inline_script_is_judged_as_code_not_as_bogus_paths(command):
    decision = _validator().check(command)
    assert decision.category == 'interpreter_exec'
    assert 'Glob' not in decision.reason
    assert 'outside allowed directories' not in decision.reason


def test_os_temp_directory_is_writable_by_default():
    assert _validator().check('touch /tmp/probe.py').action == 'allow'


def test_os_temp_directory_can_be_taken_away():
    decision = _validator(allow_temp_dir=False).check('touch /tmp/probe.py')
    assert decision.action != 'allow'


@pytest.mark.parametrize('command, fragment', [
    ('echo x > /etc/passwd', 'outside allowed directories'),
    ('ls >> /etc/hosts', 'outside allowed directories'),
    ('touch "out_*.json"', 'Glob patterns not allowed'),
    ('echo x > $HOME/y.txt', 'variable expansion'),
])
def test_real_violations_are_still_refused(command, fragment):
    decision = _validator().check(command)
    assert decision.action != 'allow', command
    assert fragment in decision.reason


@pytest.mark.parametrize('command', [
    # A pasted heredoc that arrived flattened onto one line, and one that was
    # opened but never closed — both real-world shapes.
    'python3 - <<EOFdata = [1, 2, 3]result = [x * 2 for x in data if x > 1]'
    'print(result)EOF',
    'cat <<EOF\nsome > text\n',
])
def test_an_unterminated_heredoc_is_not_refused_for_an_invented_reason(command):
    """Reading the payload as filenames produced refusals like "Glob patterns
    not allowed in create operations: 1]print" — untrue, and hiding the real
    problem. Let the shell reject it on its own terms."""
    decision = _validator().check(command)
    assert 'Glob' not in decision.reason
    assert 'outside allowed directories' not in decision.reason
    if decision.action != 'allow':
        assert decision.category == 'interpreter_exec', decision.reason
