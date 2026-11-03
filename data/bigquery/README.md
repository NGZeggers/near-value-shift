# Optional BigQuery extracts

`make bq` checks `q0_freshness.sql` first and stops before L1/L2 if the last indexed block is absent or older than `BQ_MAX_STALENESS_DAYS` (default 7). Every query is dry-run gated by `BQ_MAX_GB_PER_QUERY` and server-side `maximum_bytes_billed`; an additional `BQ_MAX_GB_PER_RUN` limits one invocation. These are not a monthly quota ledger.

| Extract | Consumer |
|---|---|
| `q0_freshness.csv` | runner freshness gate; metadata records the actual extraction cutoff |
| `l1_account_month_features.csv`, `l1_account_month_actions.csv` | `near_thesis/qaa.py` |
| `l2_intents_events.csv` | `near_thesis/intents.py` |
| `q1_daily_txns_signers.csv`, `q2_top_contracts_daily.csv`, `q3_intents_contract_daily.csv` | optional manual cross-check tables; not currently merged into the generated dashboard |

The committed project uses block extracts; no live Google query or Google schema validation is claimed. Dataset filters are explicit in `sql/`. If the dataset is stale, use the block-sample path or deliberately change the analysis window after inspecting coverage. Do not silently mix partial exports.
