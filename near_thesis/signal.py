"""L4: does usage carry information about forward returns, and how is NEAR valued against peers?

Outputs (data/derived/models/):
- signal_ic.json      Spearman information coefficient of 4-week usage changes vs 4/12-week forward NEAR returns
                      in excess of BTC and ETH, with circular block-bootstrap confidence intervals and a
                      first-half / second-half descriptive stability split
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
SEED = 20261114


def _weekly() -> pd.DataFrame:
    d = pd.read_csv(DERIVED / "daily.csv", parse_dates=["date"]).set_index("date")
    from .qaa import available_series
    q = available_series(d.index)
    if q is not None:
        d["qaa"] = q
    cols = [m for m in METRICS if m in d.columns] + ["near_price", "price_bitcoin", "price_ethereum"]
    w = d[cols].resample("W-SUN").mean()
    return w.loc[w.index <= d.index.max()]


def _bootstrap_rhos(x: np.ndarray, y: np.ndarray, block: int, n_boot: int) -> np.ndarray:
    n = len(x)
    rng = np.random.default_rng(SEED + block)
    if n < 2 * block:
        return np.array([])
    nblocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(n_boot, nblocks))
    idx = ((starts[:, :, None] + np.arange(block)) % n).reshape(n_boot, -1)[:, :n]
    a, b = stats.rankdata(x[idx], axis=1), stats.rankdata(y[idx], axis=1)
    a -= a.mean(axis=1, keepdims=True)
    b -= b.mean(axis=1, keepdims=True)
    denom = np.sqrt((a * a).sum(axis=1) * (b * b).sum(axis=1))
    rho = np.divide((a * b).sum(axis=1), denom, out=np.full(n_boot, np.nan), where=denom > 0)
    return rho[np.isfinite(rho)]


def _interval(rhos: np.ndarray, alpha: float) -> tuple[float, float]:
    return tuple(float(v) for v in np.quantile(rhos, [alpha / 2, 1 - alpha / 2])) if len(rhos) else (float("nan"), float("nan"))


def block_bootstrap_ci(x: np.ndarray, y: np.ndarray, block: int, n_boot: int = 2000, alpha: float = 0.05) -> tuple[float, float]:
    return _interval(_bootstrap_rhos(x, y, block, n_boot), alpha)


def ic_table(w: pd.DataFrame) -> list[dict]:
    out = []
    lp = np.log(w["near_price"])
    bench = {"btc": np.log(w["price_bitcoin"]), "eth": np.log(w["price_ethereum"])}
    family = len([c for c in METRICS if c in w]) * len(HORIZONS) * len(bench)
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
                # Four-week smoothing plus four-week differencing adds signal dependence.
                block = max(h, 8)
                draws = _bootstrap_rhos(df["sig"].to_numpy(), df["fwd"].to_numpy(), block=block, n_boot=4000)
                lo, hi = _interval(draws, 0.05)
                flo, fhi = _interval(draws, 0.05 / family)
                half = len(df) // 2
                r1 = stats.spearmanr(df["sig"].iloc[:half], df["fwd"].iloc[:half]).statistic
                r2 = stats.spearmanr(df["sig"].iloc[half:], df["fwd"].iloc[half:]).statistic
                out.append({"metric": m, "horizon_weeks": h, "benchmark": bname, "n": int(len(df)),
                            "start": str(df.index[0].date()), "end": str(df.index[-1].date()),
                            "spearman_ic": float(rho), "p_value_naive": float(p),
                            "ci95_block_bootstrap": [lo, hi], "ic_first_half": float(r1), "ic_second_half": float(r2),
                            "ci95_familywise_bonferroni": [flo, fhi], "family_tests": family, "bootstrap_draws": 4000, "block_weeks": block,
                            "significant_familywise": bool(np.isfinite(flo) and (flo > 0 or fhi < 0)),
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
    rng = np.random.default_rng(SEED)
    revenue = float(y["intents_revenue_usd"].sum(min_count=1)) if "intents_revenue_usd" in y else float("nan")
    holders = float(y["intents_holders_revenue_usd"].sum(min_count=1)) if "intents_holders_revenue_usd" in y else float("nan")
    capture_obs = revenue / fees_12m if fees_12m and np.isfinite(revenue) else None
    growth = np.clip(np.exp(rng.normal(0.0, 0.6, n)), 0.25, 4.0)
    take = rng.uniform(0.5 * take_bps_obs, 1.5 * take_bps_obs, n)
    share = rng.uniform(max(0, capture_obs * 0.5), min(1, capture_obs * 1.5), n) if capture_obs is not None else rng.uniform(0, 0.5, n)
    token_fees = vol_12m * growth * take / 1e4 * share + gas_fees_12m
    pf = mcap / token_fees
    q = lambda a: {f"p{int(k)}": float(np.quantile(a, k / 100)) for k in [5, 25, 50, 75, 95]}
    return {"as_of": str(last.date()), "inputs": {"intents_volume_12m_usd": vol_12m, "intents_fees_12m_usd": fees_12m,
            "intents_net_revenue_12m_usd": revenue if np.isfinite(revenue) else None,
            "intents_holders_revenue_12m_usd": holders if np.isfinite(holders) else None, "observed_capture_share": capture_obs,
            "observed_take_rate_bps": take_bps_obs, "gas_fees_12m_usd": gas_fees_12m, "market_cap_usd": mcap,
            "current_price_to_gas_fees": mcap / gas_fees_12m if gas_fees_12m else None},
            "assumptions": {"volume_multiplier": "lognormal(median 1, sigma 0.6) clipped [0.25, 4]",
                            "take_rate_bps": "uniform [0.5x, 1.5x] of observed", "share_to_token": "uniform [0.5x, 1.5x] observed net capture, bounded [0,1]" if capture_obs is not None else "uniform [0,0.5]; net capture unavailable",
                            "note": "scenarios, not forecasts: fee switch and governance-controlled buybacks are live; net capture and buyback-labelled revenue are not dividends or proof of token burning; future allocation is discretionary"},
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
