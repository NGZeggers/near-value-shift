# BigQuery extracts

`make bq` writes one CSV plus a `.meta.json` (run time, rows, bytes billed, job id) per file in `sql/`.
These files are committed so the rest of the pipeline is fully offline. Expected files:

| File | Produced by | Used by |
|---|---|---|
| `q0_freshness.csv` | sql/q0_freshness.sql | THESIS.md data-gaps section |
| `q1_daily_txns_signers.csv` | sql/q1_daily_txns_signers.sql | cross-check of NearBlocks active accounts |
| `q2_top_contracts_daily.csv` | sql/q2_top_contracts_daily.sql | contract-usage chart |
| `q3_intents_contract_daily.csv` | sql/q3_intents_contract_daily.sql | intents.near method mix |
| `l1_account_month_features.csv`, `l1_account_month_actions.csv` | sql/l1_*.sql | near_thesis/qaa.py (L1) |
| `l2_intents_events.csv` | sql/l2_intents_events.sql | near_thesis/intents.py (L2) |
