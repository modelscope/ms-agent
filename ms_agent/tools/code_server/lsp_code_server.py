import asyncio
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import json
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger
from ms_agent.utils.constants import (DEFAULT_INDEX_DIR, DEFAULT_LOCK_DIR,
                                      DEFAULT_OUTPUT_DIR)

logger = get_logger()


class LSPServer:
    """Base class for LSP server management"""

    def __init__(self, config):
        self.config = config
        self.process = None
        self.stdin = None
        self.stdout = None
        self.message_id = 0
        self.initialized = False
        self.output_dir = getattr(self.config, 'output_dir',
                                  DEFAULT_OUTPUT_DIR)
        self.workspace_dir = Path(self.output_dir).resolve()
        self.index_dir = os.path.join(self.output_dir, DEFAULT_INDEX_DIR)
        self.lock_dir = os.path.join(self.output_dir, DEFAULT_LOCK_DIR)
        self.diagnostics_cache: Dict[str, List[dict]] = {}

    async def start(self) -> bool:
        """Start the LSP server process"""
        raise NotImplementedError

    async def stop(self):
        """Stop the LSP server process"""
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
            except Exception as e:
                logger.error(f'Error stopping LSP server: {e}')
            finally:
                self.process = None
                self.stdin = None
                self.stdout = None
                self.initialized = False

    async def send_request(self, method: str, params: dict = None) -> dict:
        """Send a JSON-RPC request to the LSP server"""
        if not self.process or not self.stdin or not self.stdout:
            raise RuntimeError('LSP server not started')

        self.message_id += 1
        request_id = self.message_id
        request = {
            'jsonrpc': '2.0',
            'id': request_id,
            'method': method,
            'params': params or {}
        }

        content = json.dumps(request)
        message = f'Content-Length: {len(content)}\r\n\r\n{content}'

        try:
            self.stdin.write(message.encode('utf-8'))
            await self.stdin.drain()

            max_retries = 20
            for _ in range(max_retries):
                msg = await self._read_message()

                # Check if it's the response we're waiting for
                if 'id' in msg and msg['id'] == request_id:
                    return msg

                # It's a notification (no id) or response for different request
                # Log and continue reading
                if 'method' in msg:
                    logger.debug(
                        f"Received notification during request: {msg.get('method')}"
                    )
                    continue

            logger.warning(
                f'No response received for request {request_id} after {max_retries} attempts'
            )
            return {'error': 'No response received'}

        except Exception as e:
            logger.error(f'Error sending LSP request: {e}')
            return {'error': str(e)}

    async def send_notification(self, method: str, params: dict = None):
        """Send a JSON-RPC notification to the LSP server"""
        if not self.process or not self.stdin:
            raise RuntimeError('LSP server not started')

        notification = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params or {}
        }

        content = json.dumps(notification)
        message = f'Content-Length: {len(content)}\r\n\r\n{content}'

        try:
            self.stdin.write(message.encode('utf-8'))
            await self.stdin.drain()
        except Exception as e:
            logger.error(f'Error sending LSP notification: {e}')

    async def _read_message(self) -> dict:
        """Read a JSON-RPC message from the LSP server"""
        if not self.stdout:
            raise RuntimeError('LSP server stdout not available')

        # Read headers
        headers = {}
        while True:
            line = await self.stdout.readline()
            if not line:
                raise RuntimeError('LSP server closed connection')
            line = line.decode('utf-8').strip()
            if not line:
                break
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.strip()] = value.strip()

        # Read content
        content_length = int(headers.get('Content-Length', 0))
        if content_length > 0:
            content = await self.stdout.readexactly(content_length)
            logger.info('LSP:' + content.decode('utf-8'))
            return json.loads(content.decode('utf-8'))
        return {}

    async def initialize(self):
        """Initialize the LSP server and wait for it to be ready"""
        response = await self.send_request(
            'initialize', {
                'processId':
                os.getpid(),
                'rootUri':
                self.workspace_dir.as_uri(),
                'rootPath':
                str(self.workspace_dir),
                'workspaceFolders': [{
                    'uri': self.workspace_dir.as_uri(),
                    'name': self.workspace_dir.name
                }],
                'capabilities': {
                    'textDocument': {
                        'publishDiagnostics': {},
                        'synchronization': {
                            'didOpen': True,
                            'didChange': True,
                            'didClose': True
                        }
                    }
                }
            })

        if 'result' in response:
            await self.send_notification('initialized', {})

            # CRITICAL: Wait for server to be fully ready
            # Read and discard any startup messages
            await asyncio.sleep(
                1.0)  # Give server time to complete initialization

            await self.send_notification(
                'workspace/didChangeConfiguration', {
                    'settings': {
                        'python': {
                            'pythonPath': sys.executable,
                        },
                        'pyright': {
                            'extraPaths': [str(self.workspace_dir)]
                        },
                    }
                })

            # Consume any pending messages (like "starting" notifications)
            try:
                for _ in range(10):
                    try:
                        await asyncio.wait_for(
                            self._read_message(), timeout=2.0)
                    except asyncio.TimeoutError:
                        break
            except Exception as e:
                logger.error(f'Cleared startup messages: {e}')

            self.initialized = True
            logger.info('LSP server fully initialized and ready')
            return True

        logger.error(f'LSP initialization failed: {response}')
        return False

    async def open_document(self, file_path: str, content: str,
                            language_id: str):
        """Open a document in the LSP server"""
        file_uri = Path(file_path).resolve().as_uri()
        changes = [{'uri': file_uri, 'type': 1}]
        await self.send_notification('workspace/didChangeWatchedFiles',
                                     {'changes': changes})

        if file_path.endswith('.tsx'):
            language_id = 'typescriptreact'
        elif file_path.endswith('.jsx'):
            language_id = 'javascriptreact'
        elif file_path.endswith('.ts'):
            language_id = 'typescript'
        elif file_path.endswith('.js'):
            language_id = 'javascript'

        await self.send_notification(
            'textDocument/didOpen', {
                'textDocument': {
                    'uri': file_uri,
                    'languageId': language_id,
                    'version': 1,
                    'text': content
                }
            })
        await asyncio.sleep(2.0)

    async def close_document(self, file_path: str):
        """Close a document to clean up old index"""
        file_uri = Path(file_path).resolve().as_uri()
        await self.send_notification('textDocument/didClose',
                                     {'textDocument': {
                                         'uri': file_uri
                                     }})

    async def update_document(self,
                              file_path: str,
                              content: str,
                              version: int = 2):
        """Update a document in the LSP server"""
        file_uri = Path(file_path).resolve().as_uri()
        await self.send_notification(
            'textDocument/didChange', {
                'textDocument': {
                    'uri': file_uri,
                    'version': version
                },
                'contentChanges': [{
                    'text': content
                }]
            })

    async def get_diagnostics(self,
                              file_path: str,
                              wait_time: float = 2.0,
                              use_cache: bool = True) -> List[dict]:
        await asyncio.sleep(wait_time)

        file_uri = Path(file_path).resolve().as_uri()

        diagnostics = []
        found_target = False
        max_attempts = 99999
        consecutive_timeouts = 0

        for _ in range(max_attempts):
            try:
                msg = await asyncio.wait_for(self._read_message(), timeout=3.0)
                consecutive_timeouts = 0

                if msg.get('method') == 'textDocument/publishDiagnostics':
                    current_uri = msg.get('params', {}).get('uri')
                    current_diags = msg.get('params',
                                            {}).get('diagnostics', [])

                    self.diagnostics_cache[current_uri] = current_diags
                    logger.debug(f'Cached diagnostics for {current_uri}')

                    if current_uri == file_uri:
                        diagnostics = current_diags
                        found_target = True
                        logger.debug(
                            f'Found target diagnostics for {file_uri}')

            except asyncio.TimeoutError:
                consecutive_timeouts += 1
                if consecutive_timeouts >= 3:
                    logger.debug(
                        f'Stopped after {consecutive_timeouts} consecutive timeouts'
                    )
                    break
                else:
                    continue
            except RuntimeError as e:
                logger.error(f'Error reading diagnostics: {e}')
                break

        if not found_target:
            if use_cache and file_uri in self.diagnostics_cache:
                diagnostics = self.diagnostics_cache[file_uri]
                logger.debug(f'Using cached diagnostics for {file_uri}')
            else:
                logger.warning(
                    f'No diagnostics found for {file_uri} (cache available: {file_uri in self.diagnostics_cache})'
                )
                diagnostics = []
        else:
            if file_uri in self.diagnostics_cache:
                diagnostics = self.diagnostics_cache[file_uri]
        return diagnostics


class TypeScriptLSPServer(LSPServer):
    """TypeScript/JavaScript LSP server (tsserver)"""

    async def start(self) -> bool:
        """Start tsserver"""
        try:
            # Check if typescript is installed
            check_process = await asyncio.create_subprocess_exec(
                'npx',
                'tsc',
                '--version',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE)
            await check_process.communicate()

            if check_process.returncode != 0:
                logger.error(
                    'TypeScript not found. Install with: npm install -g typescript'
                )
                return False

            # Start typescript-language-server
            self.process = await asyncio.create_subprocess_exec(
                'npx',
                'typescript-language-server',
                '--stdio',
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace_dir))

            self.stdin = self.process.stdin
            self.stdout = self.process.stdout

            # Initialize the server
            return await self.initialize()

        except FileNotFoundError:
            logger.error(
                'typescript-language-server not found. Install with: npm install -g typescript-language-server'
            )
            return False
        except Exception as e:
            logger.error(f'Failed to start TypeScript LSP server: {e}')
            return False


class PythonLSPServer(LSPServer):
    """Python LSP server (pyright)"""

    async def start(self) -> bool:
        """Start pyright"""
        try:
            # Check if pyright is installed
            check_process = await asyncio.create_subprocess_exec(
                'pyright',
                '--version',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE)
            await check_process.communicate()

            if check_process.returncode != 0:
                logger.warning(
                    'Pyright not found. Install with: pip install pyright')
                return False

            # Start pyright langserver
            self.process = await asyncio.create_subprocess_exec(
                'pyright-langserver',
                '--stdio',
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace_dir))

            self.stdin = self.process.stdin
            self.stdout = self.process.stdout

            async def _read_server_stderr(process):
                while True:
                    line = await process.stderr.readline()
                    if not line:
                        break
                    logger.error(
                        f"LSP: {line.decode(errors='ignore').rstrip()}")

            asyncio.create_task(_read_server_stderr(self.process))

            # Initialize the server
            return await self.initialize()

        except FileNotFoundError:
            logger.error(
                'pyright-langserver not found. Install with: pip install pyright'
            )
            return False
        except Exception as e:
            logger.error(f'Failed to start Python LSP server: {e}')
            return False


class JavaLSPServer(LSPServer):
    """Java LSP server (Eclipse JDT Language Server)"""

    async def start(self) -> bool:
        """Start jdtls (Eclipse JDT Language Server)"""
        try:
            # Check if jdtls is available
            # Try common installation locations
            jdtls_paths = [
                '/usr/local/bin/jdtls',
                '/opt/homebrew/bin/jdtls',
                os.path.expanduser('~/.local/bin/jdtls'),
            ]

            jdtls_cmd = None
            for path in jdtls_paths:
                if os.path.exists(path):
                    jdtls_cmd = path
                    break

            if not jdtls_cmd:
                # Try to find in PATH
                check_process = await asyncio.create_subprocess_exec(
                    'which',
                    'jdtls',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE)
                stdout, _ = await check_process.communicate()
                if check_process.returncode == 0:
                    jdtls_cmd = stdout.decode('utf-8').strip()

            if not jdtls_cmd:
                logger.warning(
                    'jdtls not found. Install Eclipse JDT Language Server.\n'
                    'macOS: brew install jdtls\n'
                    'Or download from: https://download.eclipse.org/jdtls/snapshots/'
                )
                return False

            # Create workspace data directory for jdtls
            workspace_data_dir = Path(self.workspace_dir) / '.jdtls_workspace'
            workspace_data_dir.mkdir(exist_ok=True)

            # Start jdtls
            self.process = await asyncio.create_subprocess_exec(
                jdtls_cmd,
                '-data',
                str(workspace_data_dir),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace_dir))

            self.stdin = self.process.stdin
            self.stdout = self.process.stdout

            # Initialize the server
            return await self.initialize()

        except FileNotFoundError:
            logger.error(
                'jdtls not found. Install Eclipse JDT Language Server.\n'
                'macOS: brew install jdtls\n'
                'Or download from: https://download.eclipse.org/jdtls/snapshots/'
            )
            return False
        except Exception as e:
            logger.error(f'Failed to start Java LSP server: {e}')
            return False


class LSPCodeServer(ToolBase):

    skip_files = [
        'vite.config.ts', 'vite.config.js', 'webpack.config.js',
        'webpack.config.ts', 'rollup.config.js', 'rollup.config.ts',
        'next.config.js', 'next.config.ts', 'tsconfig.json', 'jsconfig.json',
        'package.json', 'pom.xml', 'build.gradle'
    ]

    language_mapping = {
        'typescript': ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'],
        'python': ['.py'],
        'java': ['.java'],
    }

    skip_prefixes = ['.', '..', '__pycache__', 'node_modules']

    def __init__(self, config):
        super().__init__(config)
        self.servers: Dict[str, LSPServer] = {}
        self.file_versions: Dict[str, int] = {}
        self.opened_documents: Dict[str, str] = {
        }  # Track opened documents: file_path -> language
        self.output_dir = getattr(self.config, 'output_dir',
                                  DEFAULT_OUTPUT_DIR)
        self.workspace_dir = self.output_dir
        self.index_dir = os.path.join(self.output_dir, DEFAULT_INDEX_DIR)
        self.lock_dir = os.path.join(self.output_dir, DEFAULT_LOCK_DIR)
        self.cleanup_lsp_index_dirs()

    async def connect(self) -> None:
        """Initialize LSP servers"""
        logger.info('LSP Code Server connecting...')

    def cleanup_lsp_index_dirs(self):
        cleanup_dirs = [
            os.path.join(self.output_dir, '.jdtls_workspace'),  # Java LSP
            os.path.join(self.output_dir,
                         '.pyright'),  # Python LSP (if exists)
            os.path.join(self.output_dir, 'node_modules',
                         '.cache'),  # TypeScript LSP cache
        ]

        for dir_path in cleanup_dirs:
            if os.path.exists(dir_path):
                try:
                    shutil.rmtree(dir_path, ignore_errors=True)
                except Exception as e:  # noqa
                    logger.warning(
                        f'Failed to cleanup LSP index directory {dir_path}: {e}'
                    )

    async def cleanup(self) -> None:
        """Stop all LSP servers and clear indexes"""
        # Close all open documents first
        for file_path, language in list(self.opened_documents.items()):
            server = self.servers.get(language)
            if server:
                try:
                    await server.close_document(file_path)
                except Exception as e:
                    logger.debug(f'Error closing document {file_path}: {e}')

        # Clear tracking
        self.opened_documents.clear()
        self.file_versions.clear()

        # Stop all servers
        for server in self.servers.values():
            await server.stop()
        self.servers.clear()
        logger.info('All LSP servers stopped and indexes cleared')

    async def _get_tools_inner(self) -> Dict[str, Any]:
        """Get available tools"""
        return {
            'lsp_code_server': [{
                'tool_name':
                'check_directory',
                'description':
                ('Check all code files in a directory for errors and issues. '
                 'Supports TypeScript/JavaScript, Python, Java files. '
                 'Returns a summary of all diagnostics found.'),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'directory': {
                            'type':
                            'string',
                            'description':
                            'Path to the directory to check (relative to workspace)'
                        },
                        'language': {
                            'type':
                            'string',
                            'enum': ['typescript', 'python', 'java'],
                            'description':
                            'Programming language to check (typescript for JS/TS, python for Python, java for Java)'
                        }
                    },
                    'required': ['directory', 'language']
                }
            }, {
                'tool_name':
                'update_and_check',
                'description':
                ("Incrementally update a file's content and check for errors. "
                 'Used during code generation to validate each N lines. '
                 'More efficient than checking from scratch each time.'),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'file_path': {
                            'type':
                            'string',
                            'description':
                            'Path to the file (relative to workspace)'
                        },
                        'content': {
                            'type': 'string',
                            'description': 'Updated file content'
                        },
                        'language': {
                            'type':
                            'string',
                            'enum': ['typescript', 'python', 'java'],
                            'description':
                            'Programming language to check (typescript for JS/TS, python for Python, java for Java)'
                        }
                    },
                    'required': ['file_path', 'content', 'language']
                }
            }]
        }

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        """Call a tool"""
        if tool_name == 'check_directory':
            return await self._check_directory(tool_args['directory'],
                                               tool_args['language'])

        elif tool_name == 'update_and_check':
            return await self._update_and_check(tool_args['file_path'],
                                                tool_args['content'],
                                                tool_args['language'])
        else:
            return json.dumps({'error': f'Unknown tool: {tool_name}'})

    async def _get_or_create_server(self,
                                    language: str) -> Optional[LSPServer]:
        """Get or create an LSP server for the given language"""
        if language in self.servers:
            return self.servers[language]

        # Create server
        if language == 'typescript':
            server = TypeScriptLSPServer(self.config)
        elif language == 'python':
            server = PythonLSPServer(self.config)
        elif language == 'java':
            server = JavaLSPServer(self.config)
        else:
            return None

        # Start server
        if await server.start():
            self.servers[language] = server
            return server
        return None

    async def _check_directory(self, directory: str, language: str) -> str:
        try:
            language = language.lower()
            server = await self._get_or_create_server(language)
            if not server:
                return json.dumps(
                    {'error': f'Failed to start LSP server for {language}'})

            dir_path = Path(self.workspace_dir) / directory
            if not dir_path.exists() or not dir_path.is_dir():
                return json.dumps(
                    {'error': f'Directory not found: {directory}'})

            extensions = self.language_mapping.get(language)

            if not extensions:
                return json.dumps(
                    {'error': f'No extensions found for language: {language}'})

            all_files = []
            for ext in extensions:
                all_files.extend(dir_path.rglob(f'*{ext}'))

            cleaned_files = []
            for file in all_files:
                filename = os.path.basename(file)
                if filename in self.skip_files:
                    continue

                configs = ('xml', 'json', 'yaml', 'yml', 'txt', 'md', 'gradle')
                if filename.endswith(configs):
                    continue
                if any([
                        filename.startswith(prefix)
                        for prefix in self.skip_prefixes
                ]):
                    continue
                rel_path = file.relative_to(dir_path)
                if any([
                        part.startswith(prefix) for part in rel_path.parts
                        for prefix in self.skip_prefixes
                ]):
                    continue
                cleaned_files.append(file)

            all_files = cleaned_files
            if not all_files:
                return json.dumps({
                    'message': f'No {language} files found in {directory}',
                    'file_count': 0,
                    'diagnostics': []
                })

            all_diagnostics = []
            for file_path in all_files:
                try:
                    content = file_path.read_text(encoding='utf-8')
                    rel_path = file_path.relative_to(Path(self.workspace_dir))
                    self.file_versions[str(rel_path)] = 1
                    await server.open_document(
                        str(file_path), content, language)
                    self.opened_documents[str(file_path)] = language

                    # Skip diagnostics for index-only mode (trust existing files)
                    # Uncomment below if you need to verify files:
                    # diagnostics = await server.get_diagnostics(str(file_path))
                    # if diagnostics:
                    #     all_diagnostics.append({
                    #         "file": str(rel_path),
                    #         "issues": self._format_diagnostics(diagnostics)
                    #     })
                except Exception as e:
                    logger.error(f'Error indexing file {file_path}: {e}')

            return json.dumps(
                {
                    'directory': directory,
                    'language': language,
                    'file_count': len(all_files),
                    'diagnostics': all_diagnostics,
                    'files_indexed': len(all_files) - len(all_diagnostics),
                    'status': 'indexed'
                },
                indent=2)

        except Exception as e:
            logger.error(f'Error checking directory: {e}')
            return json.dumps({'error': str(e)})

    @staticmethod
    def _format_diag_results(diagnostics_result):

        ignored_errors = [
            # 'cannot be assigned to', 'is not assignable to', 'cannot assign to',
            '"none"',
            'vue',
            'unused',
            'never used',
            'never read',
            'implicitly has'
        ]

        if diagnostics_result.get('has_errors'):
            issues = diagnostics_result.get('diagnostics', [])
            # Filter critical errors only
            critical_errors = [
                d for d in issues if d.get('severity') == 'Error' and not any([
                    ignore in d.get('message', '').lower()
                    for ignore in ignored_errors
                ])
            ]

            if critical_errors:
                error_msg = f'\n⚠️ LSP detected {len(critical_errors)} critical issues:\n'
                for i, diag in enumerate(critical_errors):
                    line = diag.get('line', 0)
                    msg = diag.get('message', '')
                    error_msg += f'{i}. Line {line}: {msg}\n'
                return error_msg
            else:
                return ''
        else:
            return ''

    async def _update_and_check(self, file_path: str, content: str,
                                language: str) -> str:
        """Update file content and check for errors"""
        try:
            server = await self._get_or_create_server(language)
            if not server:
                return json.dumps(
                    {'error': f'Failed to start LSP server for {language}'})

            full_path = Path(self.workspace_dir) / file_path
            full_path_str = str(full_path)

            if file_path not in self.file_versions:
                self.file_versions[file_path] = 1
                await server.open_document(full_path_str, content, language)
                self.opened_documents[full_path_str] = language
            else:
                self.file_versions[file_path] += 1
                await server.update_document(
                    full_path_str,
                    content,
                    version=self.file_versions[file_path])

            diagnostics = await server.get_diagnostics(str(full_path))

            diagnostics_result = {
                'file': file_path,
                'language': language,
                'version': self.file_versions[file_path],
                'has_errors': len(diagnostics) > 0,
                'diagnostic_count': len(diagnostics),
                'diagnostics': self._format_diagnostics(diagnostics)
            }

            return self._format_diag_results(diagnostics_result)

        except Exception as e:
            logger.error(f'Error updating and checking file: {e}')
            return json.dumps({'error': str(e)})

    @staticmethod
    def _format_diagnostics(diagnostics: List[dict]) -> List[dict]:
        """Format diagnostics for better readability"""
        formatted = []
        for diag in diagnostics:
            severity_map = {
                1: 'Error',
                2: 'Warning',
                3: 'Information',
                4: 'Hint'
            }

            formatted.append({
                'severity':
                severity_map.get(diag.get('severity', 1), 'Error'),
                'message':
                diag.get('message', ''),
                'line':
                diag.get('range', {}).get('start', {}).get('line', 0) + 1,
                'column':
                diag.get('range', {}).get('start', {}).get('character', 0) + 1,
                'source':
                diag.get('source', ''),
                'code':
                diag.get('code', '')
            })

        return formatted
