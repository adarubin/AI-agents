"""Separate experience stretch notes from binding non-experience requirements."""
from __future__ import annotations

import math
import re
from datetime import date

from job_agent.models import RawJob


def _requirements(job: RawJob) -> str:
    heading = re.search(r'\b(?:requirements|qualifications|all you need is)\s*:?\s*', job.description_text, re.I)
    if not heading:
        return ''  # Don't mistake company history or responsibilities for requirements.
    required = job.description_text[heading.end():]
    required = re.split(r'\b(?:nice to have|preferred qualifications|advantages|bonus points)\b', required, flags=re.I)[0]
    return required


def experience_gaps(job: RawJob, profile: dict) -> list[str]:
    """Experience gaps are information for the candidate, never a rejection criterion."""
    required = _requirements(job)
    experience = profile.get('experience_facts') or {}
    reasons = []
    # Inline <strong>/<span> markup often introduces a newline inside one requirement.
    flat_required = re.sub(r'\s+', ' ', required)
    years = re.finditer(r'\b(\d+)(?:\s*[-–]\s*\d+)?\+?\s+years?\b', flat_required, re.I)
    for match in years:
        # Interpret only the same requirement, never the following bullet/sentence.
        clause = re.split(r'[.;]', flat_required[match.end():match.end() + 200])[0]
        prefix = re.split(r'[.;]', flat_required[:match.start()])[-1][-80:]
        if re.search(r'\b(?:prefer\w*|optional)\b', prefix, re.I) or re.search(r'\b(?:preferred|advantage|optional)\b', clause, re.I):
            continue
        domain = None
        if re.search(r'\b(?:machine learning|deep learning|computer vision|\bML\b|\bCV\b)', clause, re.I):
            domain = 'years_professional_ml'
        elif re.search(r'\b(?:robotics|control design|control algorithms)\b', clause, re.I):
            domain = 'years_robotics'
        if domain and experience.get(domain) is not None:
            required_years = int(match.group(1))
            documented = float(experience[domain])
            if required_years > documented:
                reasons.append(f'Requires {required_years}+ years ({clause.strip()}); documented {domain}={documented:g}')
    return reasons


def gaps(job: RawJob, profile: dict, today: date | None = None) -> list[str]:
    required = _requirements(job)
    experience = profile.get('experience_facts') or {}
    reasons = []

    # Degree alternatives are respected: B.Sc. OR M.Sc. is satisfied by the B.Sc.
    if experience.get('masters_completed') is False and 'student' not in job.title.lower():
        for clause in re.split(r'[;\n]', required):
            clause = re.sub(r'^\s*What are we looking for\?\s*', '', clause, flags=re.I)
            starts_masters = re.match(r"\s*(?:(?:a|an|completed)\s+)?(?:m\.?sc\.?|m\.?s\.?|master['’]?s)\b", clause, re.I)
            alternative = re.search(r'\bb\.?sc\.?|bachelor|equivalent (?:industry )?experience|in.progress|student|prefer|advantage', clause, re.I)
            if starts_masters and not alternative:
                reasons.append('Requires a completed advanced degree; candidate M.Sc. is in progress: ' + clause.strip())

    semester = re.search(r'(?:at least\s+|minimum\s+)?(\d+)\s+semesters?\s+(?:left|remaining|until graduation)', required, re.I)
    graduation = (profile.get('education') or {}).get('expected_graduation_month')
    if semester and graduation:
        year, month = map(int, graduation.split('-'))
        current = today or date.today()
        months = (year - current.year) * 12 + month - current.month
        available = max(0, math.ceil(months / 6))
        if available < int(semester.group(1)):
            reasons.append(f'Requires {semester.group(1)} semesters remaining; expected graduation {graduation}')
    return reasons


def is_experience_only_flag(flag: str) -> bool:
    """Old/model-generated experience flags must not turn stretch roles into rejections."""
    experience = re.search(r'\b(?:experience|years?|seniority|tenure)\b', flag, re.I)
    hard_constraint = re.search(r'\b(?:clearance|citizenship|authorization|visa|degree|ph\.?d|m\.?sc|license|certification)\b', flag, re.I)
    return bool(experience and not hard_constraint)
