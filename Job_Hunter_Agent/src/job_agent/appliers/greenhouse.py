"""Greenhouse Easy Apply form automation.

Greenhouse's embedded application form has a stable structure across boards: #first_name,
#last_name, #email, #phone, a resume file input, and optionally custom questions. Any required
custom question this module cannot confidently answer triggers the complexity bail-out.
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
    return job.platform == Platform.GREENHOUSE


def apply(page: Page, job: RawJob, answers: dict, resume_path: str) -> ApplyAttempt:
    try:
        page.goto(job.apply_url, timeout=30_000)
        check_for_challenge(page)

        # Greenhouse embeds the form directly, or via an #application iframe on older boards.
        form = page
        if page.locator("#application_form").count() == 0 and page.locator("iframe#grnhse_iframe").count() > 0:
            frame = page.frame_locator("iframe#grnhse_iframe")
            form = frame  # FrameLocator supports the same .locator() API used below

        contact = answers.get("contact", {})
        _fill(form, "#first_name", contact.get("full_name", "").split(" ")[0] if contact.get("full_name") else None)
        humanize.between_fields()
        _fill(form, "#last_name", " ".join(contact.get("full_name", "").split(" ")[1:]) or None)
        humanize.between_fields()
        _fill(form, "#email", require_answer(contact.get("email"), "email"))
        humanize.between_fields()
        _fill(form, "#phone", require_answer(contact.get("phone"), "phone"))
        humanize.between_fields()

        resume_input = form.locator("#resume, input[type='file'][name*='resume']").first
        if resume_input.count() == 0:
            raise ComplexityBailOut("no resume upload field found")
        resume_input.set_input_files(resume_path)
        humanize.between_fields()

        _check_custom_questions(form)

        submit_button = form.locator("#submit_app, button[type='submit']").first
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


def _fill(form, selector: str, value: str | None) -> None:
    if value is None:
        return
    locator = form.locator(selector).first
    if locator.count() > 0:
        locator.fill(value)


def _check_custom_questions(form) -> None:
    """Bail if any required custom question is a free-text essay or otherwise unanswerable."""
    required_textareas = form.locator("textarea[required], textarea[aria-required='true']")
    if required_textareas.count() > 0:
        raise ComplexityBailOut("required free-text/essay question present")

    required_unfilled_text_inputs = form.locator(
        "input[type='text'][required]:not(#first_name):not(#last_name):not(#email):not(#phone)"
    )
    if required_unfilled_text_inputs.count() > 0:
        raise ComplexityBailOut("required custom question field present with no confident answer")
