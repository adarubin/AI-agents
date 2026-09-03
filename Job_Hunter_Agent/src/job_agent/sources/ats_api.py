"""Greenhouse / Lever / Ashby JSON API clients.

All three platforms expose free, unauthenticated APIs that return full job descriptions and real
posting timestamps -- the primary discovery path (see plan). Each board token failure is isolated:
a dead token is logged and skipped rather than failing the whole fetch.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from datetime import datetime, timezone

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from job_agent.models import Platform, RawJob

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
LEVER_URL = "https://api.lever.co/v0/postings/{token}"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"

_TIMEOUT = 15.0
_TAG_RE = re.compile(r"<[^>]+>")

_retry_transient = retry(
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)


def _strip_html(raw: str) -> str:
    """Greenhouse `content` is escaped HTML. Unescape, strip tags, collapse whitespace."""
    unescaped = html.unescape(raw or "")
    text = _TAG_RE.sub(" ", unescaped)
    return re.sub(r"\s+", " ", text).strip()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@_retry_transient
def _get_json(client: httpx.Client, url: str, **kwargs) -> dict:
    resp = client.get(url, timeout=_TIMEOUT, **kwargs)
    resp.raise_for_status()
    return resp.json()


def fetch_greenhouse(client: httpx.Client, token: str) -> list[RawJob]:
    data = _get_json(client, GREENHOUSE_URL.format(token=token), params={"content": "true"})
    jobs = []
    for item in data.get("jobs", []):
        location = (item.get("location") or {}).get("name")
        jobs.append(
            RawJob(
                platform=Platform.GREENHOUSE,
                external_id=str(item["id"]),
                title=item.get("title", ""),
                company=token,
                url=item.get("absolute_url", ""),
                apply_url=item.get("absolute_url", ""),
                location=location,
                is_remote=bool(location and "remote" in location.lower()),
                posted_at=_parse_iso(item.get("updated_at") or item.get("first_published")),
                description_text=_strip_html(item.get("content", "")),
            )
        )
    return jobs


def fetch_lever(client: httpx.Client, token: str) -> list[RawJob]:
    data = _get_json(client, LEVER_URL.format(token=token), params={"mode": "json"})
    jobs = []
    for item in data if isinstance(data, list) else []:
        categories = item.get("categories") or {}
        location = categories.get("location")
        created_at = item.get("createdAt")
        posted_at = (
            datetime.fromtimestamp(created_at / 1000, tz=timezone.utc)
            if isinstance(created_at, (int, float))
            else None
        )
        jobs.append(
            RawJob(
                platform=Platform.LEVER,
                external_id=str(item["id"]),
                title=item.get("text", ""),
                company=token,
                url=item.get("hostedUrl", ""),
                apply_url=item.get("applyUrl") or item.get("hostedUrl", ""),
                location=location,
                is_remote=(item.get("workplaceType") == "remote"),
                posted_at=posted_at,
                description_text=item.get("descriptionPlain") or _strip_html(item.get("description", "")),
            )
        )
    return jobs


def fetch_ashby(client: httpx.Client, token: str) -> list[RawJob]:
    data = _get_json(client, ASHBY_URL.format(token=token))
    jobs = []
    for item in data.get("jobs", []):
        jobs.append(
            RawJob(
                platform=Platform.ASHBY,
                external_id=str(item["id"]),
                title=item.get("title", ""),
                company=token,
                url=item.get("jobUrl", ""),
                apply_url=item.get("applyUrl") or item.get("jobUrl", ""),
                location=item.get("location"),
                is_remote=bool(item.get("isRemote")),
                posted_at=_parse_iso(item.get("publishedAt")),
                description_text=item.get("descriptionPlain", ""),
            )
        )
    return jobs


_FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}


def fetch_all(ats_boards: dict, errors: list[str] | None = None) -> list[RawJob]:
    """Fetch every configured board across all three platforms. A dead token is logged to
    `errors` (if provided) and skipped -- never raises for a single-board failure."""
    jobs: list[RawJob] = []
    with httpx.Client(headers={"User-Agent": "job-hunter-agent/1.0"}) as client:
        for platform, fetcher in _FETCHERS.items():
            for token in ats_boards.get(platform, []) or []:
                try:
                    jobs.extend(fetcher(client, token))
                except Exception as exc:  # noqa: BLE001 - isolate per-board failures
                    msg = f"[ats_api] {platform}:{token} failed: {exc}"
                    print(msg, file=sys.stderr)
                    if errors is not None:
                        errors.append(msg)
    return jobs


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Fetch and print jobs from one ATS board")
    parser.add_argument("--board", required=True, help="platform:token, e.g. greenhouse:anthropic")
    args = parser.parse_args()
    platform, _, token = args.board.partition(":")
    fetcher = _FETCHERS.get(platform)
    if not fetcher:
        sys.exit(f"unknown platform '{platform}', expected one of {list(_FETCHERS)}")

    with httpx.Client(headers={"User-Agent": "job-hunter-agent/1.0"}) as client:
        jobs = fetcher(client, token)

    print(f"{len(jobs)} jobs from {args.board}")
    for job in jobs[:10]:
        print(f"- [{job.posted_at}] {job.title} @ {job.company} ({job.location}) "
              f"desc={len(job.description_text)} chars -> {job.url}")


if __name__ == "__main__":
    _cli()
