"""Shared complexity bail-out and applier interface.

Every applier implements `can_handle(job) -> bool` and `apply(page, job, answers, resume_path) ->
ApplyAttempt`. The bail-out lives here so both platforms share the exact same safety rules.
"""

from __future__ import annotations

from playwright.sync_api import Page

from job_agent.models import ApplyAttempt

MAX_FORM_STEPS = 4


class ComplexityBailOut(Exception):
    """Raised internally by an applier to abandon a form without submitting."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def check_for_challenge(page: Page) -> None:
    """Bail immediately if a CAPTCHA / Cloudflare challenge is present."""
    challenge_selectors = [
        "iframe[src*='recaptcha']",
        "iframe[title*='challenge']",
        "#cf-challenge-running",
        "[class*='captcha']",
    ]
    for sel in challenge_selectors:
        if page.locator(sel).count() > 0:
            raise ComplexityBailOut(f"CAPTCHA/challenge element detected: {sel}")


def require_answer(value, field_name: str):
    """Bail if a required field has no confident answer, including unfilled TODO placeholders."""
    if value is None or value == "" or (isinstance(value, str) and value.strip().upper() == "TODO"):
        raise ComplexityBailOut(f"no confident answer for required field: {field_name}")
    return value


def bail_result(job_key: str, reason: str) -> ApplyAttempt:
    return ApplyAttempt(job_key=job_key, success=False, bailed_reason=reason)


def error_result(job_key: str, error: str) -> ApplyAttempt:
    return ApplyAttempt(job_key=job_key, success=False, error=error)


def success_result(job_key: str) -> ApplyAttempt:
    return ApplyAttempt(job_key=job_key, success=True)
