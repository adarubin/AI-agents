"""Cover letter sub-agent: Gemini generates a short, punchy cover letter per job, highlighting the
candidate's mechanical/robotics background against the job's Deep Learning / Computer Vision /
Physical AI content.

A failed call never blocks the application -- the caller falls back to no cover letter (appliers
already treat a missing cover letter as optional).
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


class _CoverLetter(BaseModel):
    cover_letter: str


_SYSTEM_PROMPT = """\
You write short cover letters for a candidate applying to a specific job. Write ONLY 3-4 \
sentences of plain text -- no headers, no "Dear Hiring Manager", no greeting or sign-off, no \
boilerplate, no markdown. Go straight into the pitch.

Highlight the exact synergy between the candidate's mechanical engineering + robotics/controls \
background and the job's modern Deep Learning / Computer Vision / Physical AI content. Be \
specific to this job's responsibilities, not generic. Do not invent facts, experience, or skills \
that are not present in the candidate profile below.

Candidate profile (YAML):
---
{profile}
---
"""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _call_gemini(client: genai.Client, system_prompt: str, job_prompt: str) -> _CoverLetter:
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=job_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=_CoverLetter,
        ),
    )
    return _CoverLetter.model_validate_json(response.text)


def generate_cover_letter(
    candidate_profile: dict, job: RawJob, api_key: str, errors: list[str] | None = None
) -> str | None:
    """Returns a 3-4 sentence plain-text cover letter for this job, or None if generation is
    unavailable -- callers simply skip the cover letter field in that case."""
    if not candidate_profile:
        return None

    description = job.description_text[:_MAX_DESCRIPTION_CHARS]
    system_prompt = _SYSTEM_PROMPT.format(profile=yaml.safe_dump(candidate_profile, sort_keys=False))
    job_prompt = f"Job title: {job.title}\nCompany: {job.company}\nDescription:\n{description}"

    client = genai.Client(api_key=api_key)
    try:
        result = _call_gemini(client, system_prompt, job_prompt)
    except Exception as exc:  # noqa: BLE001 - a cover-letter failure must not block the application
        real_exc = exc.last_attempt.exception() if isinstance(exc, RetryError) else exc
        msg = f"[cover_letter] Gemini generation failed for {job.job_key}: {real_exc}"
        print(msg, file=sys.stderr)
        if errors is not None:
            errors.append(msg)
        return None

    text = result.cover_letter.strip()
    return text or None
