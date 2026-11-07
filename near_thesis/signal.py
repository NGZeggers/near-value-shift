"""L4: does usage carry information about forward returns, and how is NEAR valued against peers?

Outputs (data/derived/models/):
- signal_ic.json      Spearman information coefficient of 4-week usage changes vs 4/12-week forward NEAR returns
                      in excess of BTC and ETH, with circular block-bootstrap confidence intervals and a
                      first-half / second-half descriptive stability split
- peer_valuation.json NEAR's rank among peers on velocity (DEX volume / TVL) and fee yield (fees / market cap)
- scenarios.json      Monte Carlo *scenarios* (not forecasts) for fee accrual to the NEAR token
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import numpy as np
import pandas as pd
from scipy import stats

from .config import DATA, DERIVED, MODELS

METRICS = ["active_accounts", "txns", "tx_fee_near", "tx_volume_usd", "intents_volume_usd", "qaa"]
HORIZONS = [4, 12]
SEED = 20261114

# Out-of-sample protocol declared 2026-11-06. Retrospective: the history had already been examined in exploratory analyses of
# the previous version, so this is a temporally separated validation, not a prospective one (see "declaration").
OOS_PROTOCOL = {
    "declaration": ("retrospective validation with temporal separation: protocol and split declared 2026-11-06 over a history that earlier "
                    "exploratory analyses of this project had already used; the code enforces calibration/evaluation separation but cannot "
                    "establish that the evaluation period was unknown when the protocol was designed"),
    "prospective": {"frozen_on": "2026-11-06", "rule": "this protocol is not re-tuned; a prospective result uses only data published after 2026-11-06",
                    "intents_and_qaa": ("not evaluable under the declared calibration end; their prospective plan is persisted once in data/prospective/oos_freeze.json "
                                        "(near-thesis oos-freeze) with the effective freeze date, the hash of the calibration rows, the learned sign, the family and the "
                                        "fixed evaluation weeks; later builds load that file and never recompute it, so adding history cannot move the cutoff or the "
                                        "scoring dates, and once the 20 evaluation targets are realized the same build scores the test under the frozen sign"),
                    "persisted_plan": "data/prospective/oos_freeze.json"},
    "hypothesis": "a four-week rise in usage is associated with the subsequent h-week NEAR log return in excess of the benchmark, with the sign fixed in calibration",
    "signal_transform": "weekly means of the daily series; log of the trailing four-week mean, differenced by four weeks; QAA only from the frozen past-only model, available on the first day of the following month",
    "target": "forward h-week log return of NEAR minus the same return of the benchmark (BTC or ETH)",
    "horizons_weeks": HORIZONS, "benchmarks": ["btc", "eth"],
    "calibration_end": "2025-06-29",
    "purge": "evaluation starts h weeks after the calibration end so that no calibration target overlaps an evaluation week",
    "fixed_rule": ("the sign of the calibration Spearman IC is frozen; success requires the evaluation IC under that sign to be positive with the "
                   "Bonferroni-adjusted (24 tests) circular block-bootstrap 95% interval above zero; the unadjusted interval is reported as exploratory only"),
    "benchmark_predictor_treatment": ("the two naive predictors are not members of the 24-test family and are not tested for passing; their evaluation IC is a "
                                      "comparison level that a usage metric should exceed to add information beyond persistence and the market"),
    "walk_forward": "expanding window: each evaluation week re-estimates the sign on targets already realized at that week (purged by h) and predicts the direction of the next target; hit rate reported",
    "family": "6 metrics x 2 horizons x 2 benchmarks = 24 declared tests; Bonferroni intervals reported",
    "benchmark_predictors": {"near_momentum": "trailing four-week NEAR excess log return (persistence)",
                             "btc_trend": "trailing four-week BTC log return (relation to the market benchmark)"},
    "minimum_rows": {"calibration": 30, "evaluation": 20},
    "limitations": ["NearBlocks and DefiLlama series are current snapshots: historical revisions and publication lags are not reconstructed, except QAA availability dates",
                    "overlapping weekly targets; block bootstrap approximates dependence",
                    "descriptive association only: no costs, liquidity or execution rules, so no trading claim"],
}


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


OOS_FAMILY = 24


def oos_criterion(draws: np.ndarray, family: int = OOS_FAMILY) -> dict:
    """Declared criterion: the familywise (Bonferroni) interval must lie above zero. The nominal interval is exploratory."""
    lo, hi = _interval(draws, 0.05)
    flo, fhi = _interval(draws, 0.05 / family)
    fam = bool(np.isfinite(flo) and flo > 0)
    nom = bool(np.isfinite(lo) and lo > 0)
    return {"ci95_block_bootstrap": [lo, hi], "ci95_familywise_bonferroni": [flo, fhi], "family_tests": family,
            "passes_declared_criterion": fam, "passes_nominal_interval_exploratory": nom,
            "status": ("association persists out of sample (familywise interval above zero)" if fam
                       else "nominal interval above zero only: exploratory, not accepted under the familywise criterion" if nom
                       else "no out-of-sample association established")}


PROSPECTIVE_FREEZE = DATA / "prospective" / "oos_freeze.json"
PROSPECTIVE_PROTOCOL_FIELDS = ("signal_transform", "target", "fixed_rule", "family", "minimum_rows", "horizons_weeks", "benchmarks")


def _test_key(predictor: str, h: int, bench: str) -> str:
    return f"{predictor} h={h} vs {bench}"


def _pairs(sig: pd.Series, fwd: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"sig": sig, "fwd": fwd}).replace([np.inf, -np.inf], np.nan).dropna()


def _calibration_hash(cal: pd.DataFrame) -> str:
    rows = [(str(t.date()), round(float(a), 10), round(float(b), 10)) for t, a, b in zip(cal.index, cal["sig"], cal["fwd"])]
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def protocol_hash() -> str:
    return hashlib.sha256(json.dumps({k: OOS_PROTOCOL[k] for k in PROSPECTIVE_PROTOCOL_FIELDS}, sort_keys=True).encode()).hexdigest()


def _draft_plan(df: pd.DataFrame, h: int) -> dict:
    """Recomputed from the current data: a draft until near-thesis oos-freeze persists it. Dates here move with the data by construction."""
    last = df.index[-1]      # last signal week whose h-week target is already realized at the data cutoff
    n_eval = OOS_PROTOCOL["minimum_rows"]["evaluation"]
    return {"frozen": False, "status": "draft: not persisted; run near-thesis oos-freeze to fix the cutoff, sign and evaluation weeks",
            "last_signal_week_with_realized_target": str(last.date()), "calibration_weeks": int(len(df)),
            "calibration_sufficient": bool(len(df) >= OOS_PROTOCOL["minimum_rows"]["calibration"]),
            "evaluation_starts": str((last + pd.Timedelta(weeks=h)).date()),
            "evaluable_from": str((last + pd.Timedelta(weeks=2 * h + n_eval)).date())}


def _freeze_entry(df: pd.DataFrame, predictor: str, h: int, bench: str, frozen_on: pd.Timestamp, data_cutoff: pd.Timestamp) -> dict:
    """Everything a later build needs to score the test without recomputing anything from the history."""
    n_eval = OOS_PROTOCOL["minimum_rows"]["evaluation"]
    cal = df[df.index <= data_cutoff]
    last = cal.index[-1]
    first_eval = frozen_on + pd.offsets.Week(weekday=6)            # first weekly signal date strictly after the freeze
    eval_weeks = pd.date_range(first_eval, periods=n_eval, freq="W-SUN")
    interim = pd.date_range(last + pd.Timedelta(weeks=1), frozen_on, freq="W-SUN")
    rho = float(stats.spearmanr(cal["sig"], cal["fwd"]).statistic) if len(cal) >= 3 else float("nan")
    return {"predictor": predictor, "horizon_weeks": h, "benchmark": bench,
            "frozen_on": str(frozen_on.date()), "data_cutoff": str(data_cutoff.date()),
            "last_signal_week_with_realized_target": str(last.date()),
            "calibration_start": str(cal.index[0].date()), "calibration_end": str(last.date()), "calibration_weeks": int(len(cal)),
            "calibration_sufficient": bool(len(cal) >= OOS_PROTOCOL["minimum_rows"]["calibration"]),
            "calibration_sha256": _calibration_hash(cal), "ic_calibration": rho, "frozen_sign": 1.0 if (np.isnan(rho) or rho >= 0) else -1.0,
            "interim_signal_weeks_excluded": [str(t.date()) for t in interim],
            "interim_reading": ("signal weeks observed before the freeze whose targets were not yet realized: excluded from calibration (no target) and "
                                "from evaluation (observed before the freeze)"),
            "evaluation_signal_weeks": [str(t.date()) for t in eval_weeks],
            "evaluation_starts": str(eval_weeks[0].date()), "evaluation_ends": str(eval_weeks[-1].date()),
            "evaluable_from": str((eval_weeks[-1] + pd.Timedelta(weeks=h)).date()),
            "family_tests": OOS_FAMILY, "block_weeks": max(h, 8), "bootstrap_draws": 4000}


def freeze_prospective_plan(w: pd.DataFrame, frozen_on: str, path=PROSPECTIVE_FREEZE, force: bool = False) -> dict:
    """Persist the prospective plan for every usage test that is not evaluable retrospectively. Written once; refuses to overwrite."""
    path = pathlib.Path(path)
    if path.exists() and not force:
        raise FileExistsError(f"{path} exists; the frozen plan is not recomputed (pass force to replace it deliberately)")
    fo, cutoff = pd.Timestamp(frozen_on), w.index.max()
    lp = np.log(w["near_price"])
    bench = {"btc": np.log(w["price_bitcoin"]), "eth": np.log(w["price_ethereum"])}
    cal_end = pd.Timestamp(OOS_PROTOCOL["calibration_end"])
    tests = {}
    for m in [c for c in METRICS if c in w.columns]:
        sig = np.log(w[m].rolling(4, min_periods=4).mean()).diff(4)
        for h in HORIZONS:
            for bname, lb in bench.items():
                fwd = (lp.shift(-h) - lp) - (lb.shift(-h) - lb)
                df = _pairs(sig, fwd)
                retro_ok = (len(df[df.index <= cal_end]) >= OOS_PROTOCOL["minimum_rows"]["calibration"]
                            and len(df[df.index > cal_end + pd.Timedelta(weeks=h)]) >= OOS_PROTOCOL["minimum_rows"]["evaluation"])
                if retro_ok or not len(df):
                    continue
                tests[_test_key(m, h, bname)] = _freeze_entry(df, m, h, bname, fo, cutoff)
    plan = {"frozen_on": str(fo.date()), "data_cutoff": str(cutoff.date()), "protocol_sha256": protocol_hash(),
            "protocol": {k: OOS_PROTOCOL[k] for k in PROSPECTIVE_PROTOCOL_FIELDS},
            "rule": ("calibration on every signal week whose target was realized at the data cutoff, sign frozen from that calibration, interim weeks excluded, "
                     f"then {OOS_PROTOCOL['minimum_rows']['evaluation']} evaluation signal weeks starting the first week after the freeze; scored once their last "
                     "target is realized, under the frozen sign and the familywise criterion; this file is loaded by later builds and never recomputed"),
            "tests": tests}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=1))
    return plan


def load_frozen_plan(path=PROSPECTIVE_FREEZE) -> dict | None:
    path = pathlib.Path(path)
    return json.loads(path.read_text()) if path.exists() else None


def prospective_evaluation(df: pd.DataFrame, entry: dict) -> dict:
    """Score the frozen plan on the fixed evaluation weeks; nothing is recomputed and no date moves."""
    weeks = pd.DatetimeIndex([pd.Timestamp(d) for d in entry["evaluation_signal_weeks"]])
    cal_now = df[df.index <= pd.Timestamp(entry["calibration_end"])]
    eva = df[df.index.isin(weeks)]
    out = {"frozen": True, "frozen_on": entry["frozen_on"], "data_cutoff_at_freeze": entry["data_cutoff"],
           "last_signal_week_with_realized_target": entry["last_signal_week_with_realized_target"],
           "calibration_weeks": entry["calibration_weeks"], "calibration_sufficient": entry["calibration_sufficient"],
           "calibration_data_unchanged": bool(len(cal_now) and _calibration_hash(cal_now) == entry["calibration_sha256"]),
           "protocol_unchanged": bool(protocol_hash() == entry.get("protocol_sha256", protocol_hash())),
           "frozen_sign": entry["frozen_sign"], "ic_calibration": entry["ic_calibration"],
           "interim_signal_weeks_excluded": len(entry["interim_signal_weeks_excluded"]),
           "evaluation_starts": entry["evaluation_starts"], "evaluation_ends": entry["evaluation_ends"], "evaluable_from": entry["evaluable_from"],
           "evaluation_targets_realized": int(len(eva)), "evaluation_weeks_required": int(len(weeks))}
    if len(eva) < len(weeks):
        out["status"] = f"not evaluable yet: {len(eva)} of {len(weeks)} evaluation targets realized; evaluable from {entry['evaluable_from']}"
        return out
    sign = float(entry["frozen_sign"])
    rho = stats.spearmanr(sign * eva["sig"], eva["fwd"]).statistic
    draws = _bootstrap_rhos((sign * eva["sig"]).to_numpy(), eva["fwd"].to_numpy(), block=int(entry["block_weeks"]), n_boot=int(entry["bootstrap_draws"]))
    crit = oos_criterion(draws, int(entry["family_tests"]))
    out.update({"ic_evaluation_signed": float(rho), **crit, "status": "prospective: " + crit["status"]
                + ("" if entry["calibration_sufficient"] else " (calibration below the declared minimum at the freeze: exploratory)")})
    return out


def _oos_one(sig: pd.Series, fwd: pd.Series, h: int, calibration_end: pd.Timestamp, frozen: dict | None = None) -> dict:
    df = _pairs(sig, fwd)
    cal = df[df.index <= calibration_end]
    eva = df[df.index > calibration_end + pd.Timedelta(weeks=h)]
    out = {"n_calibration": int(len(cal)), "n_evaluation": int(len(eva))}
    if len(cal) < OOS_PROTOCOL["minimum_rows"]["calibration"] or len(eva) < OOS_PROTOCOL["minimum_rows"]["evaluation"]:
        out["status"] = "not evaluable: too few calibration or evaluation weeks"
        if frozen:
            out["prospective_plan"] = prospective_evaluation(df, frozen)
        elif len(df):
            out["prospective_plan"] = _draft_plan(df, h)
        return out
    rho_cal = stats.spearmanr(cal["sig"], cal["fwd"]).statistic
    sign = 1.0 if rho_cal >= 0 else -1.0
    rho_eval = stats.spearmanr(sign * eva["sig"], eva["fwd"]).statistic
    draws = _bootstrap_rhos((sign * eva["sig"]).to_numpy(), eva["fwd"].to_numpy(), block=max(h, 8), n_boot=4000)
    crit = oos_criterion(draws)
    # walk-forward: re-estimate the sign each evaluation week using only targets realized by then
    hits, n_wf = 0, 0
    for t in eva.index:
        train = df[df.index <= t - pd.Timedelta(weeks=h)]
        if len(train) < OOS_PROTOCOL["minimum_rows"]["calibration"]:
            continue
        s_t = 1.0 if stats.spearmanr(train["sig"], train["fwd"]).statistic >= 0 else -1.0
        pred = s_t * (eva.loc[t, "sig"] - train["sig"].median())
        if pred != 0 and eva.loc[t, "fwd"] != 0:
            n_wf += 1
            hits += int(np.sign(pred) == np.sign(eva.loc[t, "fwd"]))
    out.update({"calibration_start": str(cal.index[0].date()), "calibration_end": str(cal.index[-1].date()), "ic_calibration": float(rho_cal), "frozen_sign": sign,
                "evaluation_start": str(eva.index[0].date()), "evaluation_end": str(eva.index[-1].date()),
                "ic_evaluation_signed": float(rho_eval), **crit,
                "walk_forward_hit_rate": (hits / n_wf) if n_wf else None, "walk_forward_n": n_wf,
                "sign_agrees": bool(rho_eval > 0)})
    return out


def oos_table(w: pd.DataFrame, frozen_plan: dict | None = None, freeze_path=PROSPECTIVE_FREEZE) -> dict:
    """Temporally separated (retrospective) out-of-sample evaluation of the usage signals and of two naive benchmark predictors.

    Tests that are not evaluable retrospectively carry the persisted prospective plan (loaded, never recomputed)."""
    frozen_plan = frozen_plan if frozen_plan is not None else (load_frozen_plan(freeze_path) or {})
    frozen_tests = frozen_plan.get("tests", {})
    lp = np.log(w["near_price"])
    bench = {"btc": np.log(w["price_bitcoin"]), "eth": np.log(w["price_ethereum"])}
    cal_end = pd.Timestamp(OOS_PROTOCOL["calibration_end"])
    rows = []
    predictors = {m: np.log(w[m].rolling(4, min_periods=4).mean()).diff(4) for m in METRICS if m in w.columns}
    naive = {"near_momentum": lambda lb: (lp - lp.shift(4)) - (lb - lb.shift(4)), "btc_trend": lambda lb: bench["btc"] - bench["btc"].shift(4)}
    for h in HORIZONS:
        for bname, lb in bench.items():
            fwd = (lp.shift(-h) - lp) - (lb.shift(-h) - lb)
            for m, sig in predictors.items():
                rows.append({"predictor": m, "kind": "usage", "horizon_weeks": h, "benchmark": bname,
                             **_oos_one(sig, fwd, h, cal_end, frozen_tests.get(_test_key(m, h, bname)))})
            for name, fn in naive.items():
                rows.append({"predictor": name, "kind": "naive_benchmark", "horizon_weeks": h, "benchmark": bname, **_oos_one(fn(lb), fwd, h, cal_end)})
    usage = [r for r in rows if r["kind"] == "usage"]
    evaluable = [r for r in usage if "ic_evaluation_signed" in r]
    passing = [r for r in evaluable if r["passes_declared_criterion"]]
    nominal_only = [r for r in evaluable if r["passes_nominal_interval_exploratory"] and not r["passes_declared_criterion"]]
    best_naive = max((r["ic_evaluation_signed"] for r in rows if r["kind"] == "naive_benchmark" and "ic_evaluation_signed" in r), default=None)
    conclusion = ("no usage metric passes the declared familywise out-of-sample criterion" if evaluable and not passing
                  else f"{len(passing)} of {len(evaluable)} evaluable usage tests pass the declared familywise criterion" if evaluable
                  else "no usage test is evaluable under the declared protocol")
    if nominal_only:
        conclusion += f" ({len(nominal_only)} would pass the unadjusted interval only; exploratory)"
    planned = [r for r in usage if r.get("prospective_plan")]
    plans = {_test_key(r["predictor"], r["horizon_weeks"], r["benchmark"]): r["prospective_plan"]["evaluable_from"] for r in planned}
    scored = [r for r in planned if "ic_evaluation_signed" in r["prospective_plan"]]
    pro_pass = [r for r in scored if r["prospective_plan"]["passes_declared_criterion"]]
    if scored:
        conclusion += f"; prospective: {len(pro_pass)} of {len(scored)} scored tests pass the familywise criterion under the frozen sign"
    prospective = {"frozen": bool(frozen_tests), "frozen_on": frozen_plan.get("frozen_on"), "data_cutoff_at_freeze": frozen_plan.get("data_cutoff"),
                   "file": str(pathlib.Path(freeze_path).relative_to(DATA.parent)) if frozen_tests and pathlib.Path(freeze_path).is_relative_to(DATA.parent) else None,
                   "tests_planned": len(planned), "tests_scored": len(scored), "tests_passing": len(pro_pass),
                   "evaluation_starts": sorted({r["prospective_plan"]["evaluation_starts"] for r in planned}),
                   "targets_realized": {_test_key(r["predictor"], r["horizon_weeks"], r["benchmark"]):
                                        f"{r['prospective_plan'].get('evaluation_targets_realized', 0)}/{r['prospective_plan'].get('evaluation_weeks_required', OOS_PROTOCOL['minimum_rows']['evaluation'])}"
                                        for r in planned},
                   "calibration_data_unchanged": all(r["prospective_plan"].get("calibration_data_unchanged", True) for r in planned),
                   "protocol_unchanged": all(r["prospective_plan"].get("protocol_unchanged", True) for r in planned)}
    return {"protocol": OOS_PROTOCOL, "tests": rows, "summary": {"usage_tests": len(usage), "evaluable": len(evaluable), "passing": len(passing),
            "passing_nominal_only": len(nominal_only),
            "not_evaluable": [_test_key(r["predictor"], r["horizon_weeks"], r["benchmark"]) for r in usage if "ic_evaluation_signed" not in r],
            "prospective_evaluable_from": plans, "prospective": prospective,
            "best_naive_benchmark_ic": best_naive, "conclusion": conclusion}}


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
    oos = oos_table(w)
    (MODELS / "signal_oos.json").write_text(json.dumps(oos, indent=1, default=str))
    pv = peer_valuation()
    (MODELS / "peer_valuation.json").write_text(json.dumps(pv, indent=1))
    sc = scenarios()
    (MODELS / "scenarios.json").write_text(json.dumps(sc, indent=1))
    sig = [r for r in ic if r.get("significant_bootstrap")]
    print(f"L4: {len(ic)} IC tests, {len(sig)} significant by block bootstrap; out of sample: {oos['summary']['conclusion']}; peers ranked; scenarios drawn")
    return {"ic": ic, "oos": oos, "peers": pv, "scenarios": sc}
