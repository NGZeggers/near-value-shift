# Plan v2: "From clicks to settlement" (NEAR Investment Thesis, track `thesis`)

Status: proposal after the first checkpoint. Supersedes the descriptive-only plan in DATA_PLAN.md.
Team: two data-science master's students + Claude Code. Deadline 2026-11-14 23:59 UTC.

## Why v2

The v1 plan (public API series + charts + THESIS.md) satisfies the track but any team with a
coding agent can produce it in a day. v2 keeps v1 as the reproducible base and adds four layers
that need real data engineering, unsupervised learning and econometrics. Judges can still
reproduce everything with one command, because every raw extract is cached in the repo.

## Thesis (unchanged, now testable with stronger instruments)

NEAR's economic activity is shifting from high-count, low-value retail transactions (2024 mini-app
era) to lower-count, higher-value cross-chain settlement through NEAR Intents. Raw activity metrics
understate the network; value-weighted and quality-adjusted metrics show growth decoupled from price.

## The five layers

### L0. Reproducible data layer (base, v1)
Public, key-less sources cached as raw snapshots: NearBlocks daily charts (2020->), DefiLlama
(Intents volume, chain DEX volume, TVL, fees, stablecoins, peers), NEAR RPC (validators, stake),
CoinGecko (price, BTC/ETH benchmarks), GitHub (developer activity). One command rebuilds everything.

### L1. Quality-Adjusted Active Accounts (QAA) via behavioral clustering  [UNIQUE]
Source: BigQuery `transactions` + `receipt_actions` (+ `account_changes` for creation metadata).
Per account-month features (2023-01 -> 2026-10): tx count, active days, distinct receivers,
distinct `method_name`, FUNCTION_CALL share, TRANSFER share, median/CV of inter-arrival time
(regularity = automation), total deposit, gas paid, name pattern (`*.tg`, `*.sweat`, implicit hex
accounts, `*.near` named), account age.
Model: log-transform + robust scaling -> HDBSCAN (fallback GMM with BIC) -> label clusters with
anchors (known relayers, HOT `*.tg` mini-app accounts, Sweat, Intents solver accounts, DeFi users).
Output: monthly QAA series = accounts in "human-like" clusters, with cluster shares over time.
Validation: silhouette, stability across months, confusion vs anchor labels. Sensitivity: results
with and without the ambiguous clusters.
Why it matters: it replaces the 200-tx heuristic with a learned segmentation and lets us say
"active accounts fell 90% from 2024, but QAA fell X%" with a defensible method.

### L2. NEAR Intents microstructure from raw on-chain events  [UNIQUE]
Source: BigQuery `execution_outcomes.logs` where `executor_account_id = 'intents.near'`, parsing
`EVENT_JSON:` DIP-4 events (`token_diff`, `intents_executed`, `mt_transfer`, `*_withdraw`).
Reconstruction: group `token_diff` entries by `intent_hash`/batch; opposite diffs identify the two
counterparties; the account that is repeatedly on the providing side across many users = solver.
Metrics (daily, 2024-11 -> 2026-11): swaps, unique users, unique solvers, top-1/top-5 solver share,
HHI, median trade size (USD via stable leg or CoinGecko daily price), asset and chain mix,
withdrawal share (volume that actually leaves vs stays), independent volume estimate to cross-check
DefiLlama/Dune (with sampling confidence intervals).
Cost control: `bq --dry_run` gate before every query; stratified day sampling (e.g. 2 days per
week) if full scans exceed the 1 TiB sandbox budget. Sampling design and CI are part of the method.

### L3. Econometrics on the regime shift
- Structural breaks: PELT / binary segmentation (`ruptures`) on log daily active accounts, txns,
  fee USD, Intents volume. Expect breaks at the 2024 mini-app ramp and the 2025 Intents ramp.
- Lead-lag: ADF tests, VAR on weekly d-log series (price, QAA, Intents volume, fee USD), Granger
  causality with lag selection by AIC, impulse responses. Report p-values and robustness to lags.
- Cointegration (Johansen) between price and value-weighted usage. If nothing cointegrates, say so.
- Rolling 90-day correlations price vs each usage metric (the "decoupling" chart, one axis, indexed).

### L4. Signal value and relative valuation
- Forward-return test: do 4-week changes in QAA / Intents volume predict 4- and 12-week forward
  NEAR returns in excess of BTC and ETH? Walk-forward, Spearman IC, with multiple-testing caveat.
  A null result is reported as evidence against the "usage leads price" reading.
- Peer panel (Solana, Base, Arbitrum, Polygon, Avalanche, Sui, Aptos, NEAR): fees/market cap,
  DEX volume/TVL velocity, stablecoin supply/TVL. NEAR as emphasis series.
- Scenario model (explicitly labeled scenarios, not forecasts): fee accrual to NEAR under
  Intents-volume and take-rate assumptions, Monte Carlo over the assumption ranges.

## Deliverables
- `THESIS.md` generated from pipeline outputs (claim, evidence for, evidence against, what would
  change our mind, data gaps and sampling design). No hand-typed numbers.
- Static dashboard (GitHub Pages): every chart with its query/source and one plain sentence,
  hover layer, table view, dark mode.
- Notebooks for L1-L4 rendered to HTML, plus the scripts that produce the same outputs headless.
- `make all` (or `uv run invoke all`): fetch -> bq (if configured) -> features -> models -> charts -> thesis.
- Tests for metric functions; a reproducibility report with SHA-256 of every raw snapshot.
- Stretch (NEAR integration beyond data): daily QAA index + methodology hash posted to a NEAR
  testnet contract from GitHub Actions, so the index is verifiable on-chain. Week 2 only if ahead.

## Stack
Python 3.12 via `uv` (pandas, polars optional, statsmodels, scikit-learn, hdbscan, ruptures,
scipy, matplotlib for notebook figures), `google-cloud-bigquery` or the `bq` CLI, Jupyter for
exploration, plain HTML/SVG for the dashboard (no JS build step). Node is not required.

## Team split (proposal)
- Person A: BigQuery, feature engineering, L1 clustering, L2 event parsing and sampling design.
- Person B: L3 econometrics, L4 signal test and peer valuation, THESIS.md narrative.
- Claude Code: scaffolding, data layer, dry-run cost gate, dashboard, README, tests, CI, video script.

## Timeline (13 days)
| Days | Milestone |
|---|---|
| Nov 1-2 | gcloud + BigQuery sandbox, `uv` env, L0 fetchers, Q0 freshness, dry-run costs for L1/L2 |
| Nov 3-5 | L1 features + first clustering; L2 event parser on a 2-week sample |
| Nov 6-8 | L2 full/sampled run; L3 breaks, VAR, Granger; L4 IC test |
| Nov 9-10 | Dashboard, THESIS.md generation, notebooks rendered, peer panel |
| Nov 11-12 | README "do X, see Y", tests, GitHub Pages, demo video, X post draft |
| Nov 13 | Buffer, final re-run from clean clone, submit (one day before deadline) |

## MVP cut line (if behind schedule)
Must ship: L0 + L1 + L3 + deliverables. Next: L2 (sampled). Last: L4 scenarios, on-chain index.

## Risks and mitigations
- BigQuery scan size: dry-run gate; sampling; cluster-friendly filters on `block_date`; export
  intermediate aggregates to repo so reruns are free.
- Dataset freshness (NEAR Lake deprecated 2026-03-24): run Q0 first; if stale, L1/L2 end at the last
  indexed date and recent weeks use NearBlocks + RPC sampling; THESIS.md states it.
- USD pricing of Intents legs: anchor on stablecoin legs; CoinGecko daily prices for majors; report
  the share of volume priced each way.
- Scope: MVP cut line above; Claude keeps the pipeline green daily.

## Status (updated 2026-11-02)
| Layer | State |
|---|---|
| L0 | done: 45 hashed snapshots, derived tables, `make fetch` |
| L1 | computed on a partial block sample (743 of 4,900 blocks, 2024-11 to 2025-02): QAA ~24% of active accounts, the rest clusters as mini-app farming; `make blocks` extends the sample (~5 h), `make bq` replaces it |
| L2 | computed on the same partial sample: real DIP-4 events parsed and priced via the 1Click token registry; independent 2025-01 volume $5.2M vs DefiLlama $6.4M; solver concentration needs the full sample |
| L3 | done: breaks, ADF, VAR/Granger, Johansen, correlations |
| L4 | done: IC with block bootstrap, peer panel, Monte Carlo scenarios |
| Out | THESIS.md generated and deterministic, dashboard (light/dark, tooltips, table views, range filter), executed notebook, CI + Pages workflow, demo script |
| Stretch | on-chain index publisher to NEAR Social testnet implemented as dry run; signing waits for the team's keys |
| Pending on the team | BigQuery sandbox (optional now), GitHub repo + push, X post, mainnet payout account, video |
