-- Q0. Dataset freshness. Run first. If MAX(block_date) is stale, THESIS.md must say so.
-- The window starts in 2026 so that a dataset that stopped updating still reports its last date instead of NULL.
SELECT MAX(block_date) AS last_block_date, COUNT(*) AS blocks_since_2026
FROM `bigquery-public-data.crypto_near_mainnet_us.blocks`
WHERE block_date >= '2026-01-01';
