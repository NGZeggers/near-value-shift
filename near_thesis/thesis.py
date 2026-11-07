"""Generate the argument and provenance from outputs; conclusions respect diagnostics and gaps."""
from __future__ import annotations

import hashlib
import json

import pandas as pd

from .config import DATA, DERIVED, DOCS, MODELS, ROOT
from . import narrative
from .http import raw_manifest


def usd(v, d=1):
    if v is None or pd.isna(v):
        return "n/a"
    a = abs(v)
    if a >= 1e9: return f"${v/1e9:.{d}f}B"
    if a >= 1e6: return f"${v/1e6:.{d}f}M"
    if a >= 1e3: return f"${v/1e3:.{d}f}K"
    return f"${v:.2f}"


def num(v, d=0):
    return "n/a" if v is None or pd.isna(v) else f"{v:,.{d}f}"


def pct(a, b):
    return "n/a" if not b or pd.isna(a) or pd.isna(b) else f"{(a/b-1)*100:+.0f}%"


def _json(name):
    return json.loads((MODELS / name).read_text())


def _opt(name):
    f = MODELS / name
    return json.loads(f.read_text()) if f.exists() else {}


def _kind(label: str) -> str:
    return f"[{label}]"


def build() -> str:
    d = pd.read_csv(DERIVED / "daily.csv", parse_dates=["date"]).set_index("date")
    m = pd.read_csv(DERIVED / "monthly.csv", parse_dates=["month"]).set_index("month")
    y = pd.read_csv(DERIVED / "yearly.csv").set_index("year")
    full = m[m.index + pd.offsets.MonthEnd(0) <= d.index.max()]
    last = full.iloc[-1]
    lm = str(last.name.date())[:7]
    qs, ins, sc = _json("qaa_status.json"), _json("intents_status.json"), _json("scenarios.json")
    vg, jo, ic = _json("var_granger.json"), _json("johansen.json"), _json("signal_ic.json")
    ratio = ins.get("ratio_to_defillama") or {}
    cross_ok = bool(ins.get("cross_check_passed"))
    inputs = sc["inputs"]
    out = ["# From clicks to settlement: an investment thesis on NEAR\n",
           f"Generated from committed snapshots; analysis through {d.index.max().date()}. `make build` rebuilds this argument, tables, dashboard and executed notebook. Numbers are computed; interpretation and source context are explicit.\n",
           "## Claim and current verdict\n",
           "NEAR's reported activity is shifting from high transaction/account counts toward cross-chain settlement. That is a claim about composition, not proof of token undervaluation or future returns. QAA is a behavioral proxy, not a count of verified humans.\n",
           "**" + narrative.verdict_statement(bool(ins.get("computed")), cross_ok) + "**\n",
           "## Observed activity\n",
           "| Metric (daily mean) | " + " | ".join(str(i) for i in y.index) + " |",
           "|---|" + "---|" * len(y.index)]
    for title, col, fmt in [("Transactions", "txns", num), ("Active accounts", "active_accounts", num),
                            ("USD moved per transaction", "usd_per_txn", usd), ("Gas fees paid, USD", "tx_fee_usd", usd),
                            ("Intents volume, USD", "intents_volume_usd", usd), ("NEAR price", "near_price", usd)]:
        out.append(f"| {title} | " + " | ".join(fmt(y.loc[i, col]) for i in y.index) + " |")
    out += [f"\nLatest full month ({lm}): Intents volume {usd(last.intents_volume_usd)}, mean daily active accounts {num(last.active_accounts)}, "
            f"USD moved per transaction {usd(last.usd_per_txn)}. Latest year has {int(y.iloc[-1]['days'])} observed days.\n",
            "## Evidence for\n",
            "- The reported Intents volume and raw activity series have diverged. This supports a change in composition, subject to source coverage. Native NEAR transfer volume and Intents cross-chain settlement are different measurements, not interchangeable totals.",
            "- A quality adjustment can distinguish behavioral groups. Its uncertainty and sensitivity are reported below; it does not establish that departing accounts were actual bots.",
            "- Intents already has a revenue mechanism. The economic question is how much is retained and allocated, rather than whether any capture exists.\n",
            "## Revenue mechanics: observed capture versus future allocation\n",
            "NEAR's [February 2026 explanation](https://www.near.org/blog/evolving-near-tokenomics) describes an active fee switch and governance-controlled buybacks. "
            "Its [Q2 update](https://www.near.org/blog/the-state-of-near-q-2-2026) describes revenue-funded purchases. These are primary-source context, not a guarantee of dividends or continued purchases. "
            "The [DefiLlama adapter](https://github.com/DefiLlama/dimension-adapters/blob/master/fees/near-intents/index.ts) measures net NEAR/wNEAR receipts into revenue wallets, excludes internal wallet hops, and labels captured revenue after its buyback start as HoldersRevenue. "
            "That classification is not transaction-level proof of each purchase or of burning.\n",
            f"On the analysis cutoff's trailing year: gross Intents fees {usd(inputs['intents_fees_12m_usd'])}; net captured receipts {usd(inputs.get('intents_net_revenue_12m_usd'))}; "
            f"buyback-labelled revenue {usd(inputs.get('intents_holders_revenue_12m_usd'))}. Ratio of net receipts to gross fees: {num(None if inputs.get('observed_capture_share') is None else 100 * inputs['observed_capture_share'], 2)}%. "
            "Receipts are realized in sweeps and can exceed fees on an individual day. The snapshots carry the adapter definitions and are cut to the same analysis end date. "
            "No independent wallet-level purchase audit or supply-destruction calculation is claimed. Gas fees paid are not automatically net supply burn across all historical protocol versions.\n",
            "## Evidence against and unresolved tests\n",
            "- Greater settlement volume does not mechanically imply greater token returns. Gross fees are not token-holder yield; net capture, future allocation and issuance still matter."]
    if ratio:
        out.append(f"- The independent sample-to-DefiLlama ratio is {ratio['ratio']:.3f}, conditional day-bootstrap interval [{ratio['ci_lo']:.3f}, {ratio['ci_hi']:.3f}], over {ratio['days']} matched days. "
                   + ("The interval contains parity." if cross_ok else "The interval excludes parity: our consistency criterion fails, so independent confirmation of the total and trend is not established."))
    elif not ins.get('computed'):
        out.append('- Independent L2 validation is unavailable: ' + ins.get('reason', 'no verified extract'))
    int_ic = next((r for r in ic if r['metric'] == 'intents_volume_usd' and r.get('horizon_weeks') == 12 and r.get('benchmark') == 'btc' and 'spearman_ic' in r), None)
    if int_ic:
        lo, hi = int_ic['ci95_block_bootstrap']
        out.append(f"- Intents growth versus twelve-week forward NEAR excess returns over BTC: IC {int_ic['spearman_ic']:+.2f}, exploratory 95% block interval [{lo:+.2f}, {hi:+.2f}], n={int_ic['n']}. "
                   f"First/second chronological halves: {int_ic['ic_first_half']:+.2f}/{int_ic['ic_second_half']:+.2f}. These are descriptive association checks, not a validated trading signal.")
    out += ["- Fixed intraday windows, sparse sampling, role assumptions, unpriced assets and routed batches can all affect the on-chain comparison. Their separate contributions are not identified.\n",
            "## Quality-adjusted accounts (L1)\n"]
    if qs.get('computed'):
        q = pd.read_csv(MODELS / 'qaa_monthly.csv', parse_dates=['month']).set_index('month')
        pk = q.active_accounts_bq.idxmax()
        out += [f"Source: {qs['source']}; {qs['n']:,} account-months, {qs['months']} months. Retrospective {qs['algorithm']} with corrected self-call counts and window-normalized activity. "
                f"At {str(pk.date())[:7]} QAA was {num(q.loc[pk,'qaa'])}; at {str(q.index[-1].date())[:7]} it was {num(q.iloc[-1].qaa)}. "
                f"The corresponding behavioral shares are {q.loc[pk,'qaa_share']:.1%} and {q.iloc[-1].qaa_share:.1%}. "
                f"Silhouette on at most 3,000 observations: {num(qs.get('silhouette_sample'),2)}. Separation is not human/bot accuracy.\n",
                f"Latest sensitivity: strict multi-app share {q.iloc[-1].quality_share_strict:.1%}; default share {q.iloc[-1].qaa_share:.1%}; including ambiguous groups {q.iloc[-1].quality_share_including_ambiguous:.1%}. "
                "Name-proxy profiles are in `qaa_anchor_profiles.csv`; monthly group counts permit composition checks. Verified human/bot anchor labels are not available. "
                "In sampled mode, shares are rescaled by NearBlocks mean daily active accounts; an inclusion-probability weighting is reported below as a sensitivity, and these remain exploratory proxies with no guaranteed conservative bias.\n"]
        causal = qs.get('causal', {})
        if causal.get('computed'):
            out.append(f"**Past-only QAA for predictive tests:** a separate GMM is calibrated through {causal['training_end']}, then its scaler, parameters and label mapping are frozen. "
                       f"Only later months are predicted; first availability is {causal['first_available_at']}. Each month becomes available on the first day of the following month. "
                       "The full-history descriptive clustering is never fed into signal or Granger tests. The model is frozen calibration, not monthly walk-forward retraining.\n")
        out += qaa_scope_section(qs)
    else:
        out.append(f"Not computed: {qs.get('reason')}.\n")
    out += ["## Intents microstructure (L2)\n"]
    if ins.get('computed'):
        cov = ins.get('coverage', {})
        out.append(f"Source: {ins['source']}. {cov.get('blocks_fetched','n/a')} blocks, {ins['sampled_days']} sampled days including observed zero-event days; "
                   f"{ins.get('days_with_token_diff','n/a')} days contain token_diff. Parsed {ins['events']:,} events. {ins['solver_accounts']} accounts satisfy the role heuristic ({ins['assumptions']['mode']}).\n")
        out.append(f"Valuation: {ins['volume_method']}. Batch coverage with any priced leg {ins['priced_batch_share_mean']:.1%}; fully priced batches {ins['fully_priced_batch_share_mean']:.1%}; priced token-diff legs {ins['priced_leg_share']:.1%}. "
                   "Leg coverage is a count share, not a known USD share. Observed users are never multiplied into daily unique users. Solvers and HHI are within-window estimates, not full-market concentration.\n")
        iq = pd.read_csv(MODELS / 'intents_quarterly.csv')
        out.append("| Quarter | Sampled days | Flow estimate / DefiLlama |\n|---|---|---|")
        for r in iq.itertuples(): out.append(f"| {r.quarter[:7]} | {r.sampled_days} | {num(r.ratio,3)} |")
        out.append("\nIntervals condition on the observed sampled days; they omit intraday, routing and pricing uncertainty. One-day strata have no estimable interval. "
                   "The estimator now retains multiple account-intents in a receipt; it still does not identify every economic swap. The gap is unresolved, not a proven tail effect or a guaranteed lower bound. "
                   "Full-day extracts would improve coverage but would not automatically validate this estimator. Role sensitivity is in `intents_solver_sensitivity.json`.\n")
    else:
        out.append('Not computed: ' + ins.get('reason', 'no verified extract') + '\n')
    out += reconciliation_section()
    out += ["## Econometrics (L3)\n", narrative.granger_summary(vg) + "\n",
            "| Metric | Weeks | VAR status | Johansen rank | Johansen status |\n|---|---|---|---|---|"]
    jmap = {r['metric']: r for r in jo}
    for r in vg:
        j = jmap.get(r['metric'], {})
        vstatus = 'diagnostics passed' if r.get('inference_valid') else r.get('note', 'inconclusive')
        out.append(f"| {r['metric']} | {r['n_weeks']} | {vstatus} | {j.get('rank_5pct','n/a')} | {j.get('note','inconclusive')} |")
    out.append("\nVAR uses weekly log changes, AIC-selected lags and ADF checks on exactly the model sample, followed by stability and residual-whiteness checks. "
               "Only passing models support inference; their directional p-values are Holm-adjusted as a family in `var_granger.json`. A failed prerequisite is inconclusive, not evidence of absence. "
               "Johansen reports ranks 0, 1 and 2 separately and checks compatibility with I(1) inputs. Full rank and mixed integration orders are not reported as absence of cointegration. "
               "Granger describes predictive precedence within the model, not economic causality.\n")
    out += ["## Forward associations (L4)\n", "| Metric | IC 12w vs BTC | Exploratory 95% interval | n |\n|---|---|---|---|"]
    for r in ic:
        if r.get('horizon_weeks') == 12 and r.get('benchmark') == 'btc' and 'spearman_ic' in r:
            lo, hi = r['ci95_block_bootstrap']
            out.append(f"| {r['metric']} | {r['spearman_ic']:+.2f} | {lo:+.2f} to {hi:+.2f} | {r['n']} |")
    out.append(f"\nDeclared family: {len(ic)} tests, two horizons and two benchmarks. Signal is the four-week change in a trailing four-week mean; target is forward excess log return. "
               "Circular block resampling addresses dependence approximately; the individual intervals are exploratory, and familywise Bonferroni intervals are reported separately. "
               "The half-sample split is a stability summary, not walk-forward portfolio evaluation. No returns after the analysis cutoff enter a target.\n")
    out += oos_section()
    out += ["## Relative valuation and scenarios\n",
            "Cross-chain settlement/TVL and local-chain DEX/TVL have different scopes. Peer ranks are descriptive, not like-for-like proof of undervaluation. Gross app-fee/market-cap is not shareholder yield.\n",
            f"The scenario model draws {sc['n']:,} assumptions around observed gross take rate and net capture; future allocation is discretionary. "
            f"Median market-cap/illustrative retained-fees multiple {num(sc['price_to_fees']['p50'])}x, range p5–p95 {num(sc['price_to_fees']['p5'])}x–{num(sc['price_to_fees']['p95'])}x. "
            "The gas-fee term is a paid-fee proxy, not audited net burn; no net-deflation, fair-price or price-forecast claim is made.\n",
            *bridge_section(),
            "## What changes the verdict\n",
            *["- " + change for change in narrative.verdict_changes(ins)], "",
            "## Evidence status of the main claims\n",
            "| Claim | Status | Where to verify |\n|---|---|---|",
            *evidence_rows(ins), "",
            "## Gaps, provenance and reproduction\n",
            "Raw and extracted inputs and frozen model artifacts are hashed in `docs/REPRODUCIBILITY.md`. Revenue definitions are stored in the raw responses. "
            "BigQuery is optional: its runner checks freshness before L1/L2; actual queries and credentials were not needed for this block-sample build. "
            "The suggested track deliverable, a swap-volume pull from the Intents Explorer API, is not implemented: "
            "the team has no partner JWT for Explorer. Setting INTENTS_EXPLORER_JWT alone does not enable a pull; "
            "an explicit request fails clearly. DefiLlama/Dune is the substitute reference for the FastNear on-chain sample cross-check, "
            "not an Explorer API result or a completed Explorer deliverable. On-chain publication is an optional dry-run-capable feature, not a claimed deployed result.\n",
            "`uv sync --locked --all-extras && make build && make test && make check-generated`; open `site/index.html` and `site/walkthrough.html`. Sampling limits: `docs/SAMPLING.md`; reconciliation method, unit and tolerance: `docs/RECONCILIATION.md`.\n"]
    return '\n'.join(out)


def qaa_scope_section(qs: dict) -> list[str]:
    sens = _opt('qaa_sensitivity.json')
    if not sens:
        return []
    scope, crit = sens['scope'], sens['criteria']
    rows = [f"**Scope and sensitivity of the behavioral groups ({sens['latest_month']}).** Groups are named after observed behavior ({', '.join(f'`{k}`: {v}' for k, v in qs.get('group_definitions', {}).items())}). "
            f"Criteria: strict {crit['strict']:.1%} ({sens['criteria']['groups_counted']['strict'][0]} only), default {crit['default']:.1%}, including ambiguous groups {crit['including_ambiguous']:.1%}. {crit['why_strict_is_low']}.",
            f"A name-only split (accounts without a `.tg`/`.sweat` name) gives {sens['name_only_baseline']['latest_month']:.1%}; its mean absolute difference from the default share over all months is {sens['name_only_baseline']['mean_abs_difference_vs_default']:.1%} "
            f"(correlation {sens['name_only_baseline']['correlation_with_default']:.2f}), so in these sparse windows the clustering adds little beyond the name class. "
            f"Inclusion-probability weighting (accounts active in fewer windows are under-observed) moves the latest share from {sens['inclusion_probability_weighting']['latest_month_unweighted']:.1%} to {sens['inclusion_probability_weighting']['latest_month_weighted']:.1%}. "
            "This is a sensitivity under stated assumptions (" + "; ".join(sens['inclusion_probability_weighting'].get('assumptions', [])) + "), not a demonstrated correction of the observation bias; "
            "never-observed accounts stay outside the index, so the QAA count is an illustrative rescaling and the share is the measured quantity."]
    if sens.get('inclusion_from_intraday_days'):
        inc = sens['inclusion_from_intraday_days']; pl = inc['pooled']; nq = pl['name_only_quality_share']; strata = pl['inclusion_by_activity']
        rows.append(f"**Inclusion measured within the day ({len(inc['design']['days'])} days with 24 hourly windows).** On the days that carry 24 windows of the same 50-block design, the two fixed windows observe {pl['inclusion_overall']:.1%} of the accounts seen across all 24 "
                    f"({pl['accounts_fixed_windows']:,} of {pl['accounts_24_windows']:,} account-days pooled): {strata['1 window']['inclusion']:.1%} of accounts active in a single window, {strata['9-24 windows']['inclusion']:.1%} of those active in nine or more. "
                    f"Inclusion by name class: " + ", ".join(f"{k} {v['inclusion']:.1%}" for k, v in pl['inclusion_by_name_class'].items() if v['accounts'] >= 100) + ". "
                    f"The composition shift is large: the name-only quality share is {nq['fixed_windows']:.1%} among accounts the fixed windows observe and {nq['all_24_windows']:.1%} among all accounts seen in 24 windows; the inclusion weighting applied to the fixed-window data moves it to {nq['fixed_windows_inclusion_weighted']:.1%}, "
                    f"in the right direction on {inc['weighting_check']['days_where_weighting_moves_toward_fuller_observation']} of {inc['weighting_check']['days_compared']} days but recovering only a small part of the gap. "
                    f"Multi-receiver behavior is observable for {pl['multi_receiver_observable_share']['fixed_windows']:.1%} of fixed-window accounts against {pl['multi_receiver_observable_share']['all_24_windows']:.1%} under 24 windows. "
                    "Reading: within a day, the two-window design over-represents frequent and named accounts, so a share computed on it sits above the share among all accounts active that day, and the weighting sensitivity under-corrects. "
                    "This is an observed within-day quantity on six days chosen for the volume reconciliation; it does not identify the month-level bias of the QAA share, and 24 windows still observe under one percent of a day's blocks. The published QAA share is therefore an upper reading for the observed-account population, not a population estimate.")
    if sens.get('refits'):
        rf = sens['refits']; lo, hi = rf['default_share_range']
        rows.append(f"**Refits ({rf['computed_on']}, `make qaa-refits`).** Refitting the clustering with other hyper-parameters and an alternative algorithm gives latest-month default shares between {lo:.1%} and {hi:.1%} (committed assignment {crit['default']:.1%}): "
                    + "; ".join(f"{v['variant']} ARI {v['adjusted_rand_index_vs_committed']:.2f}, default {v['latest_month_share']['default']:.1%}" for v in rf['variants'])
                    + ". HDBSCAN variants agree with the committed partition (adjusted Rand index above 0.97) and move the default share by a few points; the Gaussian mixture partitions differently (ARI below 0.3) and gives a lower share. The level depends on the model; the committed assignment remains the baseline and these are sensitivities.")
    if sens.get('by_window_hour'):
        bh = sens['by_window_hour']
        rows.append("By observation hour the latest share is " + ", ".join(f"{h}:00 UTC {v:.1%}" for h, v in bh['latest_month'].items()) + f"; mean absolute difference between hours {bh['mean_abs_difference_between_hours']:.1%}.")
    if sens.get('model_agreement'):
        ma = sens['model_agreement']
        rows.append(f"The frozen past-only model labels the same latest month at {ma['latest']['frozen']:.1%} against {ma['latest']['descriptive']:.1%} for the retrospective clustering (mean absolute difference {ma['mean_abs_difference']:.1%}, correlation {ma['correlation']:.2f} over {ma['months']} months): the level depends on the model, the trend less so.")
    rows.append("Label-threshold variants of the default share: " + "; ".join(f"{k}: {v:.1%}" for k, v in sens['label_threshold_variants_default_share'].items())
                + f". Noise excluded/included: {sens['noise_bounds_default_share']['noise_excluded']:.1%}/{sens['noise_bounds_default_share']['noise_included']:.1%}. "
                "Typical and least-typical account-months per group are in `qaa_examples.json`. Not done: " + "; ".join(sens['not_done']) + ".\n")
    return rows


def reconciliation_section() -> list[str]:
    rec = _opt('intents_reconciliation.json')
    if not rec.get('computed'):
        return ["## Reconciliation of the on-chain estimate\n", "Not computed: " + rec.get('reason', 'the block-sample L2 layer is unavailable') + "\n"]
    eu, comp, hold = rec['economic_unit'], rec['components'], rec['holdout']
    cov, val, rt, res = comp['temporal_coverage'], comp['valuation'], comp['route_reconstruction'], comp['residual']
    pooled = rec['pooled_ratio_all_days']
    out = ["## Reconciliation of the on-chain estimate\n",
           f"**Economic unit.** {eu['unit']}. Our measure: {eu['our_measure']} Scope: {eu['scope']}. Prices: {eu['prices']}. Reference: {eu['reference']} {eu['shared_origin']}\n",
           f"**Pooled result.** Estimate / reference {pooled['ratio']:.3f}, conditional day-bootstrap interval [{pooled['ci_lo']:.3f}, {pooled['ci_hi']:.3f}] over {pooled['days']} matched days. "
           f"The per-day table (`intents_reconciliation_daily.csv`) lists observed sampled volume, expansion factor, expanded estimate, reference, difference, window split, unpriced legs and unvalued account-intents for each of the {cov['days_sampled']} sampled days.\n",
           f"**Temporal coverage.** Two 50-block windows observe {cov['block_coverage_share_mean']:.2%} of a day's blocks. "
           + (f"On days where both windows carry volume the 15:00 UTC window has {cov['between_window_ratio_15_over_03']['median']:.1f}x the 03:00 volume (median over {cov['between_window_ratio_15_over_03']['days_both_positive']} days); "
              if cov.get('between_window_ratio_15_over_03', {}).get('median') else "")
           + f"one window carries over 80% of the day's sampled volume on {cov['share_of_days_one_window_carries_over_80pct']:.0%} of days.\n"]
    intra = rec.get('intraday') or {}
    if intra.get('days'):
        out.append(f"**Intraday expansion error (measured).** Selection rule, declared before fetching: {intra['selection_rule']}. Hourly windows of {intra['blocks_per_window']} blocks, fetched {intra['fetched_at']}.\n")
        out.append("| Day | Hourly windows | Fixed-hours share of sampled volume | Estimate from 24 hours / reference | Estimate from fixed hours / reference | Bias factor |\n|---|---|---|---|---|---|")
        for dday in intra['days']:
            if dday.get('hours_usable'):
                out.append(f"| {dday['day']} | {dday['hours_usable']} | {num(100 * dday['fixed_hours_share_of_sampled'], 1) if dday.get('fixed_hours_share_of_sampled') is not None else 'n/a'}% | "
                           f"{num(dday.get('ratio_all_hours_to_reference'), 3)} | {num(dday.get('ratio_fixed_hours_to_reference'), 3)} | {num(dday.get('fixed_window_bias_factor'), 2)} |")
            else:
                out.append(f"| {dday['day']} | 0 | n/a | n/a | n/a | n/a |")
        conc = max((d for d in intra.get('days', []) if d.get('largest_hour_share_of_sampled')), key=lambda d: d['largest_hour_share_of_sampled'], default=None)
        out.append(f"\nMedian bias factor {num(intra.get('fixed_window_bias_factor_median'), 2)} (mean {num(intra.get('fixed_window_bias_factor_mean'), 2)}"
                   + (f"; on {conc['day']} the {conc['largest_hour']}:00 window alone carries {conc['largest_hour_share_of_sampled']:.0%} of the day's sampled volume" if conc else "") + "). "
                   f"Estimates from all 24 hours reach {num(intra.get('ratio_all_hours_to_reference_median'), 2)}x the reference (median over the three days). {intra['reading']}.\n")
    else:
        out.append("**Intraday expansion error.** Not measured yet: `make blocks-intraday` fetches 24 hourly windows for three pre-declared days (highest reference volume, 2026 median day, 2025 median day).\n")
    iv = rec.get('intraday_validation') or {}
    if iv:
        rule = iv['rule']
        out.append(f"**Validation of the intraday factor (declared {rule['declared']}).** Selection: {rule['selection']}. Aggregation: {rule['aggregation']}. Acceptance: {rule['acceptance']}. {rule['not_a_correction_of_the_estimator'][0].upper() + rule['not_a_correction_of_the_estimator'][1:]}. "
                   + (f"Result: validation days {', '.join(d['day'] for d in iv.get('days', []))}; per-day factors "
                      + ", ".join(f"{d['day']} {num(d['fixed_window_bias_factor'], 2) if d.get('fixed_window_bias_factor') else ('unbounded (fixed windows observed no volume)' if d['day'] in (iv.get('days_with_unbounded_factor') or []) else 'undefined')}" for d in iv.get('days', []))
                      + f"; median over the {iv.get('days_with_defined_factor')} defined days {num(iv.get('validation_median_factor'), 2)} versus {num(iv.get('motivating_median_factor'), 2)} on the motivating days (ratio {num(iv.get('ratio_validation_over_motivating'), 2)})"
                      + (f", {num(iv.get('validation_median_factor_unbounded_as_infinite'), 2)} with the unbounded day treated as infinite (ratio {num(iv.get('ratio_validation_over_motivating_unbounded_as_infinite'), 2)})" if iv.get('days_with_unbounded_factor') else "")
                      + f". Verdict: {iv.get('verdict', '')}. The validation days are three; this supports the order of magnitude of the sensitivity, not a precise correction.\n"
                      if iv.get('validation_median_factor') else f"Status: {iv['status']}.\n"))
    chk = val['two_sided_pricing_check']
    out.append(f"**Valuation.** {val['legs_unpriced']} of {val['legs_total']} legs ({val['legs_unpriced_share']:.1%}) are unpriced, but an account-intent is valued by whichever side is priced: only {val['account_intents_without_any_priced_side']} of {val['account_intents']} account-intents in {val['batches_with_unvalued_account_intent']} batches lose value entirely. "
               f"For the {chk['account_intents_two_sided']} account-intents with both sides priced, inflow/outflow has median {chk['in_over_out']['p50']:.3f} and 5th-95th percentiles {chk['in_over_out']['p5']:.3f}-{chk['in_over_out']['p95']:.3f}: daily prices and decimals are consistent across legs. "
               "Unpriced assets and the reason for each: " + "; ".join(f"{a['symbol'] or a['asset_id'][:28]} ({a['legs']} legs: {a['reason']})" for a in val['unpriced_assets_top'][:6]) + ".\n")
    alt = rt['alternative_definitions_total_usd']
    out.append(f"**Route reconstruction.** {rt['batches_with_more_than_two_accounts_share']:.0%} of batches have more than two accounts; per-token diffs within a receipt balance to rounding dust (99th percentile of |net|/gross {rt['per_token_net_relative_to_gross']['p99']:.1e}). "
               f"Sampled totals under alternative definitions: half gross participant notional {usd(alt['half_gross_participant_notional'])}, full gross {usd(alt['full_gross_participant_notional'])}, user-side notional with heuristic roles {usd(alt['user_side_notional_heuristic_roles'])}. "
               f"If the reference counted both sides of each swap our ratio would be {res['if_reference_were_two_sided_notional']:.2f}; this is a definitional bound, not evidence about the reference.\n")
    if res.get('after_intraday_bias_correction'):
        rd = rec.get('reference_definition') or {}
        ci = rd.get('confidential_intents') or {}
        cap = lambda t: (t[:1].upper() + t[1:]) if t else t
        out.append(f"**What the reference counts.** {rd.get('adapter', {}).get('query', '')}. {cap(rd.get('dataset_maintainer', {}).get('claim', ''))} ({rd.get('dataset_maintainer', {}).get('kind', '')}). "
                   f"{cap(ci.get('claim', ''))} ({ci.get('source', '')}): cumulative USD {ci.get('cumulative_usd_billion', {}).get('public')}B public, {ci.get('cumulative_usd_billion', {}).get('confidential')}B confidential, {ci.get('cumulative_usd_billion', {}).get('dune_total')}B total, a confidential share of {res['confidential_intents_share_of_reference']:.1%}; {cap(ci.get('kind', ''))}. {cap(ci.get('implication', ''))}. "
                   f"Other references found: " + "; ".join(f"{k}: {v}" for k, v in (rd.get('other_references') or {}).items()) + f". One- or two-sided: {rd.get('one_or_two_sided', '')}.\n")
        out.append(f"**Residual.** Excluding the confidential share of the reference raises the ratio from {res['pooled_ratio']:.3f} to {res['after_confidential_intents_exclusion']:.3f} (estimate). After the measured intraday bias (median factor {res['intraday_bias_factor_used']:.2f}) the ratio would be {res['after_intraday_bias_correction']:.2f} "
                   f"({res['after_intraday_bias_correction_mean_factor']:.2f} with the mean factor), and {res['after_confidential_and_intraday']:.2f} with both identified components; a factor of {res['unexplained_factor_after_confidential_and_intraday']:.1f}x to parity remains unexplained and is reported as such, not attributed to missing large trades. "
                   f"If the reference additionally counted both sides the corrected ratio would be {res['after_both']:.2f}"
                   + ("; that exceeds parity, which shows the two readings cannot both be taken at face value together but does not identify which one overstates: estimation error and unidentified components remain.\n" if res.get('two_sided_and_intraday_overshoot') else ".\n"))
    else:
        out.append(f"**Residual.** A factor of {res['unexplained_factor_to_parity']:.1f}x to parity remains unexplained and is reported as such, not attributed to missing large trades.\n")
    cal, valid = hold['calibration'], hold['validation']
    tol = hold['tolerance']
    out.append(f"**Pre-declared tolerance and holdout.** Tolerance ({tol['declared']}): point ratio within [{tol['point_ratio_min']}, {tol['point_ratio_max']}] and interval covering {tol['interval_must_include']}; {tol['justification']}. Split: {hold['rule']}. "
               f"Calibration days ({cal.get('days', 0)}): {num(cal.get('ratio'), 3)} [{num(cal.get('ci_lo'), 3)}, {num(cal.get('ci_hi'), 3)}]. Validation days ({valid.get('days', 0)}): {num(valid.get('ratio'), 3)} [{num(valid.get('ci_lo'), 3)}, {num(valid.get('ci_hi'), 3)}]. "
               f"Verdict: {hold['verdict']}.\n")
    out.append("Traceable examples from receipt and log to priced legs and batch volume (`intents_trace_examples.json`): " + ", ".join(rec['trace_examples']) + ". Not possible here: " + "; ".join(rec['not_possible_here']) + ".\n")
    return out


from .signal import OOS_PROTOCOL as _OOS_P
OOS_MIN_EVAL = _OOS_P['minimum_rows']['evaluation']


def oos_section() -> list[str]:
    o = _opt('signal_oos.json')
    if not o.get('tests'):
        return []
    p, sm = o['protocol'], o['summary']
    out = ["## Out-of-sample evaluation (retrospective, temporally separated)\n",
           f"Scope: {p['declaration']}. Prospective use: {p['prospective']['rule']}; {p['prospective']['intents_and_qaa']}.\n",
           f"Protocol: {p['hypothesis']}. Signal: {p['signal_transform']}. Target: {p['target']}. Calibration ends {p['calibration_end']}; {p['purge']}. Rule: {p['fixed_rule']}. Benchmark predictors: {p['benchmark_predictor_treatment']}. Walk-forward: {p['walk_forward']}. Family: {p['family']}.\n",
           f"**Result: {sm['conclusion']}** ({sm['passing']} of {sm['evaluable']} evaluable usage tests pass the familywise criterion; {sm.get('passing_nominal_only', 0)} pass the unadjusted interval only; not evaluable: {', '.join(sm['not_evaluable']) or 'none'}). Best naive-benchmark evaluation IC {num(sm.get('best_naive_benchmark_ic'), 2)}.\n",
           "| Predictor | h | vs | Calibration IC (n) | Evaluation IC, signed (n) | 95% block interval (exploratory) | Familywise interval (criterion) | Walk-forward hit rate | Status |\n|---|---|---|---|---|---|---|---|---|"]
    for r in o['tests']:
        if 'ic_evaluation_signed' in r:
            lo, hi = r['ci95_block_bootstrap']; flo, fhi = r['ci95_familywise_bonferroni']
            out.append(f"| {r['predictor']} | {r['horizon_weeks']} | {r['benchmark']} | {r['ic_calibration']:+.2f} ({r['n_calibration']}) | {r['ic_evaluation_signed']:+.2f} ({r['n_evaluation']}) | {lo:+.2f} to {hi:+.2f} | {flo:+.2f} to {fhi:+.2f} | "
                       f"{num(100 * r['walk_forward_hit_rate'], 0) if r.get('walk_forward_hit_rate') is not None else 'n/a'}% ({r['walk_forward_n']}) | {r['status']} |")
        else:
            plan = r.get('prospective_plan') or {}
            if 'ic_evaluation_signed' in plan:
                lo, hi = plan['ci95_block_bootstrap']; flo, fhi = plan['ci95_familywise_bonferroni']
                out.append(f"| {r['predictor']} | {r['horizon_weeks']} | {r['benchmark']} | {plan['ic_calibration']:+.2f} ({plan['calibration_weeks']}, frozen {plan['frozen_on']}) | {plan['ic_evaluation_signed']:+.2f} ({plan['evaluation_targets_realized']}) | {lo:+.2f} to {hi:+.2f} | {flo:+.2f} to {fhi:+.2f} | n/a | {plan['status']} |")
            else:
                tail = (f"; prospective plan frozen {plan['frozen_on']}: sign {plan['frozen_sign']:+.0f} from {plan['calibration_weeks']} calibration weeks, evaluation {plan['evaluation_starts']} to {plan['evaluation_ends']}, {plan['evaluation_targets_realized']}/{plan['evaluation_weeks_required']} targets realized, scored from {plan['evaluable_from']}"
                        if plan.get('frozen') else f"; {plan['status']}" if plan else "")
                out.append(f"| {r['predictor']} | {r['horizon_weeks']} | {r['benchmark']} | n={r['n_calibration']} | n={r['n_evaluation']} | | | | {r['status']}{tail} |")
    pro = sm.get('prospective') or {}
    if pro.get('frozen'):
        out.append(f"\n**Prospective plan (persisted, not recomputed).** Frozen on {pro['frozen_on']} at data cutoff {pro['data_cutoff_at_freeze']} in `{pro['file']}` for the {pro['tests_planned']} tests that are not evaluable retrospectively. "
                   "The file records, per test, the last signal week with a realized target at the cutoff, the SHA-256 of the calibration rows, the calibration IC and its frozen sign, the interim weeks excluded (observed before the freeze, targets unrealized), the fixed evaluation signal weeks and the family. "
                   f"Evaluation signal weeks start on {', '.join(pro['evaluation_starts'])}, the first weekly date after the freeze; a test is scored once all {OOS_MIN_EVAL} evaluation targets are realized, under the frozen sign and the familywise criterion, by the same build. "
                   f"Later builds load this file: adding history cannot move the cutoff, the sign or the dates (calibration rows unchanged: {'yes' if pro['calibration_data_unchanged'] else 'NO, the history was revised'}; protocol unchanged: {'yes' if pro['protocol_unchanged'] else 'NO'}). "
                   f"Scored so far: {pro['tests_scored']} of {pro['tests_planned']} ({pro['tests_passing']} passing). Earliest scoring dates: " + "; ".join(f"{k} from {v}" for k, v in sm['prospective_evaluable_from'].items()) + ".")
    elif sm.get('prospective_evaluable_from'):
        out.append("\nProspective plan for the tests that are not evaluable: draft recomputed from the current data (not persisted; `make oos-freeze` fixes it). Earliest scoring dates: " + "; ".join(f"{k} from {v}" for k, v in sm['prospective_evaluable_from'].items()) + ".")
    out.append("\nLimitations: " + "; ".join(p['limitations']) + ". A negative or inconclusive result is a valid outcome and is carried into the verdict; no trading strategy is proposed.\n")
    return out


def bridge_section() -> list[str]:
    b = _opt('value_bridge.json')
    if not b.get('steps'):
        return []
    out = ["## Value bridge: from settlement to the token\n",
           f"Trailing year to {b['as_of']}. Each step states whether it is observed, classified, inferred or unavailable ({'; '.join(f'{k}: {v}' for k, v in b['status_legend'].items())}).\n",
           "| Step | USD | Share of previous | Status | Source |\n|---|---|---|---|---|"]
    for st in b['steps']:
        value = usd(st.get('usd')) if st.get('usd') is not None else (f"{st['near']:,.0f} NEAR" if st.get('near') else 'n/a')
        share = f"{st['share_of_previous']:.1%}" if st.get('share_of_previous') is not None else ''
        out.append(f"| {st['step']}. {st['name']} | {value} | {share} | {st['status']} | {st['source']} |")
    out.append("")
    out += [f"- Step {st['step']}: {st['note'].rstrip('.')}." for st in b['steps'] if st.get('note')]
    out.append("")
    tr, led = b.get('trace') or {}, (b.get('receipts') or {}).get('ledger') or {}
    if tr.get('sampled'):
        out.append(f"**What the receipts establish.** A pre-declared sample of {tr['sampled']} of {tr['receipts_in_snapshot_from_intents_near']} inbound receipts ({tr['rule']['sample']}) was traced to the Intents events between the originating transaction and the receipt: "
                   f"{tr['matched_native_withdraw']} match a `native_withdraw` of wrapped NEAR from {tr.get('distinct_intents_accounts', 0)} distinct Intents-side accounts, and {tr['with_token_diff_in_same_block']} show the funding `token_diff` of the same account in the same blocks "
                   f"({tr.get('with_wrap_near_bought_in_same_block', 0)} buying wrap.near). For the remaining {tr['sampled'] - tr['with_token_diff_in_same_block']} the swap is outside the blocks read and is not observed. "
                   + ((lambda ex: f"A second pass declared before any further block was read ({ex['rule']['search']}) found the funding swap for {ex['swap_found']} of the {ex['receipts_searched']} ({ex['wrap_near_bought']} buying wrap.near; distances {', '.join(str(x) for x in ex['distance_blocks'])} blocks before the withdrawal), "
                                   f"so the exchange is observed for {tr['funding_swap_observed_total']} of {tr['sampled']} sampled receipts. What the second pass establishes: {ex['rule']['what_it_establishes']}. ")(tr['extension']) if tr.get('extension') else "")
                   + f"{tr['rule']['what_it_establishes'][0].upper() + tr['rule']['what_it_establishes'][1:]}. At the trace time {sum(1 for v in (tr.get('intents_side_balances_at_fetch') or {}).values() if isinstance(v, dict) and v.get('token_ids_held'))} of those accounts still held tokens inside Intents.\n")
    if led:
        out.append(f"**Ledger reconciliation.** {led['method'][0].upper() + led['method'][1:]}. Reconstructed to the snapshot date: {led['reconstructed_balance_at_fetch_near']:,.0f} NEAR against a snapshot balance of {led['snapshot_balance_at_fetch_near']:,.0f} NEAR "
                   f"(residual {led['unexplained_residual_near']:,.1f} NEAR, {led['unexplained_residual_share_of_inflows']:.4%} of inflows). Reconstructed to the analysis cutoff {led['cutoff']}: {led['reconstructed_balance_at_cutoff_near']:,.0f} NEAR; "
                   f"{led['inflows_after_cutoff_near']:,.0f} NEAR arrived after the cutoff and are excluded from the bridge.\n")
    dl = b['dilution']
    out.append(f"**Issuance and dilution ({dl['status']}).** {dl['measure'][0].upper() + dl['measure'][1:]}. Total supply {dl['total_supply_start_near']:,.0f} to {dl['total_supply_end_near']:,.0f} NEAR: {dl['net_new_total_near']:,.0f} new NEAR ({dl['annual_total_supply_growth']:.2%}), "
               f"{usd(dl['net_new_usd_at_average_price'])} at the average price. " + (f"The buyback wallet received {dl['buyback_near_received_12m']:,.0f} NEAR from Intents, {dl['buyback_to_issuance_ratio']:.1%} of issuance (purchase attribution inferred). " if dl.get('buyback_to_issuance_ratio') else "")
               + f"The NearBlocks circulating-supply field is constant since {dl['circulating_supply_field']['last_change']} and is not used. {dl['note'][0].upper() + dl['note'][1:]}.\n")
    out.append("| Scenario | Volume | Take rate | Capture | Allocation to buybacks | New supply | Buyback accrual | Issuance | Net yield on market cap |\n|---|---|---|---|---|---|---|---|---|")
    for name, sc in b['scenarios'].items():
        a = sc['assumptions']
        out.append(f"| {name} | {usd(a['volume_usd'])} | {a['take_rate_bps']:.1f} bps | {a['capture_share']:.1%} | {a['allocation_to_buybacks']:.0%} | {a['net_new_supply_near']:,.0f} NEAR | {usd(sc['buyback_accrual_usd'])} | {usd(sc['issuance_usd'])} | {sc['net_yield_on_mcap']:+.2%} |")
    da = b['dominant_assumption']
    out.append(f"\nDominant assumption ({da['method']}): **{da['dominant']}**; ranking by effect: " + ", ".join(f"{r['assumption']} ({r['change_vs_base']:+.2%})" for r in da['ranking']) + f". What weakens the thesis: {b['what_weakens_the_thesis']} Scenarios are illustrative, not forecasts; every multiplier is in `value_bridge.json`.\n")
    return out


def evidence_rows(ins: dict) -> list[str]:
    rec, b, o, qsens = _opt('intents_reconciliation.json'), _opt('value_bridge.json'), _opt('signal_oos.json'), _opt('qaa_sensitivity.json')
    rows = [("Activity counts fell while value per transaction and reported settlement rose", "observed (third-party series)", "Observed activity table; `docs/METRICS.md`"),
            ("Intents captures net revenue and NEAR reaches the buyback wallet", "observed (adapter receipts; wallet receipts as Intents withdrawals); purchase attribution inferred" if b.get('receipts', {}).get('purchase_transfers') else "observed (adapter) / wallet receipts unavailable", "Value bridge; `value_bridge.json`"),
            ("Received NEAR is held, not burned", "inferred (ledger reconstructed at the cutoff; snapshot balance observed at fetch)" if b.get('receipts', {}).get('balance_near_at_fetch') else "unavailable", "Value bridge step 6"),
            ("Issuance exceeds buyback accrual", "observed issuance vs scenario accrual", "Value bridge scenarios"),
            ("The on-chain sample reproduces the reference level", "estimate: failing (outside declared tolerance)" if rec.get('holdout', {}).get('validation', {}).get('within_tolerance') is False else "estimate", "Reconciliation; `docs/RECONCILIATION.md`"),
            ("Departing accounts were bots", "not established: behavioral groups only; name-only split tracks the share" if qsens else "not established", "Quality-adjusted accounts (L1)"),
            ("Usage predicts forward excess returns", "inconclusive out of sample" if o.get('summary') else "inconclusive", "Out-of-sample evaluation; Forward associations"),
            ("Token undervaluation", "not claimed", "Relative valuation and scenarios")]
    return [f"| {a} | {bb} | {c} |" for a, bb, c in rows]


def reconciliation_doc() -> str:
    rec = _opt('intents_reconciliation.json')
    out = ['# Reconciliation of the on-chain Intents estimate (generated)\n',
           'Generated by `make thesis` from `data/derived/models/intents_reconciliation.json`; numbers are never typed by hand. The method, the declared tolerance and the holdout rule live in `near_thesis/reconcile.py`.\n']
    if not rec:
        return '\n'.join(out + ['Not computed.\n'])
    eu = rec['economic_unit']
    out += ['## Economic unit of comparison\n'] + [f"- **{k.replace('_', ' ')}:** {v}" for k, v in eu.items()] + ['']
    if rec.get('computed'):
        out += [line for line in reconciliation_section()[2:]]
        out += ['## How to extend the evidence\n',
                '1. `make blocks-intraday` fetches 24 hourly windows for the three motivating days and `make blocks-intraday-validation` the three validation days chosen by position (several hours each under the public rate limit); `make build` recomputes the factor and its validation.',
                '2. `make blocks BLOCKS=100` doubles the blocks per fixed window; the per-day table and the holdout are recomputed by `make build`.',
                '3. A complete-day extract needs BigQuery (`make bq`, credentials) or an archival node; the reconciliation code accepts any extract with the same schema.',
                '4. A second reference independent of Dune needs an Intents Explorer JWT or a Dune API key; neither is available to this team.\n',
                '## Per-day table\n', 'See `data/derived/models/intents_reconciliation_daily.csv` (columns: date, windows_usable, blocks_observed, blocks_in_day, block_coverage_share, batches_sampled, volume_sampled_usd, expansion_factor, volume_expanded_usd, reference_usd, difference_usd, ratio, window03_sampled_usd, window15_sampled_usd, fully_priced_batch_share, legs_unpriced, legs_total, account_intents_unvalued, batches_more_than_two_accounts_share, holdout_role).\n']
    else:
        out += ['Not computed: ' + rec.get('reason', '') + '\n']
    return '\n'.join(out)


def metrics_doc() -> str:
    rows = [
        ('txns / active_accounts', 'NearBlocks', 'daily transactions / distinct signing accounts'),
        ('tx_fee_near / tx_fee_usd', 'NearBlocks', 'gas fees paid; not audited net supply burn'),
        ('tx_volume_usd / usd_per_txn', 'NearBlocks', 'native NEAR transferred in USD / ratio to transactions'),
        ('intents_volume_usd', 'DefiLlama/Dune', 'reported cross-chain settlement volume'),
        ('intents_fees_usd', 'DefiLlama/Dune', 'gross swap fees'),
        ('intents_revenue_usd', 'DefiLlama/Dune wallet-receipt adapter', 'net captured revenue; internal revenue-wallet hops excluded'),
        ('intents_holders_revenue_usd', 'same adapter', 'buyback-labelled net revenue; not proof of each purchase, dividends or burning'),
        ('near_app_fees_usd', 'DefiLlama', 'gross application fees; not token-holder income'),
        ('tvl_usd / stablecoins_usd', 'DefiLlama', 'chain TVL / circulating stablecoin USD supply'),
        ('near_price / price_bitcoin / price_ethereum', 'NearBlocks / DefiLlama coins', 'daily prices; benchmark histories'),
        ('qaa_monthly.qaa', 'sampled blocks or BigQuery; retrospective HDBSCAN', 'behavioral quality proxy; sampled share multiplied by mean daily active accounts'),
        ('qaa_causal_monthly.qaa', 'frozen past-only calibration GMM', 'out-of-calibration proxy; available on next-month first day; used for predictive tests'),
        ('hhi_solver / top1_solver_share', 'sampled token_diff events or BigQuery', 'within-observation heuristic solver concentration'),
        ('volume_priced_usd', 'same events', 'half sum of max priced inflow/outflow by account-intent; expanded only for additive flows'),
        ('users', 'same events', 'observed unique non-solver accounts, never expanded'),
        ('intents_reconciliation_daily.*', 'reconcile.py', 'per sampled day: observed, expanded, reference, difference, coverage, pricing and routing components, holdout role'),
        ('qaa_sensitivity.json', 'qaa.py', 'criteria, thresholds, name-only baseline, inclusion weighting, hour split, model agreement'),
        ('signal_oos.json', 'signal.py', 'retrospective, temporally separated out-of-sample evaluation: frozen sign, purge, familywise criterion, walk-forward hit rate; persisted prospective plan loaded from data/prospective/oos_freeze.json'),
        ('value_bridge.json', 'bridge.py', 'volume -> fees -> captured revenue -> labelled buyback -> NEAR withdrawn from Intents into the buyback wallet (purchase attribution inferred) -> ledger at the cutoff; issuance from total supply; three scenarios'),
        ('total_supply', 'NearBlocks', 'daily total supply; its yearly change is the issuance used for dilution (circulating_supply is stale in the source)'),
    ]
    return '# Metric definitions (generated)\n\n| Column | Source | Definition |\n|---|---|---|\n' + '\n'.join(f'| `{a}` | {b} | {c} |' for a,b,c in rows) + '\n'


def repro_doc() -> str:
    out = ['# Reproducibility report (generated)\n',
           'The build reads committed snapshots. Full SHA-256 hashes cover raw files, block extracts, plans, SQL and frozen model artifacts. Snapshot times describe acquisition, not build wall-clock time.\n',
           '| Raw snapshot | Fetched at | Bytes | SHA-256 |\n|---|---|---|---|']
    for r in raw_manifest():
        out.append(f"| {r['file']} | {r['fetched_at']} | {r['bytes']} | `{r['sha256']}` |")
    out += ['\n## Extracts, query definitions and frozen model artifacts\n', '| File | Bytes | SHA-256 |\n|---|---|---|']
    files = list((DATA / 'blocks').glob('*.csv')) + list((DATA / 'blocks').glob('*.json')) + list((DATA / 'bigquery').glob('*.csv'))
    files += list((ROOT / 'sql').glob('*.sql'))
    files += [MODELS / 'qaa_assignments.csv', MODELS / 'qaa_causal_model.json']
    for p in sorted(files):
        if p.exists():
            out.append(f'| {p.relative_to(ROOT)} | {p.stat().st_size} | `{hashlib.sha256(p.read_bytes()).hexdigest()}` |')
    return '\n'.join(out) + '\n'


def run() -> None:
    (ROOT / 'THESIS.md').write_text(build())
    (DOCS / 'METRICS.md').write_text(metrics_doc())
    (DOCS / 'REPRODUCIBILITY.md').write_text(repro_doc())
    (DOCS / 'RECONCILIATION.md').write_text(reconciliation_doc())
    print('thesis: THESIS.md, reconciliation, provenance and metric docs regenerated')
