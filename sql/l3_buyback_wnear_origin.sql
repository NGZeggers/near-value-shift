-- L3 buybacks, second pass (declared 2026-11-08 after the first pass showed 40% of withdrawals without an own exchange, before running): for every
-- withdrawal, how the wrap.near reached the withdrawing account when it did not buy it itself: an internal transfer of wrap.near into the account
-- (with its source account and whether that source bought wrap.near before the transfer, one hop upstream) or a deposit of wrap.near from outside
-- (mt_mint). One pass over the public table; same filters as the first pass. For each native_withdraw whose receiver is the wallet: the Intents-side account, the amount, the latest token_diff of
-- the same account at or before the withdrawal block (the exchange: assets sold, whether wrap.near was bought, distance in blocks), whether that account
-- received the sold asset earlier by a bridge deposit (mt_mint) or an internal transfer (mt_transfer), and the distances. One row per withdrawal;
-- the search goes back one day of blocks (150,000). Declared 2026-11-08 before running.
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
  WHERE eo.block_date BETWEEN '2026-04-23' AND '2026-11-06'
    AND eo.executor_account_id = 'intents.near'
    AND eo.status IN ('SUCCESS_VALUE', 'SUCCESS_RECEIPT_ID')
    AND STARTS_WITH(log.element, 'EVENT_JSON:')
    AND (STRPOS(log.element, '"native_withdraw"') > 0 OR STRPOS(log.element, '"token_diff"') > 0
         OR STRPOS(log.element, '"mt_mint"') > 0 OR STRPOS(log.element, '"mt_transfer"') > 0)
),
ev AS (
  SELECT block_date, block_height, receipt_id, SAFE.PARSE_JSON(SUBSTR(log, 12)) AS j FROM logs
),
typed AS (
  SELECT block_date, block_height, receipt_id, j, JSON_VALUE(j, '$.event') AS event,
         IF(JSON_TYPE(JSON_QUERY(j, '$.data')) = 'array', JSON_QUERY_ARRAY(j, '$.data'), [JSON_QUERY(j, '$.data')]) AS items
  FROM ev WHERE j IS NOT NULL
),
withdraw AS (
  SELECT t.block_date, t.block_height, t.receipt_id, JSON_VALUE(item, '$.account_id') AS intents_account,
         SAFE_CAST(JSON_VALUE(item, '$.amount') AS BIGNUMERIC) AS amount_yocto
  FROM typed t, UNNEST(t.items) AS item
  WHERE t.event = 'native_withdraw' AND JSON_VALUE(item, '$.receiver_id') = 'buybacks.multisignature.near'
),
wnear_buys AS (
  SELECT t.block_height, JSON_VALUE(item, '$.account_id') AS account
  FROM typed t, UNNEST(t.items) AS item
  WHERE t.event = 'token_diff'
    AND EXISTS (SELECT 1 FROM UNNEST(diff_pairs(TO_JSON_STRING(JSON_QUERY(item, '$.diff')))) d WHERE d.asset = 'nep141:wrap.near' AND SAFE_CAST(d.amount AS BIGNUMERIC) > 0)
),
wnear_transfers AS (
  SELECT t.block_height, JSON_VALUE(item, '$.old_owner_id') AS from_account, JSON_VALUE(item, '$.new_owner_id') AS account
  FROM typed t, UNNEST(t.items) AS item
  WHERE t.event = 'mt_transfer' AND EXISTS (SELECT 1 FROM UNNEST(JSON_QUERY_ARRAY(item, '$.token_ids')) tok WHERE JSON_VALUE(tok) = 'nep141:wrap.near')
),
wnear_mints AS (
  SELECT t.block_height, JSON_VALUE(item, '$.owner_id') AS account
  FROM typed t, UNNEST(t.items) AS item
  WHERE t.event = 'mt_mint' AND EXISTS (SELECT 1 FROM UNNEST(JSON_QUERY_ARRAY(item, '$.token_ids')) tok WHERE JSON_VALUE(tok) = 'nep141:wrap.near')
),
own_swap AS (
  SELECT w.receipt_id, MAX(b.block_height) AS own_swap_block
  FROM withdraw w JOIN wnear_buys b ON b.account = w.intents_account AND b.block_height <= w.block_height AND b.block_height >= w.block_height - 150000
  GROUP BY w.receipt_id
),
transfer_in AS (
  SELECT w.receipt_id, tr.block_height AS wnear_in_block, tr.from_account AS wnear_in_from,
         ROW_NUMBER() OVER (PARTITION BY w.receipt_id ORDER BY tr.block_height DESC) AS rn
  FROM withdraw w JOIN wnear_transfers tr ON tr.account = w.intents_account AND tr.block_height <= w.block_height AND tr.block_height >= w.block_height - 150000
),
transfer_best AS (SELECT receipt_id, wnear_in_block, wnear_in_from FROM transfer_in WHERE rn = 1),
upstream AS (
  SELECT tb.receipt_id, MAX(b.block_height) AS upstream_swap_block
  FROM transfer_best tb JOIN wnear_buys b ON b.account = tb.wnear_in_from AND b.block_height <= tb.wnear_in_block AND b.block_height >= tb.wnear_in_block - 150000
  GROUP BY tb.receipt_id
),
mint_in AS (
  SELECT w.receipt_id, MAX(m.block_height) AS wnear_mint_block
  FROM withdraw w JOIN wnear_mints m ON m.account = w.intents_account AND m.block_height <= w.block_height AND m.block_height >= w.block_height - 150000
  GROUP BY w.receipt_id
)
SELECT w.block_date, w.block_height, w.receipt_id, w.intents_account, CAST(w.amount_yocto AS STRING) AS amount_yocto,
       o.own_swap_block, tb.wnear_in_block, tb.wnear_in_from, u.upstream_swap_block, mi.wnear_mint_block
FROM withdraw w LEFT JOIN own_swap o USING (receipt_id) LEFT JOIN transfer_best tb USING (receipt_id)
LEFT JOIN upstream u USING (receipt_id) LEFT JOIN mint_in mi USING (receipt_id)
ORDER BY w.block_height;
