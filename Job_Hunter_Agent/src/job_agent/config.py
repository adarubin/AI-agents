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
GEMINI_BATCH_SIZE = 8
GEMINI_MODEL = "gemini-3.6-flash"  # gemini-2.5-flash was requested but is no longer available to
# new API keys as of this build (the API itself returns 404 and points to this replacement) --
# verified live against the configured GEMINI_API_KEY.

MIN_SCORE_TO_APPLY = 7.0
MIN_SCORE_TO_REPORT = 7.0
SENIOR_APPLY_THRESHOLD = 8.5

APPLY_CAP_RANGE = (5, 7)  # randomized per-run cap on total auto-applications
DORK_QUERY_BUDGET = 12  # max search queries per run

LOCATIONS = ["Israel", "Remote"]  # remote roles restricted to other countries are penalized in scoring

ROLE_FAMILIES = [
    "Data Science",
    "AI Engineer",
    "Applied ML Engineer",
    "Machine Learning Engineer",
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
