import pytest

from job_agent.eligibility import rejection_reason
from job_agent.models import Evaluation, JobStatus, Platform, RawJob, SeniorityBucket
from job_agent.router import route


def job(location='Tel Aviv, Israel', **kwargs):
    return RawJob(Platform.GREENHOUSE, '1', 'Computer Vision Engineer', 'company',
                  'https://example.com/jobs/1', 'https://example.com/jobs/1',
                  location=location, description_text='Develop computer vision models. ' * 30, **kwargs)


@pytest.mark.parametrize('location', [
    'Mountain View, California (HQ)', 'San Francisco, CA; New York, NY',
    'Remote', 'Remote EMEA', 'Europe', 'Worldwide', 'Remote - US',
    'Canada', None, '', 'Chicago, IL', 'Remote excluding Israel',
])
def test_foreign_and_ambiguous_locations_are_blocked_even_with_perfect_score(location):
    posting = job(location)
    posting.description_text += ' Our company also has offices in Israel.'
    evaluation = Evaluation(posting.job_key, 10, SeniorityBucket.JUNIOR, 'perfect')
    assert rejection_reason(posting)
    assert route(evaluation, posting.platform, posting) == JobStatus.DISCARDED


@pytest.mark.parametrize('location', ['Israel', 'Tel Aviv', 'Tel-Aviv', 'Herzliya', 'Haifa',
                                        'Jerusalem', 'IL', 'Remote - Israel', 'Caesarea'])
def test_explicit_israel_locations_pass(location):
    assert rejection_reason(job(location)) is None


def test_short_or_irrelevant_description_is_rejected():
    posting = job()
    posting.description_text = 'Apply now'
    assert rejection_reason(posting)
    posting.title = 'Marketing Manager'
    posting.description_text = 'Manage sales and customer relationships. ' * 30
    assert rejection_reason(posting)


def test_unverified_location_is_not_reported_when_model_fails():
    posting = job(None)
    assert route(None, posting.platform, posting) == JobStatus.DISCARDED


@pytest.mark.parametrize('title', ['Senior Backend Engineer', 'Mechanical Design Engineer - Robotic Hands',
                                  'Software Engineer, Autonomy Visualization', 'Sales Engineer'])
def test_company_ai_boilerplate_does_not_make_unrelated_role_eligible(title):
    posting = job()
    posting.title = title
    posting.description_text += 'Our company builds physical AI and robotics.' * 20
    assert rejection_reason(posting)
