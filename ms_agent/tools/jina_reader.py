import asyncio
import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

DEFAULT_HEADERS: Dict[str, str] = {
    'User-Agent':
    'Mozilla/5.0 (compatible; ms-agent/1.0; +https://example.com)',
    'Accept': 'text/plain; charset=utf-8',
    'Accept-Language': 'en-US,en;q=0.9',
}


@dataclass
class JinaReaderConfig:
    base_endpoint: str = 'https://r.jina.ai/'
    timeout: float = 30.0
    retries: int = 3
    backoff_base: float = 0.8
    backoff_max: float = 8.0
    headers: Dict[str,
                  str] = field(default_factory=lambda: DEFAULT_HEADERS.copy())


def _build_reader_url(target_url: str, base_endpoint: str) -> str:
    encoded_target = quote(target_url, safe=":/?&=%#@!$'*+,;[]()")
    base = base_endpoint if base_endpoint.endswith(
        '/') else f'{base_endpoint}/'
    return f'{base}{encoded_target}'


def _postprocess_text(raw_text: str) -> str:
    """
    Lightweight cleanup suitable for LLM consumption.
    - Normalize line breaks
    - Collapse excessive blank lines
    - Trim leading/trailing whitespace
    """
    if not raw_text:
        return ''
    text = raw_text.replace('\r\n', '\n').replace('\r', '\n')
    # Collapse 3+ consecutive blank lines down to 2
    while '\n\n\n' in text:
        text = text.replace('\n\n\n', '\n\n')
    return text.strip()


def fetch_single_text(url: str, config: JinaReaderConfig) -> str:
    """
    Synchronous fetch of a single URL via Jina Reader with retry/backoff and postprocessing.
    """
    request_url = _build_reader_url(url, config.base_endpoint)
    attempt = 0
    while True:
        attempt += 1
        try:
            req = Request(request_url, headers=config.headers)
            with urlopen(req, timeout=config.timeout) as resp:
                data = resp.read()
                return _postprocess_text(
                    data.decode('utf-8', errors='replace'))
        except HTTPError as e:
            # Retry on 429 and 5xx, otherwise fail fast
            status = getattr(e, 'code', None)
            if status in (429, 500, 502, 503,
                          504) and attempt <= config.retries:
                sleep_s = min(config.backoff_max,
                              config.backoff_base * (2**(attempt - 1)))
                sleep_s *= random.uniform(0.7, 1.4)
                time.sleep(sleep_s)
                continue
            return ''
        except URLError:
            if attempt <= config.retries:
                sleep_s = min(config.backoff_max,
                              config.backoff_base * (2**(attempt - 1)))
                sleep_s *= random.uniform(0.7, 1.4)
                time.sleep(sleep_s)
                continue
            return ''
        except Exception:
            # Unknown error; do not loop excessively
            if attempt <= config.retries:
                sleep_s = min(config.backoff_max,
                              config.backoff_base * (2**(attempt - 1)))
                sleep_s *= random.uniform(0.7, 1.4)
                time.sleep(sleep_s)
                continue
            return ''


async def fetch_texts_via_jina(
        urls: List[str],
        config: Optional[JinaReaderConfig] = None,
        semaphore: Optional[asyncio.Semaphore] = None,
        executor: Optional[ThreadPoolExecutor] = None) -> List[str]:
    """
    Asynchronously fetch a list of URLs via Jina Reader.
    Allows caller-provided concurrency controls (semaphore/executor) to integrate with pipeline resource management.
    """
    if not urls:
        return []
    cfg = config or JinaReaderConfig()
    loop = asyncio.get_event_loop()

    local_sem = semaphore or asyncio.Semaphore(8)

    async def _bound(u: str) -> str:
        async with local_sem:
            return await loop.run_in_executor(executor, fetch_single_text, u,
                                              cfg)

    tasks = [_bound(u) for u in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    texts: List[str] = []
    for r in results:
        if isinstance(r, Exception):
            continue
        if isinstance(r, str) and r.strip():
            texts.append(r)
    return texts


if __name__ == '__main__':
    urls = [
        'https://arxiv.org/pdf/2408.09869',
        'https://github.com/modelscope/evalscope',
        'https://www.news.cn/talking/20250530/691e47a5d1a24c82bfa2371d1af40630/c.html',
    ]
    texts = asyncio.run(fetch_texts_via_jina(urls))
    for text in texts:
        print(text)
        print('-' * 100)
