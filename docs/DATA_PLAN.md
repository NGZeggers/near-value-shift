# Data plan (track checkpoint)

Status: DRAFT, awaiting human approval before any code is built (required by the `thesis` track prompt).
Date: 2026-11-01

## Working hypothesis

NEAR's economic activity is shifting from high-count, low-value retail transactions
(the 2024 mini-app / wallet-farming era, ~1.3M daily active accounts) to lower-count,
higher-value cross-chain settlement through NEAR Intents. Headline activity metrics
(transactions, active accounts, new accounts) therefore understate the network's traction,
while value-weighted metrics (settled USD volume, fee revenue in USD, Intents swap volume)
show growth that is decoupled from the token price.

Falsifiable predictions:
1. Intents volume and USD fee revenue rise while active accounts fall (2025 -> 2026).
2. Correlation between daily active accounts and NEAR price is positive in 2021-2024 and weak/negative in 2025-2026.
3. Unique callers of `intents.near` grow alongside volume (otherwise volume is a few market makers = weak evidence).

Quick numbers from the probe (2026-11-01), to be recomputed by the pipeline:

| metric | 2024 avg/day | 2025 avg/day | 2026 avg/day |
|---|---|---|---|
| transactions | 6.59M | 5.34M | 1.58M |
| active accounts | 1.33M | 421K | 125K |
| new accounts | 342K | 277K | 52K |
| tx fees (USD) | 23.2K | 10.1K | 2.8K |

| NEAR Intents monthly volume (DefiLlama) | USD |
|---|---|
| 2024-12 | 3M |
| 2025-06 | 184M |
| 2025-11 | 3.66B |
| 2026-09 | 4.80B |
| 2026-10 | 3.99B |

Last 90 days vs previous 90 days: active accounts -33%, new accounts -29%, transactions -6%,
tx volume USD +159%, fee USD +128%.

## Data sources

| # | Source | What we take | Auth | Reproducible by a judge? |
|---|---|---|---|---|
| S1 | NearBlocks `GET https://api.nearblocks.io/v1/charts` | daily series 2020-07 -> today: txns, active_accounts, new_accounts, new_contracts, active_contracts, gas_used, txn_fee_usd, txn_volume_usd, near_price, market_cap | none | yes, 1 call |
| S2 | DefiLlama `summary/dexs/near-intents` | daily NEAR Intents swap volume USD since 2024-12 (DefiLlama computes it from Dune `dune.near.dataset_near_intents_metrics`) | none | yes |
| S3 | DefiLlama `overview/dexs/near`, `v2/historicalChainTvl/Near`, `overview/fees/near`, `stablecoins.llama.fi/stablecoincharts/Near`, `v2/chains` | NEAR DEX volume by protocol, chain TVL history, daily fees, stablecoin supply, peer-chain TVL | none | yes |
| S4 | NEAR RPC `validators` + `status` | validator count, total stake (security budget), latest block | none | yes |
| S5 | NEAR BigQuery public dataset `bigquery-public-data.crypto_near_mainnet_us` | independent recomputation of daily active signers, tx counts, top contracts, `intents.near` calls and unique callers | Google account (BigQuery sandbox, no credit card, 1 TiB/month free) | optional; SQL + exported CSV committed so the build works without it |
| S6 | NEAR Intents Explorer API `explorer.near-intents.org/api/v0/transactions` | 1Click swap records (per-swap USD, chains) | JWT from partners.near-intents.org | optional; if we do not get a JWT, THESIS.md says so and S2+S5 cover volume |
| S7 | GitHub REST (`near` org) | monthly commits to nearcore and core repos (developer activity) | none for low volume | yes |

Rule: no number appears in THESIS.md or the dashboard that is not produced by the pipeline from these sources.
If a metric cannot be computed, THESIS.md says "not computed" with the reason.

## BigQuery tables planned

- `transactions` (partition `block_date`): `signer_account_id`, `receiver_account_id`, `transaction_hash`
- `receipt_actions` (partition `block_date`): `action_kind`, `receipt_receiver_account_id`, `receipt_predecessor_account_id`
- `receipt_origin` (partition `block_date`): link receipts to originating transaction (only if needed for signer attribution)

### Q1. Daily transactions and active signers

```sql
SELECT
  block_date,
  COUNT(*)                           AS txns,
  COUNT(DISTINCT signer_account_id)  AS active_signers
FROM `bigquery-public-data.crypto_near_mainnet_us.transactions`
WHERE block_date BETWEEN '2024-01-01' AND '2026-11-14'
GROUP BY block_date
ORDER BY block_date;
```

### Q2. Daily contract usage (top 20 contracts per day by calls)

```sql
SELECT block_date, contract, calls, callers
FROM (
  SELECT
    block_date,
    receipt_receiver_account_id                    AS contract,
    COUNT(*)                                       AS calls,
    COUNT(DISTINCT receipt_predecessor_account_id) AS callers,
    ROW_NUMBER() OVER (PARTITION BY block_date ORDER BY COUNT(*) DESC) AS rn
  FROM `bigquery-public-data.crypto_near_mainnet_us.receipt_actions`
  WHERE block_date BETWEEN '2024-01-01' AND '2026-11-14'
    AND action_kind = 'FUNCTION_CALL'
  GROUP BY block_date, contract
)
WHERE rn <= 20
ORDER BY block_date, calls DESC;
```

### Q3. NEAR Intents contract: daily calls and unique callers (independent cross-check of S2)

```sql
SELECT
  block_date,
  COUNT(*)                                       AS intents_calls,
  COUNT(DISTINCT receipt_predecessor_account_id) AS unique_callers
FROM `bigquery-public-data.crypto_near_mainnet_us.receipt_actions`
WHERE block_date BETWEEN '2024-11-01' AND '2026-11-14'
  AND receipt_receiver_account_id = 'intents.near'
  AND action_kind = 'FUNCTION_CALL'
GROUP BY block_date
ORDER BY block_date;
```

### Q4. "Organic" active accounts (exclude accounts with > 200 txns/day as likely bots/relayers)

```sql
WITH per_signer AS (
  SELECT block_date, signer_account_id, COUNT(*) AS n
  FROM `bigquery-public-data.crypto_near_mainnet_us.transactions`
  WHERE block_date BETWEEN '2024-01-01' AND '2026-11-14'
  GROUP BY block_date, signer_account_id
)
SELECT
  block_date,
  COUNTIF(n <= 200) AS organic_signers,
  COUNTIF(n >  200) AS heavy_signers,
  SUM(IF(n > 200, n, 0)) / SUM(n) AS share_of_txns_from_heavy_signers
FROM per_signer
GROUP BY block_date
ORDER BY block_date;
```

Open question to verify on first run: whether the dataset is still ingesting (NEAR Lake was deprecated 2026-03-24;
the docs say the BigQuery copy remains available but do not state freshness). `SELECT MAX(block_date)` first.

## Pipeline design

- Node 20+ / TypeScript, no database. `npm run build` = fetch (S1-S4, S7) -> cache raw JSON in `data/raw/` -> compute metrics -> write `data/derived/*.csv` -> render `site/index.html` (static, charts + the query/URL behind each chart + one plain sentence).
- `npm run fetch:bq` runs Q1-Q4 with the `bq` CLI when configured; results are committed to `data/bigquery/*.csv` so the build never depends on Google credentials.
- `npm run fetch:intents` runs only if `INTENTS_EXPLORER_JWT` is set in `.env`.
- `THESIS.md`: claim, evidence for, evidence against, what would change our mind, data gaps.
- Hosting: GitHub Pages from `site/` (hosted demo is a plus for judges; local build is the fallback).
