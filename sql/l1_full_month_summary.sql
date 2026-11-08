-- L1 full months, aggregated. Name classes: tg, sweat, kaiching (mini-app sub-accounts), implicit, eth_implicit, named, other. Per (month, name class): accounts active in the month, accounts with a single transaction, accounts with at
-- least two distinct receivers, accounts that called intents.near, transactions, mean active days and median transactions per account.
-- Reads every transaction of the month from the NEAR public dataset; the output is a few hundred rows, so it is committed as is.
-- Partition: this file covers 2024-11 .. 2026-01 and l1_full_month_summary_2.sql covers 2026-02 .. 2026-10; the two are disjoint by construction
-- and the loader rejects any (month, name_class) key present in more than one file. Provenance of the committed l1_full_month_summary.csv:
-- it was not produced by this file but by l1_full_month_summary_from_result_table.sql, the aggregation of the per-account result of job
-- 45b1ab3e-56b1-438b-9ec1-87e1eb6149fa (148.2 GB) run as job bqjob_r334ca4e1a9a7a635_000001a1ba3ce70e_1 (see the meta file). Re-running this
-- file reconstructs the same aggregate directly from the public table (about 150 GB).
WITH tx AS (
  SELECT DATE_TRUNC(block_date, MONTH) AS month, block_date, signer_account_id AS account, receiver_account_id AS receiver
  FROM `bigquery-public-data.crypto_near_mainnet_us.transactions`
  WHERE block_date BETWEEN '2024-11-01' AND '2026-01-31'
),
per_account AS (
  SELECT month, account, COUNT(*) AS txns, COUNT(DISTINCT block_date) AS active_days, COUNT(DISTINCT receiver) AS distinct_receivers,
         COUNTIF(receiver = 'intents.near') AS intents_txns,
         CASE WHEN ENDS_WITH(account, '.tg') THEN 'tg' WHEN ENDS_WITH(account, '.sweat') THEN 'sweat' WHEN ENDS_WITH(account, '.kaiching') THEN 'kaiching'
              WHEN REGEXP_CONTAINS(account, r'^[0-9a-f]{64}$') THEN 'implicit' WHEN REGEXP_CONTAINS(account, r'^0x[0-9a-f]{40}$') THEN 'eth_implicit'
              WHEN ENDS_WITH(account, '.near') THEN 'named' ELSE 'other' END AS name_class
  FROM tx GROUP BY month, account
)
SELECT month, name_class, COUNT(*) AS accounts, COUNTIF(txns = 1) AS single_tx_accounts, COUNTIF(distinct_receivers >= 2) AS multi_receiver_accounts,
       COUNTIF(intents_txns > 0) AS intents_accounts, SUM(txns) AS txns, AVG(active_days) AS active_days_mean,
       APPROX_QUANTILES(txns, 100)[OFFSET(50)] AS txns_median
FROM per_account GROUP BY month, name_class ORDER BY month, name_class;
