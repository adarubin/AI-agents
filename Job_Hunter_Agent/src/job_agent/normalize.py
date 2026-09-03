"""Dedupe, freshness filter, and state filter -- applied before any LLM call to keep per-run cost
and time bounded (see plan: "the cost-control chokepoint")."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from job_agent.models import RawJob


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def normalize(
    jobs: list[RawJob],
    seen_keys: set[str],
    freshness_hours: int,
    max_jobs: int,
) -> list[RawJob]:
    """Filter and dedupe raw jobs into the candidate set to send for scoring.

    Order matters: state filter first (cheapest), then freshness, then cross-source dedupe by
    (company, title) and by URL, then cap to the freshest `max_jobs`.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=freshness_hours)

    candidates = [j for j in jobs if j.job_key not in seen_keys]

    fresh = []
    for job in candidates:
        if job.posted_at is None:
            # Unknown date (dorked source) -- eligible, but the report should flag it.
            fresh.append(job)
            continue
        posted = job.posted_at if job.posted_at.tzinfo else job.posted_at.replace(tzinfo=timezone.utc)
        if posted >= cutoff:
            fresh.append(job)

    seen_dedupe_keys: set[str] = set()
    deduped = []
    for job in fresh:
        company_title_key = f"{_normalize_key(job.company)}:{_normalize_key(job.title)}"
        url_key = job.url.rstrip("/").lower()
        if company_title_key in seen_dedupe_keys or url_key in seen_dedupe_keys:
            continue
        seen_dedupe_keys.add(company_title_key)
        seen_dedupe_keys.add(url_key)
        deduped.append(job)

    def _sort_key(job: RawJob) -> datetime:
        # Unknown-date jobs sort last (treated as least-fresh) but are still included.
        # Defensive tz-normalization in case a source ever emits a naive datetime.
        posted = job.posted_at
        if posted is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        return posted if posted.tzinfo else posted.replace(tzinfo=timezone.utc)

    deduped.sort(key=_sort_key, reverse=True)
    return deduped[:max_jobs]
