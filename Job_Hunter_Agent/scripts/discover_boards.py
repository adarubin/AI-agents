"""Weekly (or on-demand) board-token discovery: dork for ATS career-board URLs, parse the board
token out of each URL, validate it against the live API, and merge new tokens into
profile/ats_boards.yaml. Run manually or on a separate cron -- this is NOT part of the twice-daily
run, which only reads the cached board list.

Usage:
    python -m scripts.discover_boards [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from job_agent import config  # noqa: E402
from job_agent.sources.ats_api import _FETCHERS  # noqa: E402

BOARD_URL_PATTERNS = {
    "greenhouse": re.compile(r"(?:boards|job-boards)\.greenhouse\.io/([\w-]+)", re.I),
    "lever": re.compile(r"jobs\.lever\.co/([\w-]+)", re.I),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([\w-]+)", re.I),
}

DORK_QUERIES = [
    '(site:boards.greenhouse.io OR site:job-boards.greenhouse.io) '
    '("machine learning" OR "computer vision" OR robotics OR "deep learning") (Israel OR remote)',
    'site:jobs.lever.co ("machine learning" OR "computer vision" OR robotics OR perception) '
    '(Israel OR remote)',
    'site:jobs.ashbyhq.com ("machine learning" OR robotics OR "computer vision" OR autonomy) '
    '(Israel OR remote)',
]


def extract_tokens(url: str) -> tuple[str, str] | None:
    for platform, pattern in BOARD_URL_PATTERNS.items():
        match = pattern.search(url)
        if match:
            return platform, match.group(1)
    return None


def validate_token(client: httpx.Client, platform: str, token: str) -> bool:
    try:
        _FETCHERS[platform](client, token)
        return True
    except Exception:
        return False


def discover() -> dict[str, set[str]]:
    """Run dork queries and return newly-found, validated {platform: {tokens}}."""
    try:
        from ddgs import DDGS
    except ImportError:
        print("[discover_boards] ddgs not installed, skipping search-based discovery", file=sys.stderr)
        return {}

    found: dict[str, set[str]] = {"greenhouse": set(), "lever": set(), "ashby": set()}
    with DDGS() as ddgs:
        for query in DORK_QUERIES:
            try:
                results = ddgs.text(query, max_results=25, timelimit="m")
            except Exception as exc:  # noqa: BLE001 - a rate-limited query just yields nothing
                print(f"[discover_boards] query failed: {exc}", file=sys.stderr)
                continue
            for result in results:
                url = result.get("href") or result.get("url") or ""
                parsed = extract_tokens(url)
                if parsed:
                    platform, token = parsed
                    found[platform].add(token)

    with httpx.Client(headers={"User-Agent": "job-hunter-agent/1.0"}) as client:
        for platform in found:
            found[platform] = {t for t in found[platform] if validate_token(client, platform, t)}

    return found


def merge_and_save(new_tokens: dict[str, set[str]], boards_path: Path, dry_run: bool = False) -> None:
    existing = yaml.safe_load(boards_path.read_text(encoding="utf-8")) or {}
    added = {}
    for platform, tokens in new_tokens.items():
        current = set(existing.get(platform) or [])
        merged = current | tokens
        newly_added = merged - current
        if newly_added:
            added[platform] = sorted(newly_added)
        existing[platform] = sorted(merged)

    if not added:
        print("[discover_boards] no new boards found")
        return

    print(f"[discover_boards] new boards: {added}")
    if dry_run:
        print("[discover_boards] --dry-run: not writing to ats_boards.yaml")
        return

    boards_path.write_text(yaml.safe_dump(existing, sort_keys=False), encoding="utf-8")
    print(f"[discover_boards] wrote {boards_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    new_tokens = discover()
    merge_and_save(new_tokens, config.PROFILE_DIR / "ats_boards.yaml", dry_run=args.dry_run)


if __name__ == "__main__":
    main()
