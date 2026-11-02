-- Q0. Dataset freshness. Run first. If MAX(block_date) is stale, THESIS.md must say so.
SELECT MAX(block_date) AS last_block_date, COUNT(*) AS blocks_last_30d
FROM `bigquery-public-data.crypto_near_mainnet_us.blocks`
WHERE block_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);
