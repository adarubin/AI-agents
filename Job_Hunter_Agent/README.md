# 🕵️‍♂️ Job Hunter & Auto-Apply Agent

## 🎯 Context
Goal: An unattended Python agent, run twice daily (09:00 / 15:00 Israel time) by GitHub Actions, that discovers fresh ML / AI / Robotics / CV / Physical-AI postings. It scores each one semantically with Gemini 2.5 Flash against the candidate profile (B.Sc. Mechanical Engineering, robotics/control specialization) so unconventional titles like "Perception Engineer" or "Autonomy Software" are not missed. It then auto-applies to a capped number of simple applications, and emails a single HTML report per run.

## 🔍 Discovery Strategy & ATS APIs
Instead of relying solely on fragile web scraping, this agent utilizes free, unauthenticated JSON APIs exposed by major ATS platforms:

| Platform | Endpoint | Confirmed fields |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | `id, title, location, absolute_url, updated_at, content, departments, offices` |
| Lever | `api.lever.co/v0/postings/{site}?mode=json` | `id, text, hostedUrl, applyUrl, createdAt, categories, descriptionPlain, workplaceType, salaryRange` |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{name}` | `id, title, location, isRemote, publishedAt, jobUrl, applyUrl, descriptionPlain, employmentType` |

**Discovery split:**
*   **Board discovery (weekly / on-demand):** Dorking with `ddgs` finds URLs, from which the board token is parsed, validated against the API, and cached in `profile/ats_boards.yaml`.
*   **Job fetching (every run):** Iterate the cached board tokens against the three JSON APIs. Fast, structured, rate-limit-free, with real timestamps for the 48-hour freshness filter.
*   **Dorking (supplementary):** Runs every time to catch postings on platforms without a public API. Those go through extraction and are routed to manual-lead only.

## 🏗️ Architecture
```text
main.py
  ├─ config.load()                env + profile + board list, fail fast
  ├─ state.load()                 seen / applied job IDs
  │
  ├─ DISCOVERY  (sources/)
  │    ├─ ats_api.py      cached board tokens → Greenhouse/Lever/Ashby JSON  → [RawJob]   (primary)
  │    ├─ dorking.py      ddgs queries → non-API ATS + career-page URLs      → [RawJob]   (bonus)
  │    └─ extract.py      trafilatura/bs4 cleanup, only for dorked HTML URLs
  │
  ├─ normalize.py                 dedupe by (company, title) + URL, drop >48h old, drop seen
  ├─ evaluator.py                 Gemini 2.5 Flash → score 1-10 + reason      → [Evaluation]
  ├─ router.py                    score + platform → APPLY | MANUAL | DISCARD
  ├─ appliers/                    greenhouse.py · lever.py
  ├─ state.save()
  └─ reporter.send()              HTML email: applied / manual leads / errors
🗂️ Directory Structure(Will be created during implementation)PlaintextJob_Hunter_Agent/
├─ .github/workflows/job_agent.yml
├─ src/job_agent/
│  ├─ config.py          # env vars, tunables, profile + board-list loading
│  ├─ models.py          # RawJob, Evaluation, ApplyAttempt, RunReport
│  ├─ humanize.py        # jittered delays, human typing, per-run cap randomization
│  ├─ sources/           # ats_api.py, dorking.py, extract.py
│  ├─ normalize.py       # dedupe, freshness filter, state filter
│  ├─ evaluator.py       # Gemini structured-output scoring
│  ├─ router.py          # routing rules, one place, unit-testable
│  ├─ appliers/          # greenhouse.py, lever.py
│  ├─ state.py · reporter.py · main.py
├─ scripts/discover_boards.py
├─ profile/              # candidate.yaml, answers.yaml, ats_boards.yaml
├─ assets/resume.pdf     # REQUIRED (ignored in git)
├─ data/applied_jobs.json
├─ tests/
├─ requirements.txt · .env.example · .gitignore · README.md
⚙️ Logic & RulesRouting Rules (router.py)ConditionRouteScore ≥ 7, platform ∈ {greenhouse, lever}, form passes complexity checkAPPLY (auto)Score ≥ 8.5, mid/senior, strong robotics/control overlap, simple ATSAPPLYScore ≥ 7, any other platform / complex form / CAPTCHAMANUAL LEADScore < 7DISCARD (never re-scored)Dependenciesgoogle-genai (Gemini 2.5 Flash)httpx (ATS JSON APIs)ddgs (DuckDuckGo search)trafilatura & beautifulsoup4 (Extraction)playwright (Chromium auto-apply)python-dotenv, PyYAML, tenacity, pytest🚀 Setup Prerequisites (To-Do)Before fully running the agent, the following local files must be prepared (and added to .gitignore to prevent leaking personal data):assets/resume.pdf: Required for all ATS form uploads.profile/answers.yaml: Contains personal details (phone, graduation date, work authorization, etc.)..env: API keys (GEMINI_API_KEY, GMAIL_USER, GMAIL_APP_PASSWORD, GMAIL_RECEIVER).
