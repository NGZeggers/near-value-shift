# Sampling design and limits

L1/L2 use BigQuery extracts when present; otherwise they use the committed FastNear block sample. The source is named in THESIS.md. The public block endpoint is `https://mainnet.neardata.xyz/v0/block/{height}`.

## Observation frame

The current plan starts on 2024-11-04 and observes one day every 15 days, two UTC windows (03:00 and 15:00), and 50 consecutive block heights per window. Skipped block heights are recorded. The manifests distinguish requested, fetched, missing and usable windows. Window starts are located within 90 seconds of the target time. These are fixed windows, not a probability sample of all hours; conventional population confidence guarantees do not follow.

`make blocks BLOCKS=100` tops up the cached plan. The default approximately 4,900-height sample took several hours to acquire under the public API rate limit. `make build` never downloads blocks.

## L1: behavioral proxy

Features are aggregated by account-month inside usable windows. Rows in the block CSV are actions, not unique transaction hashes. Self-call indicators compare signer and receiver before aggregation. Activity frequency is divided by observed windows, not calendar days; gaps are measured inside a window only. Names, methods, receivers, regularity and deposits are proxy features.

Retrospective HDBSCAN clusters all observed months for descriptive charts. A separate GMM fits only the first six calendar months, selects 3–6 components by BIC, then freezes scaler, component parameters and label mapping. Only subsequent months enter predictive tests, available on the first day of the next month. The frozen model is committed in `qaa_causal_model.json`; future observations cannot change its training set. This is frozen calibration, not repeated walk-forward retraining.

QAA in sampled mode multiplies the observed quality-like share by NearBlocks monthly mean daily active accounts. Account inclusion depends on transaction frequency; the monthly sampled-account share and population daily-active share need not agree. QAA is therefore exploratory, with no guarantee of conservative bias or verified human identity. Silhouette measures geometric separation. Anchor-name profiles are weak proxies, not ground-truth accuracy. Strict/default/including-ambiguous shares and monthly cluster counts expose sensitivity and composition drift.

## L2: participant flows and heuristic roles

For each receipt, account and intent, sum priced incoming and outgoing token diffs separately. Take the larger side, sum across participants and divide by two. This retains multiple participants/intents within a receipt. A two-user batch paying 10 and 20 USDC against unpriced assets retains 30 USD, rather than the largest user's 20 USD. The measurement is half gross participant notional; complex routes, unbalanced/incomplete logs and partially priced intents can differ from economic swap volume. It is not a guaranteed lower bound or a validated reconstruction of every swap.

The registry supplies asset decimals; historical prices are loaded once, with at most seven-day forward fill. Stablecoin-at-par and historical registry assumptions remain limitations. Report both any-priced-batch coverage, fully priced batch coverage and priced-leg count share. None identifies the USD share of unpriced assets.

Role rules are explicit. Full-day mode requires at least 20 batches and 10 counterparties per account-day. Sampled mode also accepts at least 5 batches, 5 counterparties and 2% of that day's batches. Sensitivity repeats 1%, 2% and 5%. Concentration refers to classified solvers inside the observed windows, not all global solvers.

Only additive batch/flow/withdrawal counts are expanded by blocks-in-day divided by blocks observed. **Unique users remain observed counts**. No daily-user upper-bound claim is made. All usable sampled days are retained, including observed zero-token-diff days; an unavailable window is not a zero observation.

## Aggregation and reconciliation

Monthly/quarterly flow estimates use the mean of expanded sampled days times calendar days (or the reference series' available days for partial quarters). Day-bootstrap intervals condition on those observed days and do not account for intraday selection, missing large trades, pricing or route reconstruction. One observed day cannot identify an interval; its endpoints are missing.

The pooled sample/reference ratio uses sums on matched reference days, including observed zeros. Quarterly ratios are displayed rather than assumed constant. Parity must fall inside the conditional interval to pass the project's consistency check. If it does not, THESIS.md calls the cross-check unresolved and treats it as evidence against independent confirmation. Missing large trades are a possible explanation, not an established cause. Full-day BigQuery extracts improve coverage but do not automatically fix pricing, role or reconstruction errors.

## Receipt status and input validation

New extracts admit only explicit `SUCCESS_VALUE` or `SUCCESS_RECEIPT_ID` outcomes. Failure and unknown protocol variants do not produce settlement logs. Slim block caches from before schema version 2 lost status information and are re-fetched rather than upgraded by assumption.

A legacy event CSV without `execution_status` makes L2 return `computed=false` and remove stale numerical outputs; the notebook, thesis and dashboard explain why. The current CSV was revalidated on 2026-11-05 against all 1,189 blocks containing the original events, retaining 7,227 successful logs and excluding 53 failed-receipt logs. Its hashes and counts are in `data/blocks/event_verification.json`; detailed evidence is in `audit/2026-11-05-revalidation/`. This does not revalidate blocks absent from the original event extract or prove full-market coverage. Run `make verify-events` to re-fetch event-bearing blocks, match receipt ID/caller/log/timestamp and exclude failures. Verification is resumable through versioned caches and replaces the CSV only after every event is checked. `--offline` never fetches a missing or legacy cache. This is public-source reconciliation, not a cryptographic proof of execution.

Pricing uses exact, case-sensitive asset IDs from the committed token registry. Unknown or differently cased identifiers stay unpriced; name substrings no longer establish asset identity. Malformed account-intent items are rejected as a whole and counted; any rejection disables production L2 metrics instead of publishing a partial estimate.
