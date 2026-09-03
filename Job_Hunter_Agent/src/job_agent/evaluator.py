"""Gemini 2.5 Flash semantic fit scoring.

Judges each job by responsibilities/required skills, not title, against the candidate profile.
A failed batch never aborts the run -- those jobs come back unscored and are routed to manual
leads by the caller.
"""

from __future__ import annotations

import json
import sys
import time

import yaml
from google import genai
from google.genai import types
from pydantic import BaseModel
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

_SECONDS_BETWEEN_BATCHES = 5  # free-tier Gemini is rate-limited to 15 RPM; stay well under it

from job_agent import config
from job_agent.models import Evaluation, RawJob, SeniorityBucket

_MAX_DESCRIPTION_CHARS = 6000  # keep prompts small; descriptions beyond this rarely add signal


class _JobEvaluation(BaseModel):
    job_key: str
    score: float
    seniority_bucket: str
    reason: str
    matched_domains: list[str]
    red_flags: list[str]


class _BatchResponse(BaseModel):
    evaluations: list[_JobEvaluation]


_SYSTEM_PROMPT = """\
You are screening job postings for a candidate. Judge each posting by its actual responsibilities \
and required skills, NOT by its job title -- unconventional titles like "Algorithms Engineer", \
"Perception Engineer", or "Autonomy Software Engineer" often describe work that is a strong match.

Candidate profile (YAML):
---
{profile}
---

For each job, return:
- score: 1-10 semantic fit score (10 = excellent fit)
- seniority_bucket: one of student, intern, junior, mid, senior
- reason: at most 2 sentences explaining the score
- matched_domains: which of the candidate's strong-positive-signal domains this job touches
- red_flags: any disqualifying_signals present (empty list if none)

Scoring guidance:
- Treat robotics, control systems, perception, autonomy, and physical-AI overlap as a strong \
positive signal even for mid/senior postings -- the candidate's mechanical engineering + robotics/\
control background can offset a lack of years in software industry roles.
- Penalize disqualifying signals (e.g. required security clearance the candidate lacks, 5+ years \
industry ML/software required with no robotics/control overlap, no technical overlap at all).
- A remote posting explicitly restricted to a country other than Israel is a red flag.
"""


def _truncate(text: str) -> str:
    return text if len(text) <= _MAX_DESCRIPTION_CHARS else text[:_MAX_DESCRIPTION_CHARS] + "..."


def _build_batch_prompt(jobs: list[RawJob]) -> str:
    entries = []
    for job in jobs:
        entries.append(
            f"### job_key: {job.job_key}\n"
            f"Title: {job.title}\n"
            f"Company: {job.company}\n"
            f"Location: {job.location} (remote={job.is_remote})\n"
            f"Description:\n{_truncate(job.description_text)}\n"
        )
    return "\n".join(entries)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def _call_gemini(client: genai.Client, system_prompt: str, batch_prompt: str) -> _BatchResponse:
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=batch_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=_BatchResponse,
        ),
    )
    return _BatchResponse.model_validate(json.loads(response.text))


def score_jobs(
    jobs: list[RawJob],
    candidate_profile: dict,
    api_key: str,
    errors: list[str] | None = None,
) -> dict[str, Evaluation]:
    """Score jobs in batches. Returns {job_key: Evaluation} -- jobs whose batch failed are simply
    absent from the result; the caller treats a missing evaluation as `unscored`."""
    if not jobs:
        return {}

    client = genai.Client(api_key=api_key)
    system_prompt = _SYSTEM_PROMPT.format(profile=yaml.safe_dump(candidate_profile, sort_keys=False))

    results: dict[str, Evaluation] = {}
    batch_size = config.GEMINI_BATCH_SIZE
    for i in range(0, len(jobs), batch_size):
        if i > 0:
            time.sleep(_SECONDS_BETWEEN_BATCHES)

        batch = jobs[i : i + batch_size]
        batch_prompt = _build_batch_prompt(batch)
        try:
            parsed = _call_gemini(client, system_prompt, batch_prompt)
        except Exception as exc:  # noqa: BLE001 - one bad batch must not abort the run
            # tenacity's RetryError hides the real cause in its own repr -- unwrap it so the
            # actual API error (e.g. 429 rate limit) is what ends up in logs and the report.
            real_exc = exc.last_attempt.exception() if isinstance(exc, RetryError) else exc
            msg = f"[evaluator] batch of {len(batch)} jobs failed to score: {real_exc}"
            print(msg, file=sys.stderr)
            if errors is not None:
                errors.append(msg)
            continue

        for item in parsed.evaluations:
            try:
                bucket = SeniorityBucket(item.seniority_bucket.lower())
            except ValueError:
                bucket = SeniorityBucket.MID  # unrecognized bucket -> safe middle default
            results[item.job_key] = Evaluation(
                job_key=item.job_key,
                score=item.score,
                seniority_bucket=bucket,
                reason=item.reason,
                matched_domains=item.matched_domains,
                red_flags=item.red_flags,
            )

    return results
