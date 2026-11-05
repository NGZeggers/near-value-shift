"""BigQuery runner with a dry-run cost gate.

`make bq` runs every sql/*.sql (or the ones given), first as a dry run. A query that would scan more
than BQ_MAX_GB_PER_QUERY is refused. Results are written to data/bigquery/<name>.csv and committed, so
the rest of the pipeline never needs Google credentials. Requires `uv sync --extra bq` and
GOOGLE_CLOUD_PROJECT in .env (see docs/SETUP_BIGQUERY.md).
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
import os
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


def run_query(sql_file: Path, *, force: bool = False, estimated_gb: float | None = None,
              remaining_bytes: int | None = None) -> Path | None:
    bigquery, client = _client()
    gb = dry_run(sql_file) if estimated_gb is None else estimated_gb
    print(f"{sql_file.name}: dry run = {gb:,.1f} GB")
    if gb > BQ_MAX_GB_PER_QUERY and not force:
        print(f"  refused: above BQ_MAX_GB_PER_QUERY={BQ_MAX_GB_PER_QUERY} GB. Narrow the date window or sample days.")
        return None
    # Enforce the byte ceiling server-side too, in case the estimate changes before execution.
    limit = None if force else int(BQ_MAX_GB_PER_QUERY * 1e9)
    if remaining_bytes is not None:
        limit = remaining_bytes if limit is None else min(limit, remaining_bytes)
    if limit is not None and (limit <= 0 or gb * 1e9 > limit):
        raise SystemExit(f"query exceeds remaining byte ceiling: {sql_file.name}")
    job = client.query(sql_file.read_text(), job_config=bigquery.QueryJobConfig(maximum_bytes_billed=limit))
    df = job.result().to_dataframe()
    processed = int(job.total_bytes_processed)
    billed = getattr(job, "total_bytes_billed", None)
    charged = max(processed, int(billed) if billed is not None else processed)
    if charged < 0 or (limit is not None and charged > limit):
        raise SystemExit(f"job reported usage outside its server-side ceiling: {sql_file.name}")
    out = BQ_DIR / f"{sql_file.stem}.csv"
    df.to_csv(out, index=False)
    meta = {"sql": sql_file.name, "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "bytes_processed": processed, "bytes_billed": billed, "accounted_bytes": charged,
            "maximum_bytes_billed": limit, "rows": int(len(df)), "job_id": job.job_id}
    (BQ_DIR / f"{sql_file.stem}.meta.json").write_text(json.dumps(meta, indent=1))
    print(f"  saved {out.name}: {len(df):,} rows, {processed / 1e9:,.1f} GB processed, {charged / 1e9:,.1f} GB accounted")
    return out


def run(names: list[str] | None = None, *, dry: bool = False, force: bool = False) -> None:
    files = sorted(SQL_DIR.glob("*.sql"))
    if names:
        files = [f for f in files if f.stem in names or f.name in names]
    freshness = SQL_DIR / "q0_freshness.sql"
    files = [freshness] + [f for f in files if f != freshness]
    total_gb = 0.0
    max_run = float(os.getenv("BQ_MAX_GB_PER_RUN", "300"))
    if not math.isfinite(max_run) or max_run <= 0 or not math.isfinite(BQ_MAX_GB_PER_QUERY) or BQ_MAX_GB_PER_QUERY <= 0:
        raise SystemExit("BigQuery budgets must be positive and finite")
    used_bytes = 0
    for f in files:
        if dry:
            gb = dry_run(f)
            total_gb += gb
            print(f"{f.name}: dry run = {gb:,.1f} GB (run total {total_gb:,.1f} GB)")
        else:
            gb = dry_run(f)
            remaining = int(max_run * 1e9) - used_bytes
            if not math.isfinite(gb) or gb < 0 or gb * 1e9 > remaining or remaining <= 0:
                raise SystemExit(f"run budget would exceed BQ_MAX_GB_PER_RUN={max_run}; no further queries executed")
            output = run_query(f, force=force, estimated_gb=gb, remaining_bytes=remaining)
            if output is None:
                raise SystemExit(f"query refused: {f.name}; stopping instead of mixing incomplete extracts")
            if f == freshness:
                import pandas as pd
                frame = pd.read_csv(output)
                last = pd.to_datetime(frame["last_block_date"], errors="coerce").max()
                max_lag = int(os.getenv("BQ_MAX_STALENESS_DAYS", "7"))
                if pd.isna(last) or (datetime.now(timezone.utc).date() - last.date()).days > max_lag:
                    raise SystemExit(f"BigQuery is stale (last block: {last}); L1/L2 not executed. Use make blocks or narrow the analysis explicitly.")
            # Charge actual billed/processed bytes, never the stale dry-run estimate.
            try:
                meta = json.loads(output.with_suffix('.meta.json').read_text())
            except (OSError, ValueError) as exc:
                raise SystemExit(f"missing byte accounting for {f.name}; stopping") from exc
            accounted = meta.get('accounted_bytes', meta.get('bytes_processed'))
            if isinstance(accounted, bool) or not isinstance(accounted, int) or accounted < 0:
                raise SystemExit(f"invalid byte accounting for {f.name}; stopping")
            used_bytes += accounted
            if used_bytes > int(max_run * 1e9):
                raise SystemExit("reported BigQuery usage exceeded the server-side ceiling; stopping")
