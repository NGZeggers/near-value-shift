-- L2 full days, valued in SQL. Every successful intents.near token_diff log of the committed sample days, valued with the same rule as the
-- Python pipeline (per receipt, per account-intent the larger of priced inflow and outflow, summed and halved; daily prices and decimals from
-- near_thesis.asset_prices, built from the committed registry and price snapshots; stablecoins at par; unpriced legs dropped). The output is one
-- row per day, so nothing large is downloaded. sampled_windows_usd_sql values only the receipts inside the committed 50-block windows: comparing it
-- with the Python value of the same windows validates the SQL valuation. Declared 2026-11-08 before running; the days are the committed sample days.
DECLARE DAYS ARRAY<DATE> DEFAULT [DATE '2024-11-04', DATE '2024-11-19', DATE '2024-12-04', DATE '2024-12-19', DATE '2025-01-03', DATE '2025-01-18', DATE '2025-02-02', DATE '2025-02-17', DATE '2025-03-04', DATE '2025-03-19', DATE '2025-04-03', DATE '2025-04-18', DATE '2025-05-03', DATE '2025-05-18', DATE '2025-06-02', DATE '2025-06-17', DATE '2025-07-02', DATE '2025-07-17', DATE '2025-08-01', DATE '2025-08-16', DATE '2025-08-31', DATE '2025-09-15', DATE '2025-09-30', DATE '2025-10-15', DATE '2025-10-30', DATE '2025-11-14', DATE '2025-11-29', DATE '2025-12-14', DATE '2025-12-29', DATE '2026-01-13', DATE '2026-01-28', DATE '2026-02-12'];
CREATE TEMP FUNCTION diff_pairs(diff STRING) RETURNS ARRAY<STRUCT<asset STRING, amount STRING>> LANGUAGE js AS r"""
  if (!diff) return [];
  let o; try { o = JSON.parse(diff); } catch (e) { return []; }
  if (o === null || typeof o !== 'object' || Array.isArray(o)) return [];
  return Object.keys(o).map(k => ({asset: k, amount: (typeof o[k] === 'string' || typeof o[k] === 'number') ? String(o[k]) : null}));
""";
WITH logs AS (
  SELECT eo.block_date, eo.block_height, eo.receipt_id, log.element AS log
  FROM `bigquery-public-data.crypto_near_mainnet_us.execution_outcomes` eo
  CROSS JOIN UNNEST(eo.logs.list) AS log
  WHERE eo.block_date IN UNNEST(DAYS) AND eo.executor_account_id = 'intents.near'
    AND eo.status IN ('SUCCESS_VALUE', 'SUCCESS_RECEIPT_ID') AND STARTS_WITH(log.element, 'EVENT_JSON:')
),
ev AS (SELECT block_date, block_height, receipt_id, SAFE.PARSE_JSON(SUBSTR(log, 12)) AS j FROM logs),
td AS (SELECT block_date, block_height, receipt_id, j FROM ev WHERE j IS NOT NULL AND JSON_VALUE(j, '$.event') = 'token_diff'),
items AS (
  SELECT block_date, block_height, receipt_id, item
  FROM td, UNNEST(IF(JSON_TYPE(JSON_QUERY(j, '$.data')) = 'array', JSON_QUERY_ARRAY(j, '$.data'), [JSON_QUERY(j, '$.data')])) AS item
),
legs AS (
  SELECT block_date, block_height, receipt_id,
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
  SELECT block_date, block_height, receipt_id, account, intent_key,
         SUM(IF(direction = 'in', usd, 0)) AS usd_in, SUM(IF(direction = 'out', usd, 0)) AS usd_out
  FROM priced WHERE usd IS NOT NULL GROUP BY 1, 2, 3, 4, 5
),
per_receipt AS (
  SELECT block_date, block_height, receipt_id, SUM(GREATEST(usd_in, usd_out)) / 2 AS half_gross FROM sides GROUP BY 1, 2, 3
),
flagged AS (
  SELECT r.*, EXISTS(SELECT 1 FROM `near-thesis-514107.near_thesis.sample_windows` w
                     WHERE w.day = r.block_date AND r.block_height BETWEEN w.start_height AND w.end_height) AS in_sampled_window
  FROM per_receipt r
),
counts AS (
  SELECT block_date, COUNT(DISTINCT receipt_id) AS receipts_with_token_diff FROM td GROUP BY block_date
),
leg_counts AS (
  SELECT block_date, COUNT(*) AS legs, COUNTIF(usd IS NULL) AS legs_unpriced FROM priced GROUP BY block_date
)
SELECT f.block_date,
       SUM(f.half_gross) AS complete_usd,
       COUNT(*) AS receipts_valued,
       SUM(IF(f.in_sampled_window, f.half_gross, 0)) AS sampled_windows_usd_sql,
       COUNTIF(f.in_sampled_window) AS sampled_windows_receipts_sql,
       MAX(c.receipts_with_token_diff) AS receipts_with_token_diff,
       MAX(lc.legs) AS legs, MAX(lc.legs_unpriced) AS legs_unpriced
FROM flagged f LEFT JOIN counts c USING (block_date) LEFT JOIN leg_counts lc USING (block_date)
GROUP BY f.block_date ORDER BY f.block_date;
