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

Latest sensitivity: strict multi-app share 0.0%; default share 62.0%; including ambiguous groups 68.3%. Name-proxy profiles are in `qaa_anchor_profiles.csv`; monthly group counts permit composition checks. Verified human/bot anchor labels are not available. In sampled mode, shares are rescaled by NearBlocks mean daily active accounts; an inclusion-probability weighting is reported below as a sensitivity, and these remain exploratory proxies with no guaranteed conservative bias.

**Past-only QAA for predictive tests:** a separate GMM is calibrated through 2025-04-30, then its scaler, parameters and label mapping are frozen. Only later months are predicted; first availability is 2025-06-01. Each month becomes available on the first day of the following month. The full-history descriptive clustering is never fed into signal or Granger tests. The model is frozen calibration, not monthly walk-forward retraining.

**Scope and sensitivity of the behavioral groups (2026-10).** Groups are named after observed behavior (`intents_participant`: median share of actions sent to intents.near above 20%, `high_frequency_regular`: median of at least 200 transactions per month with regular inter-arrival gaps (gap CV below 0.6), `miniapp_pattern`: at least half of the accounts carry a .tg or .sweat name and the median account touches fewer than two contracts, `heavy_unclassified`: median of at least 200 transactions per month without a regular gap pattern, `multi_app`: median account touches at least two contracts or two methods, `light_general`: none of the above: few actions, no mini-app name pattern, `noise`: HDBSCAN outliers, not assigned to any group). Criteria: strict 0.0% (multi_app only), default 62.0%, including ambiguous groups 68.3%. 91% of account-months show exactly one transaction inside the sampled windows and 95% are active in a single window, so multi-contract behavior is rarely observable; no cluster reaches a median of two contracts.
A name-only split (accounts without a `.tg`/`.sweat` name) gives 64.4%; its mean absolute difference from the default share over all months is 1.7% (correlation 0.98), so in these sparse windows the clustering adds little beyond the name class. Inclusion-probability weighting (accounts active in fewer windows are under-observed) moves the latest share from 62.0% to 60.6%. This is a sensitivity under stated assumptions (each account's per-window activity probability is constant over the month and estimated from the same windows that observe it; windows are independent draws for every account; the fixed 03:00/15:00 UTC design is treated as if it were random; accounts never seen in any window have no weight: the index covers observed accounts only; heterogeneity between accounts beyond activity frequency is ignored), not a demonstrated correction of the observation bias; never-observed accounts stay outside the index, so the QAA count is an illustrative rescaling and the share is the measured quantity.
By observation hour the latest share is 3:00 UTC 55.7%, 15:00 UTC 68.6%; mean absolute difference between hours 4.3%.
The frozen past-only model labels the same latest month at 20.0% against 62.0% for the retrospective clustering (mean absolute difference 14.9%, correlation 0.77 over 18 months): the level depends on the model, the trend less so.
Label-threshold variants of the default share: heavy_txns=100,multi_contracts=2: 62.0%; heavy_txns=200,multi_contracts=1: 93.7%; heavy_txns=400,multi_contracts=2: 62.0%; heavy_txns=200,multi_contracts=3: 62.0%. Noise excluded/included: 62.0%/68.3%. Typical and least-typical account-months per group are in `qaa_examples.json`. Not done: refits with other clustering hyper-parameters (platform-dependent HDBSCAN assignments would break the exact regression check; the committed assignment is reused); external human/bot labels (none available).

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

## Reconciliation of the on-chain estimate

**Economic unit.** USD notional of settled swaps per UTC calendar day on intents.near. Our measure: half gross participant notional: for each successful execute_intents receipt, for each (account, intent_hash) take the larger of priced inflow and priced outflow, sum over participants and divide by two. One two-party swap of 100 USDC against NEAR counts 100 USD once. Scope: token_diff events emitted by intents.near in receipts with an explicit successful execution status; all chains and assets that appear in those events; no deposits, withdrawals or transfers. Prices: DefiLlama coins daily USD prices (CoinGecko ids from the committed 1Click registry), stablecoins at par, at most seven-day forward fill; unknown or unpriced assets contribute zero. Reference: DefiLlama dexs/near-intents dailyVolume = SUM(volume_amount_usd) FROM dune.near.dataset_near_intents_metrics per date_at (adapter source: DefiLlama/dimension-adapters dexs/near-intents/index.ts). The dataset is a curated Dune table maintained for NEAR's metrics; whether volume_amount_usd is one-sided or two-sided notional is not published, so the two measures are compared, not assumed identical. DefiLlama does not compute this series itself; it queries Dune. A second reference independent of Dune was not accessible without credentials (Dune API key or Intents Explorer JWT).

**Pooled result.** Estimate / reference 0.253, conditional day-bootstrap interval [0.178, 0.327] over 46 matched days. The per-day table (`intents_reconciliation_daily.csv`) lists observed sampled volume, expansion factor, expanded estimate, reference, difference, window split, unpriced legs and unvalued account-intents for each of the 49 sampled days.

**Temporal coverage.** Two 50-block windows observe 0.09% of a day's blocks. On days where both windows carry volume the 15:00 UTC window has 4.8x the 03:00 volume (median over 30 days); one window carries over 80% of the day's sampled volume on 59% of days.

**Intraday expansion error (measured).** Selection rule, declared before fetching: sampled days with both fixed windows usable and a DefiLlama reference; pick the highest-volume day, the day closest to the 2026 median and the day closest to the 2025 median; declared before fetching. Hourly windows of 50 blocks, fetched 2026-11-07T04:55:45+00:00.

| Day | Hourly windows | Fixed-hours share of sampled volume | Estimate from 24 hours / reference | Estimate from fixed hours / reference | Bias factor |
|---|---|---|---|---|---|
| 2025-08-31 | 24 | 1.1% | 1.501 | 0.194 | 7.72 |
| 2026-04-13 | 24 | 4.2% | 0.374 | 0.187 | 2.00 |
| 2026-09-25 | 24 | 3.0% | 0.871 | 0.309 | 2.82 |

Median bias factor 2.82 (mean 4.18; on 2025-08-31 the 18:00 window alone carries 94% of the day's sampled volume). Estimates from all 24 hours reach 0.87x the reference (median over the three days). Factor > 1 means the two fixed windows under-represent the day's hourly mean; even 24 hourly windows observe about 1,200 of ~150,000 blocks, so this measures the intraday expansion error, not a complete day. The median across days is used for the correction because a single hourly window can carry most of a day's sampled volume and dominate the mean.

**Validation of the intraday factor (declared 2026-11-07, after the motivating days were measured and before any validation block was fetched).** Selection: sampled days with both fixed windows usable and a DefiLlama reference, excluding the three motivating days, sorted chronologically; take the days at positions floor(n/4), floor(n/2) and floor(3n/4). Aggregation: median of the per-day fixed-window bias factors over the validation days. Acceptance: the motivating median is considered supported if the validation median lies within x0.5 to x2 of it; the range reflects the day-level dispersion already observed on the motivating days (2.0 to 7.7). The declared estimator stays uncorrected; the factor is published as a sensitivity in either outcome. Status: pending: validation days not fetched yet (make blocks-intraday-validation).

**Valuation.** 222 of 3844 legs (5.8%) are unpriced, but an account-intent is valued by whichever side is priced: only 20 of 1870 account-intents in 16 batches lose value entirely. For the 1577 account-intents with both sides priced, inflow/outflow has median 1.000 and 5th-95th percentiles 0.970-1.026: daily prices and decimals are consistent across legs. Unpriced assets and the reason for each: pol (52 legs: price snapshot polygon-ecosystem-token is empty (DefiLlama coins API returned no history)); sweat (24 legs: price snapshot sweatcoin is empty (DefiLlama coins API returned no history)); xlm (10 legs: no price snapshot for stellar); bera (8 legs: price snapshot berachain-bera is empty (DefiLlama coins API returned no history)); gno (6 legs: no price snapshot for gnosis); aurora (6 legs: no price snapshot for aurora-near).

**Route reconstruction.** 52% of batches have more than two accounts; per-token diffs within a receipt balance to rounding dust (99th percentile of |net|/gross 8.0e-04). Sampled totals under alternative definitions: half gross participant notional $407.4K, full gross $814.8K, user-side notional with heuristic roles $395.2K. If the reference counted both sides of each swap our ratio would be 0.51; this is a definitional bound, not evidence about the reference.

**Residual.** After the measured intraday bias (median factor 2.82) the ratio would be 0.71 (1.06 with the mean factor); a factor of 1.4x to parity remains unexplained and is reported as such, not attributed to missing large trades. If the reference additionally counted both sides the corrected ratio would be 1.42; that exceeds parity, which shows the two readings cannot both be taken at face value together but does not identify which one overstates: estimation error and unidentified components remain.

**Pre-declared tolerance and holdout.** Tolerance (2026-11-06, before evaluating the holdout days): point ratio within [0.8, 1.25] and interval covering 1.0; covers measured pricing dispersion (a few percent), not coverage or definitional gaps. Split: sampled days with a positive reference value are sorted chronologically; even positions calibrate, odd positions validate; declared before evaluation. Calibration days (23): 0.210 [0.114, 0.305]. Validation days (23): 0.297 [0.186, 0.416]. Verdict: validation days outside the declared tolerance: the on-chain estimate does not reproduce the reference level.

Traceable examples from receipt and log to priced legs and batch volume (`intents_trace_examples.json`): simple_two_party_fully_priced, multi_participant_batch, unpriced_leg_valued_by_other_side, account_intent_without_any_price, largest_sampled_batch, legacy_single_object_event_2024. Not possible here: complete-day extracts (FastNear public rate limit ~0.35 blocks/s; a NEAR day has ~150,000 blocks); a second reference independent of Dune (no Dune API key or Intents Explorer JWT); the published definition of volume_amount_usd in dune.near.dataset_near_intents_metrics.

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

## Out-of-sample evaluation (retrospective, temporally separated)

Scope: retrospective validation with temporal separation: protocol and split declared 2026-11-06 over a history that earlier exploratory analyses of this project had already used; the code enforces calibration/evaluation separation but cannot establish that the evaluation period was unknown when the protocol was designed. Prospective use: this protocol is not re-tuned; a prospective result uses only data published after 2026-11-06; not evaluable under the declared calibration end; their prospective plan freezes calibration at the data cutoff and evaluates 20 weeks of data published after it (purged by h); the dates are listed per test and nothing is scored before then.

Protocol: a four-week rise in usage is associated with the subsequent h-week NEAR log return in excess of the benchmark, with the sign fixed in calibration. Signal: weekly means of the daily series; log of the trailing four-week mean, differenced by four weeks; QAA only from the frozen past-only model, available on the first day of the following month. Target: forward h-week log return of NEAR minus the same return of the benchmark (BTC or ETH). Calibration ends 2025-06-29; evaluation starts h weeks after the calibration end so that no calibration target overlaps an evaluation week. Rule: the sign of the calibration Spearman IC is frozen; success requires the evaluation IC under that sign to be positive with the Bonferroni-adjusted (24 tests) circular block-bootstrap 95% interval above zero; the unadjusted interval is reported as exploratory only. Benchmark predictors: the two naive predictors are not members of the 24-test family and are not tested for passing; their evaluation IC is a comparison level that a usage metric should exceed to add information beyond persistence and the market. Walk-forward: expanding window: each evaluation week re-estimates the sign on targets already realized at that week (purged by h) and predicts the direction of the next target; hit rate reported. Family: 6 metrics x 2 horizons x 2 benchmarks = 24 declared tests; Bonferroni intervals reported.

**Result: no usage metric passes the declared familywise out-of-sample criterion** (0 of 16 evaluable usage tests pass the familywise criterion; 0 pass the unadjusted interval only; not evaluable: intents_volume_usd h=4 vs btc, qaa h=4 vs btc, intents_volume_usd h=4 vs eth, qaa h=4 vs eth, intents_volume_usd h=12 vs btc, qaa h=12 vs btc, intents_volume_usd h=12 vs eth, qaa h=12 vs eth). Best naive-benchmark evaluation IC 0.43.

| Predictor | h | vs | Calibration IC (n) | Evaluation IC, signed (n) | 95% block interval (exploratory) | Familywise interval (criterion) | Walk-forward hit rate | Status |
|---|---|---|---|---|---|---|---|---|
| active_accounts | 4 | btc | +0.11 (228) | +0.18 (62) | -0.09 to +0.48 | -0.26 to +0.63 | 61% (62) | no out-of-sample association established |
| txns | 4 | btc | -0.03 (228) | -0.06 (62) | -0.50 to +0.44 | -0.60 to +0.68 | 44% (62) | no out-of-sample association established |
| tx_fee_near | 4 | btc | -0.08 (228) | -0.17 (62) | -0.65 to +0.40 | -0.80 to +0.62 | 42% (62) | no out-of-sample association established |
| tx_volume_usd | 4 | btc | -0.06 (228) | -0.21 (62) | -0.52 to +0.15 | -0.69 to +0.41 | 44% (62) | no out-of-sample association established |
| intents_volume_usd | 4 | btc | n=22 | n=62 | | | | not evaluable: too few calibration or evaluation weeks; evaluable from 2027-04-18 under the fixed plan |
| qaa | 4 | btc | n=0 | n=62 | | | | not evaluable: too few calibration or evaluation weeks; evaluable from 2027-04-18 under the fixed plan |
| near_momentum | 4 | btc | +0.01 (231) | -0.25 (62) | -0.60 to +0.03 | -0.80 to +0.19 | 50% (62) | no out-of-sample association established |
| btc_trend | 4 | btc | +0.27 (231) | +0.27 (62) | -0.33 to +0.70 | -0.72 to +0.84 | 50% (62) | no out-of-sample association established |
| active_accounts | 4 | eth | +0.05 (228) | +0.03 (62) | -0.27 to +0.36 | -0.45 to +0.52 | 50% (62) | no out-of-sample association established |
| txns | 4 | eth | -0.03 (228) | +0.08 (62) | -0.36 to +0.55 | -0.49 to +0.75 | 53% (62) | no out-of-sample association established |
| tx_fee_near | 4 | eth | -0.11 (228) | -0.05 (62) | -0.57 to +0.51 | -0.76 to +0.69 | 50% (62) | no out-of-sample association established |
| tx_volume_usd | 4 | eth | -0.04 (228) | -0.13 (62) | -0.46 to +0.23 | -0.65 to +0.40 | 52% (62) | no out-of-sample association established |
| intents_volume_usd | 4 | eth | n=22 | n=62 | | | | not evaluable: too few calibration or evaluation weeks; evaluable from 2027-04-18 under the fixed plan |
| qaa | 4 | eth | n=0 | n=62 | | | | not evaluable: too few calibration or evaluation weeks; evaluable from 2027-04-18 under the fixed plan |
| near_momentum | 4 | eth | +0.05 (231) | -0.08 (62) | -0.48 to +0.23 | -0.72 to +0.36 | 40% (62) | no out-of-sample association established |
| btc_trend | 4 | eth | +0.16 (231) | +0.31 (62) | -0.24 to +0.69 | -0.64 to +0.83 | 52% (62) | no out-of-sample association established |
| active_accounts | 12 | btc | +0.04 (228) | -0.26 (46) | -0.66 to +0.22 | -0.83 to +0.46 | 46% (46) | no out-of-sample association established |
| txns | 12 | btc | +0.06 (228) | -0.32 (46) | -0.63 to +0.28 | -0.76 to +0.62 | 37% (46) | no out-of-sample association established |
| tx_fee_near | 12 | btc | +0.08 (228) | -0.39 (46) | -0.69 to +0.25 | -0.82 to +0.60 | 33% (46) | no out-of-sample association established |
| tx_volume_usd | 12 | btc | -0.10 (228) | +0.51 (46) | -0.32 to +0.79 | -0.75 to +0.95 | 74% (46) | no out-of-sample association established |
| intents_volume_usd | 12 | btc | n=22 | n=46 | | | | not evaluable: too few calibration or evaluation weeks; evaluable from 2027-06-13 under the fixed plan |
| qaa | 12 | btc | n=0 | n=46 | | | | not evaluable: too few calibration or evaluation weeks; evaluable from 2027-06-13 under the fixed plan |
| near_momentum | 12 | btc | -0.03 (231) | +0.26 (46) | -0.36 to +0.73 | -0.65 to +0.93 | 52% (46) | no out-of-sample association established |
| btc_trend | 12 | btc | +0.02 (231) | +0.40 (46) | +0.00 to +0.67 | -0.30 to +0.81 | 65% (46) | nominal interval above zero only: exploratory, not accepted under the familywise criterion |
| active_accounts | 12 | eth | +0.04 (228) | -0.37 (46) | -0.77 to +0.14 | -0.92 to +0.42 | 46% (46) | no out-of-sample association established |
| txns | 12 | eth | +0.12 (228) | -0.36 (46) | -0.74 to +0.25 | -0.85 to +0.55 | 30% (46) | no out-of-sample association established |
| tx_fee_near | 12 | eth | +0.10 (228) | -0.44 (46) | -0.81 to +0.20 | -0.88 to +0.46 | 28% (46) | no out-of-sample association established |
| tx_volume_usd | 12 | eth | -0.14 (228) | +0.54 (46) | -0.25 to +0.85 | -0.70 to +0.93 | 83% (46) | no out-of-sample association established |
| intents_volume_usd | 12 | eth | n=22 | n=46 | | | | not evaluable: too few calibration or evaluation weeks; evaluable from 2027-06-13 under the fixed plan |
| qaa | 12 | eth | n=0 | n=46 | | | | not evaluable: too few calibration or evaluation weeks; evaluable from 2027-06-13 under the fixed plan |
| near_momentum | 12 | eth | -0.06 (231) | +0.43 (46) | -0.22 to +0.87 | -0.48 to +0.94 | 61% (46) | no out-of-sample association established |
| btc_trend | 12 | eth | -0.05 (231) | -0.46 (46) | -0.70 to -0.07 | -0.78 to +0.20 | 35% (46) | no out-of-sample association established |

Prospective plan for the tests that are not evaluable (fixed now, not to be re-tuned): calibration on every signal week with a realized target at the data cutoff, sign frozen there, purge h weeks, then 20 evaluation signal weeks whose targets realize after the cutoff, under the same familywise criterion. Earliest scoring dates: intents_volume_usd h=4 vs btc from 2027-04-18; qaa h=4 vs btc from 2027-04-18; intents_volume_usd h=4 vs eth from 2027-04-18; qaa h=4 vs eth from 2027-04-18; intents_volume_usd h=12 vs btc from 2027-06-13; qaa h=12 vs btc from 2027-06-13; intents_volume_usd h=12 vs eth from 2027-06-13; qaa h=12 vs eth from 2027-06-13.

Limitations: NearBlocks and DefiLlama series are current snapshots: historical revisions and publication lags are not reconstructed, except QAA availability dates; overlapping weekly targets; block bootstrap approximates dependence; descriptive association only: no costs, liquidity or execution rules, so no trading claim. A negative or inconclusive result is a valid outcome and is carried into the verdict; no trading strategy is proposed.

## Relative valuation and scenarios

Cross-chain settlement/TVL and local-chain DEX/TVL have different scopes. Peer ranks are descriptive, not like-for-like proof of undervaluation. Gross app-fee/market-cap is not shareholder yield.

The scenario model draws 20,000 assumptions around observed gross take rate and net capture; future allocation is discretionary. Median market-cap/illustrative retained-fees multiple 598x, range p5–p95 197x–1,563x. The gas-fee term is a paid-fee proxy, not audited net burn; no net-deflation, fair-price or price-forecast claim is made.

## Value bridge: from settlement to the token

Trailing year to 2026-11-01. Each step states whether it is observed, classified, inferred or unavailable (observed: read from a public source and reproducible from the committed snapshot; classified: a rule applied by the data provider; inferred: computed from observed items under a stated assumption; unavailable: not obtainable without credentials or absent on-chain).

| Step | USD | Share of previous | Status | Source |
|---|---|---|---|---|
| 1. Settled volume through Intents | $32.8B |  | observed (third-party series) | DefiLlama dexs/near-intents dailyVolume, a pass-through of dune.near.dataset_near_intents_metrics |
| 2. Gross swap fees | $54.2M | 0.2% | observed (third-party series) | DefiLlama fees/near-intents dailyFees: protocol fee plus affiliate fees across integrators (Dune datasets) |
| 3. Net revenue captured by NEAR (NEAR/wNEAR swept into revenue wallets) | $9.3M | 17.2% | observed (adapter wallet receipts) | DefiLlama dailyRevenue: TRANSFER and wrap.near inflows to fefundsadmin, 1csfundsadmin and buybacks wallets, internal hops excluded |
| 4. Revenue labelled as buyback (dates on or after 2026-02-23) | $7.5M | 81.0% | classified by an adapter date rule, not by transaction | DefiLlama dailyHoldersRevenue = dailyRevenue on or after BUYBACK_START |
| 5. NEAR withdrawn from Intents into buybacks.multisignature.near | $4.5M | 59.4% | observed (receipts, valued at the daily NEAR price); attribution to executed purchases inferred | https://api.nearblocks.io/v1/account/buybacks.multisignature.near/txns?per_page=250 (paginated) |
| 6. Destination at the analysis cutoff (ledger reconstructed from receipts) | 2,150,198 NEAR | 99.4% | inferred: balance at the cutoff reconstructed from receipts; the snapshot balance is shown separately at its own date | NearBlocks receipts to 2026-11-01; account snapshot 2026-11-07T00:13:36+00:00 |

- Step 2: take rate 16.5 bps of volume.
- Step 3: sweeps are periodic, so a day's receipts can exceed that day's fees.
- Step 5: 3081 inbound transfers from intents.near from 2026-03-18 to 2026-11-01; a further 510,068 NEAR arrived from the other revenue wallets (treasury moves, excluded here as the adapter excludes them) and 8,293 NEAR from other accounts. Trace of a pre-declared sample (45 of 3197 receipts, every 80th plus the five largest): 45 match a dip4 native_withdraw of wrapped NEAR from 16 distinct Intents-side accounts; for 16 the funding swap (token_diff of the same account, 16 buying wrap.near) is in the same blocks, for the other 29 it is outside the blocks read and the purchase is not observed. Receipts excluded: 0 failed, 0 without an explicit status. The wallet was created 2026-03-18, after the adapter's buyback start 2026-02-23, so labelled revenue before that date cannot be matched to this wallet.
- Step 6: inbound before the cutoff minus outbound (12,025 NEAR) minus gas, divided by all inbound NEAR before the cutoff. Snapshot balance at fetch 2,202,268 NEAR versus 2,202,268 NEAR reconstructed to the same date (residual -0.3 NEAR); inflows after the cutoff 52,070 NEAR. No burn observed; holding is not supply destruction.

**What the receipts establish.** A pre-declared sample of 45 of 3197 inbound receipts (inbound TRANSFER receipts from intents.near sorted by block timestamp: every 80th receipt starting at the first, plus the five largest by amount) was traced to the Intents events between the originating transaction and the receipt: 45 match a `native_withdraw` of wrapped NEAR from 16 distinct Intents-side accounts, and 16 show the funding `token_diff` of the same account in the same blocks (16 buying wrap.near). For the remaining 29 the swap is outside the blocks read and is not observed. The NEAR arrived as a withdrawal from an Intents-side account balance (observed for every sampled receipt); the purchase itself is the earlier token_diff of the same account, observed only when it falls inside the blocks read, so purchase attribution for the whole inflow remains inferred. At the trace time 0 of those accounts still held tokens inside Intents.

**Ledger reconciliation.** Sum of successful inbound TRANSFER receipts minus outbound TRANSFER receipts minus gas of wallet-signed transactions; no storage or staking terms. Reconstructed to the snapshot date: 2,202,268 NEAR against a snapshot balance of 2,202,268 NEAR (residual -0.3 NEAR, -0.0000% of inflows). Reconstructed to the analysis cutoff 2026-11-01: 2,150,198 NEAR; 52,070 NEAR arrived after the cutoff and are excluded from the bridge.

**Issuance and dilution (observed: NearBlocks daily total supply).** Total supply change: protocol issuance net of gas burn; unlocks of already-issued tokens are not dilution of supply. Total supply 1,278,952,621 to 1,310,576,026 NEAR: 31,623,406 new NEAR (2.47%), $65.6M at the average price. The buyback wallet received 1,643,862 NEAR from Intents, 5.2% of issuance (purchase attribution inferred). The NearBlocks circulating-supply field is constant since 2025-08-27 and is not used. Buybacks are held, not burned, so they do not reduce supply and are not netted twice: issuance is counted once here and buybacks once above.

| Scenario | Volume | Take rate | Capture | Allocation to buybacks | New supply | Buyback accrual | Issuance | Net yield on market cap |
|---|---|---|---|---|---|---|---|---|
| adverse | $16.4B | 12.4 bps | 12.9% | 50% | 39,529,257 NEAR | $1.3M | $82.0M | -1.39% |
| base | $32.8B | 16.5 bps | 17.2% | 81% | 31,623,406 NEAR | $7.5M | $65.6M | -1.00% |
| favorable | $65.5B | 20.7 bps | 21.5% | 100% | 23,717,554 NEAR | $29.1M | $49.2M | -0.35% |

Dominant assumption (one at a time: each input moved from its base to its adverse value, others held at base; ranked by the absolute change in net yield): **issuance**; ranking by effect: issuance (-0.28%), volume (-0.06%), allocation (-0.05%), take_rate (-0.03%), capture (-0.03%). What weakens the thesis: issuance above buyback accrual in every scenario means settlement growth does not translate into net token accrual; a fall in volume or capture, or an allocation decision away from buybacks, removes the accrual entirely Scenarios are illustrative, not forecasts; every multiplier is in `value_bridge.json`.

## What changes the verdict

- Independent full-day or routed-batch reconciliation would strengthen the descriptive evidence. The numerical consistency criterion is ci_lo <= 1.0 <= ci_hi: the conditional 95% interval of the on-chain estimate / DefiLlama ratio must include 1.0 on matched days. Current ratio 0.253, interval [0.178, 0.327], over 46 matched days: failing. Coverage is 49 sampled days and 4892 blocks in fixed intraday windows, not complete-day extracts. Full-day coverage of those days and independent routed-batch/pricing reconciliation are still missing. A passing conditional interval alone would not validate population coverage or economic swap reconstruction; the sample does not identify how many additional complete days would suffice.
- Audited net receipts, executed purchases and supply effects may strengthen or weaken the value-capture case; gross volume alone does not decide it.
- Stable out-of-sample associations with past-only features, dependence-aware uncertainty and multiplicity control are needed before usage can be called a return signal.
- Strong sensitivity to clustering, sampling hours or role thresholds weakens the behavioral interpretation. Verified anchors remain an external data need.

## Evidence status of the main claims

| Claim | Status | Where to verify |
|---|---|---|
| Activity counts fell while value per transaction and reported settlement rose | observed (third-party series) | Observed activity table; `docs/METRICS.md` |
| Intents captures net revenue and NEAR reaches the buyback wallet | observed (adapter receipts; wallet receipts as Intents withdrawals); purchase attribution inferred | Value bridge; `value_bridge.json` |
| Received NEAR is held, not burned | inferred (ledger reconstructed at the cutoff; snapshot balance observed at fetch) | Value bridge step 6 |
| Issuance exceeds buyback accrual | observed issuance vs scenario accrual | Value bridge scenarios |
| The on-chain sample reproduces the reference level | estimate: failing (outside declared tolerance) | Reconciliation; `docs/RECONCILIATION.md` |
| Departing accounts were bots | not established: behavioral groups only; name-only split tracks the share | Quality-adjusted accounts (L1) |
| Usage predicts forward excess returns | inconclusive out of sample | Out-of-sample evaluation; Forward associations |
| Token undervaluation | not claimed | Relative valuation and scenarios |

## Gaps, provenance and reproduction

Raw and extracted inputs and frozen model artifacts are hashed in `docs/REPRODUCIBILITY.md`. Revenue definitions are stored in the raw responses. BigQuery is optional: its runner checks freshness before L1/L2; actual queries and credentials were not needed for this block-sample build. The suggested track deliverable, a swap-volume pull from the Intents Explorer API, is not implemented: the team has no partner JWT for Explorer. Setting INTENTS_EXPLORER_JWT alone does not enable a pull; an explicit request fails clearly. DefiLlama/Dune is the substitute reference for the FastNear on-chain sample cross-check, not an Explorer API result or a completed Explorer deliverable. On-chain publication is an optional dry-run-capable feature, not a claimed deployed result.

`uv sync --locked --all-extras && make build && make test && make check-generated`; open `site/index.html` and `site/walkthrough.html`. Sampling limits: `docs/SAMPLING.md`; reconciliation method, unit and tolerance: `docs/RECONCILIATION.md`.
