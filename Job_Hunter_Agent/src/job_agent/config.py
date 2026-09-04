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

FRESHNESS_HOURS = 48
MAX_JOBS_PER_RUN = 120
GEMINI_BATCH_SIZE = 20  # fewer, larger batches -- the free tier caps *requests*/day, not tokens/request
# gemini-2.5-flash / gemini-2.0-flash both 404 for this API key (Google redirects new keys to
# gemini-3.6-flash) -- verified live. Configurable via GEMINI_MODEL so a future account with access
# to a higher-quota model doesn't require a code change, but the default must stay a model that
# actually works.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

MIN_SCORE_TO_APPLY = 6.0
MIN_SCORE_TO_REPORT = 6.0
SENIOR_APPLY_THRESHOLD = 8.5

APPLY_CAP_RANGE = (5, 7)  # randomized per-run cap on total auto-applications
DORK_QUERY_BUDGET = 12  # max search queries per run

# Remote roles restricted to a country other than Israel are penalized in scoring (see evaluator).
LOCATIONS = ["Israel", "Netanya", "Tel Aviv", "Center District", "Remote", "Remote EMEA"]

ROLE_FAMILIES = [
    "Data Science",
    "AI Engineer",
    "Applied ML Engineer",
    "Machine Learning Engineer",
    "Data Engineer",
    "MLOps",
    "AI Researcher",
    "Robotics Engineer",
    "Physical AI",
    "Drone",
    "UAV",
    "Computer Vision",
    "Deep Learning Engineer",
    "Deep Learning Researcher",
    "ML Researcher",
    "Algorithms Engineer",
    "Perception Engineer",
    "Autonomy Software",
    "Controls Engineer",
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
    )
