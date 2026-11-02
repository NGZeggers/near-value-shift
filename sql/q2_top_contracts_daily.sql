-- Q2. Top 20 contracts per day by FUNCTION_CALL receipts with distinct callers (contract usage).
SELECT block_date, contract, calls, callers
FROM (
  SELECT
    block_date,
    receipt_receiver_account_id                    AS contract,
    COUNT(*)                                       AS calls,
    COUNT(DISTINCT receipt_predecessor_account_id) AS callers,
    ROW_NUMBER() OVER (PARTITION BY block_date ORDER BY COUNT(*) DESC) AS rn
  FROM `bigquery-public-data.crypto_near_mainnet_us.receipt_actions`
  WHERE block_date BETWEEN '2023-01-01' AND '2026-11-14'
    AND action_kind = 'FUNCTION_CALL'
  GROUP BY block_date, contract
)
WHERE rn <= 20
ORDER BY block_date, calls DESC;
