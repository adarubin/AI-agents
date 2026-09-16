"""Supplementary discovery source: dork search for postings on ATS platforms without a public API
(Workday, Comeet, SmartRecruiters, career pages). Manual-lead only -- never auto-applied to.

Degrades silently: a rate-limited or failing query is logged and skipped, never raises, so this
source can never fail the run.
"""

from __future__ import annotations

import sys

from job_agent import config
from job_agent.models import Platform, RawJob
from job_agent.sources.extract import extract_text

NON_API_ATS_SITES = [
    "myworkdayjobs.com",
    "boards.greenhouse.io",
    "jobs.lever.co",
    "comeet.com",
    "smartrecruiters.com",
    "apply.workable.com",
]


def _build_queries(role_families: list[str]) -> list[str]:
    """One short query per (platform site, role pair) -- each query targets a single site with
    at most two OR'd role terms, deliberately avoiding the long combined site/role/location OR
    chains that used to time out (especially against the mobileye/ai21 career pages). Location
    filtering is left to the evaluator rather than folded into the query. Targeted-company
    queries (see config.TARGETED_COMPANY_SITES) are minimal site-only searches, listed first so
    they always fit within the query budget."""
    queries = [f"site:{site} jobs" for site in config.TARGETED_COMPANY_SITES]

    batch_size = 2
    for site in NON_API_ATS_SITES:
        for i in range(0, len(role_families), batch_size):
            batch = role_families[i : i + batch_size]
            role_clause = " OR ".join(f'"{r}"' for r in batch)
            queries.append(f"site:{site} {role_clause}")

    return queries


def fetch(errors: list[str] | None = None) -> list[RawJob]:
    try:
        from ddgs import DDGS
        from ddgs.exceptions import RatelimitException
    except ImportError:
        msg = "[dorking] ddgs not installed, skipping supplementary search source"
        print(msg, file=sys.stderr)
        if errors is not None:
            errors.append(msg)
        return []

    queries = _build_queries(config.ROLE_FAMILIES)
    budget = config.DORK_QUERY_BUDGET
    jobs: list[RawJob] = []
    seen_urls: set[str] = set()

    with DDGS() as ddgs:
        for query in queries[:budget]:
            try:
                results = ddgs.text(query, max_results=15, timelimit="w")
            except RatelimitException:
                msg = "[dorking] rate-limited by search backend, continuing on API results only"
                print(msg, file=sys.stderr)
                if errors is not None:
                    errors.append(msg)
                break
            except Exception as exc:  # noqa: BLE001 - never let one query kill the run
                msg = f"[dorking] query failed: {exc}"
                print(msg, file=sys.stderr)
                if errors is not None:
                    errors.append(msg)
                continue

            for result in results:
                url = result.get("href") or result.get("url") or ""
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                extracted = extract_text(url)
                if extracted is None:
                    continue

                title, description = extracted
                jobs.append(
                    RawJob(
                        platform=Platform.DORKED,
                        external_id=_url_hash(url),
                        title=title or result.get("title", ""),
                        company="",  # unknown for dorked sources; router/report shows the URL instead
                        url=url,
                        apply_url=url,
                        location=None,
                        is_remote=None,
                        posted_at=None,  # unknown -- normalize treats as "date unverified"
                        description_text=description,
                    )
                )

    return jobs


def _url_hash(url: str) -> str:
    import hashlib

    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
