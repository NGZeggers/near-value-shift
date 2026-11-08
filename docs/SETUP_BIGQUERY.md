# BigQuery setup (free sandbox, no credit card)

The NEAR public dataset lives at `bigquery-public-data.crypto_near_mainnet_us`. NEAR pays storage;
you pay query processing. The BigQuery sandbox gives 1 TiB of query processing per month for free.

## 1. Create a sandbox project (5 minutes, browser)
1. Open https://console.cloud.google.com/bigquery and sign in with a Google account.
2. Accept the terms. Click **Create project**, name it e.g. `near-thesis`, no organization.
3. Note the **project ID** shown (it can differ from the name, e.g. `near-thesis-478213`).

## 2. Install the CLI (macOS)
```bash
brew install --cask google-cloud-sdk
gcloud init                       # pick the project you just created
gcloud auth application-default login
```

## 3. Smoke test and freshness check
```bash
bq query --use_legacy_sql=false --dry_run < sql/q0_freshness.sql    # shows bytes to be processed, costs nothing
bq query --use_legacy_sql=false --format=csv < sql/q0_freshness.sql
```
Expected: `last_block_date` within the last day or two (checked on 2026-11-08: current to the day; the "last modified" date shown in the
console is table metadata, not the last row). If it is months old, tell Claude the date and THESIS.md will state it.

## 4. Put the project ID in `.env`
```
GOOGLE_CLOUD_PROJECT=near-thesis-478213
BQ_MAX_GB_PER_QUERY=120
```
`make bq` dry-runs every SQL file first and refuses any query above `BQ_MAX_GB_PER_QUERY`.
Results are cached in `data/bigquery/*.csv` and committed, so judges never need Google credentials.

## Budget rule of thumb
Sandbox: 1 TiB/month. Filter on `block_date` always. Prefer aggregated outputs (per account-month,
per day) over row dumps. Check the dry-run estimate before every new query.

## Runner safeguards

The current runner always executes Q0 before L1/L2, including when selecting a subset of extract names. A null last date or data older than `BQ_MAX_STALENESS_DAYS` (7 by default) stops the run. It does not silently reuse stale output as current coverage.

`BQ_MAX_GB_PER_QUERY` is enforced both with a dry-run and server-side `maximum_bytes_billed`. `BQ_MAX_GB_PER_RUN` (default 300) stops additional queries once one invocation would exceed that ceiling. Neither setting tracks your accumulated monthly Google usage. Check that quota in Google Cloud before optional extraction.

The runner uses one estimate per query, enforces `maximum_bytes_billed` against the smaller of the query ceiling and the remaining run budget, and accounts for actual billed/processed bytes before continuing. `--force` overrides only the per-query estimate gate; it cannot remove the per-run budget. Missing/invalid usage metadata stops the run. The optional L2 SQL exports `execution_status` and filters explicit successful outcomes; validate the actual Google schema with a dry-run before paid execution. A changed/missing schema is an error, never an implicit success.

## What was actually run (2026-11-08) and what it cost

The public dataset lives in region `us-east1`; helper tables must be created in the same region (`data/bigquery/helpers/README.md`).
Every query was dry-run first; the runner passes `maximum_bytes_billed` to Google so nothing can exceed the declared caps.

| SQL | Output | Scan |
| --- | --- | --- |
| `q0_freshness.sql` | last block date | 0.4 GB |
| per-account L1 (first attempt, 46M rows) | not downloaded; aggregated server-side from its result table into `l1_full_month_summary.csv` | 148 GB + 4 GB |
| `l1_full_month_summary_2.sql` | `l1_full_month_summary_2.csv` (2026-02 .. 2026-10) | 20 GB |
| `l2_full_days_valued.sql` | `l2_full_days_valued.csv` (32 sample days, one row per day) | 186 GB |
| `l2_full_days_valued_2.sql` | `l2_full_days_valued_2.csv` (17 sample days) | 34 GB |
| `l2_valuation_check_day.sql` | `l2_valuation_check_day.csv` (2025-11-14, per execution block) | 6 GB |
| `l1_full_month_summary.sql` (finer classes, re-aggregated from the result table) | `l1_full_month_summary.csv` | 4 GB |
| `l3_buyback_attribution.sql` | `l3_buyback_attribution.csv` (3,197 withdrawals, one pass) | 287 GB |
| `l3_buyback_wnear_origin.sql` | `l3_buyback_wnear_origin.csv` (how the wrap.near reached each account) | 287 GB |
| materialization attempt of the buyback logs | failed on the sandbox storage quota, no charge | counted by Google as 0 |

Month total: 1,006 GB billed over 17 queries, 0.92 TiB of the 1 TiB free tier (`data/bigquery/usage_2026-11-08.json`). The project is a sandbox
without a billing account, so nothing can be charged; queries fail once the free tier is used.

Lesson: aggregate inside BigQuery. A per-account or per-log result is tens of millions of rows; downloading it through the REST API takes
hours and the CSV cannot be committed. The valued queries return one row per day and are cross-checked against the Python valuation of the
committed sample windows (`reconcile.complete_days["sql_valuation_check"]`).
