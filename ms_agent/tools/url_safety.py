# Copyright (c) ModelScope Contributors. All rights reserved.
"""Helpers for restricting outbound fetches to public HTTP(S) destinations."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import (HTTPRedirectHandler, Request, build_opener)

_BLOCKED_HOSTNAMES = frozenset({
    'localhost',
    'localhost.localdomain',
    'metadata',
    'metadata.google.internal',
})
_BLOCKED_HOST_SUFFIXES = ('.localhost', '.local', '.internal')


def _is_public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split('%', 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_global
        and not (ip.is_private or ip.is_loopback or ip.is_link_local
                 or ip.is_multicast or ip.is_reserved or ip.is_unspecified))


def _resolve_hostname(hostname: str) -> list[str]:
    infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def validate_public_url(url: str) -> str:
    """Return ``url`` when it targets a public HTTP(S) host.

    Raises:
        ValueError: if the scheme, hostname, or resolved addresses are not
            public HTTP(S). Hostnames are resolved here so a name pointing at
            loopback, RFC1918, link-local, or cloud-metadata space is rejected.
    """
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise ValueError(f'invalid URL: {url!r}') from exc

    if parsed.scheme.lower() not in {'http', 'https'}:
        raise ValueError(f'unsupported URL scheme: {parsed.scheme!r}')
    hostname = (parsed.hostname or '').strip().lower()
    if not hostname:
        raise ValueError('URL must include a hostname')
    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith(
            _BLOCKED_HOST_SUFFIXES):
        raise ValueError(f'blocked hostname: {hostname!r}')
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f'invalid port in URL: {url!r}') from exc

    try:
        addresses = _resolve_hostname(hostname)
    except OSError as exc:
        raise ValueError(f'could not resolve hostname: {hostname!r}') from exc
    if not addresses:
        raise ValueError(f'could not resolve hostname: {hostname!r}')
    if not all(_is_public_ip(address) for address in addresses):
        raise ValueError(f'URL resolves to a non-public address: {hostname!r}')
    return url


def is_safe_public_url(url: str) -> bool:
    """Return whether ``url`` may be fetched from the local host."""
    try:
        validate_public_url(url)
    except ValueError:
        return False
    return True


class _SafeRedirectHandler(HTTPRedirectHandler):
    """Reject redirects that leave the public HTTP(S) address space."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_safe_public_url(newurl):
            raise HTTPError(
                newurl,
                code,
                f'blocked redirect to a non-public URL: {newurl}',
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_SAFE_OPENER = build_opener(_SafeRedirectHandler())


def safe_urlopen(request: Request, timeout: float) -> Any:
    """Open ``request`` and validate every redirect target before following it."""
    if not is_safe_public_url(request.full_url):
        raise ValueError(f'blocked non-public URL: {request.full_url}')
    return _SAFE_OPENER.open(request, timeout=timeout)
