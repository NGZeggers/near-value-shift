-- L3 buybacks: attribution of every inbound withdrawal of the buyback wallet, computed in one pass over the public table (the sandbox
-- storage quota does not allow materializing the filtered logs; the dry run confirms a single scan). For each native_withdraw whose receiver is the wallet: the Intents-side account, the amount, the latest token_diff of
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
         SAFE_CAST(JSON_VALUE(item, '$.amount') AS BIGNUMERIC) AS amount_yocto, JSON_VALUE(item, '$.intent_hash') AS intent_hash
  FROM typed t, UNNEST(t.items) AS item
  WHERE t.event = 'native_withdraw' AND JSON_VALUE(item, '$.receiver_id') = 'buybacks.multisignature.near'
),
diffs AS (
  SELECT t.block_height, t.receipt_id, JSON_VALUE(item, '$.account_id') AS account,
         ARRAY_TO_STRING(ARRAY(SELECT d.asset FROM UNNEST(diff_pairs(TO_JSON_STRING(JSON_QUERY(item, '$.diff')))) d WHERE SAFE_CAST(d.amount AS BIGNUMERIC) < 0 ORDER BY d.asset), '|') AS sold,
         ARRAY_TO_STRING(ARRAY(SELECT d.asset FROM UNNEST(diff_pairs(TO_JSON_STRING(JSON_QUERY(item, '$.diff')))) d WHERE SAFE_CAST(d.amount AS BIGNUMERIC) > 0 ORDER BY d.asset), '|') AS bought
  FROM typed t, UNNEST(t.items) AS item WHERE t.event = 'token_diff'
),
mints AS (
  SELECT t.block_height, JSON_VALUE(item, '$.owner_id') AS account, tok AS asset
  FROM typed t, UNNEST(t.items) AS item, UNNEST(JSON_QUERY_ARRAY(item, '$.token_ids')) AS tok_j, UNNEST([JSON_VALUE(tok_j)]) AS tok
  WHERE t.event = 'mt_mint'
),
transfers_in AS (
  SELECT t.block_height, JSON_VALUE(item, '$.new_owner_id') AS account, tok AS asset
  FROM typed t, UNNEST(t.items) AS item, UNNEST(JSON_QUERY_ARRAY(item, '$.token_ids')) AS tok_j, UNNEST([JSON_VALUE(tok_j)]) AS tok
  WHERE t.event = 'mt_transfer'
),
swap AS (
  SELECT w.receipt_id, d.block_height AS swap_block, d.receipt_id AS swap_receipt, d.sold, d.bought,
         ROW_NUMBER() OVER (PARTITION BY w.receipt_id ORDER BY d.block_height DESC) AS rn
  FROM withdraw w JOIN diffs d ON d.account = w.intents_account AND d.block_height <= w.block_height AND d.block_height >= w.block_height - 150000
    AND STRPOS(d.bought, 'nep141:wrap.near') > 0
),
best AS (SELECT * EXCEPT (rn) FROM swap WHERE rn = 1),
origin AS (
  SELECT b.receipt_id,
         MAX(m.block_height) AS deposit_block, MAX(tr.block_height) AS transfer_in_block
  FROM best b JOIN withdraw w USING (receipt_id)
  LEFT JOIN mints m ON m.account = w.intents_account AND m.block_height <= b.swap_block AND m.block_height >= b.swap_block - 150000 AND STRPOS(b.sold, m.asset) > 0
  LEFT JOIN transfers_in tr ON tr.account = w.intents_account AND tr.block_height <= b.swap_block AND tr.block_height >= b.swap_block - 150000 AND STRPOS(b.sold, tr.asset) > 0
  GROUP BY b.receipt_id
)
SELECT w.block_date, w.block_height, w.receipt_id, w.intents_account, CAST(w.amount_yocto AS STRING) AS amount_yocto, w.intent_hash,
       b.swap_block, b.swap_receipt, b.sold, b.bought,
       IF(b.swap_block IS NULL, NULL, w.block_height - b.swap_block) AS blocks_withdrawal_minus_swap,
       o.deposit_block, IF(o.deposit_block IS NULL, NULL, b.swap_block - o.deposit_block) AS blocks_swap_minus_deposit,
       o.transfer_in_block, IF(o.transfer_in_block IS NULL, NULL, b.swap_block - o.transfer_in_block) AS blocks_swap_minus_transfer_in
FROM withdraw w LEFT JOIN best b USING (receipt_id) LEFT JOIN origin o USING (receipt_id)
ORDER BY w.block_height;
