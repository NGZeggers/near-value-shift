-- Q1. Daily transactions and distinct signers (cross-check of NearBlocks active_accounts).
SELECT
  block_date,
  COUNT(*)                          AS txns,
  COUNT(DISTINCT signer_account_id) AS active_signers
FROM `bigquery-public-data.crypto_near_mainnet_us.transactions`
WHERE block_date BETWEEN '2023-01-01' AND '2026-11-14'
GROUP BY block_date
ORDER BY block_date;
