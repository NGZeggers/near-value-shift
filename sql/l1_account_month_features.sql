-- L1. Per account-month behavioral features for clustering (Quality-Adjusted Active Accounts).
-- One row per (month, signer). Aggregated output keeps the result small (~ millions of rows max).
-- Parameters: edit the date window below. Always filtered on block_date.
WITH tx AS (
  SELECT
    DATE_TRUNC(block_date, MONTH)                      AS month,
    block_date,
    signer_account_id                                  AS account,
    receiver_account_id                                AS receiver,
    block_timestamp
  FROM `bigquery-public-data.crypto_near_mainnet_us.transactions`
  WHERE block_date BETWEEN '2023-01-01' AND '2026-10-31'
),
gaps AS (
  SELECT
    month, account,
    TIMESTAMP_DIFF(block_timestamp,
      LAG(block_timestamp) OVER (PARTITION BY month, account ORDER BY block_timestamp), SECOND) AS gap_s
  FROM tx
),
gap_stats AS (
  SELECT month, account,
    APPROX_QUANTILES(gap_s, 100)[OFFSET(50)] AS gap_median_s,
    STDDEV(gap_s) / NULLIF(AVG(gap_s), 0)    AS gap_cv
  FROM gaps WHERE gap_s IS NOT NULL
  GROUP BY month, account
),
base AS (
  SELECT
    month, account,
    COUNT(*)                                   AS txns,
    COUNT(DISTINCT block_date)                 AS active_days,
    COUNT(DISTINCT receiver)                   AS distinct_receivers,
    COUNTIF(receiver = account)                AS self_txns,
    MIN(block_timestamp)                       AS first_ts,
    MAX(block_timestamp)                       AS last_ts
  FROM tx
  GROUP BY month, account
)
SELECT
  b.month, b.account, b.txns, b.active_days, b.distinct_receivers, b.self_txns,
  g.gap_median_s, g.gap_cv,
  CASE
    WHEN ENDS_WITH(b.account, '.tg')    THEN 'tg'
    WHEN ENDS_WITH(b.account, '.sweat') THEN 'sweat'
    WHEN REGEXP_CONTAINS(b.account, r'^[0-9a-f]{64}$') THEN 'implicit'
    WHEN ENDS_WITH(b.account, '.near')  THEN 'named'
    ELSE 'other' END                           AS name_class
FROM base b
LEFT JOIN gap_stats g USING (month, account)
ORDER BY b.month, b.txns DESC;
