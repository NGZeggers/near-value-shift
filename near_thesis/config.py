from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
RAW = DATA / "raw"
BQ_DIR = DATA / "bigquery"
DERIVED = DATA / "derived"
MODELS = DERIVED / "models"
SQL_DIR = ROOT / "sql"
SITE = ROOT / "site"
DOCS = ROOT / "docs"

for d in (RAW, BQ_DIR, DERIVED, MODELS, SITE):
    d.mkdir(parents=True, exist_ok=True)

GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT") or None
BQ_MAX_GB_PER_QUERY = float(os.getenv("BQ_MAX_GB_PER_QUERY", "120"))
INTENTS_EXPLORER_JWT = os.getenv("INTENTS_EXPLORER_JWT") or None

# Analysis window shared by every layer. Changing it here changes every table and chart.
START_DATE = "2021-01-01"
INTENTS_START = "2024-11-04"   # intents.near deployed 2024-11-01; first DefiLlama volume 2024-12

# Development-history repository. The hackathon submission continues from commit 5f6a144 in
# https://github.com/Alberto-Campos-de-la-Torre/near-settlement-thesis (one project, one submission).
# REPO_URL stays as is: it feeds generated links that must keep matching the committed artifacts.
REPO_URL = "https://github.com/NGZeggers/near-value-shift"
