"""Local JSON state: which jobs have been seen/applied/discarded, to avoid re-evaluating or
re-applying to the same posting. Atomic write; committed back to the repo in CI (see workflow) so
state survives beyond actions/cache's 7-day eviction.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from job_agent.models import JobStatus, RoutedJob

STATE_FILE = "applied_jobs.json"


def load(data_dir: Path) -> dict[str, dict]:
    path = data_dir / STATE_FILE
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def seen_keys(state: dict[str, dict]) -> set[str]:
    return set(state.keys())


def record(state: dict[str, dict], routed: RoutedJob) -> None:
    """Update `state` in place with the outcome of one routed job."""
    job, evaluation = routed.job, routed.evaluation
    entry = state.get(job.job_key, {})
    entry.update(
        {
            "status": routed.status.value,
            "score": evaluation.score if evaluation else None,
            "title": job.title,
            "company": job.company,
            "url": job.url,
            "first_seen": entry.get("first_seen", datetime.now(timezone.utc).isoformat()),
            "last_action": datetime.now(timezone.utc).isoformat(),
        }
    )
    state[job.job_key] = entry


def save(data_dir: Path, state: dict[str, dict]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / STATE_FILE
    fd, tmp_path = tempfile.mkstemp(dir=data_dir, prefix=".applied_jobs_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
