"""Build chart specifications (data + source + query + one plain sentence) into site/data.json.

The dashboard's JavaScript renders every spec as SVG (line, column, ranked bar, diverging bar) with a
hover layer, a legend, a table view and dark mode. Python decides WHAT is shown; the renderer decides HOW.
Spec fields: id, section, title, sentence, type, unit, y_log, series[{name, points[[iso_date, value]]}],
annotations[{date, label}], source, query, note.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .config import DERIVED, INTENTS_START, MODELS, SITE
from . import narrative
from .http import raw_manifest

SQL_NOTE = "SQL in sql/; run with `make bq`"


def _pts(s: pd.Series, *, freq: str | None = None, how: str = "mean", round_to: int = 2) -> list:
    s = s.dropna()
    if freq:
        s = getattr(s.resample(freq), how)()
        s = s.dropna()
    return [[str(i.date()), round(float(v), round_to)] for i, v in s.items()]


def _roll(s: pd.Series, w: int = 30) -> pd.Series:
    return s.rolling(w, min_periods=max(7, w // 3)).mean()


def _spec(id, section, title, sentence, type, series, *, unit="", y_log=False, annotations=None, source="", query="", note="", y_domain=None):
    return {"id": id, "section": section, "title": title, "sentence": sentence, "type": type, "unit": unit, "y_log": y_log,
            "series": series, "annotations": annotations or [], "source": source, "query": query, "note": note, "y_domain": y_domain}


def _label(column: str) -> str:
    """Human label for a metric column (shared with the narrative layer)."""
    return narrative.METRIC_NAMES.get(column, column)


def _breaks(name: str) -> list[dict]:
    b = json.loads((MODELS / "breaks.json").read_text()).get(name, {})
    return [{"date": d, "label": "break"} for d in b.get("breaks", [])]


def build() -> dict:
    d = pd.read_csv(DERIVED / "daily.csv", parse_dates=["date"]).set_index("date")
    m = pd.read_csv(DERIVED / "monthly.csv", parse_dates=["month"]).set_index("month")
    peers = pd.read_csv(DERIVED / "peers.csv")
    yc = pd.read_csv(MODELS / "yearly_corr.csv")
    rc = pd.read_csv(MODELS / "rolling_corr.csv", parse_dates=["date"]).set_index("date")
    ic = json.loads((MODELS / "signal_ic.json").read_text())
    vg = json.loads((MODELS / "var_granger.json").read_text())
    qaa_status = json.loads((MODELS / "qaa_status.json").read_text())
    intents_status = json.loads((MODELS / "intents_status.json").read_text())
    NB = "NearBlocks API, GET https://api.nearblocks.io/v1/charts (data/raw/nearblocks_charts.json)"
    LL_I = "DefiLlama, GET https://api.llama.fi/summary/dexs/near-intents (data/raw/llama_intents_volume.json); DefiLlama sources Dune table dune.near.dataset_near_intents_metrics"

    full_months = m.index + pd.offsets.MonthEnd(0) <= d.index.max()
    specs = []
    # ---- Section 1: the activity collapse (raw metrics)
    specs.append(_spec("active_accounts", "1. Raw activity", "Daily active accounts, 30-day mean",
        "Active accounts peaked in 2024 and are down roughly 90% from that peak; vertical lines are statistically detected regime breaks.",
        "line", [{"name": "active accounts (30d mean)", "points": _pts(_roll(d["active_accounts"]), round_to=0)}],
        unit="accounts", y_log=True, annotations=_breaks("active_accounts"), source=NB,
        query="charts[].active_accounts; 30-day trailing mean; breaks: PELT on standardized log series (near_thesis/econ.py)"))
    specs.append(_spec("txns", "1. Raw activity", "Daily transactions, 30-day mean",
        "Transaction counts followed the same arc: a 2024 surge driven by mini-app traffic, then a decline to 2023 levels.",
        "line", [{"name": "transactions (30d mean)", "points": _pts(_roll(d["txns"]), round_to=0)}],
        unit="txns", y_log=True, annotations=_breaks("txns"), source=NB, query="charts[].txns; 30-day trailing mean"))
    specs.append(_spec("usd_per_txn", "1. Raw activity", "USD moved per transaction, 30-day mean",
        "The average transaction carries far more value than in 2024: count fell faster than volume.",
        "line", [{"name": "USD per transaction (30d mean)", "points": _pts(_roll(d["usd_per_txn"]), round_to=1)}],
        unit="USD", y_log=True, source=NB, query="charts[].txn_volume_usd / charts[].txns; 30-day trailing mean"))

    # ---- Section 2: value-weighted activity
    specs.append(_spec("intents_volume_monthly", "2. Value-weighted activity", "NEAR Intents swap volume per month",
        "Reported cross-chain settlement grew from millions to billions per month. Only complete months are shown; the independent sample reconciliation remains unresolved.",
        "column", [{"name": "Intents volume (USD, monthly)", "points": _pts(m.loc[full_months, "intents_volume_usd"], round_to=0)}],
        unit="USD", source=LL_I, query="sum of totalDataChart by calendar month"))
    specs.append(_spec("fees_split", "2. Value-weighted activity", "Fees on NEAR per month: protocol gas fees vs application fees",
        "Application-level fees (mostly Intents) are now an order of magnitude larger than the gas fees paid to the protocol.",
        "line", [{"name": "gas fees paid (USD)", "points": _pts(m["tx_fee_usd"], round_to=0)},
                 {"name": "application fees (USD)", "points": _pts(m.loc[m.index >= INTENTS_START, "near_app_fees_usd"], round_to=0)}],
        unit="USD", y_log=True, source=f"{NB}; DefiLlama GET https://api.llama.fi/overview/fees/near (data/raw/llama_fees_near.json)",
        query="monthly sums of charts[].txn_fee_usd and DefiLlama totalDataChart",
        note=f"application fees shown from {INTENTS_START}: DefiLlama's fee coverage of NEAR apps is sparse before NEAR Intents"))
    specs.append(_spec("indexed", "2. Value-weighted activity", "Indexed to 100 at 2025-01: activity vs value vs price",
        "Since January 2025, raw activity fell while Intents volume rose by orders of magnitude; the token price did neither.",
        "line", [{"name": n, "points": p} for n, p in _indexed(m)],
        unit="index (log)", y_log=True, source=f"{NB}; {LL_I}", query="monthly series divided by their 2025-01 value x 100"))
    specs.append(_spec("tvl_stables", "2. Value-weighted activity", "TVL and stablecoin supply on NEAR",
        "Value that settles through NEAR does not stay on NEAR: TVL and stablecoin supply are flat to down while Intents volume exploded.",
        "line", [{"name": "TVL (USD)", "points": _pts(_roll(d["tvl_usd"], 7), round_to=0)},
                 {"name": "stablecoins (USD)", "points": _pts(_roll(d["stablecoins_usd"], 7), round_to=0)}],
        unit="USD", source="DefiLlama GET https://api.llama.fi/v2/historicalChainTvl/Near and https://stablecoins.llama.fi/stablecoincharts/Near",
        query="7-day trailing means"))

    # ---- Section 3: quality-adjusted (L1) and microstructure (L2)
    if qaa_status.get("computed"):
        q = pd.read_csv(MODELS / "qaa_monthly.csv", parse_dates=["month"]).set_index("month")
        bq1 = qaa_status.get("source") == "bigquery"
        partial = "" if bq1 or len(q) >= 12 else f" Sampled mode, {len(q)} months covered so far (partial block sample; see docs/SAMPLING.md)."
        specs.append(_spec("qaa", "3. Quality-adjusted", "Active accounts vs Quality-Adjusted Active Accounts (QAA)",
            "Retrospective behavioral proxy, not a count of verified humans. Sensitivity and anchor-name profiles are reported separately; predictive tests use a frozen past-only model." + partial,
            "line", [{"name": "active accounts (BigQuery)" if bq1 else "active accounts (NearBlocks)", "points": _pts(q["active_accounts_bq"], round_to=0)},
                     {"name": "QAA", "points": _pts(q["qaa"], round_to=0)}],
            unit="accounts", y_log=True, source=("BigQuery crypto_near_mainnet_us (sql/l1_*.sql)" if qaa_status.get("source") == "bigquery" else "FastNear neardata sampled blocks (data/blocks/tx_sampled.csv, near_thesis/blocks.py)") + "; clustering in near_thesis/qaa.py",
            query=("sql/l1_account_month_features.sql + sql/l1_account_month_actions.sql; " if qaa_status.get("source") == "bigquery" else "per (month, signer) features inside sampled windows; QAA = share outside the mini-app and high-frequency patterns x NearBlocks mean daily active accounts; ") + qaa_status.get("algorithm", "")))
        labels = [c for c in q.columns if c in {"noise", "high_frequency_regular", "miniapp_pattern", "heavy_unclassified", "light_general", "multi_app", "intents_participant"}]
        specs.append(_spec("qaa_shares", "3. Quality-adjusted", "Account-months by behavioral group",
            "Account-months in each behavioral group; the mini-app name pattern dominates the 2024 era. Group names describe observed behavior, not verified identity." + (" Sampled windows only." if not bq1 else ""),
            "stacked", [{"name": c.replace("_", " "), "points": _pts(q[c], round_to=0)} for c in labels[:6]],
            unit="account-months", source=("BigQuery crypto_near_mainnet_us" if bq1 else "FastNear neardata sampled blocks (data/blocks/tx_sampled.csv)") + " + near_thesis/qaa.py", query="cluster label counts per month"))
    else:
        specs.append(_spec("qaa", "3. Quality-adjusted", "Quality-Adjusted Active Accounts (QAA)", "Not computed: " + qaa_status.get("reason", ""),
            "empty", [], source="BigQuery crypto_near_mainnet_us", query=SQL_NOTE))
    if intents_status.get("computed"):
        im = pd.read_csv(MODELS / "intents_monthly.csv", parse_dates=["month"]).set_index("month")
        L2SRC = ("BigQuery execution_outcomes.logs (sql/l2_intents_events.sql)" if intents_status.get("source") == "bigquery"
                 else "FastNear neardata sampled blocks, intents.near execution-outcome logs (data/blocks/intents_events_sampled.csv)") + "; parsed by near_thesis/intents.py"
        cov = intents_status.get("coverage") or {}
        partial2 = "" if intents_status.get("source") == "bigquery" or cov.get("sample_complete") else f" Partial block sample ({cov.get('blocks_fetched', 0):,} of {cov.get('blocks_requested', 0):,} blocks); months without sampled days are absent."
        if im["hhi_solver"].notna().any():
            specs.append(_spec("intents_conc", "3. Quality-adjusted", "Solver concentration in NEAR Intents (HHI and top-1 share)",
                "Lower is more competitive; computed from raw token_diff events on sampled days." + partial2,
                "line", [{"name": "HHI", "points": _pts(im["hhi_solver"], round_to=3)}, {"name": "top-1 solver share", "points": _pts(im["top1_solver_share"], round_to=3)}],
                unit="share", y_domain=[0, 1], source=L2SRC, query="daily HHI of solver outflow USD, monthly mean"))
        else:
            specs.append(_spec("intents_conc", "3. Quality-adjusted", "Solver concentration in NEAR Intents (HHI and top-1 share)",
                "Not estimable yet: no sampled day has enough batches to classify solvers." + partial2, "empty", [], source=L2SRC, query="daily HHI of solver outflow USD, monthly mean"))
        specs.append(_spec("intents_users", "3. Quality-adjusted", "Observed non-solver accounts in sampled windows",
            "Counts inside the observed windows; not an estimate of daily unique users. Solver roles are behavioral assumptions." + partial2,
            "line", [{"name": "observed accounts", "points": _pts(im["users_per_day"], round_to=0)}],
            unit="accounts", source=L2SRC, query="unique non-solver accounts inside each day's sampled windows; monthly mean; no expansion of users"))
        iq = pd.read_csv(MODELS / "intents_quarterly.csv", parse_dates=["quarter"]).set_index("quarter")
        rr = intents_status.get("ratio_to_defillama") or {}
        specs.append(_spec("intents_xcheck", "3. Quality-adjusted", "Intents quarterly volume: on-chain estimate vs DefiLlama",
            "Our independent estimate from raw token_diff events (priced legs, expanded from sampled blocks) against the DefiLlama/Dune series, by quarter. "
            + (f"Pooled ratio {rr['ratio']*100:.0f}% (conditional day-bootstrap interval {rr['ci_lo']*100:.0f}% to {rr['ci_hi']*100:.0f}%). Discrepancy unresolved: this does not independently validate the reported total or its trend." if rr else "") + partial2,
            "line", [{"name": "on-chain estimate (priced)", "points": _pts(iq["volume_est_usd"], round_to=0)},
                     {"name": "DefiLlama", "points": _pts(iq["defillama_usd"], round_to=0)}],
            unit="USD", y_log=True, source=L2SRC + "; DefiLlama", query="near_thesis/intents.py quarterly_estimates and pooled_ratio (ratio of sums, day bootstrap)"))
    else:
        specs.append(_spec("intents_conc", "3. Quality-adjusted", "Intents microstructure (solver concentration, users, trade size)",
            "Not computed: " + intents_status.get("reason", ""), "empty", [], source="BigQuery execution_outcomes.logs", query=SQL_NOTE))

    # ---- Section 4: price decoupling and econometrics
    specs.append(_spec("yearly_corr", "4. Price and usage", "Correlation of log price with log usage, by calendar year",
        "Within-year correlation of price with active accounts flipped sign in 2026; correlation with Intents volume was negative in 2025.",
        "diverging", [{"name": _label(c), "points": [[str(int(y)), round(float(v), 2)] for y, v in zip(yc["year"], yc[c]) if pd.notna(v)]}
                      for c in ["active_accounts", "txns", "tx_volume_usd", "intents_volume_usd"] if c in yc.columns],
        unit="Pearson r", y_domain=[-1, 1], source="data/derived/daily.csv", query="Pearson(log price, log metric) per year (near_thesis/econ.py yearly_corr)"))
    specs.append(_spec("rolling_corr", "4. Price and usage", "Rolling 90-day correlation of log price with log usage",
        "The price-usage link is unstable; long stretches are near zero or negative, which is what decoupling looks like.",
        "line", [{"name": _label(c), "points": _pts(rc[c], round_to=2)} for c in ["active_accounts", "tx_volume_usd", "intents_volume_usd"] if c in rc.columns],
        unit="Pearson r", y_domain=[-1, 1], source="data/derived/daily.csv", query="rolling(90).corr on log levels (near_thesis/econ.py)"))
    specs.append(_spec("granger", "4. Price and usage", "Granger causality p-values (weekly, lag by AIC)",
        "Only models passing stationarity, stability and residual-whiteness checks are shown. Holm-adjusted p-values; omitted tests are inconclusive, not evidence of no relation.",
        "ranked", [{"name": "usage -> price", "points": [[_label(r["metric"]), round(r["usage_granger_causes_price"]["p_value_holm"], 3)] for r in vg if r.get("inference_valid")]},
                   {"name": "price -> usage", "points": [[_label(r["metric"]), round(r["price_granger_causes_usage"]["p_value_holm"], 3)] for r in vg if r.get("inference_valid")]}],
        unit="p-value", y_domain=[0, 1], source="data/derived/daily.csv", query="VAR on weekly d-log series, statsmodels test_causality (near_thesis/econ.py)"))
    specs.append(_spec("ic", "4. Price and usage", "Does a 4-week change in usage predict 12-week excess returns vs BTC?",
        "Exploratory Spearman association; overlapping returns and multiple tests limit inference. QAA is trained only on past calibration months and released after month-end. This is not a trading backtest.",
        "ranked", [{"name": "IC (12w, vs BTC)", "points": [[_label(r["metric"]), round(r["spearman_ic"], 2)] for r in ic if r.get("horizon_weeks") == 12 and r.get("benchmark") == "btc" and "spearman_ic" in r]}],
        unit="Spearman IC", y_domain=[-1, 1], source="data/derived/daily.csv", query="near_thesis/signal.py ic_table",
        note="95% block-bootstrap intervals: " + json.dumps({_label(r["metric"]): r["ci95_block_bootstrap"] for r in ic if r.get("horizon_weeks") == 12 and r.get("benchmark") == "btc" and "spearman_ic" in r})))

    # ---- Section 5: peers
    p = peers.set_index("chain")
    specs.append(_spec("peer_velocity", "5. Peers", "DEX volume (30d) divided by TVL",
        "Descriptive ratio only: cross-chain Intents settlement and local DEX activity have different coverage; this ranking does not establish relative undervaluation.",
        "ranked", [{"name": "velocity", "points": [[c, round(float(v), 1)] for c, v in p["dex_volume_to_tvl_30d"].sort_values(ascending=False).items()]}],
        unit="x", source="DefiLlama overview/dexs/<chain>, v2/chains", query="total30d / tvl", note="emphasis:Near"))
    specs.append(_spec("peer_fees", "5. Peers", "Annualized application fees divided by market cap",
        "Gross application fees are not token-holder yield. Intents net capture and buyback-labelled revenue are tracked separately in the revenue chart.",
        "ranked", [{"name": "fees / mcap", "points": [[c, round(float(v), 3)] for c, v in p["fees_to_mcap_annualized"].dropna().sort_values(ascending=False).items()]}],
        unit="ratio", source="DefiLlama overview/fees/<chain>; CoinGecko coins/markets", query="total30d x 12 / market_cap", note="emphasis:Near"))

    # ---- Section 6: developers
    dev = pd.read_csv(DERIVED / "developer.csv", parse_dates=["week"])
    if len(dev):
        core = dev[dev["repo"] == "near/nearcore"].set_index("week")["commits"]
        specs.append(_spec("dev", "6. Developers", "Weekly commits to near/nearcore (last 52 weeks)",
            "Protocol development continued at a steady pace through the activity decline.",
            "column", [{"name": "commits", "points": _pts(core, round_to=0)}], unit="commits",
            source="GitHub REST repos/near/nearcore/stats/commit_activity", query="weekly totals"))

    if "intents_revenue_usd" in m and m["intents_revenue_usd"].notna().any():
        specs.append(_spec("intents_capture", "2. Value-weighted activity", "Intents: gross fees, net captured revenue and buyback-labelled revenue",
            "Net capture is already observed. The adapter labels post-fee-switch receipts as buyback revenue; this is not proof of burning or dividends, and future allocation remains discretionary.",
            "line", [{"name": title, "points": _pts(m.loc[full_months, col], round_to=0)} for title, col in [
                ("gross fees", "intents_fees_usd"), ("net captured revenue", "intents_revenue_usd"),
                ("buyback-labelled revenue", "intents_holders_revenue_usd")]],
            unit="USD", source="DefiLlama summary/fees/near-intents: dailyFees, dailyRevenue, dailyHoldersRevenue (Dune/wallet receipts)",
            query="monthly sums of matched-cutoff raw snapshots; methodology included in each response"))
    specs += reconciliation_specs()
    specs += bridge_specs(m)
    specs += oos_specs()
    kpis = narrative.story_kpis(d, m, intents_status)
    story = narrative.build(d, m, qaa_status, intents_status, ic, vg)
    manifest = raw_manifest()
    return {"built_at": max(r["fetched_at"] for r in manifest), "data_through": str(d.index.max().date()),
            "kpis": kpis, "charts": specs, "raw_manifest": manifest, **story}


def _optional(name: str) -> dict:
    f = MODELS / name
    return json.loads(f.read_text()) if f.exists() else {}


def reconciliation_specs() -> list[dict]:
    rec = _optional("intents_reconciliation.json")
    if not rec.get("computed"):
        return []
    t = pd.read_csv(MODELS / "intents_reconciliation_daily.csv", parse_dates=["date"]).set_index("date")
    t = t[t["reference_usd"] > 0]
    pooled = rec.get("pooled_ratio_all_days") or {}
    hold = (rec.get("holdout") or {}).get("validation") or {}
    out = [_spec("intents_recon_daily", "3. Quality-adjusted", "Per-day reconciliation: on-chain estimate divided by the DefiLlama reference",
        ("Each sampled day with a reference value. A ratio of 1 would mean the expanded sample reproduces the reference; " +
         (f"the pooled ratio is {pooled.get('ratio', 0):.2f} and the pre-declared validation days give {hold['ratio']:.2f} [{hold['ci_lo']:.2f}, {hold['ci_hi']:.2f}], outside the declared x0.8 to x1.25 band. " if "ratio" in hold else "") +
         "The table view carries observed volume, expansion factor, reference, difference and the per-day components (coverage, unpriced legs, window split)."),
        "column", [{"name": "estimate / reference", "points": [[str(i.date()), round(float(v), 3)] for i, v in t["ratio"].items()]}],
        unit="ratio", source="near_thesis/reconcile.py from data/blocks/intents_events_sampled.csv and data/derived/daily.csv (DefiLlama reference)",
        query="intents_reconciliation_daily.csv: volume_expanded_usd / reference_usd per sampled day; holdout_role marks calibration and validation days",
        note=("economic unit: " + rec["economic_unit"]["our_measure"]))]
    intra = rec.get("intraday") or {}
    days = [x for x in intra.get("days", []) if x.get("hour_share_of_sampled")]
    if days:
        series = [{"name": x["day"], "points": [[f"{h}h", round(float(v or 0) * 100, 1)] for h, v in sorted(x["hour_share_of_sampled"].items())]} for x in days]
        bias = intra.get("fixed_window_bias_factor_median")
        out.append(_spec("intents_intraday", "3. Quality-adjusted", "Intraday profile on the pre-declared reconciliation days: share of sampled volume by hour",
            (f"Twenty-four 50-block windows per day. The fixed 03:00 and 15:00 UTC windows of the main sample under-represent the hourly mean by a median factor of {bias:.2f} on these days (mean {intra.get('fixed_window_bias_factor_mean'):.2f}; one hourly window can carry most of a day's sampled volume); " if bias else "") +
            "a flat profile would put about 4.2% in every hour. Selection rule: " + (intra.get("selection_rule") or "") + ".",
            "diverging", series, unit="% of day's sampled volume", y_domain=[0, max(5.0, max(p[1] for sr in series for p in sr["points"]) * 1.1)],
            source="make blocks-intraday: FastNear neardata hourly windows (data/blocks/intraday_events.csv, intraday_manifest.json)",
            query="near_thesis/reconcile.py intraday(): half gross notional per hourly window / day total"))
    return out


def bridge_specs(m: pd.DataFrame) -> list[dict]:
    b = _optional("value_bridge.json")
    if not b.get("steps"):
        return []
    pts = [[f"{s['step']}. {s.get('short', s['name'])}", round(float(s["usd"]), 0)] for s in b["steps"] if s.get("usd") is not None]
    out = [_spec("value_bridge", "2. Value-weighted activity", "Value bridge, trailing year: from settled volume to tokens received by the buyback wallet (USD)",
        "Each bar is one step of the chain; the status of each step (observed, classified, inferred, unavailable) is in the table view and in THESIS.md. "
        + (f"Issuance over the same year added {b['dilution']['net_new_total_near']:,.0f} NEAR ({b['dilution']['annual_total_supply_growth']:.1%} of total supply), "
           f"worth {b['dilution']['net_new_usd_at_average_price'] / 1e6:,.0f}M USD at the average price, more than any buyback step." if b.get("dilution", {}).get("net_new_total_near") else ""),
        "ranked", [{"name": "USD, trailing year", "points": pts}], unit="USD",
        source="DefiLlama dexs/fees adapters for steps 1-4; NearBlocks receipts of buybacks.multisignature.near for steps 5-6 (data/raw/nearblocks_buybacks_*.json); near_thesis/bridge.py",
        query="value_bridge.json steps[]; share_of_previous gives the funnel ratios; dilution from NearBlocks total supply",
        note="statuses: " + "; ".join(f"{s['step']}: {s['status']}" for s in b["steps"]))]
    f = MODELS / "value_bridge_monthly.csv"
    if f.exists():
        vm = pd.read_csv(f, parse_dates=["month"]).set_index("month")
        if "buyback_wallet_usd_in" in vm and vm["buyback_wallet_usd_in"].notna().any():
            out.append(_spec("buybacks_vs_label", "2. Value-weighted activity", "Buyback-labelled revenue (adapter) vs NEAR actually received by the buyback wallet, per month",
                "The adapter labels all captured revenue after 2026-02-23 as buyback revenue; the wallet series shows what arrived at buybacks.multisignature.near, valued at the daily NEAR price. Differences are timing, routing through other treasury wallets and the wallet's creation date.",
                "line", [{"name": "buyback-labelled revenue (USD)", "points": _pts(vm["buyback_labelled_revenue_usd"], round_to=0)},
                         {"name": "received by buyback wallet (USD at daily price)", "points": _pts(vm["buyback_wallet_usd_in"], round_to=0)}],
                unit="USD", source="DefiLlama dailyHoldersRevenue; NearBlocks account txns (TRANSFER receipts) for buybacks.multisignature.near", query="value_bridge_monthly.csv"))
    return out


def oos_specs() -> list[dict]:
    o = _optional("signal_oos.json")
    if not o.get("tests"):
        return []
    rows = [r for r in o["tests"] if r.get("horizon_weeks") == 12 and r.get("benchmark") == "btc" and "ic_evaluation_signed" in r]
    if not rows:
        return []
    return [_spec("oos", "4. Price and usage", "Out-of-sample test (retrospective, temporally separated): evaluation-period IC with the sign frozen in calibration (12 weeks vs BTC)",
        f"Calibration through {o['protocol']['calibration_end']}, evaluation purged by the horizon. {o['summary']['conclusion']}. "
        "Two naive predictors (NEAR momentum, BTC trend) are evaluated the same way as references; Intents volume and QAA are not evaluable for lack of calibration weeks.",
        "ranked", [{"name": "evaluation IC (signed)", "points": [[_label(r["predictor"]) if r["kind"] == "usage" else r["predictor"].replace("_", " "), round(r["ic_evaluation_signed"], 2)] for r in rows]}],
        unit="Spearman IC", y_domain=[-1, 1], source="data/derived/daily.csv; near_thesis/signal.py oos_table", query="signal_oos.json tests[] where horizon_weeks=12 and benchmark=btc",
        note="95% block-bootstrap intervals: " + json.dumps({(_label(r["predictor"]) if r["kind"] == "usage" else r["predictor"]): [round(x, 2) for x in r["ci95_block_bootstrap"]] for r in rows}))]


def _indexed(m: pd.DataFrame) -> list[tuple[str, list]]:
    base = pd.Timestamp("2025-01-01")
    out = []
    for name, col in [("active accounts", "active_accounts"), ("Intents volume", "intents_volume_usd"), ("NEAR price", "near_price"), ("gas fees (NEAR)", "tx_fee_near")]:
        s = m[col].loc[m.index >= base]
        s = s[s.index < m.index.max()]  # drop the partial current month
        if base in s.index and s[base] > 0:
            out.append((name, [[str(i.date()), round(float(v / s[base] * 100), 1)] for i, v in s.dropna().items()]))
    return out


def run() -> None:
    spec = build()
    (SITE / "data.json").write_text(json.dumps(spec, separators=(",", ":"), allow_nan=False))
    print(f"charts: {len(spec['charts'])} specs, {len(spec['kpis'])} KPIs -> site/data.json ({(SITE / 'data.json').stat().st_size / 1024:,.0f} KB)")
