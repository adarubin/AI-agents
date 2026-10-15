"""Public SmartRecruiters listings and full job ads. Discovery only, no submissions."""
from __future__ import annotations

import sys

import httpx

from job_agent.eligibility import location_rejection, title_may_match
from job_agent.models import Platform, RawJob
from job_agent.sources.ats_api import _get_json, _parse_iso, _strip_html

BASE = 'https://api.smartrecruiters.com/v1/companies'


def parse_posting(item: dict, company: str) -> RawJob | None:
    if item.get('active') is not True or item.get('visibility') not in (None, 'PUBLIC'):
        return None
    location = item.get('location') or {}
    country = location.get('country') or ''
    # Country metadata, not company description or search text, establishes eligibility.
    if country.lower() != 'il':
        return None
    url = item.get('postingUrl')
    if not url or not item.get('id'):
        return None
    sections = (item.get('jobAd') or {}).get('sections') or {}
    description = '\n'.join(
        f"{sections[key].get('title', key)}\n{_strip_html(sections[key].get('text', ''))}"
        for key in ('jobDescription', 'qualifications', 'additionalInformation') if key in sections
    )
    return RawJob(
        Platform.DORKED, f"smartrecruiters:{company}:{item['id']}", item.get('name', ''),
        (item.get('company') or {}).get('name') or company, url, item.get('applyUrl') or url,
        location=', '.join(filter(None, [location.get('city'), 'Israel'])),
        is_remote=location.get('remote'), posted_at=_parse_iso(item.get('releasedDate')),
        description_text=description, active_verified=True,
    )


def fetch(companies: list[str], errors: list[str] | None = None) -> list[RawJob]:
    jobs = []
    with httpx.Client(timeout=20) as client:
        for company in companies:
            try:
                offset = 0
                seen = set()
                while True:
                    listing = _get_json(client, f'{BASE}/{company}/postings', params={'limit': 100, 'offset': offset})
                    items = listing.get('content') or []
                    if not items:
                        break
                    for item in items:
                        identifier = item.get('id')
                        if not identifier or identifier in seen:
                            continue
                        seen.add(identifier)
                        if (item.get('location') or {}).get('country', '').lower() != 'il' or not title_may_match(item.get('name', '')):
                            continue
                        try:
                            detail = _get_json(client, f'{BASE}/{company}/postings/{identifier}')
                            job = parse_posting(detail, company)
                            if job and location_rejection(job) is None:
                                jobs.append(job)
                        except Exception as exc:
                            _error(f'{company}:{identifier}', exc, errors)
                    offset += len(items)
                    if offset >= listing.get('totalFound', offset) or offset >= 1000:
                        break
            except Exception as exc:
                _error(company, exc, errors)
    return jobs


def _error(source: str, exc: Exception, errors: list[str] | None) -> None:
    message = f'[smartrecruiters] {source} failed: {exc}'
    print(message, file=sys.stderr)
    if errors is not None:
        errors.append(message)
