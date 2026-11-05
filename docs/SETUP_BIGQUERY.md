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
Expected: `last_block_date` within the last day or two. If it is months old, the dataset is stale
(NEAR Lake was deprecated on 2026-03-24); tell Claude the date and THESIS.md will state it.

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
