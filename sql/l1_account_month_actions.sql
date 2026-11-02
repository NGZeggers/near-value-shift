-- L1b. Receiver-side action mix per account-month (FUNCTION_CALL share, distinct methods, deposits, gas).
SELECT
  DATE_TRUNC(block_date, MONTH)                     AS month,
  receipt_predecessor_account_id                    AS account,
  COUNT(*)                                          AS actions,
  COUNTIF(action_kind = 'FUNCTION_CALL')            AS function_calls,
  COUNTIF(action_kind = 'TRANSFER')                 AS transfers,
  COUNT(DISTINCT method_name)                       AS distinct_methods,
  COUNT(DISTINCT receipt_receiver_account_id)       AS distinct_contracts,
  COUNTIF(receipt_receiver_account_id = 'intents.near') AS intents_actions,
  SUM(SAFE_CAST(deposit AS BIGNUMERIC)) / 1e24      AS deposit_near
FROM `bigquery-public-data.crypto_near_mainnet_us.receipt_actions`
WHERE block_date BETWEEN '2023-01-01' AND '2026-10-31'
  AND receipt_predecessor_account_id != 'system'
GROUP BY month, account;
