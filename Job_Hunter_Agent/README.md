# Job Hunter & Auto-Apply Agent

Twice-daily agent that discovers fresh ML / AI / Robotics / Computer-Vision job postings on
Greenhouse, Lever, and Ashby, scores each one against your profile with Gemini 2.5 Flash, auto-applies
to a capped number of simple applications, and emails one HTML report per run.

See the architecture plan for full design rationale.

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
