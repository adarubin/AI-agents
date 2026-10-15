"""Deterministic gates. A model score can never override these requirements."""
from __future__ import annotations

import re

from job_agent.models import RawJob

_ISRAEL = re.compile(
    r"\b(?:israel|tel[ -]?aviv|haifa|herzliya|herzlia|jerusalem|netanya|"
    r"ramat[ -]?gan|ra['’]?anana|rehovot|petah[ -]?tikva|petach[ -]?tikva|"
    r"yokneam|yokne'am|beer[ -]?sheva|be'er[ -]?sheva|caesarea|hod[ -]?hasharon)\b|ישראל",
    re.I,
)
_EXCLUDED_ISRAEL = re.compile(r"\b(?:excluding|except|not (?:open|available) (?:in|to))\s+israel\b", re.I)
_TARGET = re.compile(
    r"\b(?:machine learning|deep learning|computer vision|perception|robotics?|"
    r"reinforcement learning|diffusion|physical ai|embodied ai|autonom(?:y|ous)|"
    r"sensor fusion|slam|image processing|motion planning|guidance|localization|navigation|control algorithms|applied ai|ai researcher|ml engineer|"
    r"algorithms? (?:engineer|developer|researcher))\b",
    re.I,
)
_OTHER_TITLE = re.compile(
    r"\b(?:mechanical|electrical|quality engineer|reliability engineer|sales|marketing|recruiter|"
    r"account executive|technical support|product manager|backend|back-end|"
    r"full[ -]?stack|front[ -]?end|devops|visualization)\b", re.I,
)
_TECHNICAL_TITLE = re.compile(
    r"\b(?:software engineer|software developer|algorithm\w*|research\w*|scientist|"
    r"robotics?|controls?|guidance|localization|navigation|ml|machine learning|ai engineer|perception|vision|deep learning)\b", re.I,
)
_DUTY = re.compile(
    r"\b(?:design|develop|train|implement|research|build|optimize)\w*\b.{0,100}"
    r"\b(?:machine learning|deep learning|computer vision|perception|robotic|"
    r"reinforcement learning|diffusion|autonomy|control algorithm|neural network|sensor fusion)\w*\b",
    re.I | re.S,
)


def title_may_match(title: str) -> bool:
    """Cheap discovery prefilter; full description and location gates still run afterward."""
    return bool(_TECHNICAL_TITLE.search(title) and not _OTHER_TITLE.search(title))


def location_rejection(job: RawJob) -> str | None:
    """Only posting-specific location metadata is evidence; office boilerplate isn't.

    Remote/EMEA/Worldwide alone does not establish an employer can hire in Israel.
    ISO IL is accepted only as a complete location component, never inside IL, USA.
    """
    location = (job.location or '').strip()
    if not location:
        return 'Location unverified: no posting-specific Israel location'
    if _EXCLUDED_ISRAEL.search(location):
        return 'Posting explicitly excludes Israel'
    if _ISRAEL.search(location):
        return None
    if location.upper() == 'IL':
        return None
    return f'Location not eligible for Israel: {location}'


def rejection_reason(job: RawJob) -> str | None:
    reason = location_rejection(job)
    if reason:
        return reason
    if len(job.description_text.strip()) < 400:
        return 'Insufficient job description to assess responsibilities and requirements'
    if _OTHER_TITLE.search(job.title):
        return 'Role is outside the target algorithm / ML / perception families'
    if not _TECHNICAL_TITLE.search(job.title):
        return 'Title does not identify a target technical role'
    if not _TARGET.search(job.title) and not _DUTY.search(job.description_text):
        return 'No explicit ML / CV / robotics / autonomy responsibilities'
    return None
