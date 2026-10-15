from argparse import Namespace
from datetime import datetime, timezone
from unittest.mock import MagicMock
from contextlib import nullcontext
import pytest

from job_agent import config, evaluator, main, reporter, state
from job_agent.appliers.base import confirmed_result
from job_agent.models import Evaluation, JobStatus, Platform, RoutedJob, RunReport, SeniorityBucket
from job_agent.screener import _direct_answer, answer_question
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from tests.test_eligibility import job


def setup_run(monkeypatch, tmp_path, *, scored=True):
    posting = job()
    cfg = config.Config('unused', 'unused', 'unused', 'unused', {}, {}, {}, {})
    monkeypatch.setattr(config, 'load', lambda: cfg)
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(main, '_discover', lambda *args: [posting])
    ev = Evaluation(posting.job_key, 9, SeniorityBucket.JUNIOR, 'good')
    monkeypatch.setattr(evaluator, 'score_jobs', lambda *args, **kwargs: {posting.job_key: ev} if scored else {})
    return posting


def test_no_apply_never_reports_submission_or_writes_state(monkeypatch, tmp_path):
    setup_run(monkeypatch, tmp_path)
    report = main.run(Namespace(no_apply=True, dry_run=False))
    assert not report.applied
    assert len(report.manual_leads) == 1
    assert not (tmp_path / state.STATE_FILE).exists()


def test_dry_run_does_not_consume_jobs(monkeypatch, tmp_path):
    setup_run(monkeypatch, tmp_path)
    report = main.run(Namespace(no_apply=False, dry_run=True, max_apply=1, local=False))
    assert not report.applied
    assert len(report.manual_leads) == 1
    assert not (tmp_path / state.STATE_FILE).exists()


def test_model_outage_is_not_recommendation_and_can_be_retried(monkeypatch, tmp_path):
    posting = setup_run(monkeypatch, tmp_path, scored=False)
    report = main.run(Namespace(no_apply=True, dry_run=False))
    assert not report.manual_leads
    assert len(report.unscored) == 1
    existing = {posting.job_key: {'status': 'unscored'}, 'confirmed': {'status': 'applied'}, 'uncertain': {'status': 'failed'}}
    assert state.seen_keys(existing) == {'confirmed', 'uncertain'}


def test_policy_upgrade_reconsiders_old_decisions_without_reapplying():
    existing = {'old': {'status': 'discarded'}, 'old_lead': {'status': 'manual_lead'},
                'current': {'status': 'discarded', 'policy_version': state.POLICY_VERSION},
                'submitted': {'status': 'applied'}}
    assert state.seen_keys(existing) == {'current', 'submitted'}


def test_highest_score_gets_apply_slot(monkeypatch):
    jobs = [RoutedJob(job(), Evaluation('x', score, SeniorityBucket.JUNIOR, 'good'), JobStatus.READY_TO_APPLY)
            for score in [7, 9, 8]]
    context = MagicMock()
    monkeypatch.setattr(main.session, 'browser_context', lambda **kwargs: nullcontext(context))
    monkeypatch.setattr(main, '_resume_for_job', lambda *args: 'unused.pdf')
    monkeypatch.setattr(main.cover_letter, 'generate_cover_letter', lambda *args, **kwargs: None)
    applier = MagicMock()
    applier.apply.return_value = main.ApplyAttempt('x', success=False, bailed_reason='manual review')
    monkeypatch.setattr(main.appliers, 'get_applier', lambda job: applier)
    main._run_apply_phase(jobs, 1, False, {}, {}, '', {}, False, [])
    assert jobs[1].status == JobStatus.BAIL_COMPLEX  # score 9 gets the only slot
    assert jobs[0].status == jobs[2].status == JobStatus.MANUAL_LEAD
    assert applier.apply.call_count == 1


def test_no_confirmation_cannot_report_success():
    form = MagicMock()
    form.get_by_text.return_value.first.wait_for.side_effect = PlaywrightTimeoutError('no receipt')
    attempt = confirmed_result(form, 'job:1')
    assert not attempt.success
    assert 'unconfirmed' in attempt.error


def test_visible_confirmation_reports_success():
    assert confirmed_result(MagicMock(), 'job:1').success


def test_foreign_jobs_do_not_reach_model(monkeypatch):
    monkeypatch.setattr(evaluator.genai, 'Client', lambda **kwargs: (_ for _ in ()).throw(AssertionError('model called')))
    posting = job('San Francisco, CA')
    results = evaluator.score_jobs([posting], {}, 'unused')
    assert results[posting.job_key].score == 0


def test_unknown_and_duplicate_model_ids_cannot_route(monkeypatch):
    posting = job()
    monkeypatch.setattr(evaluator.genai, 'Client', lambda **kwargs: None)
    item = dict(score=10, seniority_bucket='junior', reason='good', matched_domains=[], red_flags=[])
    response = evaluator._BatchResponse(evaluations=[
        evaluator._JobEvaluation(job_key='invented', **item),
        evaluator._JobEvaluation(job_key=posting.job_key, **item),
        evaluator._JobEvaluation(job_key=posting.job_key, **item),
    ])
    monkeypatch.setattr(evaluator, '_call_gemini', lambda *args: response)
    assert evaluator.score_jobs([posting], {}, 'unused') == {}


def test_model_outage_uses_configured_fallback(monkeypatch):
    posting = job()
    monkeypatch.setattr(evaluator.genai, 'Client', lambda **kwargs: None)
    monkeypatch.setattr(config, 'GEMINI_FALLBACK_MODEL', 'fallback')
    calls = []
    class Unavailable(Exception):
        code = 503
    def call(client, system, prompt, model=None):
        calls.append(model)
        if model is None:
            raise Unavailable('overloaded')
        return evaluator._BatchResponse(evaluations=[evaluator._JobEvaluation(
            job_key=posting.job_key, score=8, seniority_bucket='junior', reason='good',
            matched_domains=['computer vision'], red_flags=[])])
    monkeypatch.setattr(evaluator, '_call_gemini', call)
    assert evaluator.score_jobs([posting], {}, 'unused')[posting.job_key].score == 8
    assert calls == [None, 'fallback']


def test_experience_stretch_is_scored_and_can_be_applied(monkeypatch):
    from job_agent.router import route
    posting = job()
    posting.description_text += '\nRequirements\n5+ years of machine learning experience.'
    monkeypatch.setattr(evaluator.genai, 'Client', lambda **kwargs: None)
    response = evaluator._BatchResponse(evaluations=[evaluator._JobEvaluation(
        job_key=posting.job_key, score=8, seniority_bucket='senior', reason='strong CV fit',
        matched_domains=['computer vision'], red_flags=['Requires 5+ years of professional ML experience'])])
    monkeypatch.setattr(evaluator, '_call_gemini', lambda *args: response)
    profile = {'experience_facts': {'years_professional_ml': 1}}
    result = evaluator.score_jobs([posting], profile, 'unused')[posting.job_key]
    assert result.score == 8
    assert not result.red_flags
    assert result.experience_gaps
    assert route(result, posting.platform, posting) == JobStatus.READY_TO_APPLY


def test_experience_does_not_hide_clearance_requirement():
    from job_agent.router import route
    posting = job()
    evaluation = Evaluation(posting.job_key, 9, SeniorityBucket.SENIOR, 'good', ['robotics'],
                            ['Requires security clearance and 5 years experience'])
    assert route(evaluation, posting.platform, posting) == JobStatus.DISCARDED


def test_both_models_failing_keeps_job_unscored(monkeypatch):
    posting = job()
    monkeypatch.setattr(evaluator.genai, 'Client', lambda **kwargs: None)
    class Unavailable(Exception):
        code = 503
    def call(*args):
        raise Unavailable('overloaded')
    monkeypatch.setattr(evaluator, '_call_gemini', call)
    errors = []
    assert evaluator.score_jobs([posting], {}, 'unused', errors) == {}
    assert errors


def test_screener_does_not_convert_general_experience_to_skill_years():
    answers = {'experience': {'years_of_professional_experience': 6, 'years_of_robotics_experience': 3}}
    assert _direct_answer('How many years of experience with Python?', answers) is None
    assert _direct_answer('How many years of experience with C++?', answers) is None
    assert _direct_answer('Are you authorized to work in Israel?', {}) is None
    assert _direct_answer('Do you require visa sponsorship in Israel?', {}) is None


def test_appliers_reject_foreign_job_before_touching_browser():
    from job_agent.appliers import greenhouse, lever
    page = MagicMock()
    for applier in [greenhouse, lever]:
        result = applier.apply(page, job('Mountain View, California'), {}, 'unused.pdf')
        assert not result.success
        assert result.bailed_reason
    page.goto.assert_not_called()


def test_crash_signals_failure_to_github_actions(monkeypatch):
    monkeypatch.setattr(main, '_parse_args', lambda: Namespace(no_email=True))
    def crash(args):
        raise RuntimeError('discovery crashed')
    monkeypatch.setattr(main, 'run', crash)
    with pytest.raises(SystemExit) as result:
        main.main()
    assert result.value.code == 1


def test_report_includes_location_and_separates_unscored():
    report = RunReport(datetime.now(timezone.utc))
    report.unscored.append(RoutedJob(job(), None, JobStatus.UNSCORED))
    html = reporter.build_html(report)
    assert 'Tel Aviv, Israel' in html
    assert 'Not evaluated (1)' in html
    assert 'Recommended for Manual Apply (0)' in html
