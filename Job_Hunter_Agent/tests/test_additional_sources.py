import httpx
import pytest

from job_agent.eligibility import rejection_reason
from job_agent.sources import smartrecruiters, workday


def smart_posting(country='il', active=True):
    return {'id': '42', 'name': 'Computer Vision Engineer', 'active': active, 'visibility': 'PUBLIC',
            'company': {'name': 'Acme'}, 'location': {'city': 'Tel Aviv', 'country': country},
            'postingUrl': 'https://jobs.smartrecruiters.com/Acme/42',
            'jobAd': {'sections': {
                'companyDescription': {'text': 'Global offices in Israel'},
                'jobDescription': {'title': 'Responsibilities', 'text': '<p>Develop computer vision models.</p>' * 30},
                'qualifications': {'title': 'Qualifications', 'text': '<p>Python and PyTorch required.</p>'},
            }}}


def test_smartrecruiters_preserves_requirements_and_rejects_foreign_and_inactive():
    job = smartrecruiters.parse_posting(smart_posting(), 'Acme')
    assert rejection_reason(job) is None
    assert 'Qualifications\nPython and PyTorch required.' in job.description_text
    assert 'Global offices' not in job.description_text
    assert smartrecruiters.parse_posting(smart_posting('us'), 'Acme') is None
    assert smartrecruiters.parse_posting(smart_posting(active=False), 'Acme') is None


def test_smartrecruiters_paginates_and_checks_detail_country_again(monkeypatch):
    original_client = httpx.Client
    def respond(request):
        if request.url.path.endswith('/postings'):
            offset = int(request.url.params.get('offset', 0))
            identifier = str(offset + 1)
            return httpx.Response(200, json={'totalFound': 2, 'content': [
                {'id': identifier, 'name': 'ML Engineer', 'location': {'country': 'il'}}]})
        # The second result moved abroad between listing and detail retrieval.
        return httpx.Response(200, json=smart_posting('il' if request.url.path.endswith('/1') else 'us'))
    monkeypatch.setattr(smartrecruiters.httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(respond)))
    jobs = smartrecruiters.fetch(['Acme'])
    assert len(jobs) == 1
    assert jobs[0].location == 'Tel Aviv, Israel'


def workday_posting(location='Israel, Tel Aviv', **changes):
    return dict({'jobReqId': 'JR1', 'title': 'Computer Vision Engineer', 'canApply': True,
                 'posted': True, 'location': location,
                 'externalUrl': 'https://example.myworkdayjobs.com/Careers/job/CV_JR1',
                 'jobDescription': '<p>Develop computer vision algorithms.</p>' * 30}, **changes)


def test_workday_requires_actual_job_locations_and_active_state():
    parse = lambda item: workday.parse_posting(item, 'Acme', 'example.myworkdayjobs.com')
    assert rejection_reason(parse(workday_posting())) is None
    assert parse(workday_posting('5 Locations')) is None
    assert parse(workday_posting('US, California')) is None
    assert parse(workday_posting(canApply=False)) is None
    assert parse(workday_posting(externalUrl='https://evil.example/job/1')) is None
    assert parse(workday_posting('US, California', additionalLocations=['Israel, Haifa'])) is not None


def test_workday_discovers_nested_israel_facet():
    assert workday.israel_facet([{'facetParameter': 'parent', 'values': [
        {'facetParameter': 'locationHierarchy1', 'values': [{'descriptor': 'Israel', 'id': 'israel-id'}]}
    ]}]) == ('locationHierarchy1', 'israel-id')
    assert workday.israel_facet([]) is None


def test_workday_paginates_dedupes_and_keeps_graduates_within_cap(monkeypatch):
    import json
    original_client = httpx.Client
    retrieved = []
    def respond(request):
        if request.method == 'POST':
            body = json.loads(request.content)
            if body['searchText'] == 'Israel':
                return httpx.Response(200, json={'facets': [{'facetParameter': 'country', 'values': [{'descriptor': 'Israel', 'id': 'IL'}]}]})
            assert body['appliedFacets'] == {'country': ['IL']}
            items = [{'title': 'Senior Computer Vision Engineer', 'externalPath': f'/job/Israel/CV_JR{i}'} for i in range(20)]
            if body['offset']:
                items = [{'title': 'Computer Vision Engineer - New College Graduate', 'externalPath': '/job/Israel/Graduate_JR20'}]
            return httpx.Response(200, json={'total': 21, 'jobPostings': items})
        retrieved.append(request.url.path)
        return httpx.Response(200, json={'jobPostingInfo': workday_posting(jobReqId=request.url.path.rsplit('_', 1)[-1])})
    monkeypatch.setattr(workday.httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(respond)))
    board = {'name': 'Acme', 'base_url': 'https://example.myworkdayjobs.com/wday/cxs/acme/Careers',
             'queries': ['computer vision', 'deep learning'], 'max_jobs': 2}
    jobs = workday.fetch([board])
    assert len(jobs) == len(retrieved) == 2
    assert any('Graduate_JR20' in path for path in retrieved)
    assert len(set(retrieved)) == 2


def test_guidance_engineer_is_a_target_despite_unconventional_title():
    from tests.test_eligibility import job
    posting = job()
    posting.title = 'Senior Guidance Engineer'
    assert rejection_reason(posting) is None
