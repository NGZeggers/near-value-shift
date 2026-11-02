# Metric definitions (generated)

| Column | Source | Definition |
|---|---|---|
| `txns` | NearBlocks | transactions included per day |
| `active_accounts` | NearBlocks | distinct accounts that signed a transaction that day |
| `new_accounts` | NearBlocks | accounts created that day |
| `active_contracts` | NearBlocks | contracts that received a call that day |
| `tx_fee_usd / tx_fee_near` | NearBlocks | gas fees burned, in USD and NEAR |
| `tx_volume_usd` | NearBlocks | USD value of native NEAR transferred |
| `usd_per_txn` | derived | tx_volume_usd / txns |
| `near_price, market_cap_usd` | NearBlocks | daily price and market cap |
| `intents_volume_usd` | DefiLlama (Dune) | NEAR Intents swap volume |
| `intents_fees_usd` | DefiLlama | fees paid on NEAR Intents swaps |
| `near_dex_volume_usd` | DefiLlama | all DEX volume attributed to NEAR, Intents included |
| `near_app_fees_usd` | DefiLlama | application fees on NEAR (all protocols) |
| `tvl_usd` | DefiLlama | total value locked on NEAR |
| `stablecoins_usd` | DefiLlama | circulating stablecoin supply on NEAR |
| `price_bitcoin, price_ethereum` | DefiLlama coins | daily benchmark prices |
| `qaa` | BigQuery + clustering | quality-adjusted active accounts (L1) |
| `hhi_solver, top1_solver_share` | BigQuery events | solver concentration in Intents (L2) |
