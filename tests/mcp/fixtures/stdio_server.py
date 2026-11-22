"""Tiny real stdio peer for lifecycle tests; no third-party imports."""
import json
import os
import signal
import sys
import time
from pathlib import Path

mode, pidfile = sys.argv[1:3]
Path(pidfile).write_text(str(os.getpid()))
if mode == 'ignore_term':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if mode == 'exit':
    print('package download failed HTTP 403 token=secret-value', file=sys.stderr)
    raise SystemExit(1)
for line in sys.stdin:
    request = json.loads(line)
    method = request.get('method')
    if 'id' not in request:
        continue
    if method == 'initialize':
        if mode in ('initialize', 'ignore_term'):
            time.sleep(60)
        result = {'protocolVersion': request['params']['protocolVersion'],
                  'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'fixture', 'version': '1'}}
    elif method == 'tools/list':
        if mode == 'list_tools':
            time.sleep(60)
        result = {'tools': [{'name': 'demo', 'description': 'fixture',
                            'inputSchema': {'type': 'object'}}]}
    else:
        result = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
