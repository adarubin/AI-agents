"""Builds and sends the HTML (+ plain-text) run report over Gmail SMTP (SSL, port 465)."""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from job_agent import config
from job_agent.models import RoutedJob, RunReport

_CSS = """
body { font-family: -apple-system, Segoe UI, Arial, sans-serif; color: #1a1a1a; }
h2 { border-bottom: 2px solid #ddd; padding-bottom: 4px; }
table { width: 100%; border-collapse: collapse; margin-bottom: 24px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #eee; font-size: 13px; }
th { background: #f5f5f5; }
.score { font-weight: bold; }
.errors { background: #fff4f4; padding: 8px 12px; border-radius: 6px; }
.unverified { color: #b36b00; font-size: 11px; }
"""


def _job_row(routed: RoutedJob, include_reason: bool = True) -> str:
    job, ev = routed.job, routed.evaluation
    score = f"{ev.score:.1f}" if ev else "-"
    reason = escape(ev.reason) if ev else ""
    date_note = "" if job.posted_at else ' <span class="unverified">(date unverified)</span>'
    cells = [
        f'<td><a href="{escape(job.url)}">{escape(job.title)}</a></td>',
        f"<td>{escape(job.company or '-')}</td>",
        f'<td class="score">{score}</td>',
        f"<td>{escape(job.platform.value)}{date_note}</td>",
    ]
    if include_reason:
        cells.append(f"<td>{reason}</td>")
    return "<tr>" + "".join(cells) + "</tr>"


def _table(rows: list[RoutedJob], headers: list[str], empty_message: str) -> str:
    if not rows:
        return f"<p>{empty_message}</p>"
    header_html = "".join(f"<th>{h}</th>" for h in headers)
    body_html = "".join(_job_row(r, include_reason="Rationale" in headers) for r in rows)
    return f"<table><tr>{header_html}</tr>{body_html}</table>"


def build_html(report: RunReport) -> str:
    duration = ""
    if report.finished_at:
        duration = f" (took {(report.finished_at - report.started_at).total_seconds():.0f}s)"

    applied_table = _table(
        report.applied,
        ["Title", "Company", "Score", "Platform"],
        "No applications were submitted this run.",
    )
    manual_table = _table(
        report.manual_leads,
        ["Title", "Company", "Score", "Platform", "Rationale"],
        "No manual leads to review this run.",
    )
    errors_html = ""
    if report.errors:
        items = "".join(f"<li>{escape(e)}</li>" for e in report.errors)
        errors_html = f'<div class="errors"><h2>Errors / Skipped / CAPTCHAs</h2><ul>{items}</ul></div>'

    return f"""\
<html><head><style>{_CSS}</style></head><body>
<h1>Job Hunter Report -- {report.started_at:%Y-%m-%d %H:%M} UTC{duration}</h1>

<h2>Submitted via Auto-Apply ({len(report.applied)})</h2>
{applied_table}

<h2>Recommended for Manual Apply ({len(report.manual_leads)})</h2>
{manual_table}

<p>Discarded (score below threshold): {report.discarded_count}</p>

{errors_html}
</body></html>
"""


def build_plaintext(report: RunReport) -> str:
    lines = [f"Job Hunter Report -- {report.started_at:%Y-%m-%d %H:%M} UTC", ""]
    lines.append(f"Submitted via Auto-Apply ({len(report.applied)}):")
    for r in report.applied:
        lines.append(f"  - {r.job.title} @ {r.job.company} -> {r.job.url}")
    lines.append("")
    lines.append(f"Recommended for Manual Apply ({len(report.manual_leads)}):")
    for r in report.manual_leads:
        score = f"{r.evaluation.score:.1f}" if r.evaluation else "-"
        reason = r.evaluation.reason if r.evaluation else ""
        lines.append(f"  - [{score}] {r.job.title} @ {r.job.company} -> {r.job.url} :: {reason}")
    lines.append("")
    lines.append(f"Discarded: {report.discarded_count}")
    if report.errors:
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"  - {e}" for e in report.errors)
    return "\n".join(lines)


def send(report: RunReport, gmail_user: str, gmail_app_password: str, receiver: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Job Hunter Report - {report.started_at:%Y-%m-%d %H:%M} - " \
                      f"{len(report.applied)} applied, {len(report.manual_leads)} leads"
    msg["From"] = gmail_user
    msg["To"] = receiver
    msg.attach(MIMEText(build_plaintext(report), "plain"))
    msg.attach(MIMEText(build_html(report), "html"))

    with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT) as server:
        server.login(gmail_user, gmail_app_password)
        server.sendmail(gmail_user, [receiver], msg.as_string())
