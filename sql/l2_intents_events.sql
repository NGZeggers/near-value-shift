-- L2. Raw DIP-4 events emitted by intents.near (token_diff, intents_executed, mt_transfer, *_withdraw).
-- Output: one row per event log line, with the JSON payload. Parsed in Python.
-- Sampling: set the date list in DAYS (stratified sample) or a BETWEEN window. Dry-run first.
DECLARE DAYS ARRAY<DATE> DEFAULT GENERATE_DATE_ARRAY('2024-11-04', '2026-11-14', INTERVAL 7 DAY);
SELECT
  eo.block_date,
  eo.executed_in_block_timestamp AS block_timestamp,
  eo.receipt_id,
  r.predecessor_account_id       AS caller,
  log,
  eo.status AS execution_status
FROM `bigquery-public-data.crypto_near_mainnet_us.execution_outcomes` eo
LEFT JOIN `bigquery-public-data.crypto_near_mainnet_us.receipt_details` r
  ON r.receipt_id = eo.receipt_id AND r.block_date = eo.block_date
CROSS JOIN UNNEST(eo.logs) AS log
WHERE eo.block_date IN UNNEST(DAYS)
  AND eo.executor_account_id = 'intents.near'
  AND eo.status IN ('SUCCESS_VALUE', 'SUCCESS_RECEIPT_ID')
  AND STARTS_WITH(log, 'EVENT_JSON:');
