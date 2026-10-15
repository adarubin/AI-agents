import json

from job_agent.sources import comeet, dorking, extract, ats_api
from job_agent.eligibility import rejection_reason


def test_search_query_budget_reaches_comeet_and_workable():
    from job_agent import config
    queries = dorking._build_queries(config.ROLE_FAMILIES)[:config.DORK_QUERY_BUDGET]
    assert any('comeet.com' in q for q in queries)
    assert any('apply.workable.com' in q for q in queries)
    assert all('"Israel"' in q for q in queries)


def test_ads_and_irrelevant_domains_are_rejected():
    for url in ['https://www.bing.com/aclick?u=anything', 'https://www.forbes.com/profile/person',
                'https://jobs.lever.co.evil.com/acme/123', 'https://comeet.com/jobs/acme/A1.001']:
        assert not dorking._is_job_url(url)
    assert dorking._is_job_url('https://www.comeet.com/jobs/acme/A1.001/ml-engineer/B2.002')


def test_comeet_reads_position_facts_not_angular_boilerplate():
    item = {'uid': 'A1', 'name': 'Computer Vision Engineer', 'company_name': 'Acme',
            'location': {'name': 'Herzliya', 'country': 'IL'},
            'url_comeet_hosted_page': 'https://www.comeet.com/jobs/acme/1/cv/A1',
            'custom_fields': {'details': [
                {'name': 'Responsibilities', 'value': '<p>Develop computer vision models.</p>' * 30},
                {'name': 'Requirements', 'value': '<p>Python and PyTorch</p>'},
            ]}}
    html = 'COMPANY_POSITIONS_DATA = ' + json.dumps([item]) + ';'
    jobs = comeet.embedded_data(html, 'COMPANY_POSITIONS_DATA')
    posting = comeet.parse_position(jobs[0])
    assert posting.location == 'Herzliya, Israel'
    assert 'Requirements\nPython and PyTorch' in posting.description_text
    assert posting.active_verified
    assert rejection_reason(posting) is None
    item['is_internal'] = True
    assert comeet.parse_position(item) is None


def test_search_location_cannot_come_from_company_office_text(monkeypatch):
    schema = {'@type': 'JobPosting', 'title': 'ML Engineer',
              'description': 'Develop machine learning. We have offices in Israel. ' * 30,
              'hiringOrganization': {'name': 'Company'},
              'jobLocation': {'address': {'addressLocality': 'New York', 'addressCountry': 'US'}}}
    monkeypatch.setattr(extract, '_fetch_html', lambda url: '<script type="application/ld+json">' + json.dumps(schema) + '</script>')
    posting = extract.extract_posting('https://example.com/job/1', '1')
    assert posting.location == 'New York, US'
    assert rejection_reason(posting)


def test_search_article_without_job_schema_is_rejected(monkeypatch):
    monkeypatch.setattr(extract, '_fetch_html', lambda url: '<h1>AI news in Israel</h1>' + 'AI news ' * 100)
    assert extract.extract_posting('https://example.com/job/1', '1') is None


def test_lever_includes_requirements_lists(monkeypatch):
    monkeypatch.setattr(ats_api, '_get_json', lambda *args, **kwargs: [{
        'id': '1', 'text': 'ML Engineer', 'descriptionPlain': 'About company',
        'categories': {'location': 'Israel'},
        'lists': [{'text': 'Requirements', 'content': '<li>Ph.D. required</li>'}],
    }])
    posting = ats_api.fetch_lever(None, 'acme')[0]
    assert 'Requirements\nPh.D. required' in posting.description_text


def test_mobileye_keeps_job_location_and_requirements_separate_from_company_intro():
    from job_agent.sources.mobileye import parse_jobs
    html = '''<div class="jobItem">
      <a href="/jobs/algorithm-engineer/uuid-1">Open</a>
      <p class="jobTitle">Algorithm Engineer</p>
      <div><img alt="location icon"><p>Jerusalem</p></div>
      <div class="bottomSection">
        <div class="positionIntroTextWrapper">Our company has offices everywhere</div>
        <p>Develop computer vision algorithms.</p><p>Requirements: 1+ years Python.</p>
      </div></div>'''
    posting = parse_jobs(html)[0]
    assert posting.location == 'Jerusalem'
    assert 'Requirements: 1+ years Python.' in posting.description_text
    assert 'offices everywhere' not in posting.description_text
    assert posting.active_verified
