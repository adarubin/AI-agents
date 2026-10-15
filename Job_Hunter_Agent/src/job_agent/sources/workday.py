"""Public Workday career search with an advertised Israel facet and verified job details."""
from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx

from job_agent.eligibility import location_rejection, title_may_match
from job_agent.models import Platform, RawJob
from job_agent.sources.ats_api import _get_json, _parse_iso, _strip_html


def israel_facet(facets: list[dict]) -> tuple[str, str] | None:
    for facet in facets:
        parameter = facet.get('facetParameter')
        for value in facet.get('values') or []:
            if value.get('descriptor', '').casefold() == 'israel' and value.get('id'):
                return parameter, value['id']
            if 'facetParameter' in value:
                nested = israel_facet([value])
                if nested:
                    return nested
    return None


def parse_posting(info: dict, company: str, expected_host: str) -> RawJob | None:
    if info.get('canApply') is not True or info.get('posted') is not True:
        return None
    url = info.get('externalUrl')
    if not url or urlparse(url).hostname != expected_host or not info.get('jobReqId'):
        return None
    locations = [info.get('location')]
    locations.extend(info.get('additionalLocations') or [])
    requisition = info.get('jobRequisitionLocation') or {}
    if (requisition.get('country') or {}).get('alpha2Code') == 'IL':
        locations.append(requisition.get('descriptor') or 'Israel')
    locations = [loc for loc in locations if isinstance(loc, str) and not re.fullmatch(r'\d+ Locations?', loc, re.I)]
    job = RawJob(
        Platform.DORKED, f"workday:{company}:{info['jobReqId']}", info.get('title', ''), company,
        url, url, location='; '.join(dict.fromkeys(locations)) or None,
        posted_at=_parse_iso(info.get('startDate')),
        description_text=_strip_html(info.get('jobDescription', '')), active_verified=True,
    )
    return job if location_rejection(job) is None else None


def _search(client: httpx.Client, base: str, query: str, offset: int, facets: dict) -> dict:
    response = client.post(base + '/jobs', json={
        'limit': 20, 'offset': offset, 'searchText': query, 'appliedFacets': facets,
    })
    response.raise_for_status()
    return response.json()


def fetch(boards: list[dict], errors: list[str] | None = None) -> list[RawJob]:
    jobs = []
    seen_keys = set()
    with httpx.Client(timeout=20) as client:
        for board in boards:
            name, base = board['name'], board['base_url'].rstrip('/')
            try:
                seed = _search(client, base, 'Israel', 0, {})
                facet = israel_facet(seed.get('facets') or [])
                if facet is None:
                    raise ValueError('Israel location facet is unavailable')
                candidates = {}
                for query in board.get('queries', ['deep learning', 'computer vision', 'robotics']):
                    try:
                        for offset in range(0, 100, 20):
                            listing = _search(client, base, query, offset, {facet[0]: [facet[1]]})
                            items = listing.get('jobPostings') or []
                            for item in items:
                                path = item.get('externalPath', '')
                                if path.startswith('/job/') and title_may_match(item.get('title', '')):
                                    candidates[path] = item
                            if not items or offset + len(items) >= listing.get('total', 0):
                                break
                    except Exception as exc:
                        _error(f'{name} query {query}', exc, errors)
                # Keep junior opportunities visible even when senior postings dominate a board.
                ordered = sorted(candidates, key=lambda p: not any(
                    word in candidates[p].get('title', '').lower() for word in ('student', 'intern', 'new college', 'graduate', 'junior')
                ))
                def load_detail(path: str):
                    try:
                        detail = _get_json(client, base + path)
                        job = parse_posting(detail.get('jobPostingInfo') or {}, name, urlparse(base).hostname)
                        return path, job, None
                    except Exception as exc:
                        return path, None, exc

                # Bound concurrent detail reads so large boards fit the scheduled run budget.
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for path, job, error in pool.map(load_detail, ordered[:board.get('max_jobs', 40)]):
                        if error is not None:
                            _error(f'{name}:{path}', error, errors)
                        elif job and job.job_key not in seen_keys:
                            seen_keys.add(job.job_key)
                            jobs.append(job)
            except Exception as exc:
                _error(name, exc, errors)
    return jobs


def _error(source: str, exc: Exception, errors: list[str] | None) -> None:
    message = f'[workday] {source} failed: {exc}'
    print(message, file=sys.stderr)
    if errors is not None:
        errors.append(message)
