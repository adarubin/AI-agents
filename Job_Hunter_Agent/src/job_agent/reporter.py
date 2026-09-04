"""Builds and sends the HTML (+ plain-text) run report over Gmail SMTP (SSL, port 465)."""

from __future__ import annotations

import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from job_agent import config
from job_agent.models import RoutedJob, RunReport

# Gmail (and many other webmail clients) strip <head><style> blocks entirely, so every visual
# rule here must be an inline `style=` attribute or the table renders as unstyled, unspaced text.
_TD = 'padding:6px 8px;border-bottom:1px solid #eee;font-size:13px;text-align:left;'
_TH = _TD + 'background:#f5f5f5;font-weight:bold;'


def _job_row(routed: RoutedJob, include_reason: bool = True) -> str:
    job, ev = routed.job, routed.evaluation
    score = f"{ev.score:.1f}" if ev else "-"
    reason = escape(ev.reason) if ev else ""
    date_note = (
        "" if job.posted_at
        else ' <span style="color:#b36b00;font-size:11px;">(date unverified)</span>'
    )
    cells = [
        f'<td style="{_TD}"><a href="{escape(job.url)}">{escape(job.title)}</a></td>',
        f'<td style="{_TD}">{escape(job.company or "-")}</td>',
        f'<td style="{_TD}font-weight:bold;">{score}</td>',
        f'<td style="{_TD}">{escape(job.platform.value)}{date_note}</td>',
    ]
    if include_reason:
        cells.append(f'<td style="{_TD}">{reason}</td>')
    return "<tr>" + "".join(cells) + "</tr>"


def _table(rows: list[RoutedJob], headers: list[str], empty_message: str) -> str:
    if not rows:
        return f"<p>{empty_message}</p>"
    header_html = "".join(f'<th style="{_TH}">{h}</th>' for h in headers)
    body_html = "".join(_job_row(r, include_reason="Rationale" in headers) for r in rows)
    return (
        '<table style="width:100%;border-collapse:collapse;margin-bottom:24px;">'
        f"<tr>{header_html}</tr>{body_html}</table>"
    )


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
        errors_html = (
            '<div style="background:#fff4f4;padding:8px 12px;border-radius:6px;">'
            f"<h2>Errors / Skipped / CAPTCHAs</h2><ul>{items}</ul></div>"
        )

    return f"""\
<html><body style="font-family:-apple-system,Segoe UI,Arial,sans-serif;color:#1a1a1a;">
<h1>Job Hunter Report -- {report.started_at:%Y-%m-%d %H:%M} UTC{duration}</h1>

<h2 style="border-bottom:2px solid #ddd;padding-bottom:4px;">Submitted via Auto-Apply ({len(report.applied)})</h2>
{applied_table}

<h2 style="border-bottom:2px solid #ddd;padding-bottom:4px;">Recommended for Manual Apply ({len(report.manual_leads)})</h2>
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
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Job Hunter Report - {report.started_at:%Y-%m-%d %H:%M} - " \
                      f"{len(report.applied)} applied, {len(report.manual_leads)} leads"
    msg["From"] = gmail_user
    msg["To"] = receiver

    body = MIMEMultipart("alternative")
    body.attach(MIMEText(build_plaintext(report), "plain"))
    body.attach(MIMEText(build_html(report), "html"))
    msg.attach(body)

    resume_path = config.ASSETS_DIR / "Adar_Rubin_CV.pdf"
    if resume_path.is_file():
        with open(resume_path, "rb") as f:
            attachment = MIMEApplication(f.read(), _subtype="pdf")
        attachment.add_header("Content-Disposition", "attachment", filename=resume_path.name)
        msg.attach(attachment)

    with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT) as server:
        server.login(gmail_user, gmail_app_password)
        server.sendmail(gmail_user, [receiver], msg.as_string())
