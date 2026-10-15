"""Per-job resume tailoring via Gemini: reorders the base resume's skills and each experience
entry's bullet points to match a job description, so relevant content surfaces first.

Gemini is constrained to a schema that can only reorder existing strings -- it cannot introduce
new ones. The response is also validated against the base resume's own skills/bullets (same
items, any order); any mismatch, or any API failure, discards the tailoring and the caller falls
back to the untailored base resume. This is a stronger structural safeguard than the prompt
instruction alone against fabricated resume content reaching a real employer.
"""

from __future__ import annotations

import sys

import yaml
from google import genai
from google.genai import types
from pydantic import BaseModel
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

from job_agent import config
from job_agent.models import RawJob

_MAX_DESCRIPTION_CHARS = 4000


class _TailoredResume(BaseModel):
    skills: list[str]
    experience_bullets: list[list[str]]


_SYSTEM_PROMPT = """\
You are tailoring a candidate's resume to a specific job description. You may ONLY reorder the \
existing skills list and reorder the bullet points within each experience entry, putting the \
items most relevant to the job description first. Do NOT invent, fabricate, or hallucinate any \
experience, degrees, or skills that do not exist in the base resume. Return ONLY the exact same \
skills and the exact same bullets for each experience entry, just reordered.

Base resume skills (YAML list):
{skills}

Base resume experience bullets, one YAML list per experience entry, in order:
{bullets}
"""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _call_gemini(client: genai.Client, system_prompt: str, job_prompt: str) -> _TailoredResume:
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=job_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=_TailoredResume,
        ),
    )
    return _TailoredResume.model_validate_json(response.text)


def _unchanged_content(tailored: _TailoredResume, base_skills: list[str], base_bullets: list[list[str]]) -> bool:
    """True only if the response contains exactly the same items as the base resume, any order."""
    if sorted(tailored.skills) != sorted(base_skills):
        return False
    if len(tailored.experience_bullets) != len(base_bullets):
        return False
    return all(sorted(got) == sorted(want) for got, want in zip(tailored.experience_bullets, base_bullets))


def tailor_resume(
    base_content: dict, job: RawJob, api_key: str, errors: list[str] | None = None
) -> dict | None:
    """Returns a copy of base_content with skills/bullets reordered for this job, or None if
    tailoring is unavailable or its output could not be trusted -- callers fall back to the
    untailored base resume in that case."""
    base_skills = base_content.get("skills", [])
    if not base_skills or not all(isinstance(s, str) for s in base_skills):
        return None  # dict-shaped skill groups aren't a supported tailoring target; skip safely

    experience = base_content.get("experience", [])
    base_bullets = [entry.get("bullets", []) for entry in experience]
    if not any(base_bullets):
        return None  # nothing to reorder

    description = job.description_text[:_MAX_DESCRIPTION_CHARS]
    system_prompt = _SYSTEM_PROMPT.format(
        skills=yaml.safe_dump(base_skills, sort_keys=False),
        bullets=yaml.safe_dump(base_bullets, sort_keys=False),
    )
    job_prompt = f"Job title: {job.title}\nCompany: {job.company}\nDescription:\n{description}"

    client = genai.Client(api_key=api_key)
    try:
        tailored = _call_gemini(client, system_prompt, job_prompt)
    except Exception as exc:  # noqa: BLE001 - a tailoring failure must not block the application
        real_exc = exc.last_attempt.exception() if isinstance(exc, RetryError) else exc
        msg = f"[tailor] Gemini tailoring failed for {job.job_key}: {real_exc}"
        print(msg, file=sys.stderr)
        if errors is not None:
            errors.append(msg)
        return None

    if not _unchanged_content(tailored, base_skills, base_bullets):
        msg = f"[tailor] Gemini tailoring for {job.job_key} did not preserve base content -- discarding"
        print(msg, file=sys.stderr)
        if errors is not None:
            errors.append(msg)
        return None

    tailored_content = dict(base_content)
    tailored_content["skills"] = tailored.skills
    tailored_content["experience"] = [
        {**entry, "bullets": bullets} for entry, bullets in zip(experience, tailored.experience_bullets)
    ]
    return tailored_content
