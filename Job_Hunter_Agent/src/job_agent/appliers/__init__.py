"""Applier registry: dispatches a routed job to the applier that can handle its platform."""

from __future__ import annotations

from job_agent.appliers import greenhouse, lever
from job_agent.models import RawJob

_APPLIERS = [greenhouse, lever]


def get_applier(job: RawJob):
    for applier in _APPLIERS:
        if applier.can_handle(job):
            return applier
    return None
