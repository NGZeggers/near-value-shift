"""L3: econometrics of the regime shift.

Outputs (data/derived/models/):
- breaks.json          structural breaks (PELT, l2 cost on standardized log series) per metric
- stationarity.json    ADF on log levels and weekly log differences
- var_granger.json     VAR on weekly d-log series, lag by AIC, pairwise Granger tests both directions
- johansen.json        Johansen trace test price vs each usage metric (log levels, weekly)
- rolling_corr.csv     rolling 90-day correlation of log price vs log usage metrics (daily levels)
- yearly_corr.csv      Pearson correlation per calendar year, price vs each metric (log levels)
Every test reports the sample window and the number of observations, so a reader can judge power.
"""
from __future__ import annotations

import json
import math
import warnings

import numpy as np
import pandas as pd
import ruptures as rpt
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import adfuller
from statsmodels.tsa.vector_ar.vecm import coint_johansen

from .config import DERIVED, MODELS

USAGE = ["active_accounts", "txns", "tx_fee_usd", "tx_volume_usd", "intents_volume_usd", "near_app_fees_usd"]
PRICE = "near_price"


def _load_daily() -> pd.DataFrame:
    d = pd.read_csv(DERIVED / "daily.csv", parse_dates=["date"]).set_index("date")
    # QAA (L1) is merged if present so the same tests run on the quality-adjusted series
    qaa = MODELS / "qaa_monthly.csv"
    if qaa.exists():
        q = pd.read_csv(qaa, parse_dates=["month"]).set_index("month")["qaa"]
        d["qaa"] = q.reindex(d.index, method="ffill")
    return d


def _logs(s: pd.Series) -> pd.Series:
    s = s.astype(float).where(s > 0)
    return np.log(s)


# ---------- structural breaks ----------

def detect_breaks(s: pd.Series, *, min_size: int = 90, smooth: int = 7, pen_mult: float = 3.0) -> dict:
    x = _logs(s.rolling(smooth, min_periods=1).mean()).dropna()
    if len(x) < 3 * min_size:
        return {"n": int(len(x)), "breaks": [], "note": "series too short"}
    z = ((x - x.mean()) / x.std()).to_numpy().reshape(-1, 1)
    n = len(z)
    pen = pen_mult * math.log(n)  # on a standardized signal, sigma^2 = 1
    idx = rpt.Pelt(model="l2", min_size=min_size, jump=1).fit(z).predict(pen=pen)
    cuts = [i for i in idx if i < n]
    segs, prev = [], 0
    for c in cuts + [n]:
        seg = x.iloc[prev:c]
        segs.append({"start": str(seg.index[0].date()), "end": str(seg.index[-1].date()),
                     "mean_level": float(np.exp(seg.mean())), "days": int(len(seg))})
        prev = c
    return {"n": n, "start": str(x.index[0].date()), "end": str(x.index[-1].date()), "penalty": pen,
            "breaks": [str(x.index[i].date()) for i in cuts], "segments": segs}


# ---------- stationarity ----------

def adf(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) < 30:
        return {"n": int(len(s)), "note": "too short"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stat, p, lags, nobs, crit, _ = adfuller(s, autolag="AIC")
    return {"n": int(nobs), "adf_stat": float(stat), "p_value": float(p), "lags": int(lags),
            "stationary_5pct": bool(p < 0.05)}


# ---------- VAR / Granger ----------

def weekly_dlogs(d: pd.DataFrame, cols: list[str], start: str | None = None) -> pd.DataFrame:
    w = d[cols].resample("W-SUN").mean()
    if start:
        w = w.loc[w.index >= pd.Timestamp(start)]
    return _logs_df(w).diff().dropna()


def _logs_df(df: pd.DataFrame) -> pd.DataFrame:
    return df.apply(_logs)


def var_granger(d: pd.DataFrame, metric: str, start: str | None) -> dict:
    cols = [PRICE, metric]
    w = weekly_dlogs(d, cols, start)
    w = w.replace([np.inf, -np.inf], np.nan).dropna()
    if len(w) < 40:
        return {"metric": metric, "n_weeks": int(len(w)), "note": "fewer than 40 weekly observations"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = VAR(w)
        res = model.fit(maxlags=min(8, len(w) // 10), ic="aic")
        lag = int(res.k_ar) if res.k_ar > 0 else 1
        if res.k_ar == 0:
            res = model.fit(1)
        g_usage_to_price = res.test_causality(PRICE, [metric], kind="f")
        g_price_to_usage = res.test_causality(metric, [PRICE], kind="f")
        irf = res.irf(8)
    # cumulative response of price to a one-sd shock in usage (orthogonalized, usage ordered first)
    order = [metric, PRICE]
    res2 = VAR(w[order]).fit(lag)
    cum = res2.irf(8).orth_cum_effects  # shape (periods+1, k, k) response i to shock j
    k = order.index(PRICE)
    j = order.index(metric)
    return {
        "metric": metric, "start": str(w.index[0].date()), "end": str(w.index[-1].date()), "n_weeks": int(len(w)),
        "lag_aic": lag,
        "usage_granger_causes_price": {"F": float(g_usage_to_price.test_statistic), "p_value": float(g_usage_to_price.pvalue)},
        "price_granger_causes_usage": {"F": float(g_price_to_usage.test_statistic), "p_value": float(g_price_to_usage.pvalue)},
        "cum_price_response_to_usage_shock_8w": float(cum[8, k, j]),
        "contemporaneous_corr_dlog": float(w[PRICE].corr(w[metric])),
    }


def johansen(d: pd.DataFrame, metric: str, start: str | None) -> dict:
    cols = [PRICE, metric]
    w = d[cols].resample("W-SUN").mean()
    if start:
        w = w.loc[w.index >= pd.Timestamp(start)]
    lw = _logs_df(w).replace([np.inf, -np.inf], np.nan).dropna()
    if len(lw) < 40:
        return {"metric": metric, "n_weeks": int(len(lw)), "note": "fewer than 40 weekly observations"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        jr = coint_johansen(lw, det_order=0, k_ar_diff=2)
    trace0, trace1 = float(jr.lr1[0]), float(jr.lr1[1])
    cv0, cv1 = jr.cvt[0], jr.cvt[1]  # 90, 95, 99
    return {"metric": metric, "n_weeks": int(len(lw)), "start": str(lw.index[0].date()), "end": str(lw.index[-1].date()),
            "trace_r0": trace0, "cv95_r0": float(cv0[1]), "trace_r1": trace1, "cv95_r1": float(cv1[1]),
            "cointegrated_5pct": bool(trace0 > cv0[1] and trace1 <= cv1[1])}


# ---------- correlations ----------

def rolling_corr(d: pd.DataFrame, window: int = 90) -> pd.DataFrame:
    lp = _logs(d[PRICE])
    out = pd.DataFrame(index=d.index)
    for m in [c for c in USAGE + ["qaa"] if c in d.columns]:
        out[m] = lp.rolling(window, min_periods=window).corr(_logs(d[m]))
    out.index.name = "date"
    return out.dropna(how="all")


def yearly_corr(d: pd.DataFrame) -> pd.DataFrame:
    lp = _logs(d[PRICE])
    rows = []
    for y, grp in d.groupby(d.index.year):
        row = {"year": int(y), "days": int(len(grp))}
        for m in [c for c in USAGE + ["qaa"] if c in d.columns]:
            x = _logs(grp[m]); yv = lp.loc[grp.index]
            ok = x.notna() & yv.notna()
            row[m] = float(x[ok].corr(yv[ok])) if ok.sum() > 30 else None
        rows.append(row)
    return pd.DataFrame(rows)


def run() -> dict:
    d = _load_daily()
    metrics = [c for c in USAGE + ["qaa"] if c in d.columns]
    starts = {m: ("2024-12-01" if m == "intents_volume_usd" else "2023-01-01" if m == "near_app_fees_usd" else None) for m in metrics}

    breaks = {m: detect_breaks(d[m]) for m in metrics + [PRICE]}
    (MODELS / "breaks.json").write_text(json.dumps(breaks, indent=1))

    stat = {}
    for m in metrics + [PRICE]:
        wk = d[[m]].resample("W-SUN").mean()[m]
        stat[m] = {"log_level_weekly": adf(_logs(wk)), "dlog_weekly": adf(_logs(wk).diff())}
    (MODELS / "stationarity.json").write_text(json.dumps(stat, indent=1))

    vg = [var_granger(d, m, starts[m]) for m in metrics]
    (MODELS / "var_granger.json").write_text(json.dumps(vg, indent=1))

    jo = [johansen(d, m, starts[m]) for m in metrics]
    (MODELS / "johansen.json").write_text(json.dumps(jo, indent=1))

    rolling_corr(d).to_csv(MODELS / "rolling_corr.csv")
    yearly_corr(d).to_csv(MODELS / "yearly_corr.csv", index=False)
    print(f"L3: breaks for {len(breaks)} series, VAR/Granger for {len(vg)} metrics, Johansen for {len(jo)}")
    return {"breaks": breaks, "var_granger": vg, "johansen": jo}
