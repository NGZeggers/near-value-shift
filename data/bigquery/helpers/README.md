# Helper tables loaded into BigQuery (`near-thesis-514107.near_thesis`, region us-east1)

Both files are derived from committed inputs and are tiny; they exist so that the complete-day valuation runs inside BigQuery and
returns one row per day instead of millions of log rows.

- `asset_prices.csv` (asset_id, day, usd_per_raw_unit): for every asset of the committed 1Click registry (`data/raw/intents_tokens.json`) and
  every committed sample day, the DefiLlama daily price (`data/raw/price_*.json`, forward-filled at most seven days) divided by 10^decimals;
  stablecoins at par; assets without a price are absent, so their legs stay unpriced exactly as in `near_thesis.intents.price_leg`.
- `window_ranges.csv` (day, hour, start_height, end_height): the committed 50-block sample windows (`data/blocks/sample_plan.json`, usable
  windows only), used to value the same receipts in SQL and in Python as a cross-check.

Load (after `bq mk --dataset --location=us-east1 <project>:near_thesis`):

```bash
bq load --source_format=CSV --skip_leading_rows=1 --replace near_thesis.asset_prices  data/bigquery/helpers/asset_prices.csv  asset_id:STRING,day:DATE,usd_per_raw_unit:FLOAT64
bq load --source_format=CSV --skip_leading_rows=1 --replace near_thesis.sample_windows data/bigquery/helpers/window_ranges.csv day:DATE,hour:INT64,start_height:INT64,end_height:INT64
```
