-- Q3. intents.near: daily FUNCTION_CALL receipts, distinct callers, and method mix.
SELECT
  block_date,
  method_name,
  COUNT(*)                                       AS calls,
  COUNT(DISTINCT receipt_predecessor_account_id) AS unique_callers
FROM `bigquery-public-data.crypto_near_mainnet_us.receipt_actions`
WHERE block_date BETWEEN '2024-11-01' AND '2026-11-14'
  AND receipt_receiver_account_id = 'intents.near'
  AND action_kind = 'FUNCTION_CALL'
GROUP BY block_date, method_name
ORDER BY block_date, calls DESC;
