"""HTML -> clean text extraction for dorked job pages, with a fallback chain and a sanity floor."""

from __future__ import annotations

import sys
import json
from datetime import datetime, timezone

import httpx
from job_agent.models import Platform, RawJob

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


def extract_posting(url: str, external_id: str) -> RawJob | None:
    """Only structured JobPosting data can establish a searched page's location.

    Do not infer a location from the search query, company offices, or page footer.
    Comeet serves actual position data separately from its Angular templates.
    """
    from bs4 import BeautifulSoup
    from job_agent.sources.ats_api import _parse_iso, _strip_html
    from job_agent.sources.comeet import embedded_data, parse_position

    raw = _fetch_html(url)
    if raw is None:
        return None
    position = embedded_data(raw, 'POSITION_DATA')
    if isinstance(position, dict):
        return parse_position(position)
    soup = BeautifulSoup(raw, 'lxml')
    nodes = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.get_text())
            nodes.extend(value if isinstance(value, list) else [value])
        except ValueError:
            continue
    postings = []
    while nodes:
        node = nodes.pop()
        if not isinstance(node, dict):
            continue
        nodes.extend(node.get('@graph') or [])
        types = node.get('@type')
        if types == 'JobPosting' or isinstance(types, list) and 'JobPosting' in types:
            postings.append(node)
    # A list page must not masquerade as one job.
    if len(postings) != 1:
        return None
    item = postings[0]
    expires = _parse_iso(item.get('validThrough'))
    if expires:
        expires = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            return None
    locations = item.get('jobLocation') or []
    locations = locations if isinstance(locations, list) else [locations]
    names = []
    for loc in locations:
        address = loc.get('address') or {} if isinstance(loc, dict) else {}
        if not isinstance(address, dict):
            continue
        country = address.get('addressCountry') or ''
        if isinstance(country, dict):
            country = country.get('name', '')
        if country.upper() == 'IL':
            country = 'Israel'
        names.append(', '.join(filter(None, [address.get('addressLocality'), address.get('addressRegion'), country])))
    remote = item.get('jobLocationType') == 'TELECOMMUTE'
    if remote:
        eligibility = item.get('applicantLocationRequirements') or []
        eligibility = eligibility if isinstance(eligibility, list) else [eligibility]
        names.extend('Remote - ' + str(x.get('name', '')) for x in eligibility if isinstance(x, dict))
    org = item.get('hiringOrganization') or {}
    return RawJob(
        platform=Platform.DORKED, external_id=external_id,
        title=item.get('title') or '', company=org.get('name', '') if isinstance(org, dict) else '',
        url=url, apply_url=url, location='; '.join(filter(None, names)) or None,
        is_remote=remote, posted_at=_parse_iso(item.get('datePosted')),
        description_text=_strip_html(item.get('description', '')),
    )
