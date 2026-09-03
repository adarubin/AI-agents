from datetime import datetime, timedelta, timezone

from job_agent.models import Platform, RawJob
from job_agent.normalize import normalize


def _job(external_id, title="ML Engineer", company="acme", hours_ago=1, url=None):
    posted_at = datetime.now(timezone.utc) - timedelta(hours=hours_ago) if hours_ago is not None else None
    return RawJob(
        platform=Platform.GREENHOUSE,
        external_id=external_id,
        title=title,
        company=company,
        url=url or f"https://boards.greenhouse.io/acme/jobs/{external_id}",
        apply_url="https://example.com/apply",
        posted_at=posted_at,
        description_text="x" * 500,
    )


def test_drops_seen_jobs():
    jobs = [_job("1"), _job("2")]
    result = normalize(jobs, seen_keys={jobs[0].job_key}, freshness_hours=48, max_jobs=100)
    assert [j.external_id for j in result] == ["2"]


def test_drops_stale_jobs():
    jobs = [_job("1", hours_ago=1), _job("2", hours_ago=100)]
    result = normalize(jobs, seen_keys=set(), freshness_hours=48, max_jobs=100)
    assert [j.external_id for j in result] == ["1"]


def test_unknown_date_jobs_kept_and_sorted_last():
    fresh = _job("1", hours_ago=1, company="fresh-co")
    unknown = _job("2", hours_ago=None, company="unknown-co")
    result = normalize([unknown, fresh], seen_keys=set(), freshness_hours=48, max_jobs=100)
    assert [j.external_id for j in result] == ["1", "2"]


def test_dedupes_by_company_and_title():
    jobs = [
        _job("1", title="ML Engineer", company="Acme", url="https://a.com/1"),
        _job("2", title="ml engineer", company="acme", url="https://a.com/2"),
    ]
    result = normalize(jobs, seen_keys=set(), freshness_hours=48, max_jobs=100)
    assert len(result) == 1


def test_dedupes_by_url():
    same_url = "https://boards.greenhouse.io/acme/jobs/1"
    jobs = [
        _job("1", title="ML Engineer", company="acme", url=same_url),
        _job("2", title="Robotics Engineer", company="acme", url=same_url),
    ]
    result = normalize(jobs, seen_keys=set(), freshness_hours=48, max_jobs=100)
    assert len(result) == 1


def test_caps_to_max_jobs_keeping_freshest():
    jobs = [_job(str(i), hours_ago=i, company=f"c{i}") for i in range(10)]
    result = normalize(jobs, seen_keys=set(), freshness_hours=48, max_jobs=3)
    assert [j.external_id for j in result] == ["0", "1", "2"]
