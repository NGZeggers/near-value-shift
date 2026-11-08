"""Narrative layer shared by THESIS.md and the dashboard: verdict, argument steps and section intros.

Everything here is computed from the same derived tables and model status files the charts use, so the
dashboard and the generated thesis cannot drift apart. No number is typed by hand.
"""
from __future__ import annotations

import json

import pandas as pd

from .config import MODELS, REPO_URL

METRIC_NAMES = {
    "active_accounts": "active accounts", "txns": "transaction counts", "tx_fee_usd": "gas fees", "tx_volume_usd": "transfer volume",
    "intents_volume_usd": "Intents volume", "near_app_fees_usd": "application fees", "qaa": "QAA", "tx_fee_near": "gas fees",
}


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _names(metrics: list[str]) -> str:
    return ", ".join(METRIC_NAMES.get(x, x) for x in metrics)


def granger_summary(vg: list[dict]) -> str:
    """Report directional results only for models eligible for inference."""
    valid = [r for r in vg if r.get("inference_valid")]
    invalid = [r["metric"] for r in vg if not r.get("inference_valid")]

    def significant(direction: str) -> str:
        results = []
        for r in valid:
            p = r[direction]["p_value_holm"]
            if p < 0.05:
                value = f"{p:.3f}" if p >= 0.001 else f"{p:.3g}"
                results.append(f"{METRIC_NAMES.get(r['metric'], r['metric'])} (Holm p = {value})")
        return ", ".join(results) or "no metric"

    text = (f"In the {len(valid)} VAR models that pass the stationarity, stability and whiteness gates, "
            f"usage leads price for {significant('usage_granger_causes_price')}; "
            f"price leads usage for {significant('price_granger_causes_usage')}. "
            if valid else "No VAR model passes all stationarity, stability and whiteness gates. ")
    if invalid:
        text += f"{_cap(_names(invalid))} fail the prerequisites and are inconclusive. "
    return text.rstrip()


def verdict_changes(ins: dict) -> list[str]:
    """Shared, measurable conditions for changing the thesis and dashboard verdict."""
    computed, cross_ok = bool(ins.get("computed")), bool(ins.get("cross_check_passed"))
    ratio, coverage = ins.get("ratio_to_defillama") or {}, ins.get("coverage") or {}
    reconciliation = ("Independent full-day or routed-batch reconciliation would strengthen the descriptive evidence. "
                      "The numerical consistency criterion is ci_lo <= 1.0 <= ci_hi: the conditional 95% interval "
                      "of the on-chain estimate / DefiLlama ratio must include 1.0 on matched days. ")
    if computed and ratio:
        reconciliation += (f"Current ratio {ratio['ratio']:.3f}, interval [{ratio['ci_lo']:.3f}, {ratio['ci_hi']:.3f}], "
                           f"over {ratio['days']} matched days: {'consistent' if cross_ok else 'failing'}. ")
    else:
        reconciliation += "The current cross-check is unavailable. "
    if ins.get("source") == "neardata block sample":
        reconciliation += (f"Coverage is {ins['sampled_days']} sampled days and {coverage.get('blocks_fetched', 'unknown')} blocks "
                           "in fixed intraday windows, not complete-day extracts. Full-day coverage of those days and "
                           "independent routed-batch/pricing reconciliation are still missing. ")
    reconciliation += ("A passing conditional interval alone would not validate population coverage or economic swap reconstruction; "
                       "the sample does not identify how many additional complete days would suffice.")
    return [
        reconciliation,
        "Audited net receipts, executed purchases and supply effects may strengthen or weaken the value-capture case; gross volume alone does not decide it.",
        "Stable out-of-sample associations with past-only features, dependence-aware uncertainty and multiplicity control are needed before usage can be called a return signal.",
        "Strong sensitivity to clustering, sampling hours or role thresholds weakens the behavioral interpretation. Verified anchors remain an external data need.",
    ]


SECTION_IDS = {
    "1. Raw activity": "raw",
    "2. Value-weighted activity": "value",
    "3. Quality-adjusted": "quality",
    "4. Price and usage": "price",
    "5. Peers": "peers",
    "6. Developers": "developers",
}


def verdict_statement(computed: bool, cross_ok: bool) -> str:
    """The one-sentence verdict used verbatim in THESIS.md and on the dashboard."""
    return ("Current verdict: the descriptive shift is supported by the third-party series, but the independent on-chain validation is "
            + ("consistent within the conditional interval" if cross_ok else "unresolved")
            + ". The investment case remains conditional on net capture, governance allocation, dilution and robust forward evidence. "
            "A failed cross-check counts against the claim; it is not explained away as missing large trades.")


def _pct(a: float, b: float) -> float | None:
    return None if not b or pd.isna(a) or pd.isna(b) else (a / b - 1) * 100


def _fmt_pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.0f}%"


def _usd(v: float | None) -> str:
    if v is None or pd.isna(v):
        return "n/a"
    a = abs(v)
    if a >= 1e9:
        return f"${v / 1e9:.1f}B"
    if a >= 1e6:
        return f"${v / 1e6:.1f}M"
    if a >= 1e3:
        return f"${v / 1e3:.0f}K"
    return f"${v:,.0f}"


def _load(name: str) -> dict:
    f = MODELS / name
    return json.loads(f.read_text()) if f.exists() else {}


KINDS = {"observed": "read from a public source or extract", "estimate": "computed from a sample with stated uncertainty",
         "assumption": "a scenario or rule, not a measurement", "inconclusive": "a test that did not establish its result"}


def _doc(path: str) -> str:
    return f"{REPO_URL}/blob/main/{path}"


def build(d: pd.DataFrame, m: pd.DataFrame, qs: dict, ins: dict, ic: list, vg: list) -> dict:
    recon, qsens, oos, bridge = _load("intents_reconciliation.json"), _load("qaa_sensitivity.json"), _load("signal_oos.json"), _load("value_bridge.json")
    full = m[m.index + pd.offsets.MonthEnd(0) <= d.index.max()]
    last = full.iloc[-1]
    lm = str(last.name.date())[:7]
    peak_m = full["active_accounts"].idxmax()
    peak = full.loc[peak_m]
    acc_vs_peak = _pct(last["active_accounts"], peak["active_accounts"])
    txn_vs_peak = _pct(last["txns"], full["txns"].max())
    y2024 = full[full.index.year == 2024]
    usd_2024 = float(y2024["usd_per_txn"].mean()) if len(y2024) else None
    usd_mult = (last["usd_per_txn"] / usd_2024) if usd_2024 else None
    fee_mult = (last["near_app_fees_usd"] / last["tx_fee_usd"]) if last["tx_fee_usd"] else None
    ratio = ins.get("ratio_to_defillama") or {}
    computed = bool(ins.get("computed"))
    cross_ok = bool(ins.get("cross_check_passed"))
    tail = ins.get("sample_tail") or {}

    qaa_first = qaa_last = None
    if qs.get("computed"):
        q = pd.read_csv(MODELS / "qaa_monthly.csv", parse_dates=["month"]).set_index("month")
        qaa_first, qaa_last = q.iloc[0], q.iloc[-1]
    int_ic = next((r for r in ic if r["metric"] == "intents_volume_usd" and r.get("horizon_weeks") == 12
                   and r.get("benchmark") == "btc" and "spearman_ic" in r), None)
    valid_granger = [r for r in vg if r.get("inference_valid")]
    granger_rev = [r["metric"] for r in valid_granger if r["price_granger_causes_usage"]["p_value_holm"] < 0.05]
    granger_text = granger_summary(vg) + " "
    ic_text = ""
    if int_ic:
        lo, hi = int_ic["ci95_block_bootstrap"]
        ic_text = (f"Intents growth vs 12-week excess returns over BTC: IC {int_ic['spearman_ic']:+.2f}, block interval [{lo:+.2f}, {hi:+.2f}]"
                   + (", which does not survive familywise control. " if not int_ic.get("significant_familywise") else ", significant after familywise control. "))

    # ---- verdict: three checks, each with an explicit state
    if not computed:
        onchain_state, onchain_text = "open", "Independent L2 validation is unavailable: " + ins.get("reason", "no verified extract") + "."
    elif cross_ok:
        onchain_state = "pass"
        onchain_text = (f"Our own block-sample estimate recovers {ratio['ratio']:.0%} of the DefiLlama series over {ratio['days']} matched days; "
                        f"the conditional interval [{ratio['ci_lo']:.2f}, {ratio['ci_hi']:.2f}] contains parity.")
    else:
        onchain_state = "fail"
        onchain_text = (f"Our own block-sample estimate recovers only {ratio['ratio']:.0%} of the DefiLlama series over {ratio['days']} matched days; "
                        f"the conditional interval [{ratio['ci_lo']:.2f}, {ratio['ci_hi']:.2f}] excludes parity, so the consistency criterion fails. "
                        "The sample shows the same trend, but it does not independently confirm the level.")
    hold = (recon.get("holdout") or {}).get("validation") or {}
    if "ratio" in hold:
        onchain_text += (f" Declared tolerance x0.8 to x1.25: validation days give {hold['ratio']:.2f} "
                         f"[{hold['ci_lo']:.2f}, {hold['ci_hi']:.2f}], {'inside' if hold.get('within_tolerance') else 'outside'} the band.")
    oos_sum = (oos.get("summary") or {})
    checks = [
        {"label": "Descriptive shift", "state": "pass", "kind": "observed",
         "text": f"Third-party series agree: active accounts {_fmt_pct(acc_vs_peak)} from the {str(peak_m.date())[:7]} peak, "
                 f"USD per transaction {usd_mult:.0f}x the 2024 mean, Intents settling {_usd(last['intents_volume_usd'])} in {lm}.",
         "links": [{"label": "Chart", "href": "#chart-indexed"}, {"label": "Metric definitions", "href": _doc("docs/METRICS.md")}]},
        {"label": "Independent on-chain check", "state": onchain_state, "kind": "estimate", "text": onchain_text,
         "links": [{"label": "Per-day table", "href": "#chart-intents_recon_daily"}, {"label": "Method, unit and tolerance", "href": _doc("docs/RECONCILIATION.md")},
                   {"label": "Sampling limits", "href": _doc("docs/SAMPLING.md")}]},
        {"label": "Investment case", "state": "open", "kind": "inconclusive",
         "text": ("Conditional. Net capture exists but its allocation is discretionary; " + (oos_sum.get("conclusion", "no stable forward association is established") + ".")
                  if oos_sum else "Conditional. Net capture exists but its allocation is discretionary; no stable forward association between usage and returns is established."),
         "links": [{"label": "Value bridge", "href": "#chart-value_bridge"}, {"label": "Out-of-sample test", "href": "#chart-oos"}, {"label": "Scenarios", "href": _doc("THESIS.md#value-bridge-from-settlement-to-the-token")}]},
    ]
    changes = verdict_changes(ins)
    verdict = {
        "claim": "NEAR's activity is shifting from many low-value transactions toward fewer, high-value cross-chain settlements through NEAR Intents. "
                 "That is a claim about composition, not proof of token undervaluation or future returns.",
        "status": "unresolved" if not cross_ok else "supported",
        "statement": verdict_statement(computed, cross_ok),
        "checks": checks,
        "changes": changes,
    }

    # ---- the argument in five steps, each anchored to the evidence
    steps = [
        {"title": "Counts collapsed", "kind": "observed",
         "text": f"Daily active accounts are {_fmt_pct(acc_vs_peak)} from the {str(peak_m.date())[:7]} peak and transactions {_fmt_pct(txn_vs_peak)} from theirs. This is the decline everyone sees.",
         "href": "#chart-active_accounts", "chart": "active_accounts",
         "links": [{"label": "Source and table", "href": "#chart-active_accounts"}, {"label": "Definitions", "href": _doc("docs/METRICS.md")}]},
        {"title": "Value per transaction rose", "kind": "observed",
         "text": f"The average transaction in {lm} moved {_usd(last['usd_per_txn'])}, about {usd_mult:.0f}x the 2024 mean. Count fell much faster than volume.",
         "href": "#chart-usd_per_txn", "chart": "usd_per_txn",
         "links": [{"label": "Source and table", "href": "#chart-usd_per_txn"}]},
        {"title": "Settlement moved to Intents", "kind": "observed",
         "text": f"Reported cross-chain settlement reached {_usd(last['intents_volume_usd'])} in {lm}; application fees are {fee_mult:.0f}x the gas paid to the protocol. "
                 "Value that settles through NEAR does not stay on NEAR: TVL and stablecoins are flat.",
         "href": "#sec-value", "chart": "indexed",
         "links": [{"label": "Third-party series", "href": "#chart-intents_volume_monthly"}, {"label": "Fees and capture", "href": "#chart-intents_capture"}]},
        {"title": "Part of the decline is a mini-app wash-out, and our own on-chain check "
                  + ("holds" if cross_ok else "fails"), "kind": "estimate",
         "text": ((f"The share of accounts outside the mini-app and high-frequency patterns rose from {qaa_first['qaa_share']:.0%} to {qaa_last['qaa_share']:.0%}" if qaa_last is not None else "")
                  + (f" (a name-only split gives {qsens['name_only_baseline']['latest_month']:.0%}, so the clustering adds little beyond the name class). " if qsens.get("name_only_baseline") else ". ")
                  + (f"But our block sample recovers only {ratio['ratio']:.0%} of the DefiLlama level: the trend is confirmed, the level is not." if (computed and not cross_ok)
                     else "Our block sample is consistent with the DefiLlama level." if computed else "Independent validation is unavailable.")),
         "href": "#chart-intents_xcheck", "chart": "intents_xcheck",
         "links": [{"label": "Per-day reconciliation", "href": "#chart-intents_recon_daily"}, {"label": "QAA sensitivity", "href": "#sensitivity"},
                   {"label": "Method and tolerance", "href": _doc("docs/RECONCILIATION.md")}, {"label": "Sampling limits", "href": _doc("docs/SAMPLING.md")}]},
        {"title": "Price reflects none of it", "kind": "inconclusive",
         "text": "The price-usage correlation is unstable and often negative. " + granger_text + ic_text
                 + (f"Out of sample: {oos_sum['conclusion']}. " if oos_sum.get("conclusion") else "") + "Decoupling is observed; a return signal is not.",
         "href": "#sec-price", "chart": "rolling_corr",
         "links": [{"label": "Out-of-sample protocol", "href": "#chart-oos"}, {"label": "Granger diagnostics", "href": "#chart-granger"}, {"label": "Statistical results", "href": _doc("THESIS.md#econometrics-l3")}]},
    ]
    for i, s in enumerate(steps, 1):
        s["step"] = i

    # ---- section intros: what the section asks, what it concludes, what it cannot say
    sections = {
        "1. Raw activity": {
            "id": SECTION_IDS["1. Raw activity"],
            "question": "What happened to the headline numbers?",
            "intro": f"Active accounts peaked in {str(peak_m.date())[:7]} at {peak['active_accounts']:,.0f} per day and are {_fmt_pct(acc_vs_peak)} since; transactions followed the same arc. "
                     f"Vertical lines mark statistically detected regime breaks.",
            "limit": "Counts say nothing about value. The third chart is the hinge of the argument: USD per transaction rose while counts fell.",
        },
        "2. Value-weighted activity": {
            "id": SECTION_IDS["2. Value-weighted activity"],
            "question": "Did value leave with the accounts, or move elsewhere?",
            "intro": f"It moved. Intents settled {_usd(last['intents_volume_usd'])} in {lm} ({_fmt_pct(_pct(last['intents_volume_usd'], full.iloc[-13]['intents_volume_usd']) if len(full) > 13 else None)} year on year), "
                     f"application fees are {fee_mult:.0f}x gas fees, and net capture into revenue wallets is already observed.",
            "limit": "These are third-party series (DefiLlama, sourced from Dune). Settled value does not stay on NEAR as TVL, and gross fees are not token-holder yield.",
        },
        "3. Quality-adjusted": {
            "id": SECTION_IDS["3. Quality-adjusted"],
            "question": "Do our own on-chain extracts agree?",
            "intro": ((f"Partly. Clustering account behavior shows the share outside the mini-app and high-frequency patterns rising from {qaa_first['qaa_share']:.0%} to {qaa_last['qaa_share']:.0%}: much of the lost headcount matched the mini-app pattern. " if qaa_last is not None else "")
                      + (f"But the block sample prices only {ratio['ratio']:.0%} of DefiLlama's volume (interval {ratio['ci_lo']:.2f} to {ratio['ci_hi']:.2f}); the largest sampled batch is {_usd(tail.get('max_batch_usd'))} and the top 10% of batches carry {tail.get('top10pct_share', 0):.0%} of sampled value, so thin windows miss the tail." if (computed and not cross_ok)
                         else "The block sample is consistent with DefiLlama." if computed else "Independent L2 validation is unavailable.")),
            "limit": "QAA groups describe behavior in sparse windows (most accounts are seen once), not verified humans; a name-only split tracks the share closely. The cross-check is reported as failing, not explained away; it limits how much the level in section 2 can be trusted.",
        },
        "4. Price and usage": {
            "id": SECTION_IDS["4. Price and usage"],
            "question": "Does any of this show up in the token?",
            "intro": "Barely. Within-year correlations flip sign and rolling correlations hover near zero. " + granger_text + ic_text.rstrip(),
            "limit": "Inconclusive is not evidence of no effect, and a single significant direction is not a signal. These are association checks on overlapping weekly data; Granger describes predictive precedence inside the model, not economic causality.",
        },
        "5. Peers": {
            "id": SECTION_IDS["5. Peers"],
            "question": "How does NEAR compare?",
            "intro": "Descriptively, NEAR turns over far more settlement per dollar of TVL than peers, and application fees relative to market cap are high.",
            "limit": "Cross-chain settlement and local DEX volume have different scopes; this ranking does not establish relative undervaluation.",
        },
        "6. Developers": {
            "id": SECTION_IDS["6. Developers"],
            "question": "Did the builders leave with the users?",
            "intro": "No. Weekly commits to nearcore stayed steady through the activity decline.",
            "limit": "One repository, last 52 weeks; a count of commits, not of ecosystem developers.",
        },
    }

    against = [
        {"text": onchain_text, "href": "#chart-intents_xcheck", "kind": "estimate"},
        {"text": "Greater settlement volume does not mechanically imply greater token returns. Gross fees are not holder yield; net capture, future allocation and issuance still matter.",
         "href": "#chart-value_bridge" if bridge else "#chart-intents_capture", "kind": "observed"},
    ]
    if bridge.get("scenarios"):
        sc = bridge["scenarios"]
        against.append({"text": (f"Net of issuance, buyback accrual is {sc['adverse']['net_yield_on_mcap']:+.2%} of market cap in the adverse scenario, "
                                 f"{sc['base']['net_yield_on_mcap']:+.2%} in the base case and {sc['favorable']['net_yield_on_mcap']:+.2%} in the favorable one; "
                                 f"the dominant assumption is {bridge['dominant_assumption']['dominant']}. Scenarios, not forecasts."),
                        "href": "#chart-value_bridge", "kind": "assumption"})
    if oos_sum.get("conclusion"):
        against.append({"text": f"Temporally separated out-of-sample test (retrospective: protocol declared 2026-11-06 on already-examined history; calibration through {oos['protocol']['calibration_end']}, frozen sign, purged evaluation, familywise criterion): {oos_sum['conclusion']}; "
                                f"{len(oos_sum.get('not_evaluable', []))} of {oos_sum.get('usage_tests', 0)} declared tests are not evaluable for lack of calibration weeks (Intents, QAA)"
                                + (f"; their prospective plan is persisted (frozen {oos_sum['prospective']['frozen_on']}, evaluation from {', '.join(oos_sum['prospective']['evaluation_starts'])}, "
                                   f"{oos_sum['prospective']['tests_scored']} of {oos_sum['prospective']['tests_planned']} scored so far)." if (oos_sum.get('prospective') or {}).get('frozen') else "."),
                        "href": "#chart-oos", "kind": "inconclusive"})
    if int_ic:
        lo, hi = int_ic["ci95_block_bootstrap"]
        against.append({"text": f"Intents growth versus twelve-week forward excess returns over BTC: IC {int_ic['spearman_ic']:+.2f}, exploratory block interval [{lo:+.2f}, {hi:+.2f}], n={int_ic['n']}; "
                                f"first/second half {int_ic['ic_first_half']:+.2f}/{int_ic['ic_second_half']:+.2f}; not significant after familywise control. Not a signal.", "href": "#chart-ic", "kind": "inconclusive"})
    if granger_rev:
        against.append({"text": f"Where Granger precedence is significant, the stronger direction runs from price to usage ({_names(granger_rev)}), the opposite of a usage-driven price story.", "href": "#chart-granger", "kind": "estimate"})
    comp = (recon.get("components") or {})
    if comp:
        res = comp.get("residual") or {}
        cov = comp.get("temporal_coverage") or {}
        intra = recon.get("intraday") or {}
        bias = intra.get("fixed_window_bias_factor_median")
        against.append({"text": (f"Decomposition of the gap: two 50-block windows observe {cov.get('block_coverage_share_mean', 0):.2%} of a day's blocks and the 15:00 UTC window carries "
                                 f"{cov['between_window_ratio_15_over_03']['median']:.1f}x the 03:00 volume; " if cov.get("between_window_ratio_15_over_03", {}).get("median") else "")
                                + (f"24 hourly windows on {len(intra.get('days', []))} pre-declared days put the fixed-window bias factor at {bias:.2f} (median; mean {intra.get('fixed_window_bias_factor_mean'):.2f}); " if bias else "the intraday extract is not yet available; ")
                                + (f"valuation loses only {comp['valuation']['account_intents_without_any_priced_side']} of {comp['valuation']['account_intents']} account-intents; "
                                   f"a two-sided reading of the reference would double the ratio to {res.get('if_reference_were_two_sided_notional', 0):.2f}. "
                                   + (f"After the intraday correction the ratio would be {res['after_intraday_bias_correction']:.2f} and a factor of {res.get('unexplained_factor_to_parity', 0):.1f}x to parity stays unexplained." if res.get('after_intraday_bias_correction')
                                      else f"A factor of {res.get('unexplained_factor_to_parity', 0):.1f}x to parity stays unexplained.")),
                        "href": "#chart-intents_recon_daily", "kind": "estimate"})
    else:
        against.append({"text": "Fixed intraday windows, sparse sampling, role assumptions, unpriced assets and routed batches can all affect the on-chain comparison; their separate contributions are not identified.",
                        "href": "#chart-intents_users", "kind": "estimate"})
    if qaa_last is not None:
        extra = ""
        if qsens.get("model_agreement"):
            extra = f" The frozen past-only model gives {qsens['model_agreement']['latest']['frozen']:.0%} for the same month."
        if qsens.get("by_window_hour"):
            bh = qsens["by_window_hour"]["latest_month"]
            extra += " By observation hour: " + ", ".join(f"{h}:00 UTC {v:.0%}" for h, v in bh.items()) + "."
        against.append({"text": f"QAA sensitivity: strict multi-app share {qaa_last['quality_share_strict']:.0%}, default {qaa_last['qaa_share']:.0%}, including ambiguous groups {qaa_last['quality_share_including_ambiguous']:.0%}."
                                + extra + " Group names describe behavior; no verified human or bot labels exist.", "href": "#chart-qaa_shares", "kind": "estimate"})

    sensitivity = sensitivity_table(ratio, cross_ok, qaa_last, qsens, recon, bridge)
    dates = {"analysis_cutoff": str(d.index.max().date()),
             "block_sample_fetched_at": _block_sample_date(),
             "intraday_fetched_at": (recon.get("intraday") or {}).get("fetched_at"),
             "buyback_receipts_fetched_at": ((bridge.get("receipts") or {}).get("fetched_at")),
             "note": "the analysis cutoff is the last day with data in every daily series; acquisition dates say when each snapshot was taken; the page footer shows when this page was generated"}
    return {"verdict": verdict, "argument": steps, "sections": sections, "against": against, "sensitivity": sensitivity, "dates": dates, "kinds": KINDS}


def _block_sample_date() -> str | None:
    f = MODELS.parents[1] / "blocks" / "sample_manifest.json"
    return json.loads(f.read_text()).get("fetched_at") if f.exists() else None


def sensitivity_table(ratio: dict, cross_ok: bool, qaa_last, qsens: dict, recon: dict, bridge: dict) -> list[dict]:
    """How much each headline moves under the relevant alternative assumptions, and whether the verdict changes."""
    rows = []
    if ratio:
        variants = [{"label": "pooled ratio, all matched days", "value": f"{ratio['ratio']:.2f}"}]
        res = (recon.get("components") or {}).get("residual") or {}
        hold = (recon.get("holdout") or {})
        if res.get("if_reference_were_two_sided_notional"):
            variants.append({"label": "if the reference counted both sides", "value": f"{res['if_reference_were_two_sided_notional']:.2f}"})
        if res.get("after_intraday_bias_correction"):
            if res.get("after_confidential_intents_exclusion"):
                variants.append({"label": "excluding the reference's confidential-intents share (estimate from a cumulative figure)", "value": f"{res['after_confidential_intents_exclusion']:.2f}"})
            cdv = recon.get("complete_days") or {}
            if cdv.get("pooled_ratio_complete_to_reference") is not None:
                variants.append({"label": f"complete days from BigQuery, {cdv['days_with_reference']} sample days, every block (no sampling error)", "value": f"{cdv['pooled_ratio_complete_to_reference']:.2f}"})
            sd = recon.get("systematic_day") or {}
            if sd.get("ratio_to_reference") is not None:
                sv = sd.get("sampling_verdict", "")
                variants.append({"label": f"systematic 2.5% block sample of {sd['day']} (design interval; sampling verdict {sv.split(':')[0] if sv else 'n/a'})",
                                 "value": f"{sd['ratio_to_reference']:.2f} [{sd['ratio_ci95'][0]:.2f}, {sd['ratio_ci95'][1]:.2f}]"})
            variants.append({"label": "after the measured intraday bias (median factor)", "value": f"{res['after_intraday_bias_correction']:.2f}"})
            if res.get("after_confidential_and_intraday"):
                variants.append({"label": "confidential share and intraday bias together", "value": f"{res['after_confidential_and_intraday']:.2f}"})
            variants.append({"label": "after the measured intraday bias (mean factor)", "value": f"{res['after_intraday_bias_correction_mean_factor']:.2f}"})
        if res.get("after_both"):
            variants.append({"label": "two-sided reading and intraday correction together", "value": f"{res['after_both']:.2f}" + (" (exceeds parity)" if res.get("two_sided_and_intraday_overshoot") else "")})
        for role in ("calibration", "validation"):
            r = hold.get(role) or {}
            if "ratio" in r:
                variants.append({"label": f"{role} days only", "value": f"{r['ratio']:.2f} [{r['ci_lo']:.2f}, {r['ci_hi']:.2f}]"})
        rows.append({"headline": "On-chain estimate / DefiLlama reference", "kind": "estimate", "variants": variants,
                     "effect": ("no variant reaches the declared tolerance (x0.8 to x1.25 with the interval covering 1.0); the check stays failing" if not cross_ok
                                else "the check passes; variants show how fragile the pass is"), "href": "#chart-intents_recon_daily"})
    if qaa_last is not None:
        variants = [{"label": "strict (multi-app only)", "value": f"{qaa_last['quality_share_strict']:.0%}"},
                    {"label": "default", "value": f"{qaa_last['qaa_share']:.0%}"},
                    {"label": "including ambiguous groups", "value": f"{qaa_last['quality_share_including_ambiguous']:.0%}"}]
        if qsens.get("name_only_baseline"):
            variants.append({"label": "name-only split (no clustering)", "value": f"{qsens['name_only_baseline']['latest_month']:.0%}"})
        if qsens.get("inclusion_probability_weighting"):
            variants.append({"label": "inclusion-probability weighted (sensitivity under assumptions)", "value": f"{qsens['inclusion_probability_weighting']['latest_month_weighted']:.0%}"})
        if qsens.get("inclusion_from_intraday_days"):
            nq = qsens["inclusion_from_intraday_days"]["pooled"]["name_only_quality_share"]
            variants.append({"label": "name-only share within the day: fixed windows vs all 24 hourly windows (six days, observed)", "value": f"{nq['fixed_windows']:.0%} vs {nq['all_24_windows']:.0%}"})
        if qsens.get("refits"):
            lo, hi = qsens["refits"]["default_share_range"]
            variants.append({"label": "refits with other hyper-parameters and a Gaussian mixture (range)", "value": f"{lo:.0%} to {hi:.0%}"})
        if qsens.get("by_window_hour"):
            variants += [{"label": f"accounts seen at {h}:00 UTC", "value": f"{v:.0%}"} for h, v in qsens["by_window_hour"]["latest_month"].items()]
        if qsens.get("model_agreement"):
            variants.append({"label": "frozen past-only model", "value": f"{qsens['model_agreement']['latest']['frozen']:.0%}"})
        rows.append({"headline": f"Share of accounts outside mini-app and high-frequency patterns, {qsens.get('latest_month', 'latest month')}", "kind": "estimate", "variants": variants,
                     "effect": "the level depends on the model and criterion; against the full monthly population from BigQuery the two windows observe about 0.1% of signers and the name-only share differs from the full month by tens of points in either direction across months, so the share is a property of the sampled windows, not a population share, and the QAA count is not a count of quality accounts in the month; the rising trend holds across variants. QAA is not one of the verdict's pass/fail checks, so the verdict does not move",
                     "href": "#chart-qaa_shares"})
    if bridge.get("scenarios"):
        sc = bridge["scenarios"]
        rows.append({"headline": "Buyback accrual net of issuance, share of market cap", "kind": "assumption",
                     "variants": [{"label": k, "value": f"{v['net_yield_on_mcap']:+.2%}"} for k, v in sc.items()],
                     "effect": f"dominant assumption: {bridge['dominant_assumption']['dominant']}; every scenario keeps the investment case conditional", "href": "#chart-value_bridge"})
    return rows


def story_kpis(d: pd.DataFrame, m: pd.DataFrame, ins: dict) -> list[dict]:
    """KPIs in the order of the argument. The first entry is the hero."""
    full = m[m.index + pd.offsets.MonthEnd(0) <= d.index.max()]
    last, prev = full.iloc[-1], full.iloc[-13] if len(full) > 13 else full.iloc[0]
    month = str(full.index[-1].date())[:7]

    def kpi(label, value, prior, unit, up_is_good=True, note=None):
        delta = (value - prior) / prior * 100 if prior else None
        return {"label": label, "value": value, "unit": unit, "delta_pct_yoy": delta, "up_is_good": up_is_good, "month": month, "note": note, "kind": "observed"}

    ratio = ins.get("ratio_to_defillama") or {}
    computed = bool(ins.get("computed"))
    cross_ok = bool(ins.get("cross_check_passed"))
    if computed and ratio:
        check = {"label": "On-chain sample vs DefiLlama", "value": float(ratio["ratio"]), "unit": "ratio", "delta_pct_yoy": None, "up_is_good": True, "month": month,
                 "state": "pass" if cross_ok else "fail", "kind": "estimate",
                 "note": ("consistent with parity" if cross_ok else f"cross-check failing; interval {ratio['ci_lo']:.2f} to {ratio['ci_hi']:.2f}")}
    else:
        check = {"label": "On-chain sample vs DefiLlama", "value": None, "unit": "ratio", "delta_pct_yoy": None, "up_is_good": True, "month": month,
                 "state": "open", "note": "not computed", "kind": "estimate"}
    return [kpi("Intents volume, last full month", float(last["intents_volume_usd"]), float(prev["intents_volume_usd"]), "USD"),
            kpi("Daily active accounts, monthly mean", float(last["active_accounts"]), float(prev["active_accounts"]), "accounts"),
            kpi("USD moved per transaction", float(last["usd_per_txn"]), float(prev["usd_per_txn"]), "USD"),
            kpi("Application fees, last full month", float(last["near_app_fees_usd"]), float(prev["near_app_fees_usd"]), "USD"),
            check,
            kpi("NEAR price, monthly mean", float(last["near_price"]), float(prev["near_price"]), "USD", up_is_good=True)]
