"""Core data models shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Platform(str, Enum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    DORKED = "dorked"  # unknown ATS, found via search, manual-lead only


class SeniorityBucket(str, Enum):
    STUDENT = "student"
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"


class JobStatus(str, Enum):
    APPLIED = "applied"
    MANUAL_LEAD = "manual_lead"
    DISCARDED = "discarded"
    BAIL_COMPLEX = "bail_complex"
    FAILED = "failed"
    UNSCORED = "unscored"


@dataclass
class RawJob:
    """A job posting as fetched from a discovery source, before scoring."""

    platform: Platform
    external_id: str  # unique within platform; e.g. greenhouse job id, or url hash for dorked
    title: str
    company: str
    url: str
    apply_url: str
    location: str | None = None
    is_remote: bool | None = None
    posted_at: datetime | None = None  # None = unknown (dorked source)
    description_text: str = ""

    @property
    def job_key(self) -> str:
        """Stable key for state tracking: {platform}:{external_id}."""
        return f"{self.platform.value}:{self.external_id}"


@dataclass
class Evaluation:
    """Gemini's semantic-fit judgment for one job."""

    job_key: str
    score: float  # 1-10
    seniority_bucket: SeniorityBucket
    reason: str  # <= 2 sentences
    matched_domains: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)


@dataclass
class ApplyAttempt:
    """Outcome of an auto-apply attempt."""

    job_key: str
    success: bool
    bailed_reason: str | None = None  # set when the complexity bail-out fired
    error: str | None = None


@dataclass
class RoutedJob:
    """A job plus its evaluation plus the routing decision, ready for the report."""

    job: RawJob
    evaluation: Evaluation | None  # None when Gemini failed to score it
    status: JobStatus
    apply_attempt: ApplyAttempt | None = None


@dataclass
class RunReport:
    """Everything the email reporter needs for one run."""

    started_at: datetime
    finished_at: datetime | None = None
    applied: list[RoutedJob] = field(default_factory=list)
    manual_leads: list[RoutedJob] = field(default_factory=list)
    discarded_count: int = 0
    errors: list[str] = field(default_factory=list)
