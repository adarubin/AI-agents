"""Screening-questions sub-agent: answers custom application form fields encountered during
Playwright application (years of experience, work authorization, notice period, and other
free-text screening questions).

Facts are read strictly from `answers` (profile/answers.yaml). A small set of common screening
questions (years of experience with a named skill, work authorization in Israel, notice period)
are answered directly from those facts, with no model call. Anything else is routed to Gemini
under a strict zero-hallucination instruction: answer ONLY from the facts given, and return None
when the facts don't cover the question, so the caller's complexity bail-out fires -- a
confidently wrong answer sent to a real employer is worse than bailing out.
"""

from __future__ import annotations

import re
import sys

import yaml
from google import genai
from google.genai import types
from pydantic import BaseModel
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

from job_agent import config

_SKILL_YEARS_ANSWERS = {
    "python": "years_of_professional_experience",
    "pytorch": "years_of_ml_experience",
    "c++": "years_of_robotics_experience",
}


class _ScreeningAnswer(BaseModel):
    has_sufficient_info: bool
    answer: str


_SYSTEM_PROMPT = """\
You answer job-application screening questions for a candidate, using ONLY the facts given below. \
Do NOT invent, guess, estimate, or infer any fact that is not explicitly present in these facts -- \
if the facts do not clearly answer the question, set has_sufficient_info to false and leave answer \
empty, rather than fabricate anything. When you do have sufficient info, answer in at most one \
concise sentence, written as a direct response the candidate would type into the form field.

Candidate facts (YAML):
---
{facts}
---
"""


def _years_question(question: str) -> str | None:
    match = re.search(r"years?.{0,20}experience", question, re.IGNORECASE)
    if not match:
        return None
    lowered = question.lower()
    for skill in _SKILL_YEARS_ANSWERS:
        if skill in lowered:
            return skill
    return None


def _direct_answer(question: str, answers: dict) -> str | None:
    """Covers the common, high-confidence screening questions directly from `answers` -- no model
    call, no hallucination risk."""
    lowered = question.lower()

    skill = _years_question(question)
    if skill is not None:
        field = _SKILL_YEARS_ANSWERS[skill]
        value = answers.get("experience", {}).get(field)
        return str(value) if value is not None else None

    if "authoriz" in lowered and "israel" in lowered:
        # Default to authorized in Israel per profile convention, even if the key is absent.
        authorized = answers.get("work_authorization", {}).get("authorized_in_israel", True)
        return "Yes" if authorized else "No"

    if "visa" in lowered and "sponsor" in lowered:
        requires_visa = answers.get("work_authorization", {}).get("requires_visa_sponsorship", False)
        return "No" if not requires_visa else "Yes"

    if "notice period" in lowered:
        value = answers.get("notice_period")
        return str(value) if value else None

    if "salary" in lowered or "compensation" in lowered:
        value = answers.get("compensation", {}).get("salary_expectation")
        return str(value) if value else None

    return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _call_gemini(client: genai.Client, system_prompt: str, question: str) -> _ScreeningAnswer:
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=f"Screening question: {question}",
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=_ScreeningAnswer,
        ),
    )
    return _ScreeningAnswer.model_validate_json(response.text)


def answer_question(
    question: str,
    answers: dict,
    candidate_profile: dict,
    api_key: str,
    errors: list[str] | None = None,
) -> str | None:
    """Returns a confident one-sentence answer to `question`, or None if no fact (direct or via
    Gemini) supports one -- callers must treat None as "no confident answer" and bail out rather
    than submit with a blank or guessed field."""
    direct = _direct_answer(question, answers)
    if direct is not None:
        return direct

    facts = {"answers": answers, "candidate_profile": candidate_profile}
    system_prompt = _SYSTEM_PROMPT.format(facts=yaml.safe_dump(facts, sort_keys=False))

    client = genai.Client(api_key=api_key)
    try:
        result = _call_gemini(client, system_prompt, question)
    except Exception as exc:  # noqa: BLE001 - a screening failure must not crash the run
        real_exc = exc.last_attempt.exception() if isinstance(exc, RetryError) else exc
        msg = f"[screener] Gemini failed to answer screening question: {real_exc}"
        print(msg, file=sys.stderr)
        if errors is not None:
            errors.append(msg)
        return None

    if not result.has_sufficient_info or not result.answer.strip():
        return None
    return result.answer.strip()
