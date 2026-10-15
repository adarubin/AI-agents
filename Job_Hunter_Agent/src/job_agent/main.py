"""Orchestrator. CLI flags: --dry-run (no submissions), --max-apply N, --no-email, --local (headed
browser). Always sends the report from a `finally` block so a crash mid-run still produces an
email containing the traceback, per the plan's reliability requirement.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from job_agent import appliers, config, cover_letter, evaluator, humanize, normalize, reporter, screener, session, state, tailor
from job_agent.appliers.base import ComplexityBailOut
from job_agent.eligibility import rejection_reason
from job_agent.qualifications import gaps as qualification_gaps
from job_agent.models import ApplyAttempt, JobStatus, RawJob, RoutedJob, RunReport
from job_agent.router import route
from job_agent.sources import ats_api, comeet, dorking, hn, mobileye, smartrecruiters, workday
from scripts.generate_resume import generate as generate_resume_pdf


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Job Hunter & Auto-Apply Agent")
    parser.add_argument("--dry-run", action="store_true", help="never submit applications")
    parser.add_argument("--no-apply", action="store_true", help="skip the apply phase entirely")
    parser.add_argument("--max-apply", type=int, default=None, help="override the randomized apply cap")
    parser.add_argument("--no-email", action="store_true", help="skip sending the report email")
    parser.add_argument("--local", action="store_true", help="run the browser headed, for debugging")
    return parser.parse_args()


def _discover(cfg: config.Config, errors: list[str]) -> list:
    jobs = ats_api.fetch_all(cfg.ats_boards, errors=errors)
    jobs.extend(comeet.fetch(cfg.ats_boards.get('comeet', []) or [], errors=errors))
    jobs.extend(mobileye.fetch(errors=errors))
    jobs.extend(smartrecruiters.fetch(cfg.ats_boards.get('smartrecruiters', []) or [], errors=errors))
    jobs.extend(workday.fetch(cfg.ats_boards.get('workday', []) or [], errors=errors))
    jobs.extend(dorking.fetch(errors=errors))
    jobs.extend(hn.fetch(errors=errors))
    return jobs


def _resume_for_job(
    job: RawJob, base_resume_content: dict, api_key: str, errors: list[str], tmp_dir: str
) -> str:
    """A per-job resume PDF path: tailored to the job description when possible, else the
    static fallback generated in CI from the untailored base content."""
    fallback_path = str(config.ASSETS_DIR / "Adar_Rubin_CV.pdf")
    if not base_resume_content:
        return fallback_path

    tailored = tailor.tailor_resume(base_resume_content, job, api_key, errors=errors)
    if tailored is None:
        return fallback_path

    temp_yaml_path = Path(tmp_dir) / "resume.yaml"
    temp_pdf_path = Path(tmp_dir) / "resume.pdf"
    with open(temp_yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(tailored, f, sort_keys=False)

    try:
        generate_resume_pdf(temp_yaml_path, temp_pdf_path)
    except Exception as exc:  # noqa: BLE001 - a render failure must not block the application
        msg = f"[tailor] failed to render tailored PDF for {job.job_key}: {exc}"
        print(msg, file=sys.stderr)
        errors.append(msg)
        return fallback_path

    return str(temp_pdf_path)


def _run_apply_phase(
    candidates: list[RoutedJob],
    cap: int,
    dry_run: bool,
    base_resume_content: dict,
    candidate_profile: dict,
    api_key: str,
    answers: dict,
    headed: bool,
    errors: list[str],
    record_result: Callable[[RoutedJob], None] | None = None,
) -> None:
    """Attempt auto-apply for eligible jobs up to `cap`. Anything past the cap, or that bails,
    is downgraded to MANUAL_LEAD so nothing is silently lost.

    Per job, the orchestrator runs three sub-agents before handing off to the applier: the resume
    tailor (PDF), the cover-letter generator, and the screener (answers custom form fields)."""
    eligible = sorted(
        [r for r in candidates if r.status == JobStatus.READY_TO_APPLY],
        key=lambda r: r.evaluation.score if r.evaluation else 0,
        reverse=True,
    )
    cap = max(0, cap)
    to_attempt, overflow = eligible[:cap], eligible[cap:]

    for routed in overflow:
        routed.status = JobStatus.MANUAL_LEAD

    if not to_attempt:
        return

    if dry_run:
        # Rehearsal mode: report what WOULD be attempted, but never touch a real browser/form.
        for routed in to_attempt:
            # Recheck at the submission boundary, independent of the model and router.
            if rejection_reason(routed.job):
                routed.status = JobStatus.DISCARDED
                continue
            routed.status = JobStatus.MANUAL_LEAD
        return

    with session.browser_context(headless=not headed) as context:
        for routed in to_attempt:
            if rejection_reason(routed.job) or qualification_gaps(routed.job, candidate_profile):
                routed.status = JobStatus.DISCARDED
                continue
            applier = appliers.get_applier(routed.job)
            if applier is None:
                routed.status = JobStatus.MANUAL_LEAD
                continue

            # Persist the attempt before opening a form. A crash must not trigger a duplicate.
            if record_result:
                record_result(routed)

            with tempfile.TemporaryDirectory() as tmp_dir:
                resume_path = _resume_for_job(routed.job, base_resume_content, api_key, errors, tmp_dir)
                letter = cover_letter.generate_cover_letter(
                    candidate_profile, routed.job, api_key, errors=errors
                )

                def screener_fn(question: str) -> str | None:
                    return screener.answer_question(
                        question, answers, candidate_profile, api_key, errors=errors
                    )

                page = context.new_page()
                try:
                    attempt: ApplyAttempt = applier.apply(
                        page, routed.job, answers, resume_path, cover_letter=letter, screener_fn=screener_fn
                    )
                except ComplexityBailOut as exc:
                    attempt = ApplyAttempt(job_key=routed.job.job_key, success=False, bailed_reason=exc.reason)
                finally:
                    page.close()
                # tmp_dir (and any tailored resume.yaml/resume.pdf inside it) is removed on exit,
                # whether apply() succeeded, bailed, or raised.

            routed.apply_attempt = attempt
            if attempt.success:
                routed.status = JobStatus.APPLIED
            elif attempt.bailed_reason:
                routed.status = JobStatus.BAIL_COMPLEX
            else:
                routed.status = JobStatus.FAILED

            if record_result:
                record_result(routed)

            if attempt.success:
                humanize.between_applications()


def run(args: argparse.Namespace) -> RunReport:
    cfg = config.load()
    report = RunReport(started_at=datetime.now(timezone.utc))

    existing_state = state.load(config.DATA_DIR)

    raw_jobs = _discover(cfg, report.errors)
    report.discovered_count = len(raw_jobs)
    eligible_jobs = [job for job in raw_jobs if rejection_reason(job) is None]
    report.discarded_count = len(raw_jobs) - len(eligible_jobs)
    candidates = normalize.normalize(
        eligible_jobs,
        seen_keys=state.seen_keys(existing_state),
        freshness_hours=config.FRESHNESS_HOURS,
        max_jobs=config.MAX_JOBS_PER_RUN,
    )

    evaluations = evaluator.score_jobs(
        candidates, cfg.candidate_profile, cfg.gemini_api_key, errors=report.errors
    )
    report.screened_count = len(candidates)

    routed_jobs = [
        RoutedJob(job=job, evaluation=evaluations.get(job.job_key), status=JobStatus.UNSCORED)
        for job in candidates
    ]
    for routed in routed_jobs:
        routed.status = route(routed.evaluation, routed.job.platform, routed.job)

    if not args.no_apply:
        cap = args.max_apply if args.max_apply is not None else humanize.apply_cap()
        def record_result(routed: RoutedJob) -> None:
            state.record(existing_state, routed)
            state.save(config.DATA_DIR, existing_state)

        _run_apply_phase(
            routed_jobs,
            cap,
            dry_run=args.dry_run,
            base_resume_content=cfg.resume_content,
            candidate_profile=cfg.candidate_profile,
            api_key=cfg.gemini_api_key,
            answers=cfg.answers,
            headed=args.local,
            errors=report.errors,
            record_result=None if args.dry_run else record_result,
        )

    # --no-apply and --dry-run must never claim a submission or consume seen-state.
    for routed in routed_jobs:
        if routed.status == JobStatus.READY_TO_APPLY:
            routed.status = JobStatus.MANUAL_LEAD
        if not args.dry_run and not args.no_apply:
            state.record(existing_state, routed)
        if routed.status == JobStatus.APPLIED:
            report.applied.append(routed)
        elif routed.status in (JobStatus.MANUAL_LEAD, JobStatus.BAIL_COMPLEX):
            report.manual_leads.append(routed)
        elif routed.status == JobStatus.UNSCORED:
            report.unscored.append(routed)
        elif routed.status == JobStatus.FAILED:
            report.failed.append(routed)
        elif routed.status == JobStatus.DISCARDED:
            report.discarded_count += 1

    report.manual_leads.sort(key=lambda r: r.evaluation.score if r.evaluation else 0, reverse=True)
    if not args.dry_run and not args.no_apply:
        state.save(config.DATA_DIR, existing_state)
    report.finished_at = datetime.now(timezone.utc)
    return report


def main() -> None:
    args = _parse_args()
    report = None
    exit_code = 0
    try:
        report = run(args)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - top-level catch so we can still email the traceback
        exit_code = 1
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        report = RunReport(
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            errors=[f"Run crashed:\n{tb}"],
        )
    finally:
        if report is not None and not args.no_email:
            try:
                cfg = config.load()
                reporter.send(report, cfg.gmail_user, cfg.gmail_app_password, cfg.gmail_receiver)
            except Exception as exc:  # noqa: BLE001 - never let the reporter crash the process
                print(f"[main] failed to send report email: {exc}", file=sys.stderr)
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
