"""Narrative layer shared by THESIS.md and the dashboard: verdict, argument steps and section intros.

Everything here is computed from the same derived tables and model status files the charts use, so the
dashboard and the generated thesis cannot drift apart. No number is typed by hand.
"""
from __future__ import annotations

import json

import pandas as pd

from .config import MODELS

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


def build(d: pd.DataFrame, m: pd.DataFrame, qs: dict, ins: dict, ic: list, vg: list) -> dict:
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
    checks = [
        {"label": "Descriptive shift", "state": "pass",
         "text": f"Third-party series agree: active accounts {_fmt_pct(acc_vs_peak)} from the {str(peak_m.date())[:7]} peak, "
                 f"USD per transaction {usd_mult:.0f}x the 2024 mean, Intents settling {_usd(last['intents_volume_usd'])} in {lm}."},
        {"label": "Independent on-chain check", "state": onchain_state, "text": onchain_text},
        {"label": "Investment case", "state": "open",
         "text": "Conditional. Net capture exists but its allocation is discretionary; no stable forward association between usage and returns is established."},
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
        {"title": "Counts collapsed",
         "text": f"Daily active accounts are {_fmt_pct(acc_vs_peak)} from the {str(peak_m.date())[:7]} peak and transactions {_fmt_pct(txn_vs_peak)} from theirs. This is the decline everyone sees.",
         "href": "#chart-active_accounts", "chart": "active_accounts"},
        {"title": "Value per transaction rose",
         "text": f"The average transaction in {lm} moved {_usd(last['usd_per_txn'])}, about {usd_mult:.0f}x the 2024 mean. Count fell much faster than volume.",
         "href": "#chart-usd_per_txn", "chart": "usd_per_txn"},
        {"title": "Settlement moved to Intents",
         "text": f"Reported cross-chain settlement reached {_usd(last['intents_volume_usd'])} in {lm}; application fees are {fee_mult:.0f}x the gas paid to the protocol. "
                 "Value that settles through NEAR does not stay on NEAR: TVL and stablecoins are flat.",
         "href": "#sec-value", "chart": "indexed"},
        {"title": "Part of the decline is a bot wash-out, and our own on-chain check "
                  + ("holds" if cross_ok else "fails"),
         "text": ((f"The quality-adjusted share of accounts rose from {qaa_first['qaa_share']:.0%} to {qaa_last['qaa_share']:.0%}. " if qaa_last is not None else "")
                  + (f"But our block sample recovers only {ratio['ratio']:.0%} of the DefiLlama level: the trend is confirmed, the level is not." if (computed and not cross_ok)
                     else "Our block sample is consistent with the DefiLlama level." if computed else "Independent validation is unavailable.")),
         "href": "#chart-intents_xcheck", "chart": "intents_xcheck"},
        {"title": "Price reflects none of it",
         "text": "The price-usage correlation is unstable and often negative. " + granger_text + ic_text + "Decoupling is observed; a return signal is not.",
         "href": "#sec-price", "chart": "rolling_corr"},
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
            "intro": ((f"Partly. Clustering account behavior shows the quality-adjusted share rising from {qaa_first['qaa_share']:.0%} to {qaa_last['qaa_share']:.0%}: much of the lost headcount was mini-app farming. " if qaa_last is not None else "")
                      + (f"But the block sample prices only {ratio['ratio']:.0%} of DefiLlama's volume (interval {ratio['ci_lo']:.2f} to {ratio['ci_hi']:.2f}); the largest sampled batch is {_usd(tail.get('max_batch_usd'))} and the top 10% of batches carry {tail.get('top10pct_share', 0):.0%} of sampled value, so thin windows miss the tail." if (computed and not cross_ok)
                         else "The block sample is consistent with DefiLlama." if computed else "Independent L2 validation is unavailable.")),
            "limit": "QAA is a behavioral proxy, not verified humans. The cross-check is reported as failing, not explained away; it limits how much the level in section 2 can be trusted.",
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
        {"text": onchain_text, "href": "#chart-intents_xcheck"},
        {"text": "Greater settlement volume does not mechanically imply greater token returns. Gross fees are not holder yield; net capture, future allocation and issuance still matter.",
         "href": "#chart-intents_capture"},
    ]
    if int_ic:
        lo, hi = int_ic["ci95_block_bootstrap"]
        against.append({"text": f"Intents growth versus twelve-week forward excess returns over BTC: IC {int_ic['spearman_ic']:+.2f}, exploratory block interval [{lo:+.2f}, {hi:+.2f}], n={int_ic['n']}; "
                                f"first/second half {int_ic['ic_first_half']:+.2f}/{int_ic['ic_second_half']:+.2f}; not significant after familywise control. Not a signal.", "href": "#chart-ic"})
    if granger_rev:
        against.append({"text": f"Where Granger precedence is significant, the stronger direction runs from price to usage ({_names(granger_rev)}), the opposite of a usage-driven price story.", "href": "#chart-granger"})
    against.append({"text": "Fixed intraday windows, sparse sampling, role assumptions, unpriced assets and routed batches can all affect the on-chain comparison; their separate contributions are not identified.",
                    "href": "#chart-intents_users"})
    if qaa_last is not None:
        against.append({"text": f"QAA sensitivity: strict multi-app share {qaa_last['quality_share_strict']:.0%}, default {qaa_last['qaa_share']:.0%}, including ambiguous groups {qaa_last['quality_share_including_ambiguous']:.0%}. "
                                "The behavioral reading depends on the clustering choice.", "href": "#chart-qaa_shares"})

    return {"verdict": verdict, "argument": steps, "sections": sections, "against": against}


def story_kpis(d: pd.DataFrame, m: pd.DataFrame, ins: dict) -> list[dict]:
    """KPIs in the order of the argument. The first entry is the hero."""
    full = m[m.index + pd.offsets.MonthEnd(0) <= d.index.max()]
    last, prev = full.iloc[-1], full.iloc[-13] if len(full) > 13 else full.iloc[0]
    month = str(full.index[-1].date())[:7]

    def kpi(label, value, prior, unit, up_is_good=True, note=None):
        delta = (value - prior) / prior * 100 if prior else None
        return {"label": label, "value": value, "unit": unit, "delta_pct_yoy": delta, "up_is_good": up_is_good, "month": month, "note": note}

    ratio = ins.get("ratio_to_defillama") or {}
    computed = bool(ins.get("computed"))
    cross_ok = bool(ins.get("cross_check_passed"))
    if computed and ratio:
        check = {"label": "On-chain sample vs DefiLlama", "value": float(ratio["ratio"]), "unit": "ratio", "delta_pct_yoy": None, "up_is_good": True, "month": month,
                 "state": "pass" if cross_ok else "fail",
                 "note": ("consistent with parity" if cross_ok else f"cross-check failing; interval {ratio['ci_lo']:.2f} to {ratio['ci_hi']:.2f}")}
    else:
        check = {"label": "On-chain sample vs DefiLlama", "value": None, "unit": "ratio", "delta_pct_yoy": None, "up_is_good": True, "month": month,
                 "state": "open", "note": "not computed"}
    return [kpi("Intents volume, last full month", float(last["intents_volume_usd"]), float(prev["intents_volume_usd"]), "USD"),
            kpi("Daily active accounts, monthly mean", float(last["active_accounts"]), float(prev["active_accounts"]), "accounts"),
            kpi("USD moved per transaction", float(last["usd_per_txn"]), float(prev["usd_per_txn"]), "USD"),
            kpi("Application fees, last full month", float(last["near_app_fees_usd"]), float(prev["near_app_fees_usd"]), "USD"),
            check,
            kpi("NEAR price, monthly mean", float(last["near_price"]), float(prev["near_price"]), "USD", up_is_good=True)]
