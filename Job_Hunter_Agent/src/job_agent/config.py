"""Environment, tunables, and profile/board-list loading. Fails fast on missing secrets."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

# python-dotenv is a no-op in CI where .env does not exist; GitHub Secrets populate
# os.environ directly.
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = PROJECT_ROOT / "profile"
DATA_DIR = PROJECT_ROOT / "data"
ASSETS_DIR = PROJECT_ROOT / "assets"

REQUIRED_ENV_VARS = [
    "GEMINI_API_KEY",
    "GMAIL_USER",
    "GMAIL_APP_PASSWORD",
    "GMAIL_RECEIVER",
]

# --- Tunables -----------------------------------------------------------

FRESHNESS_HOURS = 24 * 30  # active postings are useful beyond their first two days
MAX_JOBS_PER_RUN = 120
GEMINI_BATCH_SIZE = 20  # fewer, larger batches -- the free tier caps *requests*/day, not tokens/request
# Configurable without a source change. API overload/quota failures remain unscored.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_FALLBACK_MODEL = os.environ.get('GEMINI_FALLBACK_MODEL', 'gemini-3.5-flash-lite')

MIN_SCORE_TO_APPLY = 7.0
MIN_SCORE_TO_REPORT = 5.5
SENIOR_APPLY_THRESHOLD = 7.0  # strong domain overlap matters more than years/seniority

APPLY_CAP_RANGE = (5, 7)  # randomized per-run cap on total auto-applications
DORK_QUERY_BUDGET = 12  # max search queries per run

# Remote eligibility must explicitly include Israel; EMEA alone is insufficient.
LOCATIONS = ["Israel", "Netanya", "Tel Aviv", "Herzliya", "Haifa", "Jerusalem"]

# Strictly the five focus families the candidate is targeting -- generic titles like plain
# "Software Engineer" or "Data Science" are intentionally excluded (see evaluator scoring prompt).
ROLE_FAMILIES = [
    "Applied AI Researcher",
    "Physical AI",
    "Robotics Algorithms",
    "Computer Vision",
    "Deep Learning Engineer",
]

# Career pages tracked directly by name, even though none of them expose the Greenhouse/Lever/Ashby
# JSON APIs the primary source relies on (verified live: all 404). These feed the dorking source's
# targeted-company query and are manual-lead only, same as every other dorked result -- there is no
# reliable free JSON API for Workday (Nvidia, Microsoft) or Mobileye/AI21 Labs' own career sites.
TARGETED_COMPANY_SITES = [
    "careers.mobileye.com",
    "ai21.com/careers",
    "nvidia.com/en-us/about-nvidia/careers",
    "careers.microsoft.com",
]

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


@dataclass
class Config:
    gemini_api_key: str
    gmail_user: str
    gmail_app_password: str
    gmail_receiver: str
    candidate_profile: dict
    answers: dict
    ats_boards: dict
    resume_content: dict


def _fail(message: str) -> None:
    print(f"[config] FATAL: {message}", file=sys.stderr)
    sys.exit(1)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        _fail(f"missing required environment variable: {name}")
    return value  # type: ignore[return-value]


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        _fail(f"missing required profile file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_yaml_optional(path: Path) -> dict:
    """Like _load_yaml, but a missing file just means the feature it backs is unavailable --
    not a reason to crash the whole run (resume_content.yaml is gitignored and may not exist,
    e.g. locally without the RESUME_CONTENT_YAML secret restored)."""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load() -> Config:
    """Validate all secrets and load profile files. Exits the process on failure."""
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        _fail(f"missing required environment variable(s): {', '.join(missing)}")

    return Config(
        gemini_api_key=_require_env("GEMINI_API_KEY"),
        gmail_user=_require_env("GMAIL_USER"),
        gmail_app_password=_require_env("GMAIL_APP_PASSWORD"),
        gmail_receiver=_require_env("GMAIL_RECEIVER"),
        candidate_profile=_load_yaml(PROFILE_DIR / "candidate.yaml"),
        answers=_load_yaml(PROFILE_DIR / "answers.yaml"),
        ats_boards=_load_yaml(PROFILE_DIR / "ats_boards.yaml"),
        resume_content=_load_yaml_optional(PROFILE_DIR / "resume_content.yaml"),
    )
