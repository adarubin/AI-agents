"""Lever Easy Apply form automation.

Lever's application form uses name-based selectors: input[name="name"], [name="email"],
[name="phone"], and a resume file input. Same complexity bail-out rules as Greenhouse.
"""

from __future__ import annotations

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from job_agent import humanize
from job_agent.appliers.base import (
    ComplexityBailOut,
    bail_result,
    check_for_challenge,
    error_result,
    require_answer,
    success_result,
)
from job_agent.models import ApplyAttempt, Platform, RawJob

_FORM_TIMEOUT = 10_000


def can_handle(job: RawJob) -> bool:
    return job.platform == Platform.LEVER


def apply(page: Page, job: RawJob, answers: dict, resume_path: str) -> ApplyAttempt:
    try:
        page.goto(job.apply_url, timeout=30_000)
        check_for_challenge(page)

        contact = answers.get("contact", {})
        _fill(page, "input[name='name']", contact.get("full_name"))
        humanize.between_fields()
        _fill(page, "input[name='email']", require_answer(contact.get("email"), "email"))
        humanize.between_fields()
        _fill(page, "input[name='phone']", require_answer(contact.get("phone"), "phone"))
        humanize.between_fields()

        resume_input = page.locator("input[name='resume'], input[type='file']").first
        if resume_input.count() == 0:
            raise ComplexityBailOut("no resume upload field found")
        resume_input.set_input_files(resume_path)
        humanize.between_fields()

        _check_custom_questions(page)

        submit_button = page.locator("button[type='submit']").first
        if submit_button.count() == 0:
            raise ComplexityBailOut("no submit button found")
        submit_button.click(timeout=_FORM_TIMEOUT)
        page.wait_for_timeout(2000)

        return success_result(job.job_key)

    except ComplexityBailOut as exc:
        return bail_result(job.job_key, exc.reason)
    except PlaywrightTimeoutError as exc:
        return error_result(job.job_key, f"timeout: {exc}")
    except Exception as exc:  # noqa: BLE001 - an unexpected form must never crash the run
        return error_result(job.job_key, str(exc))


def _fill(page: Page, selector: str, value: str | None) -> None:
    if value is None:
        return
    locator = page.locator(selector).first
    if locator.count() > 0:
        locator.fill(value)


def _check_custom_questions(page: Page) -> None:
    required_textareas = page.locator("textarea[required]")
    if required_textareas.count() > 0:
        raise ComplexityBailOut("required free-text/essay question present")

    required_unfilled_text_inputs = page.locator(
        "input[type='text'][required]:not([name='name']):not([name='email']):not([name='phone'])"
    )
    if required_unfilled_text_inputs.count() > 0:
        raise ComplexityBailOut("required custom question field present with no confident answer")
