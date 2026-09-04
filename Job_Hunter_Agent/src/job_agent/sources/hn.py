"""Supplementary discovery source: Hacker News monthly "Who is hiring?" thread, via the free,
unauthenticated Algolia HN Search API (no scraping, no API key). Manual-lead only, like dorking --
there is no ATS to auto-apply through, just a comment with a company's own contact details.

Degrades silently: any failure is logged and skipped, never raises, so this source can never fail
the run.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from job_agent import config
from job_agent.models import Platform, RawJob

_ALGOLIA_BASE = "https://hn.algolia.com/api/v1"
_MIN_COMMENT_CHARS = 200  # short comments are almost never a real job posting


def _latest_hiring_thread_id(client: httpx.Client) -> int | None:
    resp = client.get(
        f"{_ALGOLIA_BASE}/search_by_date",
        params={"tags": "story,author_whoishiring", "hitsPerPage": 10},
    )
    resp.raise_for_status()
    hits = resp.json().get("hits", [])
    hiring = [h for h in hits if (h.get("title") or "").lower().startswith("ask hn: who is hiring")]
    if not hiring:
        return None
    hiring.sort(key=lambda h: h.get("created_at_i", 0), reverse=True)
    return int(hiring[0]["objectID"])


def _matches_interest(text_lower: str) -> bool:
    keywords = [r.lower() for r in config.ROLE_FAMILIES]
    locations = [loc.lower() for loc in config.LOCATIONS]
    return any(k in text_lower for k in keywords) and any(loc in text_lower for loc in locations)


def fetch(errors: list[str] | None = None) -> list[RawJob]:
    jobs: list[RawJob] = []
    try:
        with httpx.Client(timeout=15) as client:
            story_id = _latest_hiring_thread_id(client)
            if story_id is None:
                return []

            resp = client.get(
                f"{_ALGOLIA_BASE}/search_by_date",
                params={"tags": f"comment,story_{story_id}", "hitsPerPage": 1000},
            )
            resp.raise_for_status()
            comments = resp.json().get("hits", [])
    except Exception as exc:  # noqa: BLE001 - never let this source kill the run
        msg = f"[hn] failed to fetch 'who is hiring' thread: {exc}"
        print(msg, file=sys.stderr)
        if errors is not None:
            errors.append(msg)
        return []

    for comment in comments:
        html = comment.get("comment_text") or ""
        if len(html) < _MIN_COMMENT_CHARS:
            continue
        text = BeautifulSoup(html, "html.parser").get_text("\n").strip()
        if not _matches_interest(text.lower()):
            continue

        object_id = comment["objectID"]
        first_line = text.splitlines()[0][:120] if text else "HN Who is Hiring posting"
        created_at_i = comment.get("created_at_i")
        posted_at = (
            datetime.fromtimestamp(created_at_i, tz=timezone.utc) if created_at_i else None
        )
        url = f"https://news.ycombinator.com/item?id={object_id}"
        jobs.append(
            RawJob(
                platform=Platform.DORKED,
                external_id=f"hn:{object_id}",
                title=first_line,
                company="",  # unknown -- the comment text itself names the company
                url=url,
                apply_url=url,
                location=None,
                is_remote=None,
                posted_at=posted_at,
                description_text=text,
            )
        )

    return jobs
