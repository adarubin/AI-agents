from job_agent.models import Evaluation, JobStatus, Platform, SeniorityBucket
from job_agent.router import is_apply_eligible, route


def _eval(score=8.0, bucket=SeniorityBucket.JUNIOR, red_flags=None, domains=None):
    return Evaluation(
        job_key="x:1",
        score=score,
        seniority_bucket=bucket,
        reason="ok",
        matched_domains=domains or [],
        red_flags=red_flags or [],
    )


def test_junior_high_score_greenhouse_is_apply_eligible():
    e = _eval(score=8.0, bucket=SeniorityBucket.JUNIOR)
    assert is_apply_eligible(e, Platform.GREENHOUSE)


def test_junior_below_threshold_not_eligible():
    e = _eval(score=6.9, bucket=SeniorityBucket.JUNIOR)
    assert not is_apply_eligible(e, Platform.GREENHOUSE)


def test_senior_requires_higher_threshold_and_overlap():
    e = _eval(score=8.0, bucket=SeniorityBucket.SENIOR, domains=["robotics"])
    assert not is_apply_eligible(e, Platform.LEVER)  # below 8.5
    e2 = _eval(score=9.0, bucket=SeniorityBucket.SENIOR, domains=[])
    assert not is_apply_eligible(e2, Platform.LEVER)  # no overlap
    e3 = _eval(score=9.0, bucket=SeniorityBucket.SENIOR, domains=["robotics"])
    assert is_apply_eligible(e3, Platform.LEVER)


def test_dorked_platform_never_eligible():
    e = _eval(score=10.0, bucket=SeniorityBucket.JUNIOR)
    assert not is_apply_eligible(e, Platform.DORKED)


def test_red_flag_blocks_apply():
    e = _eval(score=9.0, bucket=SeniorityBucket.JUNIOR, red_flags=["needs clearance"])
    assert not is_apply_eligible(e, Platform.GREENHOUSE)


def test_route_unscored():
    assert route(None, Platform.GREENHOUSE) == JobStatus.UNSCORED


def test_route_applied_when_eligible():
    e = _eval(score=8.0, bucket=SeniorityBucket.JUNIOR)
    assert route(e, Platform.GREENHOUSE) == JobStatus.APPLIED


def test_route_manual_lead_when_relevant_but_not_eligible():
    e = _eval(score=8.0, bucket=SeniorityBucket.JUNIOR)
    assert route(e, Platform.DORKED) == JobStatus.MANUAL_LEAD


def test_route_discarded_when_low_score():
    e = _eval(score=3.0, bucket=SeniorityBucket.JUNIOR)
    assert route(e, Platform.GREENHOUSE) == JobStatus.DISCARDED
