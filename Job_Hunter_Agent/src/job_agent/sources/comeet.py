"""Read public Comeet career-page JSON without executing JavaScript. Manual apply only."""
from __future__ import annotations

import json
import re
import sys

import httpx

from job_agent.models import Platform, RawJob
from job_agent.sources.ats_api import _parse_iso, _strip_html


def embedded_data(html: str, variable: str):
    match = re.search(r'\b' + re.escape(variable) + r'\s*=\s*', html)
    if not match:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(html[match.end():])
        return value
    except ValueError:
        return None


def parse_position(item: dict, company: str = '') -> RawJob | None:
    if item.get('is_internal') or not item.get('uid'):
        return None
    url = item.get('url_comeet_hosted_page') or item.get('url_recruit_hosted_page')
    if not url:
        return None
    loc = item.get('location') or {}
    country = loc.get('country') or ''
    # Keep country even if it conflicts with an Israeli-looking city name.
    location = ', '.join(filter(None, [loc.get('name'), 'Israel' if country == 'IL' else country]))
    details = (item.get('custom_fields') or {}).get('details') or []
    description = '\n'.join(
        f"{d.get('name', '')}\n{_strip_html(d.get('value', ''))}" for d in details
    )
    return RawJob(
        platform=Platform.DORKED,
        external_id=f"comeet:{company or item.get('company_name', '')}:{item['uid']}",
        title=item.get('name', ''), company=item.get('company_name') or company,
        url=url, apply_url=url, location=location or None,
        is_remote=loc.get('is_remote', False),
        posted_at=_parse_iso(item.get('time_updated')), description_text=description,
        active_verified=True,
    )


def fetch(boards: list[str], errors: list[str] | None = None) -> list[RawJob]:
    jobs = []
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for board in boards:
            try:
                response = client.get(board)
                response.raise_for_status()
                positions = embedded_data(response.text, 'COMPANY_POSITIONS_DATA')
                if not isinstance(positions, list):
                    raise ValueError('public career-page position data missing')
                company = embedded_data(response.text, 'COMPANY_DATA') or {}
                for item in positions:
                    job = parse_position(item, company.get('name', ''))
                    if job:
                        jobs.append(job)
            except Exception as exc:
                msg = f'[comeet] {board} failed: {exc}'
                print(msg, file=sys.stderr)
                if errors is not None:
                    errors.append(msg)
    return jobs
