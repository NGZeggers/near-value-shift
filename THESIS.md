# From clicks to settlement: an investment thesis on NEAR

Generated from committed snapshots; analysis through 2026-11-01. `make build` rebuilds this argument, tables, dashboard and executed notebook. Numbers are computed; interpretation and source context are explicit.

## Claim and current verdict

NEAR's reported activity is shifting from high transaction/account counts toward cross-chain settlement. That is a claim about composition, not proof of token undervaluation or future returns. QAA is a behavioral proxy, not a count of verified humans.

**Current verdict: the descriptive shift is supported by the third-party series, but the independent on-chain validation is unresolved. The investment case remains conditional on net capture, governance allocation, dilution and robust forward evidence. A failed cross-check counts against the claim; it is not explained away as missing large trades.**

## Observed activity

| Metric (daily mean) | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|
| Transactions | 166,251 | 535,662 | 1,014,186 | 6,593,296 | 5,340,987 | 1,583,849 |
| Active accounts | 10,705 | 33,610 | 314,090 | 1,331,906 | 421,371 | 125,436 |
| USD moved per transaction | $814.23 | $154.11 | $37.57 | $17.56 | $10.89 | $97.30 |
| Gas fees paid, USD | $1.9K | $9.0K | $3.8K | $23.2K | $10.1K | $2.8K |
| Intents volume, USD | n/a | n/a | n/a | $135.0K | $24.1M | $89.5M |
| NEAR price | $5.59 | $6.97 | $1.74 | $5.28 | $2.74 | $2.11 |

Latest full month (2026-10): Intents volume $4.0B, mean daily active accounts 72,046, USD moved per transaction $345.98. Latest year has 305 observed days.

## Evidence for

- The reported Intents volume and raw activity series have diverged. This supports a change in composition, subject to source coverage. Native NEAR transfer volume and Intents cross-chain settlement are different measurements, not interchangeable totals.
- A quality adjustment can distinguish behavioral groups. Its uncertainty and sensitivity are reported below; it does not establish that departing accounts were actual bots.
- Intents already has a revenue mechanism. The economic question is how much is retained and allocated, rather than whether any capture exists.

## Revenue mechanics: observed capture versus future allocation

NEAR's [February 2026 explanation](https://www.near.org/blog/evolving-near-tokenomics) describes an active fee switch and governance-controlled buybacks. Its [Q2 update](https://www.near.org/blog/the-state-of-near-q-2-2026) describes revenue-funded purchases. These are primary-source context, not a guarantee of dividends or continued purchases. The [DefiLlama adapter](https://github.com/DefiLlama/dimension-adapters/blob/master/fees/near-intents/index.ts) measures net NEAR/wNEAR receipts into revenue wallets, excludes internal wallet hops, and labels captured revenue after its buyback start as HoldersRevenue. That classification is not transaction-level proof of each purchase or of burning.

On the analysis cutoff's trailing year: gross Intents fees $54.2M; net captured receipts $9.3M; buyback-labelled revenue $7.5M. Ratio of net receipts to gross fees: 17.20%. Receipts are realized in sweeps and can exceed fees on an individual day. The snapshots carry the adapter definitions and are cut to the same analysis end date. No independent wallet-level purchase audit or supply-destruction calculation is claimed. Gas fees paid are not automatically net supply burn across all historical protocol versions.

## Evidence against and unresolved tests

- Greater settlement volume does not mechanically imply greater token returns. Gross fees are not token-holder yield; net capture, future allocation and issuance still matter.
- The independent sample-to-DefiLlama ratio is 0.253, conditional day-bootstrap interval [0.178, 0.327], over 46 matched days. The interval excludes parity: our consistency criterion fails, so independent confirmation of the total and trend is not established.
- Intents growth versus twelve-week forward NEAR excess returns over BTC: IC -0.58, exploratory 95% block interval [-0.73, -0.13], n=80. First/second chronological halves: +0.05/-0.52. These are descriptive association checks, not a validated trading signal.
- Fixed intraday windows, sparse sampling, role assumptions, unpriced assets and routed batches can all affect the on-chain comparison. Their separate contributions are not identified.

## Quality-adjusted accounts (L1)

Source: neardata block sample; 32,173 account-months, 24 months. Retrospective hdbscan with corrected self-call counts and window-normalized activity. At 2024-12 QAA was 233,963; at 2026-10 it was 44,634. The corresponding behavioral shares are 25.3% and 62.0%. Silhouette on at most 3,000 observations: 0.91. Separation is not human/bot accuracy.

Latest sensitivity: strict multi-app share 0.0%; default share 62.0%; including ambiguous groups 68.3%. Name-proxy profiles are in `qaa_anchor_profiles.csv`; monthly group counts permit composition checks. Verified human/bot anchor labels are not available. In sampled mode, shares are rescaled by NearBlocks mean daily active accounts; unequal account inclusion probabilities are not corrected, so these are exploratory proxies with no guaranteed conservative bias.

**Past-only QAA for predictive tests:** a separate GMM is calibrated through 2025-04-30, then its scaler, parameters and label mapping are frozen. Only later months are predicted; first availability is 2025-06-01. Each month becomes available on the first day of the following month. The full-history descriptive clustering is never fed into signal or Granger tests. The model is frozen calibration, not monthly walk-forward retraining.

## Intents microstructure (L2)

Source: neardata block sample. 4892 blocks, 49 sampled days including observed zero-event days; 39 days contain token_diff. Parsed 7,227 events. 9 accounts satisfy the role heuristic (absolute or (batch share >= 2%, batches >= 5, counterparties >= 5)).

Valuation: half gross participant notional: sum max(priced inflow, priced outflow) per account-intent / 2; fixed-window expansion; not a validated total or guaranteed lower bound. Batch coverage with any priced leg 99.8%; fully priced batches 74.5%; priced token-diff legs 94.2%. Leg coverage is a count share, not a known USD share. Observed users are never multiplied into daily unique users. Solvers and HHI are within-window estimates, not full-market concentration.

| Quarter | Sampled days | Flow estimate / DefiLlama |
|---|---|---|
| 2024-10 | 4 | 0.040 |
| 2025-01 | 6 | 0.043 |
| 2025-04 | 6 | 0.271 |
| 2025-07 | 7 | 0.065 |
| 2025-10 | 6 | 0.269 |
| 2026-01 | 6 | 0.175 |
| 2026-04 | 6 | 0.330 |
| 2026-07 | 6 | 0.184 |
| 2026-10 | 2 | 0.402 |

Intervals condition on the observed sampled days; they omit intraday, routing and pricing uncertainty. One-day strata have no estimable interval. The estimator now retains multiple account-intents in a receipt; it still does not identify every economic swap. The gap is unresolved, not a proven tail effect or a guaranteed lower bound. Full-day extracts would improve coverage but would not automatically validate this estimator. Role sensitivity is in `intents_solver_sensitivity.json`.

## Econometrics (L3)

In the 5 VAR models that pass the stationarity, stability and whiteness gates, usage leads price for transaction counts (Holm p = 0.005); price leads usage for gas fees (Holm p = 8.83e-07), transfer volume (Holm p = 1.49e-07). Intents volume, QAA fail the prerequisites and are inconclusive.

| Metric | Weeks | VAR status | Johansen rank | Johansen status |
|---|---|---|---|---|
| active_accounts | 304 | diagnostics passed | 0 | rank 0: no rejection |
| txns | 304 | diagnostics passed | 0 | inconclusive: I(1) prerequisites not established or full rank |
| tx_fee_usd | 304 | diagnostics passed | 0 | inconclusive: I(1) prerequisites not established or full rank |
| tx_volume_usd | 304 | diagnostics passed | 2 | inconclusive: I(1) prerequisites not established or full rank |
| intents_volume_usd | 98 | inconclusive: ADF does not establish stationary log differences for both series | 0 | inconclusive: I(1) prerequisites not established or full rank |
| near_app_fees_usd | 128 | diagnostics passed | 0 | rank 0: no rejection |
| qaa | 74 | inconclusive: stability or residual-whiteness check failed | 1 | rank 1 detected |

VAR uses weekly log changes, AIC-selected lags and ADF checks on exactly the model sample, followed by stability and residual-whiteness checks. Only passing models support inference; their directional p-values are Holm-adjusted as a family in `var_granger.json`. A failed prerequisite is inconclusive, not evidence of absence. Johansen reports ranks 0, 1 and 2 separately and checks compatibility with I(1) inputs. Full rank and mixed integration orders are not reported as absence of cointegration. Granger describes predictive precedence within the model, not economic causality.

## Forward associations (L4)

| Metric | IC 12w vs BTC | Exploratory 95% interval | n |
|---|---|---|---|
| active_accounts | -0.03 | -0.25 to +0.19 | 286 |
| txns | -0.05 | -0.31 to +0.21 | 286 |
| tx_fee_near | -0.02 | -0.27 to +0.24 | 286 |
| tx_volume_usd | -0.16 | -0.37 to +0.04 | 286 |
| intents_volume_usd | -0.58 | -0.73 to -0.13 | 80 |
| qaa | +0.32 | -0.02 to +0.72 | 56 |

Declared family: 24 tests, two horizons and two benchmarks. Signal is the four-week change in a trailing four-week mean; target is forward excess log return. Circular block resampling addresses dependence approximately; the individual intervals are exploratory, and familywise Bonferroni intervals are reported separately. The half-sample split is a stability summary, not walk-forward portfolio evaluation. No returns after the analysis cutoff enter a target.

## Relative valuation and scenarios

Cross-chain settlement/TVL and local-chain DEX/TVL have different scopes. Peer ranks are descriptive, not like-for-like proof of undervaluation. Gross app-fee/market-cap is not shareholder yield.

The scenario model draws 20,000 assumptions around observed gross take rate and net capture; future allocation is discretionary. Median market-cap/illustrative retained-fees multiple 598x, range p5–p95 197x–1,563x. The gas-fee term is a paid-fee proxy, not audited net burn; no net-deflation, fair-price or price-forecast claim is made.

## What changes the verdict

- Independent full-day or routed-batch reconciliation would strengthen the descriptive evidence. The numerical consistency criterion is ci_lo <= 1.0 <= ci_hi: the conditional 95% interval of the on-chain estimate / DefiLlama ratio must include 1.0 on matched days. Current ratio 0.253, interval [0.178, 0.327], over 46 matched days: failing. Coverage is 49 sampled days and 4892 blocks in fixed intraday windows, not complete-day extracts. Full-day coverage of those days and independent routed-batch/pricing reconciliation are still missing. A passing conditional interval alone would not validate population coverage or economic swap reconstruction; the sample does not identify how many additional complete days would suffice.
- Audited net receipts, executed purchases and supply effects may strengthen or weaken the value-capture case; gross volume alone does not decide it.
- Stable out-of-sample associations with past-only features, dependence-aware uncertainty and multiplicity control are needed before usage can be called a return signal.
- Strong sensitivity to clustering, sampling hours or role thresholds weakens the behavioral interpretation. Verified anchors remain an external data need.

## Gaps, provenance and reproduction

Raw and extracted inputs and frozen model artifacts are hashed in `docs/REPRODUCIBILITY.md`. Revenue definitions are stored in the raw responses. BigQuery is optional: its runner checks freshness before L1/L2; actual queries and credentials were not needed for this block-sample build. The suggested track deliverable, a swap-volume pull from the Intents Explorer API, is not implemented: the team has no partner JWT for Explorer. Setting INTENTS_EXPLORER_JWT alone does not enable a pull; an explicit request fails clearly. DefiLlama/Dune is the substitute reference for the FastNear on-chain sample cross-check, not an Explorer API result or a completed Explorer deliverable. On-chain publication is an optional dry-run-capable feature, not a claimed deployed result.

`uv sync --locked --all-extras && make build && make test && make check-generated`; open `site/index.html` and `site/walkthrough.html`. Sampling limits: `docs/SAMPLING.md`.
