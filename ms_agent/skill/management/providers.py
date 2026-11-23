"""Public GitHub and ModelScope Skill sources; no writes to installed files."""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote, unquote, urlencode, urlparse

import httpx

from .content import extract_archive, relative_path
from .models import ManagedSource, SkillManagementError, SourceCollection
from .io import complete_io

MAX_DOWNLOAD = 64 * 1024 * 1024
_IDENTITY = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
MAX_COLLECTION_MEMBERS = 100


class SkillSourceProvider:
    """An async provider shared across operations; owns its HTTP client."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._owned = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(30, connect=10), follow_redirects=False)

    async def aclose(self):
        if self._owned:
            await self.client.aclose()

    def _headers(self, url: str) -> dict:
        headers = {'User-Agent': 'ms-agent-skill-manager'}
        parsed = urlparse(url)
        if (parsed.scheme == 'https' and parsed.port in (None, 443)
                and not parsed.username and not parsed.password
                and parsed.hostname in ('www.modelscope.cn', 'modelscope.cn')):
            token = os.environ.get('MODELSCOPE_API_KEY')
            if token:
                headers['Authorization'] = 'Bearer ' + token
        return headers

    @staticmethod
    def _check(response):
        status = response.status_code
        if status < 400:
            return
        retry = response.headers.get('retry-after', '')
        retry_after = int(retry) if retry.isdigit() else None
        if status == 429 or (status == 403
                             and response.headers.get('x-ratelimit-remaining')
                             == '0'):
            raise SkillManagementError('RATE_LIMITED',
                                       'The source rate limit was reached.',
                                       retry_after)
        if status in (401, 403):
            raise SkillManagementError('AUTH_REQUIRED',
                                       'The source requires authorization.')
        if status == 404:
            raise SkillManagementError(
                'SOURCE_UNAVAILABLE', 'The source or revision was not found.')
        raise SkillManagementError('SOURCE_UNAVAILABLE',
                                   'The source is temporarily unavailable.')

    async def _json(self, url: str, *, optional=False):
        try:
            async with self.client.stream(
                    'GET', url, headers=self._headers(url),
                    follow_redirects=False) as response:
                if optional and response.status_code == 404:
                    return None
                self._check(response)
                content = bytearray()
                async for block in response.aiter_bytes(65536):
                    content.extend(block)
                    if len(content) > 8 * 1024 * 1024:
                        raise SkillManagementError(
                            'INVALID_PACKAGE',
                            'Source metadata exceeds the limit.')
                return json.loads(content)
        except (httpx.HTTPError, ValueError) as exc:
            raise SkillManagementError(
                'SOURCE_UNAVAILABLE',
                'Could not read source metadata.') from exc

    async def resolve(self, value: str) -> ManagedSource | SourceCollection:
        value = value.strip()
        url = urlparse(value)
        if url.username or url.password or url.query:
            raise SkillManagementError(
                'UNSUPPORTED_SOURCE',
                'Use a public Skill page or repository URL.')
        if value.startswith(('modelscope://', '@')):
            raw = value.removeprefix('modelscope://')
            raw, _, subdir = raw.partition('#')
            prefix = '@' if raw.startswith('@') else ''
            repo, _, ref = raw.lstrip('@').partition('@')
            return await self._modelscope(
                prefix + repo,
                ref or 'master',
                subdir,
                pinned=bool(ref),
                discover=True)
        if url.scheme != 'https':
            raise SkillManagementError(
                'UNSUPPORTED_SOURCE',
                'Use an HTTPS GitHub or ModelScope link.')
        parts = [unquote(p) for p in url.path.strip('/').split('/') if p]
        if url.hostname == 'github.com' and len(parts) >= 2:
            repo = '/'.join(parts[:2]).removesuffix('.git')
            self._identity(repo)
            try:
                metadata = await self._json(
                    f'https://api.github.com/repos/{repo}')
            except SkillManagementError as exc:
                if exc.code != 'RATE_LIMITED':
                    raise
                return await self._resolve_git_fallback(repo, parts)
            ref = metadata['default_branch']
            kind = 'branch'
            subdir = ''
            if len(parts) > 2:
                if parts[2] not in ('tree', 'blob') or len(parts) < 4:
                    raise SkillManagementError(
                        'UNSUPPORTED_SOURCE',
                        'Use a repository or directory link.')
                tail = parts[3:]
                resolved = None
                # Resolve the longest *existing* ref; branches may contain '/'.
                for count in range(min(16, len(tail)), 0, -1):
                    candidate = '/'.join(tail[:count])
                    for namespace, selector in (('heads', 'branch'), ('tags',
                                                                      'tag')):
                        info = await self._json(
                            f'https://api.github.com/repos/{repo}/git/ref/'
                            f'{namespace}/{quote(candidate, safe="")}',
                            optional=True)
                        if info:
                            resolved = (candidate, selector, count)
                            break
                    if resolved:
                        break
                    if re.fullmatch(r'[0-9a-fA-F]{7,40}', candidate):
                        resolved = (candidate, 'commit', count)
                        break
                if not resolved:
                    raise SkillManagementError(
                        'SOURCE_UNAVAILABLE',
                        'The branch or revision was not found.')
                ref, kind, count = resolved
                subdir = '/'.join(tail[count:])
                if parts[2] == 'blob' and subdir.endswith('/SKILL.md'):
                    subdir = subdir[:-len('/SKILL.md')]
                elif parts[2] == 'blob' and subdir == 'SKILL.md':
                    subdir = ''
            if subdir:
                relative_path(subdir)
            commit = await self._github_revision(repo, ref)
            return ManagedSource('github', repo, ref, commit, kind, subdir,
                                 f'https://github.com/{repo}')
        if url.hostname in ('modelscope.cn', 'www.modelscope.cn',
                            'modelscope.ai', 'www.modelscope.ai'):
            if len(parts) == 3 and parts[0] == 'collections':
                try:
                    return await asyncio.wait_for(
                        self._collection('/'.join(parts[1:])), timeout=30)
                except asyncio.TimeoutError as exc:
                    raise SkillManagementError(
                        'SOURCE_UNAVAILABLE',
                        'The collection listing timed out.') from exc
            if len(parts) >= 3 and parts[0] == 'skills':
                return await self._modelscope(
                    '/'.join(parts[1:3]), discover=True)
        raise SkillManagementError('UNSUPPORTED_SOURCE',
                                   'Use a GitHub or ModelScope Skill link.')

    async def _collection(self, identity: str) -> SourceCollection:
        self._identity(identity)
        members = []
        seen = set()
        offset = 0
        title = identity
        # The website's collection API uses page numbers, not cursors. Require
        # progress and a stable total so a changed/truncated listing isn't
        # silently presented as a complete collection.
        total = None
        for page in range(1, MAX_COLLECTION_MEMBERS + 1):
            query = urlencode(
                dict(
                    Fid=identity,
                    PageNumber=page,
                    PageSize=50,
                    ElementType='skill'))
            response = await self._json(
                'https://www.modelscope.cn/api/v1/collections?' + query)
            data = response.get('Data') or {}
            listing = data.get('CollectionElements') or {}
            rows = listing.get('CollectionElementVoList')
            count = listing.get('Total')
            if (response.get('Success') is not True
                    or not isinstance(rows, list) or type(count) is not int
                    or count < 0 or (total is not None and count != total)):
                raise SkillManagementError('SOURCE_UNAVAILABLE',
                                           'Could not read the collection.')
            total = count
            if (total > MAX_COLLECTION_MEMBERS
                    or offset + len(rows) > MAX_COLLECTION_MEMBERS):
                raise SkillManagementError('PACKAGE_TOO_LARGE',
                                           'The collection is too large.')
            title = str(data.get('Name') or identity)
            added = 0
            for row in rows:
                if row.get('ElementType') != 'skill':
                    continue
                member = (
                    str(row.get('ElementPath', '')) + '/'
                    + str(row.get('ElementName', '')))
                self._identity(member.removeprefix('@'))
                if member not in seen:
                    members.append(member)
                    seen.add(member)
                    added += 1
            offset += len(rows)
            if offset >= total:
                break
            if not rows or not added:
                raise SkillManagementError(
                    'SOURCE_UNAVAILABLE',
                    'The collection listing is incomplete.')
        if not members:
            raise SkillManagementError('SKILL_NOT_FOUND',
                                       'This collection contains no Skills.')
        return SourceCollection(
            identity, 'https://modelscope.cn/collections/' + identity, title,
            members)

    async def resolve_member(self, registry_id: str) -> ManagedSource:
        # A collection provides an exact registry identity. Never substitute
        # an @ mirror for a deleted/unavailable native repository or vice versa.
        return await self._modelscope(registry_id)

    @staticmethod
    def _identity(repo: str):
        if not _IDENTITY.fullmatch(repo) or any(
                part in ('.', '..') for part in repo.split('/')):
            raise SkillManagementError('UNSUPPORTED_SOURCE',
                                       'Invalid repository identity.')

    async def _github_revision(self, repo: str, ref: str) -> str:
        try:
            data = await self._json(
                f'https://api.github.com/repos/{repo}/commits/'
                f'{quote(ref, safe="")}')
        except SkillManagementError as exc:
            if exc.code != 'RATE_LIMITED':
                raise
            _, refs = await self._read_git_refs(repo)
            revision = refs.get('refs/heads/' + ref) or refs.get(
                'refs/tags/' + ref + '^{}') or refs.get('refs/tags/' + ref)
            if revision:
                return revision
            raise
        revision = data.get('sha', '')
        if not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise SkillManagementError('SOURCE_UNAVAILABLE',
                                       'The source did not provide a commit.')
        return revision

    async def _read_git_refs(self, repo):
        """Public git transport remains usable when anonymous REST is limited."""
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                'git',
                'ls-remote',
                '--symref',
                f'https://github.com/{repo}',
                'HEAD',
                'refs/heads/*',
                'refs/tags/*',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env={
                    **os.environ, 'GIT_TERMINAL_PROMPT': '0'
                })
            output, _ = await asyncio.wait_for(process.communicate(), 30)
            if process.returncode or len(output) > 2 * 1024 * 1024:
                raise SkillManagementError(
                    'SOURCE_UNAVAILABLE', 'Could not resolve repository refs.')
            default, refs = None, {}
            for line in output.decode('utf-8').splitlines():
                value, _, name = line.partition('\t')
                if value.startswith('ref: refs/heads/') and name == 'HEAD':
                    default = value[len('ref: refs/heads/'):]
                elif re.fullmatch(r'[0-9a-f]{40}', value):
                    refs[name] = value
            if not default or not refs:
                raise SkillManagementError('SOURCE_UNAVAILABLE',
                                           'Repository refs are unavailable.')
            return default, refs
        except (OSError, asyncio.TimeoutError) as exc:
            raise SkillManagementError(
                'RATE_LIMITED',
                'GitHub is rate limited and the Git fallback is unavailable.'
            ) from exc
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()

    async def _resolve_git_fallback(self, repo, parts):
        default, refs = await self._read_git_refs(repo)
        ref, kind, subdir = default, 'branch', ''
        revision = refs.get('refs/heads/' + default)
        if len(parts) > 2:
            if parts[2] not in ('tree', 'blob') or len(parts) < 4:
                raise SkillManagementError(
                    'UNSUPPORTED_SOURCE',
                    'Use a repository or directory link.')
            tail = parts[3:]
            found = False
            for count in range(len(tail), 0, -1):
                ref = '/'.join(tail[:count])
                for prefix, kind in (('refs/heads/', 'branch'), ('refs/tags/',
                                                                 'tag')):
                    revision = refs.get(prefix + ref
                                        + '^{}') or refs.get(prefix + ref)
                    if revision:
                        found = True
                        break
                if not found and re.fullmatch(r'[0-9a-f]{40}', ref):
                    revision, kind, found = ref, 'commit', True
                if found:
                    subdir = '/'.join(tail[count:])
                    break
            if not found:
                raise SkillManagementError(
                    'SOURCE_UNAVAILABLE',
                    'The branch or revision was not found.')
            if parts[2] == 'blob':
                subdir = subdir.removesuffix('SKILL.md').rstrip('/')
        if subdir:
            relative_path(subdir)
        return ManagedSource('github', repo, ref, revision, kind, subdir,
                             f'https://github.com/{repo}')

    async def _modelscope(self,
                          identity: str,
                          ref='master',
                          subdir='',
                          pinned=False,
                          discover=False):
        repo = identity.removeprefix('@')
        self._identity(repo)
        if subdir:
            relative_path(subdir)
        identities = [identity]
        if discover:
            identities.append(repo if identity.startswith('@') else '@' + repo)
        for registry_id in identities:
            data = await self._json(
                f'https://www.modelscope.cn/api/v1/skills/{registry_id}/repo/files'
                f'?Revision={quote(ref, safe="")}&Root=&Recursive=true',
                optional=discover)
            if data is not None:
                break
        else:
            raise SkillManagementError('SOURCE_UNAVAILABLE',
                                       'The Skill repository was not found.')
        revision = (data.get('Data') or {}).get('LatestCommitter',
                                                {}).get('Id')
        if not revision or not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise SkillManagementError(
                'SOURCE_UNAVAILABLE',
                'The Skill repository did not provide a commit.')
        return ManagedSource(
            'modelscope',
            repo,
            ref,
            revision,
            'commit' if pinned else 'branch',
            subdir,
            f'https://www.modelscope.cn/skills/{registry_id}',
            registry_id=registry_id)

    async def latest(self, source: ManagedSource) -> ManagedSource:
        if source.selector_kind != 'branch':
            return source
        if source.provider == 'github':
            return replace(
                source,
                revision=await self._github_revision(source.repository,
                                                     source.ref))
        resolved = await self._modelscope(source.identity[1], source.ref,
                                          source.subdir)
        return replace(source, revision=resolved.revision)

    async def materialize(self, source: ManagedSource,
                          destination: Path) -> Path:
        if source.provider == 'github':
            url = (f'https://codeload.github.com/{source.repository}/zip/'
                   f'{source.revision}')
        else:
            url = (
                f'https://www.modelscope.cn/api/v1/skills/{source.identity[1]}'
                f'/archive/zip/{source.revision}')
        destination.mkdir(parents=True, exist_ok=False)
        archive = destination / 'source.zip'
        try:
            await asyncio.wait_for(self._download(url, archive), timeout=120)
            root = await complete_io(extract_archive, archive,
                                     destination / 'content')
            archive.unlink(missing_ok=True)
            return root
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            raise SkillManagementError(
                'SOURCE_UNAVAILABLE',
                'The source download failed or timed out.') from exc

    async def _download(self, url: str, target: Path):
        for _ in range(5):
            async with self.client.stream(
                    'GET', url, headers=self._headers(url),
                    follow_redirects=False) as response:
                if response.is_redirect:
                    next_url = str(
                        response.url.join(response.headers['location']))
                    parsed = urlparse(next_url)
                    host = parsed.hostname or ''
                    if (parsed.scheme != 'https' or parsed.username
                            or parsed.password
                            or parsed.port not in (None, 443)
                            or not (host in
                                    ('api.github.com', 'codeload.github.com',
                                     'www.modelscope.cn', 'modelscope.cn')
                                    or host.endswith(
                                        ('.modelscope.cn', '.aliyuncs.com')))):
                        raise SkillManagementError(
                            'UNSUPPORTED_SOURCE',
                            'Unsupported download redirect.')
                    url = next_url
                    continue
                self._check(response)
                total = 0
                with target.open('xb') as output:
                    async for block in response.aiter_bytes(65536):
                        total += len(block)
                        if total > MAX_DOWNLOAD:
                            raise SkillManagementError(
                                'PACKAGE_TOO_LARGE',
                                'Download exceeds the size limit.')
                        output.write(block)
                return
        raise SkillManagementError('SOURCE_UNAVAILABLE', 'Too many redirects.')
