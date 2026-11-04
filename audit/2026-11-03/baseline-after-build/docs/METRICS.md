# Metric definitions (generated)

| Column | Source | Definition |
|---|---|---|
| `txns / active_accounts` | NearBlocks | daily transactions / distinct signing accounts |
| `tx_fee_near / tx_fee_usd` | NearBlocks | gas fees paid; not audited net supply burn |
| `tx_volume_usd / usd_per_txn` | NearBlocks | native NEAR transferred in USD / ratio to transactions |
| `intents_volume_usd` | DefiLlama/Dune | reported cross-chain settlement volume |
| `intents_fees_usd` | DefiLlama/Dune | gross swap fees |
| `intents_revenue_usd` | DefiLlama/Dune wallet-receipt adapter | net captured revenue; internal revenue-wallet hops excluded |
| `intents_holders_revenue_usd` | same adapter | buyback-labelled net revenue; not proof of each purchase, dividends or burning |
| `near_app_fees_usd` | DefiLlama | gross application fees; not token-holder income |
| `tvl_usd / stablecoins_usd` | DefiLlama | chain TVL / circulating stablecoin USD supply |
| `near_price / price_bitcoin / price_ethereum` | NearBlocks / DefiLlama coins | daily prices; benchmark histories |
| `qaa_monthly.qaa` | sampled blocks or BigQuery; retrospective HDBSCAN | behavioral quality proxy; sampled share multiplied by mean daily active accounts |
| `qaa_causal_monthly.qaa` | frozen past-only calibration GMM | out-of-calibration proxy; available on next-month first day; used for predictive tests |
| `hhi_solver / top1_solver_share` | sampled token_diff events or BigQuery | within-observation heuristic solver concentration |
| `volume_priced_usd` | same events | half sum of max priced inflow/outflow by account-intent; expanded only for additive flows |
| `users` | same events | observed unique non-solver accounts, never expanded |
