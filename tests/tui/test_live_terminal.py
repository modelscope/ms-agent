# Copyright (c) ModelScope Contributors. All rights reserved.
"""The streaming region and the prompt share a real terminal.

A pipe cannot show this: Live has to redraw in place, and paste / arrow keys
are only keys once prompt_toolkit owns the tty by itself.
"""
import os
import pty
import select
import struct
import subprocess
import sys
import termios
import time

import fcntl
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHILD = r'''
import asyncio
import sys

from rich.console import Console

from ms_agent.tui.input import PromptToolkitInput
from ms_agent.tui.renderer import RichEventSink
from ms_agent.tui.state import TuiState
from ms_agent.ui.events import ContentDelta, ContentEnd


async def main():
    console = Console(force_terminal=True, width=40, height=12)
    sink = RichEventSink(console, TuiState())
    body = "\n".join("line %02d unique-token" % i for i in range(30))
    sink.emit(ContentDelta(body))
    await asyncio.sleep(0.45)
    sink.emit(ContentEnd())
    inp = PromptToolkitInput(TuiState(), console=console, renderer=sink)
    if inp._session is None:
        print("NO_SESSION", file=sys.stderr, flush=True)
        return
    inp._session.history.append_string("previous-command")
    recalled = await inp.read_prompt()
    pasted = await inp.read_prompt()
    queued = await inp.read_prompt()
    print("RESULTS %r %r %r" % (recalled, pasted, queued), file=sys.stderr, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
'''


def _read_pty(master, proc, buf, timeout):
    """Pull pty bytes and stderr until timeout. Returns (buf, stderr_lines, why)."""
    err_lines = []
    end = time.time() + timeout
    while time.time() < end:
        watch = [master]
        if proc.stderr is not None:
            watch.append(proc.stderr)
        ready, _, _ = select.select(watch, [], [], 0.1)
        if master in ready:
            try:
                buf += os.read(master, 65536)
            except OSError:
                return buf, err_lines, 'closed'
        if proc.stderr is not None and proc.stderr in ready:
            line = proc.stderr.readline()
            if line:
                err_lines.append(line)
                if line.startswith(b'RESULTS') or line.startswith(b'NO_SESSION'):
                    return buf, err_lines, 'done'
        if proc.poll() is not None and not ready:
            return buf, err_lines, 'exit'
    return buf, err_lines, 'timeout'


@pytest.mark.skipif(sys.platform == 'win32', reason='needs a posix pty')
def test_one_screen_live_then_paste_and_history(tmp_path):
    script = tmp_path / 'drive.py'
    script.write_text(CHILD)
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 12, 40, 0, 0))
    env = os.environ.copy()
    env['PYTHONPATH'] = REPO
    env['PYTHONUNBUFFERED'] = '1'
    env['TERM'] = 'xterm-256color'
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        stdin=slave,
        stdout=slave,
        stderr=subprocess.PIPE,
        env=env,
        cwd=REPO,
    )
    os.close(slave)
    buf = b''
    err_lines = []
    try:
        prompt = '❯'.encode()
        deadline = time.time() + 8
        while time.time() < deadline and prompt not in buf:
            buf, extra, why = _read_pty(master, proc, buf, 0.3)
            err_lines.extend(extra)
            if why in ('done', 'closed'):
                break
        assert prompt in buf, buf[-400:]
        os.write(master, b'\x1b[A\r')

        deadline = time.time() + 5
        while time.time() < deadline and buf.count(prompt) < 2:
            buf, extra, why = _read_pty(master, proc, buf, 0.3)
            err_lines.extend(extra)
            if why in ('done', 'closed'):
                break
        assert buf.count(prompt) >= 2, buf[-400:]
        os.write(master, b'\x1b[200~/model qwen\nhello\x1b[201~\r')

        buf, extra, why = _read_pty(master, proc, buf, 4)
        err_lines.extend(extra)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
        os.close(master)

    text = buf.decode('utf-8', 'replace')
    err = b''.join(err_lines).decode()
    # The first line of a tall reply is typeset once. The refresh loop only
    # rewrites the last screen, in place.
    assert text.count('line 00') == 1
    assert text.count('Assistant') == 1
    assert b'\x1b[1A' in buf
    assert '^[[200~' not in text and '^[[201~' not in text
    assert "RESULTS 'previous-command' '/model qwen' 'hello'" in err
