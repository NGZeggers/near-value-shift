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
        "Cross-chain settlement through NEAR Intents grew from a few million dollars a month in late 2024 to billions a month in 2026.",
        "column", [{"name": "Intents volume (USD, monthly)", "points": _pts(d["intents_volume_usd"], freq="MS", how="sum", round_to=0)}],
        unit="USD", source=LL_I, query="sum of totalDataChart by calendar month"))
    specs.append(_spec("fees_split", "2. Value-weighted activity", "Fees on NEAR per month: protocol gas fees vs application fees",
        "Application-level fees (mostly Intents) are now an order of magnitude larger than the gas fees burned by the protocol.",
        "line", [{"name": "gas fees burned (USD)", "points": _pts(m["tx_fee_usd"], round_to=0)},
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
        specs.append(_spec("qaa", "3. Quality-adjusted", "Active accounts vs Quality-Adjusted Active Accounts (QAA)",
            "QAA removes account-months whose behavior clusters with automation and mini-app farming; the decline is far shallower than the headline.",
            "line", [{"name": "active accounts (BigQuery)", "points": _pts(q["active_accounts_bq"], round_to=0)},
                     {"name": "QAA", "points": _pts(q["qaa"], round_to=0)}],
            unit="accounts", y_log=True, source=("BigQuery crypto_near_mainnet_us (sql/l1_*.sql)" if qaa_status.get("source") == "bigquery" else "FastNear neardata sampled blocks (data/blocks/tx_sampled.csv, near_thesis/blocks.py)") + "; clustering in near_thesis/qaa.py",
            query=("sql/l1_account_month_features.sql + sql/l1_account_month_actions.sql; " if qaa_status.get("source") == "bigquery" else "per (month, signer) features inside sampled windows; QAA = human-like share x NearBlocks active accounts; ") + qaa_status.get("algorithm", "")))
        labels = [c for c in q.columns if c not in ("active_accounts_bq", "qaa", "qaa_share")]
        specs.append(_spec("qaa_shares", "3. Quality-adjusted", "Account-months by behavioral cluster",
            "Shares of each behavioral cluster per month; the 2024 bulge is automation and mini-app farming.",
            "stacked", [{"name": c, "points": _pts(q[c], round_to=0)} for c in labels[:6]],
            unit="account-months", source="BigQuery + near_thesis/qaa.py", query="cluster label counts per month"))
    else:
        specs.append(_spec("qaa", "3. Quality-adjusted", "Quality-Adjusted Active Accounts (QAA)", "Not computed: " + qaa_status.get("reason", ""),
            "empty", [], source="BigQuery crypto_near_mainnet_us", query=SQL_NOTE))
    if intents_status.get("computed"):
        im = pd.read_csv(MODELS / "intents_monthly.csv", parse_dates=["month"]).set_index("month")
        L2SRC = ("BigQuery execution_outcomes.logs (sql/l2_intents_events.sql)" if intents_status.get("source") == "bigquery"
                 else "FastNear neardata sampled blocks, intents.near execution-outcome logs (data/blocks/intents_events_sampled.csv)") + "; parsed by near_thesis/intents.py"
        specs.append(_spec("intents_conc", "3. Quality-adjusted", "Solver concentration in NEAR Intents (HHI and top-1 share)",
            "Lower is more competitive; computed from raw token_diff events on sampled days.",
            "line", [{"name": "HHI", "points": _pts(im["hhi_solver"], round_to=3)}, {"name": "top-1 solver share", "points": _pts(im["top1_solver_share"], round_to=3)}],
            unit="share", y_domain=[0, 1], source=L2SRC, query="daily HHI of solver outflow USD, monthly mean"))
        specs.append(_spec("intents_users", "3. Quality-adjusted", "Unique Intents users per day (sampled days)",
            "Distinct non-solver accounts that executed a swap on a sampled day.",
            "line", [{"name": "users per day", "points": _pts(im["users_per_day"], round_to=0)}],
            unit="accounts", source=L2SRC, query="count of accounts not classified as solvers, per sampled day (expanded by blocks-in-day / blocks-sampled in sampled mode; an upper bound)"))
        specs.append(_spec("intents_xcheck", "3. Quality-adjusted", "Intents monthly volume: on-chain estimate vs DefiLlama",
            "Our independent estimate from raw events (priced legs only, with a day-bootstrap 95% interval) against the DefiLlama/Dune series.",
            "line", [{"name": "on-chain estimate (priced)", "points": _pts(im["volume_est_usd"], round_to=0)},
                     {"name": "DefiLlama", "points": _pts(d["intents_volume_usd"], freq="MS", how="sum", round_to=0)}],
            unit="USD", y_log=True, source=L2SRC + "; DefiLlama", query="see near_thesis/intents.py monthly_estimates"))
    else:
        specs.append(_spec("intents_conc", "3. Quality-adjusted", "Intents microstructure (solver concentration, users, trade size)",
            "Not computed: " + intents_status.get("reason", ""), "empty", [], source="BigQuery execution_outcomes.logs", query=SQL_NOTE))

    # ---- Section 4: price decoupling and econometrics
    specs.append(_spec("yearly_corr", "4. Price and usage", "Correlation of log price with log usage, by calendar year",
        "Within-year correlation of price with active accounts flipped sign in 2026; correlation with Intents volume was negative in 2025.",
        "diverging", [{"name": c, "points": [[str(int(y)), round(float(v), 2)] for y, v in zip(yc["year"], yc[c]) if pd.notna(v)]}
                      for c in ["active_accounts", "txns", "tx_volume_usd", "intents_volume_usd"] if c in yc.columns],
        unit="Pearson r", y_domain=[-1, 1], source="data/derived/daily.csv", query="Pearson(log price, log metric) per year (near_thesis/econ.py yearly_corr)"))
    specs.append(_spec("rolling_corr", "4. Price and usage", "Rolling 90-day correlation of log price with log usage",
        "The price-usage link is unstable; long stretches are near zero or negative, which is what decoupling looks like.",
        "line", [{"name": c, "points": _pts(rc[c], round_to=2)} for c in ["active_accounts", "tx_volume_usd", "intents_volume_usd"] if c in rc.columns],
        unit="Pearson r", y_domain=[-1, 1], source="data/derived/daily.csv", query="rolling(90).corr on log levels (near_thesis/econ.py)"))
    specs.append(_spec("granger", "4. Price and usage", "Granger causality p-values (weekly, lag by AIC)",
        "Low p-values mean the past of one series helps predict the other. Transactions and gas fees show two-way links; Intents volume shows none at this sample size.",
        "ranked", [{"name": "usage -> price", "points": [[r["metric"], round(r["usage_granger_causes_price"]["p_value"], 3)] for r in vg if "usage_granger_causes_price" in r]},
                   {"name": "price -> usage", "points": [[r["metric"], round(r["price_granger_causes_usage"]["p_value"], 3)] for r in vg if "price_granger_causes_usage" in r]}],
        unit="p-value", y_domain=[0, 1], source="data/derived/daily.csv", query="VAR on weekly d-log series, statsmodels test_causality (near_thesis/econ.py)"))
    specs.append(_spec("ic", "4. Price and usage", "Does a 4-week change in usage predict 12-week excess returns vs BTC?",
        "Spearman information coefficient with block-bootstrap 95% intervals. A negative, significant value for Intents volume is evidence AGAINST usage leading price.",
        "ranked", [{"name": "IC (12w, vs BTC)", "points": [[r["metric"], round(r["spearman_ic"], 2)] for r in ic if r.get("horizon_weeks") == 12 and r.get("benchmark") == "btc" and "spearman_ic" in r]}],
        unit="Spearman IC", y_domain=[-1, 1], source="data/derived/daily.csv", query="near_thesis/signal.py ic_table",
        note=json.dumps({r["metric"]: r["ci95_block_bootstrap"] for r in ic if r.get("horizon_weeks") == 12 and r.get("benchmark") == "btc" and "spearman_ic" in r})))

    # ---- Section 5: peers
    p = peers.set_index("chain")
    specs.append(_spec("peer_velocity", "5. Peers", "DEX volume (30d) divided by TVL",
        "NEAR turns over its locked value more times than any peer: a settlement layer, not a vault.",
        "ranked", [{"name": "velocity", "points": [[c, round(float(v), 1)] for c, v in p["dex_volume_to_tvl_30d"].sort_values(ascending=False).items()]}],
        unit="x", source="DefiLlama overview/dexs/<chain>, v2/chains", query="total30d / tvl", note="emphasis:Near"))
    specs.append(_spec("peer_fees", "5. Peers", "Annualized application fees divided by market cap",
        "On fee yield NEAR sits near the bottom of the peer group: high throughput, low capture.",
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

    kpis = _kpis(d, m)
    return {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data_through": str(d.index.max().date()),
            "kpis": kpis, "charts": specs, "raw_manifest": raw_manifest()}


def _indexed(m: pd.DataFrame) -> list[tuple[str, list]]:
    base = pd.Timestamp("2025-01-01")
    out = []
    for name, col in [("active accounts", "active_accounts"), ("Intents volume", "intents_volume_usd"), ("NEAR price", "near_price"), ("gas fees (NEAR)", "tx_fee_near")]:
        s = m[col].loc[m.index >= base]
        s = s[s.index < m.index.max()]  # drop the partial current month
        if base in s.index and s[base] > 0:
            out.append((name, [[str(i.date()), round(float(v / s[base] * 100), 1)] for i, v in s.dropna().items()]))
    return out


def _kpis(d: pd.DataFrame, m: pd.DataFrame) -> list[dict]:
    full = m[m.index < m.index.max()]
    last, prev = full.iloc[-1], full.iloc[-13] if len(full) > 13 else full.iloc[0]
    def kpi(label, value, prior, unit, up_is_good=True):
        delta = (value - prior) / prior * 100 if prior else None
        return {"label": label, "value": value, "unit": unit, "delta_pct_yoy": delta, "up_is_good": up_is_good, "month": str(full.index[-1].date())[:7]}
    return [kpi("Intents volume, last full month", float(last["intents_volume_usd"]), float(prev["intents_volume_usd"]), "USD"),
            kpi("Daily active accounts, monthly mean", float(last["active_accounts"]), float(prev["active_accounts"]), "accounts"),
            kpi("USD moved per transaction", float(last["usd_per_txn"]), float(prev["usd_per_txn"]), "USD"),
            kpi("Application fees, last full month", float(last["near_app_fees_usd"]), float(prev["near_app_fees_usd"]), "USD"),
            kpi("Gas fees burned, last full month", float(last["tx_fee_usd"]), float(prev["tx_fee_usd"]), "USD"),
            kpi("NEAR price, monthly mean", float(last["near_price"]), float(prev["near_price"]), "USD", up_is_good=True)]


def run() -> None:
    spec = build()
    (SITE / "data.json").write_text(json.dumps(spec, separators=(",", ":"), allow_nan=False))
    print(f"charts: {len(spec['charts'])} specs, {len(spec['kpis'])} KPIs -> site/data.json ({(SITE / 'data.json').stat().st_size / 1024:,.0f} KB)")
