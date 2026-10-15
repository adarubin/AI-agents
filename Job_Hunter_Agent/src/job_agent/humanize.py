"""Jittered delays and per-run randomization to make the applier's browsing pattern less uniform."""

from __future__ import annotations

import random
import time

from job_agent import config


def jitter_sleep(min_s: float, max_s: float) -> None:
    time.sleep(random.uniform(min_s, max_s))


def between_fields() -> None:
    jitter_sleep(0.8, 3.5)


def between_applications() -> None:
    jitter_sleep(12, 28)


def apply_cap() -> int:
    """Randomized per-run cap on total auto-applications, per plan's APPLY_CAP_RANGE."""
    lo, hi = config.APPLY_CAP_RANGE
    return random.randint(lo, hi)
