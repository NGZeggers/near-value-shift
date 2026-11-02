"""L4: does usage carry information about forward returns, and how is NEAR valued against peers?

Outputs (data/derived/models/):
- signal_ic.json      Spearman information coefficient of 4-week usage changes vs 4/12-week forward NEAR returns
                      in excess of BTC and ETH, with circular block-bootstrap confidence intervals and a
                      first-half / second-half split (walk-forward sanity check)
- peer_valuation.json NEAR's rank among peers on velocity (DEX volume / TVL) and fee yield (fees / market cap)
- scenarios.json      Monte Carlo *scenarios* (not forecasts) for fee accrual to the NEAR token
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy import stats

from .config import DERIVED, MODELS

METRICS = ["active_accounts", "txns", "tx_fee_near", "tx_volume_usd", "intents_volume_usd", "qaa"]
HORIZONS = [4, 12]
RNG = np.random.default_rng(20261114)


def _weekly() -> pd.DataFrame:
    d = pd.read_csv(DERIVED / "daily.csv", parse_dates=["date"]).set_index("date")
    qaa = MODELS / "qaa_monthly.csv"
    if qaa.exists():
        q = pd.read_csv(qaa, parse_dates=["month"]).set_index("month")["qaa"]
        d["qaa"] = q.reindex(d.index, method="ffill")
    cols = [m for m in METRICS if m in d.columns] + ["near_price", "price_bitcoin", "price_ethereum"]
    w = d[cols].resample("W-SUN").mean()
    return w


def block_bootstrap_ci(x: np.ndarray, y: np.ndarray, block: int, n_boot: int = 2000, alpha: float = 0.05) -> tuple[float, float]:
    n = len(x)
    if n < 2 * block:
        return (float("nan"), float("nan"))
    nblocks = int(np.ceil(n / block))
    rhos = []
    for _ in range(n_boot):
        starts = RNG.integers(0, n, size=nblocks)
        idx = np.concatenate([(s + np.arange(block)) % n for s in starts])[:n]
        r = stats.spearmanr(x[idx], y[idx]).statistic
        if np.isfinite(r):
            rhos.append(r)
    return (float(np.quantile(rhos, alpha / 2)), float(np.quantile(rhos, 1 - alpha / 2)))


def ic_table(w: pd.DataFrame) -> list[dict]:
    out = []
    lp = np.log(w["near_price"])
    bench = {"btc": np.log(w["price_bitcoin"]), "eth": np.log(w["price_ethereum"])}
    for m in [c for c in METRICS if c in w.columns]:
        sig = np.log(w[m].rolling(4, min_periods=4).mean()).diff(4)  # 4-week change of the 4-week mean
        for h in HORIZONS:
            for bname, lb in bench.items():
                fwd = (lp.shift(-h) - lp) - (lb.shift(-h) - lb)
                df = pd.DataFrame({"sig": sig, "fwd": fwd}).replace([np.inf, -np.inf], np.nan).dropna()
                if len(df) < 30:
                    out.append({"metric": m, "horizon_weeks": h, "benchmark": bname, "n": int(len(df)), "note": "too few weeks"})
                    continue
                rho, p = stats.spearmanr(df["sig"], df["fwd"])
                lo, hi = block_bootstrap_ci(df["sig"].to_numpy(), df["fwd"].to_numpy(), block=h)
                half = len(df) // 2
                r1 = stats.spearmanr(df["sig"].iloc[:half], df["fwd"].iloc[:half]).statistic
                r2 = stats.spearmanr(df["sig"].iloc[half:], df["fwd"].iloc[half:]).statistic
                out.append({"metric": m, "horizon_weeks": h, "benchmark": bname, "n": int(len(df)),
                            "start": str(df.index[0].date()), "end": str(df.index[-1].date()),
                            "spearman_ic": float(rho), "p_value_naive": float(p),
                            "ci95_block_bootstrap": [lo, hi], "ic_first_half": float(r1), "ic_second_half": float(r2),
                            "significant_bootstrap": bool(np.isfinite(lo) and (lo > 0 or hi < 0))})
    return out


def peer_valuation() -> dict:
    p = pd.read_csv(DERIVED / "peers.csv")
    def rank(col, ascending=False):
        s = p.set_index("chain")[col].dropna().sort_values(ascending=ascending)
        return {"order": list(s.index), "values": {k: float(v) for k, v in s.items()},
                "near_rank": int(list(s.index).index("Near")) + 1 if "Near" in s.index else None, "n": int(len(s))}
    return {"dex_volume_to_tvl_30d": rank("dex_volume_to_tvl_30d"),
            "fees_to_mcap_annualized": rank("fees_to_mcap_annualized"),
            "stables_to_tvl": rank("stables_to_tvl"),
            "raw": p.to_dict(orient="records")}


def scenarios(n: int = 20000) -> dict:
    d = pd.read_csv(DERIVED / "daily.csv", parse_dates=["date"]).set_index("date")
    last = d.index.max()
    y = d.loc[d.index > last - pd.Timedelta(days=365)]
    vol_12m = float(y["intents_volume_usd"].sum())
    fees_12m = float(y["intents_fees_usd"].sum())
    take_bps_obs = fees_12m / vol_12m * 1e4 if vol_12m else float("nan")
    mcap = float(d["market_cap_usd"].dropna().iloc[-1])
    gas_fees_12m = float(y["tx_fee_usd"].sum())
    # assumption ranges (documented in THESIS.md): volume multiplier lognormal(median 1.0, sigma 0.6) clipped to [0.25, 4],
    # take rate uniform between half and 1.5x the observed rate, share accruing to NEAR holders uniform [0, 0.5]
    growth = np.clip(np.exp(RNG.normal(0.0, 0.6, n)), 0.25, 4.0)
    take = RNG.uniform(0.5 * take_bps_obs, 1.5 * take_bps_obs, n)
    share = RNG.uniform(0.0, 0.5, n)
    token_fees = vol_12m * growth * take / 1e4 * share + gas_fees_12m
    pf = mcap / token_fees
    q = lambda a: {f"p{int(k)}": float(np.quantile(a, k / 100)) for k in [5, 25, 50, 75, 95]}
    return {"as_of": str(last.date()), "inputs": {"intents_volume_12m_usd": vol_12m, "intents_fees_12m_usd": fees_12m,
            "observed_take_rate_bps": take_bps_obs, "gas_fees_12m_usd": gas_fees_12m, "market_cap_usd": mcap,
            "current_price_to_gas_fees": mcap / gas_fees_12m if gas_fees_12m else None},
            "assumptions": {"volume_multiplier": "lognormal(median 1, sigma 0.6) clipped [0.25, 4]",
                            "take_rate_bps": "uniform [0.5x, 1.5x] of observed", "share_to_token": "uniform [0, 0.5]",
                            "note": "scenarios, not forecasts; no fee-sharing mechanism exists on NEAR today"},
            "token_fees_usd": q(token_fees), "price_to_fees": q(pf), "n": n}


def run() -> dict:
    w = _weekly()
    ic = ic_table(w)
    (MODELS / "signal_ic.json").write_text(json.dumps(ic, indent=1))
    pv = peer_valuation()
    (MODELS / "peer_valuation.json").write_text(json.dumps(pv, indent=1))
    sc = scenarios()
    (MODELS / "scenarios.json").write_text(json.dumps(sc, indent=1))
    sig = [r for r in ic if r.get("significant_bootstrap")]
    print(f"L4: {len(ic)} IC tests, {len(sig)} significant by block bootstrap; peers ranked; scenarios drawn")
    return {"ic": ic, "peers": pv, "scenarios": sc}
