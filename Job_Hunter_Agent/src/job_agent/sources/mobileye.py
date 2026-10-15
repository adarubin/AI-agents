"""Public Mobileye career cards contain per-job locations and complete requirements."""
from __future__ import annotations

import sys
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from job_agent.models import Platform, RawJob

URL = 'https://careers.mobileye.com/jobs'


def parse_jobs(html: str) -> list[RawJob]:
    soup = BeautifulSoup(html, 'lxml')
    jobs = []
    seen = set()
    for card in soup.select('.jobItem'):
        title = card.select_one('.jobTitle')
        link = card.select_one('a[href^="/jobs/"]')
        icon = card.select_one('img[alt="location icon"]')
        body = card.select_one('.bottomSection')
        if title is None or link is None or icon is None or body is None:
            continue
        location = icon.parent.find('p')
        if location is None:
            continue
        url = urljoin(URL, link['href'])
        if url in seen:
            continue
        seen.add(url)
        # Company-wide AI boilerplate cannot make every role an ML role.
        for element in body.select('.positionIntroTextWrapper, .additionalText, .btnsWrapper'):
            element.decompose()
        for item in body.select('li'):
            item.append(' ; ')
        jobs.append(RawJob(
            platform=Platform.DORKED, external_id='mobileye:' + urlparse(url).path.rsplit('/', 1)[-1],
            title=title.get_text(' ', strip=True), company='Mobileye', url=url, apply_url=url,
            location=location.get_text(' ', strip=True), description_text=body.get_text(' ', strip=True),
            active_verified=True,
        ))
    return jobs


def fetch(errors: list[str] | None = None) -> list[RawJob]:
    try:
        response = httpx.get(URL, timeout=25, follow_redirects=True)
        response.raise_for_status()
        jobs = parse_jobs(response.text)
        if not jobs:
            raise ValueError('career cards missing; source markup may have changed')
        return jobs
    except Exception as exc:
        msg = f'[mobileye] public careers listing failed: {exc}'
        print(msg, file=sys.stderr)
        if errors is not None:
            errors.append(msg)
        return []
