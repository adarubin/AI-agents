# Job Hunter & Auto-Apply Agent

Twice-daily agent that discovers fresh ML / AI / Robotics / Computer-Vision job postings on
Greenhouse, Lever, and Ashby, scores each one against your profile with Gemini 2.5 Flash, auto-applies
to a capped number of simple applications, and emails one HTML report per run.

See the architecture plan for full design rationale.

## Location and quality gates

Only posting-specific, verified Israeli locations are eligible, including remote roles explicitly
listing Israel. `Remote`, `EMEA`, `Worldwide`, and missing locations are rejected before the model
call and checked again at routing and application time. A company having an Israeli office does
not establish eligibility for a particular job.

Discovery reads Greenhouse/Lever/Ashby active listings and public Comeet career-page position
JSON plus public Mobileye career cards. Comeet includes Samsung algorithm/student roles and
robotics/algorithm boards at Mentee, ForSight, Exodigo, AITAN and Maytronics. Search is
supplementary: only recognized employer/ATS job URLs with structured posting data are accepted;
ads, articles and generic career indexes cannot become recommendations. Active employer-listed
postings remain eligible even when originally published more than 48 hours ago.

Additional direct sources include UVeye, Imagry, XTEND, Percepto, Innoviz and Immunai on Comeet;
Bluevine Israel and Hello Heart on Greenhouse; Wix on SmartRecruiters; and NVIDIA on Workday.
SmartRecruiters paginates listings and retrieves full descriptions/qualifications. Workday
discovers the employer's Israel location facet, searches ML/CV/robotics/algorithm terms, dedupes
results, then validates actual locations on each job detail. It prioritizes student/graduate
roles and retrieves at most 40 details per employer per run (up to 100 search results per query).
These two platforms produce manual leads; they do not add unsupported automatic submissions.
Employer boards with no current matching jobs remain monitored for future openings.

Auto-apply requires at least 7/10, with domain overlap for mid/senior roles. Manual leads
require 5.5/10. Binding non-experience constraints block recommendations and applications. The profile
distinguishes professional ML experience from general engineering experience and an in-progress
M.Sc. from a completed degree. Applications are attempted in descending score order.
The candidate explicitly wants to try roles requiring more experience: years and seniority do
not block applying or reduce fit scores by themselves. Experience gaps appear in the report,
while application answers retain the documented actual tenure. Degree and graduation constraints
are checked separately. Older scoring decisions are reconsidered once after the policy upgrade, while historical
submissions and uncertain attempts stay protected against reapplication.

Scoring retries temporary model errors, then uses `GEMINI_FALLBACK_MODEL` (default
`gemini-3.5-flash-lite`) if the primary model is unavailable, quota-limited or retired. Set this
variable to an empty string to disable fallback. If both models fail, jobs remain unscored and
are never promoted to recommendations or applications.

`ready_to_apply` is distinct from `applied`: only a visible employer receipt confirms submission.
Failed/unconfirmed submissions and unscored jobs have separate report sections. Unscored jobs can
be retried on later runs; uncertain submissions are retained to prevent duplicates. State includes
location, rationale, red flags and application errors. State is saved around each attempt and
committed in CI even after a run failure. Existing historic `applied` entries are preserved and
should not be treated as independently verified employer receipts.

`--dry-run` and `--no-apply` never submit or write seen-state. Add `--no-email` for a rehearsal
that also sends no report. Live forms and employer receipt selectors still require validation
against each supported ATS; unfamiliar forms bail to manual review.

## Setup

```bash
pip install -r requirements.txt
playwright install --with-deps chromium
cp .env.example .env   # fill in secrets
```

Required files before the first run:

- `assets/Adar_Rubin_CV.pdf` — required; every ATS form mandates a resume upload.
- `profile/candidate.yaml` — your background, filled in for the LLM.
- `profile/answers.yaml` — canned answers for application form questions (`TODO:` markers must be
  filled in before auto-apply is enabled).
- `profile/ats_boards.yaml` — Greenhouse/Lever/Ashby board tokens to fetch from.

## Running

```bash
python -m job_agent.main --dry-run          # read-only rehearsal, no applications, no email suppressed
python -m job_agent.main --dry-run --no-email
python -m job_agent.main --max-apply 1      # apply to at most 1 job, for a real end-to-end test
python -m job_agent.main                    # full run: up to 5-7 auto-applications, email sent
```

## Secrets (local `.env` / GitHub Secrets)

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Gemini 2.5 Flash scoring |
| `GMAIL_USER` | SMTP sender address |
| `GMAIL_APP_PASSWORD` | 16-character Gmail App Password (not your normal password) |
| `GMAIL_RECEIVER` | Where the HTML report is sent |
| `RESUME_PDF_BASE64` (GitHub Secret only) | Base64-encoded `Adar_Rubin_CV.pdf`, restored to `assets/Adar_Rubin_CV.pdf` on each CI run. Not read from `.env` locally -- just put the real file at `assets/Adar_Rubin_CV.pdf` for local runs. Encode with `base64 -w0 Adar_Rubin_CV.pdf` (Linux/macOS) or `[Convert]::ToBase64String([IO.File]::ReadAllBytes("Adar_Rubin_CV.pdf"))` (PowerShell). |

LinkedIn is out of scope for this project — no LinkedIn credentials or cookies are used.

## Tests

```bash
pytest tests/
```
