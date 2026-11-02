"""BigQuery runner with a dry-run cost gate.

`make bq` runs every sql/*.sql (or the ones given), first as a dry run. A query that would scan more
than BQ_MAX_GB_PER_QUERY is refused. Results are written to data/bigquery/<name>.csv and committed, so
the rest of the pipeline never needs Google credentials. Requires `uv sync --extra bq` and
GOOGLE_CLOUD_PROJECT in .env (see docs/SETUP_BIGQUERY.md).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import BQ_DIR, BQ_MAX_GB_PER_QUERY, GOOGLE_CLOUD_PROJECT, SQL_DIR


def _client():
    try:
        from google.cloud import bigquery  # type: ignore
    except ImportError:
        sys.exit("google-cloud-bigquery not installed. Run: uv sync --extra bq")
    if not GOOGLE_CLOUD_PROJECT:
        sys.exit("GOOGLE_CLOUD_PROJECT is not set in .env (see docs/SETUP_BIGQUERY.md)")
    return bigquery, bigquery.Client(project=GOOGLE_CLOUD_PROJECT)


def dry_run(sql_file: Path) -> float:
    bigquery, client = _client()
    job = client.query(sql_file.read_text(), job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
    return job.total_bytes_processed / 1e9


def run_query(sql_file: Path, *, force: bool = False) -> Path | None:
    bigquery, client = _client()
    gb = dry_run(sql_file)
    print(f"{sql_file.name}: dry run = {gb:,.1f} GB")
    if gb > BQ_MAX_GB_PER_QUERY and not force:
        print(f"  refused: above BQ_MAX_GB_PER_QUERY={BQ_MAX_GB_PER_QUERY} GB. Narrow the date window or sample days.")
        return None
    job = client.query(sql_file.read_text())
    df = job.result().to_dataframe()
    out = BQ_DIR / f"{sql_file.stem}.csv"
    df.to_csv(out, index=False)
    meta = {"sql": sql_file.name, "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "bytes_processed": job.total_bytes_processed, "rows": int(len(df)), "job_id": job.job_id}
    (BQ_DIR / f"{sql_file.stem}.meta.json").write_text(json.dumps(meta, indent=1))
    print(f"  saved {out.name}: {len(df):,} rows, {job.total_bytes_processed / 1e9:,.1f} GB billed")
    return out


def run(names: list[str] | None = None, *, dry: bool = False, force: bool = False) -> None:
    files = sorted(SQL_DIR.glob("*.sql"))
    if names:
        files = [f for f in files if f.stem in names or f.name in names]
    for f in files:
        if dry:
            print(f"{f.name}: dry run = {dry_run(f):,.1f} GB")
        else:
            run_query(f, force=force)
