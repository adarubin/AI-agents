"""HTML -> clean text extraction for dorked job pages, with a fallback chain and a sanity floor."""

from __future__ import annotations

import sys

import httpx

_MIN_CHARS = 400
_TIMEOUT = 15.0
_HEADERS = {"User-Agent": "Mozilla/5.0 (job-hunter-agent/1.0; +https://github.com)"}


def _fetch_html(url: str) -> str | None:
    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:  # noqa: BLE001 - a single dead link must not break discovery
        print(f"[extract] failed to fetch {url}: {exc}", file=sys.stderr)
        return None


def _extract_trafilatura(html: str, url: str) -> str | None:
    try:
        import trafilatura
    except ImportError:
        return None
    return trafilatura.extract(html, url=url)


def _extract_bs4(html: str) -> str | None:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def _extract_title(html: str) -> str | None:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else None


def extract_text(url: str) -> tuple[str | None, str] | None:
    """Fetch and extract (title, description_text) for a dorked job URL.

    Returns None when the fetch fails or the extracted text is too short to be a real job
    description (guards against feeding junk into the Gemini scoring step).
    """
    html = _fetch_html(url)
    if html is None:
        return None

    text = _extract_trafilatura(html, url) or _extract_bs4(html)
    if not text or len(text) < _MIN_CHARS:
        return None

    title = _extract_title(html)
    return title, text
