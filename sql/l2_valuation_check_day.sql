-- L2 valuation check, one day. Per execution block, the SQL-valued half-gross notional of 2025-11-14, the day for which the repository holds the most
-- locally extracted blocks (systematic sample, 24 hourly windows, two fixed windows): Python values the same blocks from the local extracts and the two are
-- compared block by block. Receipts are attributed to the block that executed them (executed_in_block_hash joined to blocks), as the block API does.
-- L2 full days, valued in SQL. Every successful intents.near token_diff log of the committed sample days, valued with the same rule as the
-- Python pipeline (per receipt, per account-intent the larger of priced inflow and outflow, summed and halved; daily prices and decimals from
-- near_thesis.asset_prices, built from the committed registry and price snapshots; stablecoins at par; unpriced legs dropped). The output is one
-- row per day, so nothing large is downloaded. sampled_windows_usd_sql values only the receipts inside the committed 50-block windows: comparing it
-- with the Python value of the same windows validates the SQL valuation. Declared 2026-11-08 before running; the days are the committed sample days.
DECLARE DAYS ARRAY<DATE> DEFAULT [DATE '2025-11-14'];
CREATE TEMP FUNCTION diff_pairs(diff STRING) RETURNS ARRAY<STRUCT<asset STRING, amount STRING>> LANGUAGE js AS r"""
  if (!diff) return [];
  let o; try { o = JSON.parse(diff); } catch (e) { return []; }
  if (o === null || typeof o !== 'object' || Array.isArray(o)) return [];
  return Object.keys(o).map(k => ({asset: k, amount: (typeof o[k] === 'string' || typeof o[k] === 'number') ? String(o[k]) : null}));
""";
WITH logs AS (
  SELECT eo.block_date, eo.block_height, eo.executed_in_block_hash, eo.receipt_id, log.element AS log
  FROM `bigquery-public-data.crypto_near_mainnet_us.execution_outcomes` eo
  CROSS JOIN UNNEST(eo.logs.list) AS log
  WHERE eo.block_date IN UNNEST(DAYS) AND eo.executor_account_id = 'intents.near'
    AND eo.status IN ('SUCCESS_VALUE', 'SUCCESS_RECEIPT_ID') AND STARTS_WITH(log.element, 'EVENT_JSON:')
),
ev AS (SELECT block_date, block_height, executed_in_block_hash, receipt_id, SAFE.PARSE_JSON(SUBSTR(log, 12)) AS j FROM logs),
td AS (SELECT block_date, block_height, executed_in_block_hash, receipt_id, j FROM ev WHERE j IS NOT NULL AND JSON_VALUE(j, '$.event') = 'token_diff'),
items AS (
  SELECT block_date, block_height, executed_in_block_hash, receipt_id, item
  FROM td, UNNEST(IF(JSON_TYPE(JSON_QUERY(j, '$.data')) = 'array', JSON_QUERY_ARRAY(j, '$.data'), [JSON_QUERY(j, '$.data')])) AS item
),
legs AS (
  SELECT block_date, block_height, executed_in_block_hash, receipt_id,
         JSON_VALUE(item, '$.account_id') AS account,
         COALESCE(JSON_VALUE(item, '$.intent_hash'), JSON_VALUE(item, '$.hash'), 'legacy') AS intent_key,
         d.asset AS asset,
         IF(REGEXP_CONTAINS(d.amount, r'^-?[0-9]{1,39}$'), SAFE_CAST(d.amount AS BIGNUMERIC), NULL) AS amount
  FROM items, UNNEST(diff_pairs(TO_JSON_STRING(JSON_QUERY(item, '$.diff')))) AS d
  WHERE JSON_VALUE(item, '$.account_id') IS NOT NULL
),
priced AS (
  SELECT l.*, ABS(CAST(l.amount AS FLOAT64)) * p.usd_per_raw_unit AS usd, IF(l.amount < 0, 'out', 'in') AS direction
  FROM legs l LEFT JOIN `near-thesis-514107.near_thesis.asset_prices` p ON p.asset_id = l.asset AND p.day = l.block_date
  WHERE l.amount IS NOT NULL
),
sides AS (
  SELECT block_date, block_height, executed_in_block_hash, receipt_id, account, intent_key,
         SUM(IF(direction = 'in', usd, 0)) AS usd_in, SUM(IF(direction = 'out', usd, 0)) AS usd_out
  FROM priced WHERE usd IS NOT NULL GROUP BY 1, 2, 3, 4, 5, 6
),
per_receipt AS (
  SELECT block_date, block_height, executed_in_block_hash, receipt_id, SUM(GREATEST(usd_in, usd_out)) / 2 AS half_gross FROM sides GROUP BY 1, 2, 3, 4
),
exec_blocks AS (
  SELECT block_hash, block_height AS executed_height FROM `bigquery-public-data.crypto_near_mainnet_us.blocks` WHERE block_date BETWEEN '2025-11-14' AND '2025-11-15'
)
SELECT r.block_date, COALESCE(b.executed_height, r.block_height) AS executed_block_height, r.block_height AS receipt_block_height,
       SUM(r.half_gross) AS half_gross_usd, COUNT(*) AS receipts
FROM per_receipt r LEFT JOIN exec_blocks b ON b.block_hash = r.executed_in_block_hash
GROUP BY 1, 2, 3 ORDER BY 2;
