"""Routing rules: score + platform + seniority -> APPLY | MANUAL LEAD | DISCARD.

Kept as pure functions with no I/O so they are cheaply unit-testable -- the cheapest possible
protection against the bug that auto-applies to something it shouldn't (see plan).
"""

from __future__ import annotations

from job_agent import config
from job_agent.eligibility import rejection_reason
from job_agent.qualifications import is_experience_only_flag
from job_agent.models import Evaluation, JobStatus, Platform, RawJob, SeniorityBucket

_AUTO_APPLY_PLATFORMS = {Platform.GREENHOUSE, Platform.LEVER}
_JUNIOR_BUCKETS = {SeniorityBucket.STUDENT, SeniorityBucket.INTERN, SeniorityBucket.JUNIOR}
_SENIOR_BUCKETS = {SeniorityBucket.MID, SeniorityBucket.SENIOR}


def is_apply_eligible(evaluation: Evaluation, platform: Platform) -> bool:
    """Would this job be auto-applied to, ignoring the per-run cap? Does not check the
    complexity bail-out -- that happens inside the applier itself, at apply time."""
    if platform not in _AUTO_APPLY_PLATFORMS:
        return False
    if any(not is_experience_only_flag(flag) for flag in evaluation.red_flags):
        return False

    if evaluation.seniority_bucket in _JUNIOR_BUCKETS:
        return evaluation.score >= config.MIN_SCORE_TO_APPLY

    if evaluation.seniority_bucket in _SENIOR_BUCKETS:
        strong_overlap = bool(evaluation.matched_domains)
        return evaluation.score >= config.SENIOR_APPLY_THRESHOLD and strong_overlap

    return False


def route(evaluation: Evaluation | None, platform: Platform, job: RawJob) -> JobStatus:
    """Decide the status for a scored job. `evaluation is None` means Gemini failed to score it.

    JobStatus.READY_TO_APPLY means "eligible for auto-apply" -- main.py
    enforces the per-run cap across all eligible jobs, then the applier attempts each one and
    overwrites this with the real outcome (APPLIED on success, BAIL_COMPLEX or FAILED otherwise).
    Any eligible job not reached because the cap was hit is downgraded to MANUAL_LEAD.
    """
    if rejection_reason(job):
        return JobStatus.DISCARDED
    if evaluation is None:
        return JobStatus.UNSCORED

    if is_apply_eligible(evaluation, platform):
        return JobStatus.READY_TO_APPLY

    if any(not is_experience_only_flag(flag) for flag in evaluation.red_flags):
        return JobStatus.DISCARDED

    if evaluation.score >= config.MIN_SCORE_TO_REPORT:
        return JobStatus.MANUAL_LEAD

    return JobStatus.DISCARDED
