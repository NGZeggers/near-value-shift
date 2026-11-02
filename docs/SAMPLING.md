# Sampling design for the on-chain layers without BigQuery

When `data/bigquery/*.csv` are absent, L1 and L2 run on a stratified sample of full blocks read from FastNear's
public block API (`https://mainnet.neardata.xyz/v0/block/{height}`, no key, rate-limited to 2.5 requests/s by us).

## Frame and strata
- Population: every block from 2024-11-04 (INTENTS_START) to yesterday.
- Strata: one day every 15 days (deterministic from INTENTS_START), two fixed UTC windows per day (03:00 and 15:00),
  250 consecutive blocks per window (about 2.5 minutes of chain each). The plan is saved in `data/blocks/sample_plan.json`.
- Window starts are located by a secant search on block timestamps (tolerance 90 s), see `near_thesis/blocks.py`.

## Estimators
- **L2 daily totals** (batches, priced volume, withdrawals): sampled count x (blocks in the day / blocks sampled).
  Blocks per day come from NearBlocks (`data/derived/daily.csv`, column `blocks`). Monthly totals are the mean of
  the sampled days' expanded values x days in month; the 95% interval is a bootstrap over sampled days.
- **Unique users per day**: the same expansion is an upper bound (a user active in two windows is counted twice).
- **Solver concentration** (HHI, top-1 share): computed inside the sample; solvers are accounts in >= 2% of a day's
  sampled batches with >= 5 counterparties (>= 20 batches and >= 10 counterparties in the BigQuery full-day mode).
- **L1 QAA**: account features are computed inside the sampled windows (transactions, receivers, methods, deposits,
  within-window inter-arrival regularity, name class). Clustering gives a human-like share per month; QAA = that
  share x NearBlocks' monthly mean of daily active accounts.

## Known biases, stated in THESIS.md
- Time-of-day: two fixed hours per day; activity with a strong intraday pattern is over- or under-weighted.
- Short windows under-count low-frequency accounts (a human with one transaction a week is rarely in a 2.5-minute window),
  so the sampled human-like share is biased downward; QAA in sampled mode is conservative.
- Priced volume covers only legs in stablecoins, NEAR, BTC or ETH; the share of priced batches is reported.
- The BigQuery path (`make bq`) removes all three biases; THESIS.md names which path produced each number.
