"""Reconciliation of the on-chain Intents flow estimate against the DefiLlama/Dune reference.

Answers the audit questions about the L2 volume gap with artifacts a third party can re-run:

- The economic unit of comparison is written down once (ECONOMIC_UNIT) and reported next to the numbers.
- A per-day table (intents_reconciliation_daily.csv) shows observed sampled volume, the expanded estimate, the
  reference, their difference and the components that can be measured for that day.
- The gap is decomposed into temporal coverage, valuation and route reconstruction; whatever cannot be attributed
  stays an explicit residual.
- A tolerance and a holdout split were declared before the holdout days were evaluated (TOLERANCE, HOLDOUT_RULE).
- Traceable examples go from receipt and log to priced legs and batch volume (intents_trace_examples.json).
- When the intraday extract exists (make blocks-intraday), the fixed two-window expansion is compared with 24
  hourly windows on the pre-declared days to measure the intraday expansion error.

Nothing here fetches data. Outputs (data/derived/models/): intents_reconciliation.json, intents_reconciliation_daily.csv,
intents_trace_examples.json.
"""
from __future__ import annotations

import json
from .serialization import dumps as json_dumps

import numpy as np
import pandas as pd

from .config import DATA, DERIVED, MODELS
from . import intents
from .blocks import (SUCCESS_STATUSES, INTRADAY_EVENTS, INTRADAY_MANIFEST, INTRADAY_VALIDATION_EVENTS, INTRADAY_VALIDATION_MANIFEST,
                     INTRADAY_VALIDATION_RULE, usable_windows)

ECONOMIC_UNIT = {
    "unit": "USD notional of settled swaps per UTC calendar day on intents.near",
    "our_measure": ("half gross participant notional: for each successful execute_intents receipt, for each (account, intent_hash) "
                    "take the larger of priced inflow and priced outflow, sum over participants and divide by two. One two-party "
                    "swap of 100 USDC against NEAR counts 100 USD once."),
    "scope": "token_diff events emitted by intents.near in receipts with an explicit successful execution status; all chains and assets that appear in those events; no deposits, withdrawals or transfers",
    "day_boundary": "UTC; a sampled window is attributed to the planned UTC day",
    "prices": "DefiLlama coins daily USD prices (CoinGecko ids from the committed 1Click registry), stablecoins at par, at most seven-day forward fill; unknown or unpriced assets contribute zero",
    "reference": ("DefiLlama dexs/near-intents dailyVolume = SUM(volume_amount_usd) FROM dune.near.dataset_near_intents_metrics "
                  "per date_at (adapter source: DefiLlama/dimension-adapters dexs/near-intents/index.ts). The dataset is a curated Dune "
                  "table maintained for NEAR's metrics; whether volume_amount_usd is one-sided or two-sided notional is not published, "
                  "so the two measures are compared, not assumed identical."),
    "shared_origin": ("DefiLlama does not compute this series itself; it queries Dune. Every public reference found derives from NEAR's own metrics "
                      "datasets (Dune dune.near.*, the ClickHouse table behind near-intents.org, revenue.near.org volumeUsd), so none is of independent "
                      "origin; the Dune series also covers confidential intents, which emit no public token_diff logs and are therefore outside what "
                      "any on-chain log extraction can observe (see reference_definition)."),
}

# What the reference counts, established 2026-11-07 from public sources (adapter code, GitHub issue and PR, site docs); recorded here
# because none of these numbers can be recomputed from this repository.
REFERENCE_DEFINITION = {
    "established": "2026-11-07",
    "adapter": {"source": "DefiLlama/dimension-adapters dexs/near-intents/index.ts", "query": "SUM(CAST(volume_amount_usd AS DOUBLE)) FROM dune.near.dataset_near_intents_metrics WHERE date_at = day",
                "notes": "no methodology comments in the adapter; flagged isExpensiveAdapter; start 2024-11-05"},
    "dataset_maintainer": {"claim": "the dune.near.dataset_near_intents_* tables are uploaded by NEAR (the DefiLlama issue #10317 waits for 'near's datasets' to catch up when fee rows are missing)",
                           "kind": "observed in a public issue, not confirmed by NEAR documentation"},
    "confidential_intents": {"claim": "the Dune all-time volume includes confidential intents, which the ClickHouse table behind near-intents.org excludes",
                             "source": "near/near-intents pull request #77 (hero stat hotfix)", "cumulative_usd_billion": {"public": 30.83, "confidential": 2.52, "dune_total": 33.35, "clickhouse_public_only": 31.03},
                             "share_of_dune_total": 2.52 / 33.35,
                             "kind": "estimate: a cumulative share from a secondary source, applied here to the comparison period as if constant; the period share is unknown",
                             "implication": "confidential intents do not emit public token_diff logs, so they are structurally outside our on-chain measure while inside the reference"},
    "other_references": {"revenue.near.org": "publishes volumeUsd per day equal to the Dune figure (same origin); no API or download",
                         "near-intents.org": "ClickHouse near_intents_metrics.intents_external_metrics, public intents only; no public API",
                         "Intents Explorer API": "1Click swaps only, JWT required, 1 request per 5 s: not a protocol-wide volume source",
                         "Flipside ez_intents": "independent indexer of intents.near logs (one row per token_diff leg, USD per leg); requires an account; not accessed"},
    "one_or_two_sided": "not published anywhere found; the comparison keeps both readings",
}

# Declared 2026-11-06 before the holdout days were evaluated. Symmetric on the log scale (x0.8 to x1.25).
# Daily-close versus execution prices, stablecoin-at-par and forward fill produce dispersion of a few percent (the
# two-sided pricing check below measures it); routed batches and the one- versus two-sided definition can move the
# ratio by tens of percent. A band of +-25% therefore tolerates pricing noise but not missing hours or a definitional
# mismatch. It must not be widened to make the comparison pass.
TOLERANCE = {"point_ratio_min": 0.8, "point_ratio_max": 1.25, "interval_must_include": 1.0,
             "declared": "2026-11-06, before evaluating the holdout days",
             "justification": "covers measured pricing dispersion (a few percent), not coverage or definitional gaps"}
HOLDOUT_RULE = ("sampled days with a positive reference value are sorted chronologically; even positions calibrate, "
                "odd positions validate; declared before evaluation")


def _legs_with_prices(raw: pd.DataFrame, prices: dict) -> pd.DataFrame:
    legs = intents.batches_from_events(raw)
    legs["usd"] = [intents.price_leg(t, a, prices.get(str(d), {})) for t, a, d in zip(legs["token"], legs["amount"], legs["block_date"])]
    legs["intent_key"] = legs["intent_hash"].fillna("legacy")
    legs["direction"] = np.where(legs["amount"] < 0, "out", "in")
    hours = raw[["receipt_id", "window_hour", "block_height", "block_timestamp"]].drop_duplicates("receipt_id")
    return legs.merge(hours, on="receipt_id", how="left")


def batch_values(legs: pd.DataFrame) -> pd.DataFrame:
    """Per receipt: half gross notional, full gross notional and the user-side notional (non-solver accounts)."""
    sides = legs.dropna(subset=["usd"]).groupby(["receipt_id", "account", "intent_key", "direction"])["usd"].sum().unstack(fill_value=0)
    for c in ("in", "out"):
        if c not in sides:
            sides[c] = 0.0
    sides["side"] = sides[["in", "out"]].max(axis=1)
    per = sides.groupby("receipt_id").agg(gross=("side", "sum"))
    per["half_gross"] = per["gross"] / 2
    return per


def two_sided_pricing_check(legs: pd.DataFrame) -> dict:
    """For account-intents whose inflow and outflow are both priced, inflow / outflow should be near 1 at market prices."""
    sides = legs.dropna(subset=["usd"]).groupby(["receipt_id", "account", "intent_key", "direction"])["usd"].sum().unstack(fill_value=0)
    if "in" not in sides or "out" not in sides:
        return {"account_intents_two_sided": 0}
    both = sides[(sides["in"] > 0) & (sides["out"] > 0)]
    r = both["in"] / both["out"]
    q = r.quantile([0.05, 0.25, 0.5, 0.75, 0.95]) if len(r) else pd.Series(dtype=float)
    return {"account_intents_two_sided": int(len(both)),
            "in_over_out": {f"p{int(k * 100)}": float(v) for k, v in q.items()},
            "within_3pct_share": float(((r > 0.97) & (r < 1.03)).mean()) if len(r) else None,
            "reading": "near 1.0 means daily prices and decimals are consistent across the two legs of the same intent"}


def valuation_component(legs: pd.DataFrame) -> dict:
    ai = legs.groupby(["receipt_id", "account", "intent_key"])["usd"].apply(lambda s: s.notna().any())
    unvalued = ai[~ai]
    unpriced = legs[legs["usd"].isna()]
    reg = intents.registry()
    reasons = []
    for token, n in unpriced["token"].value_counts().head(12).items():
        entry = reg.get(token)
        if entry is None:
            reason = "asset id not in the committed 1Click registry"
        else:
            gid = intents.GECKO_ALIASES.get(entry[2], entry[2])
            f = DATA / "raw" / f"price_{gid}.json" if gid else None
            if gid is None:
                reason = "registry entry has no CoinGecko id"
            elif not f.exists():
                reason = f"no price snapshot for {gid}"
            elif not (json.loads(f.read_text()).get("data") or []):
                reason = f"price snapshot {gid} is empty (DefiLlama coins API returned no history)"
            else:
                reason = f"price for {gid} missing on those days beyond the seven-day forward fill"
        reasons.append({"asset_id": token, "legs": int(n), "symbol": entry[0] if entry else None, "reason": reason})
    return {"legs_total": int(len(legs)), "legs_unpriced": int(len(unpriced)), "legs_unpriced_share": float(len(unpriced) / max(1, len(legs))),
            "account_intents": int(len(ai)), "account_intents_without_any_priced_side": int(len(unvalued)),
            "batches_with_unvalued_account_intent": int(unvalued.reset_index()["receipt_id"].nunique()) if len(unvalued) else 0,
            "unpriced_assets_top": reasons, "two_sided_pricing_check": two_sided_pricing_check(legs),
            "reading": ("an account-intent is valued by whichever side is priced, so unpriced legs lose value only when neither side is priced; "
                        "the count above bounds that loss in account-intents, not in USD, which is unobservable without a price")}


def route_component(legs: pd.DataFrame, roles: pd.DataFrame) -> dict:
    per = legs.groupby("receipt_id").agg(accounts=("account", "nunique"), intents=("intent_key", "nunique"), tokens=("token", "nunique"), legs=("token", "size"))
    net = legs.groupby(["receipt_id", "token"]).agg(net=("amount", "sum"), gross=("amount", lambda a: a.abs().sum()))
    rel = (net["net"].abs() / net["gross"].replace(0, np.nan)).dropna()
    bv = batch_values(legs)
    solver_accounts = set(roles.loc[roles["is_solver"], "account"]) if len(roles) else set()
    user_legs = legs[~legs["account"].isin(solver_accounts)]
    user_side = user_legs.dropna(subset=["usd"]).groupby(["receipt_id", "account", "intent_key", "direction"])["usd"].sum().unstack(fill_value=0).max(axis=1).groupby("receipt_id").sum()
    return {"batches": int(len(per)), "accounts_per_batch": per["accounts"].value_counts().sort_index().to_dict(),
            "intents_per_batch": per["intents"].value_counts().sort_index().to_dict(),
            "batches_with_more_than_two_accounts_share": float((per["accounts"] > 2).mean()) if len(per) else None,
            "per_token_net_relative_to_gross": {"p50": float(rel.quantile(0.5)) if len(rel) else None, "p99": float(rel.quantile(0.99)) if len(rel) else None,
                                                "reading": "diffs within a receipt balance per token up to rounding dust; fees are not inside token_diff"},
            "alternative_definitions_total_usd": {"half_gross_participant_notional": float(bv["half_gross"].sum()),
                                                  "full_gross_participant_notional": float(bv["gross"].sum()),
                                                  "user_side_notional_heuristic_roles": float(user_side.sum())},
            "reading": ("if the reference counted both sides of every swap, our ratio would double; if it counted only user legs, it would move by the "
                        "user-side/half-gross factor. These bounds are definitional, not evidence about the reference")}


def daily_table(daily: pd.DataFrame, legs: pd.DataFrame, raw: pd.DataFrame, llama: pd.Series, blocks_per_day: pd.Series) -> pd.DataFrame:
    man = json.loads((DATA / "blocks" / "sample_manifest.json").read_text())
    wins = pd.DataFrame(man["windows"])
    wins = wins[wins["usable"]]
    per_day_windows = wins.groupby("day").agg(windows_usable=("hour", "nunique"), blocks_observed=("fetched", "sum"))
    bv = batch_values(legs).join(legs.drop_duplicates("receipt_id").set_index("receipt_id")[["block_date", "window_hour"]])
    by_hour = bv.groupby(["block_date", "window_hour"])["half_gross"].sum().unstack(fill_value=0.0)
    ai = legs.groupby(["receipt_id", "account", "intent_key"]).agg(valued=("usd", lambda s: s.notna().any()), day=("block_date", "first"))
    unvalued = ai[~ai["valued"]].groupby("day").size()
    legs_unpriced = legs[legs["usd"].isna()].groupby("block_date").size()
    multi = legs.groupby("receipt_id").agg(accounts=("account", "nunique"), day=("block_date", "first"))
    multi_share = multi.groupby("day")["accounts"].apply(lambda a: float((a > 2).mean()))
    rows = []
    d = daily.set_index(daily["date"].dt.date)
    for day, r in d.iterrows():
        ref = llama.get(pd.Timestamp(day))
        w = per_day_windows.loc[str(day)] if str(day) in per_day_windows.index else None
        blocks_obs = int(w["blocks_observed"]) if w is not None else 0
        bpd = float(blocks_per_day.get(pd.Timestamp(day), np.nan))
        rows.append({"date": str(day), "windows_usable": int(w["windows_usable"]) if w is not None else 0,
                     "blocks_observed": blocks_obs, "blocks_in_day": bpd, "block_coverage_share": blocks_obs / bpd if bpd else np.nan,
                     "batches_sampled": float(r.get("batches_sampled", np.nan)), "volume_sampled_usd": float(r.get("volume_priced_usd_sampled", np.nan)),
                     "expansion_factor": float(r.get("expansion_factor", np.nan)), "volume_expanded_usd": float(r["volume_priced_usd"]),
                     "reference_usd": float(ref) if ref is not None and pd.notna(ref) else np.nan,
                     "difference_usd": float(r["volume_priced_usd"] - ref) if ref is not None and pd.notna(ref) else np.nan,
                     "ratio": float(r["volume_priced_usd"] / ref) if ref is not None and pd.notna(ref) and ref > 0 else np.nan,
                     "window03_sampled_usd": float(by_hour.loc[day, 3]) if day in by_hour.index and 3 in by_hour.columns else 0.0,
                     "window15_sampled_usd": float(by_hour.loc[day, 15]) if day in by_hour.index and 15 in by_hour.columns else 0.0,
                     "fully_priced_batch_share": float(r.get("fully_priced_batch_share", np.nan)),
                     "legs_unpriced": int(legs_unpriced.get(day, 0)), "legs_total": int(r.get("total_legs", 0)),
                     "account_intents_unvalued": int(unvalued.get(day, 0)),
                     "batches_more_than_two_accounts_share": float(multi_share.get(day, np.nan))})
    out = pd.DataFrame(rows)
    with_ref = out["reference_usd"].notna() & (out["reference_usd"] > 0)
    order = out.loc[with_ref].sort_values("date").reset_index()
    out["holdout_role"] = ""
    out.loc[order.loc[order.index % 2 == 0, "index"], "holdout_role"] = "calibration"
    out.loc[order.loc[order.index % 2 == 1, "index"], "holdout_role"] = "validation"
    return out


def _pooled(a: np.ndarray, b: np.ndarray, n_boot: int = 4000, seed: int = 11) -> dict:
    if len(a) == 0 or b.sum() <= 0:
        return {"days": int(len(a))}
    rng = np.random.default_rng(seed)
    ratio = a.sum() / b.sum()
    idx = rng.integers(0, len(a), size=(n_boot, len(a)))
    boots = a[idx].sum(axis=1) / b[idx].sum(axis=1)
    return {"days": int(len(a)), "ratio": float(ratio), "ci_lo": float(np.quantile(boots, 0.025)), "ci_hi": float(np.quantile(boots, 0.975))}


def holdout(table: pd.DataFrame) -> dict:
    out = {"rule": HOLDOUT_RULE, "tolerance": TOLERANCE}
    for role in ("calibration", "validation"):
        t = table[table["holdout_role"] == role]
        r = _pooled(t["volume_expanded_usd"].to_numpy(dtype=float), t["reference_usd"].to_numpy(dtype=float), seed=11 if role == "calibration" else 13)
        if "ratio" in r:
            r["within_tolerance"] = bool(TOLERANCE["point_ratio_min"] <= r["ratio"] <= TOLERANCE["point_ratio_max"] and r["ci_lo"] <= TOLERANCE["interval_must_include"] <= r["ci_hi"])
        out[role] = r
    v = out.get("validation", {})
    out["verdict"] = ("validation days within the declared tolerance" if v.get("within_tolerance")
                      else "validation days outside the declared tolerance: the on-chain estimate does not reproduce the reference level" if "ratio" in v
                      else "not evaluable")
    return out


def _reference_days() -> list[str]:
    """Sampled days with both fixed windows usable and a positive DefiLlama reference, from the committed per-day table."""
    t = pd.read_csv(MODELS / "intents_reconciliation_daily.csv")
    return sorted(t.loc[(t["windows_usable"] == 2) & (t["reference_usd"] > 0), "date"].astype(str))


def intraday(prices: dict, blocks_per_day: pd.Series, llama: pd.Series, fixed_hours: tuple[int, ...] = (3, 15),
             events=None, manifest=None) -> dict | None:
    """Compare the two fixed windows with all hourly windows of the selected days (motivating extract by default)."""
    events = INTRADAY_EVENTS if events is None else events
    manifest = INTRADAY_MANIFEST if manifest is None else manifest
    if not events.exists() or not manifest.exists():
        return None
    man = json.loads(manifest.read_text())
    raw = pd.read_csv(events)
    if raw.empty and not man.get("windows"):
        return None
    usable = {(w["day"], int(w["hour"])): int(w["fetched"]) for w in man["windows"] if w.get("usable")}
    raw = raw[raw["execution_status"].isin(SUCCESS_STATUSES)].copy() if len(raw) else raw
    if len(raw):
        raw = raw[[(d, int(h)) in usable for d, h in zip(raw["window_day"], raw["window_hour"])]].copy()
        raw["block_date"] = pd.to_datetime(raw["window_day"]).dt.date
    legs = _legs_with_prices(raw, prices) if len(raw) else pd.DataFrame(columns=["receipt_id", "usd", "account", "intent_key", "direction", "window_hour", "block_date"])
    bv = batch_values(legs) if len(legs) else pd.DataFrame(columns=["half_gross"])
    if len(bv):
        bv = bv.join(legs.drop_duplicates("receipt_id").set_index("receipt_id")[["block_date", "window_hour"]])
    days = []
    for day in man["days"]:
        hours_ok = sorted(h for (d, h) in usable if d == day)
        if not hours_ok:
            days.append({"day": day, "hours_usable": 0, "note": "no usable hourly window"})
            continue
        per_hour = {h: 0.0 for h in hours_ok}
        blocks_h = {h: usable[(day, h)] for h in hours_ok}
        if len(bv):
            sub = bv[bv["block_date"] == pd.Timestamp(day).date()]
            for h, v in sub.groupby("window_hour")["half_gross"].sum().items():
                if int(h) in per_hour:
                    per_hour[int(h)] = float(v)
        bpd = float(blocks_per_day.get(pd.Timestamp(day), np.nan))
        rate_all = np.mean([per_hour[h] / blocks_h[h] for h in hours_ok])            # USD per block, all hours
        fixed = [h for h in fixed_hours if h in per_hour]
        rate_fixed = np.mean([per_hour[h] / blocks_h[h] for h in fixed]) if fixed else np.nan
        est_all = rate_all * bpd if bpd else np.nan
        est_fixed = rate_fixed * bpd if bpd and fixed else np.nan
        ref = llama.get(pd.Timestamp(day))
        total = sum(per_hour.values())
        days.append({"day": day, "hours_usable": len(hours_ok), "blocks_observed": int(sum(blocks_h.values())),
                     "usd_per_hour_window": {f"{h:02d}": per_hour[h] for h in hours_ok},
                     "hour_share_of_sampled": {f"{h:02d}": (per_hour[h] / total if total else None) for h in hours_ok},
                     "fixed_hours_share_of_sampled": float(sum(per_hour[h] for h in fixed) / total) if total and fixed else None,
                     "largest_hour": (f"{max(per_hour, key=per_hour.get):02d}" if total else None),
                     "largest_hour_share_of_sampled": float(max(per_hour.values()) / total) if total else None,
                     "expanded_from_all_hours_usd": float(est_all) if np.isfinite(est_all) else None,
                     "expanded_from_fixed_hours_usd": float(est_fixed) if np.isfinite(est_fixed) else None,
                     "fixed_window_bias_factor": float(rate_all / rate_fixed) if fixed and rate_fixed > 0 else None,
                     "reference_usd": float(ref) if ref is not None and pd.notna(ref) else None,
                     "ratio_all_hours_to_reference": float(est_all / ref) if ref and np.isfinite(est_all) else None,
                     "ratio_fixed_hours_to_reference": float(est_fixed / ref) if ref and np.isfinite(est_fixed) else None})
    factors = [d["fixed_window_bias_factor"] for d in days if d.get("fixed_window_bias_factor")]
    # A day whose fixed windows observed nothing while other hours did has an unbounded factor (all-hours rate / 0).
    unbounded = [d["day"] for d in days if d.get("fixed_window_bias_factor") is None and d.get("fixed_hours_share_of_sampled") == 0.0]
    ratios_all = [d["ratio_all_hours_to_reference"] for d in days if d.get("ratio_all_hours_to_reference")]
    return {"selection_rule": man.get("selection_rule"), "fetched_at": man.get("fetched_at"), "blocks_per_window": man.get("blocks_per_window"),
            "complete": man.get("complete"), "days": days,
            "days_with_defined_factor": len(factors), "days_with_unbounded_factor": unbounded,
            "fixed_window_bias_factor_mean": float(np.mean(factors)) if factors else None,
            "fixed_window_bias_factor_median": float(np.median(factors)) if factors else None,
            "fixed_window_bias_factor_median_unbounded_as_infinite": (float(np.median(factors + [np.inf] * len(unbounded))) if factors else None),
            "aggregate_used_for_correction": "median",
            "ratio_all_hours_to_reference_median": float(np.median(ratios_all)) if ratios_all else None,
            "reading": ("Factor > 1 means the two fixed windows under-represent the day's hourly mean; even 24 hourly windows observe "
                        "about 1,200 of ~150,000 blocks, so this measures the intraday expansion error, not a complete day. "
                        "The median across days is used for the correction because a single hourly window can carry most of a day's "
                        "sampled volume and dominate the mean"),
            "scope": ("the days were selected by reference volume and are not a representative sample of the history; the factor is a "
                      "sensitivity and is not applied to the declared estimator. It is checked on separately selected validation days "
                      "(see intraday_validation)")}


SYSTEMATIC_ASSUMPTIONS = [
    "the successive-difference variance estimator assumes that adjacent sampled blocks behave like a stratified sample of pairs; it is "
    "conservative under smooth trends and understates the error when the volume process has a periodic or dependent component at the "
    "sampling interval or a divisor of it, which a single systematic start cannot detect from the selected blocks alone",
    "the percentile bootstrap resamples the selected blocks as if independent; it is a second approximation that shares the same "
    "unobserved blocks, not an independent observation of the error",
    "the normal interval is approximate for a volume concentrated in a few blocks",
    "skipped heights (null blocks) are not population units; the mean is taken over existing sampled blocks and scaled to the heights of the day",
]
SYSTEMATIC_COVERAGE_RULE = {
    "declared": "2026-11-08, before the diagnostic was computed",
    "proxy_population": ("the 24 fifty-block hourly windows of the same day (consecutive blocks), whose total is known; every one of the step "
                         "phases is applied to it and the estimate and its design standard error are computed for each phase"),
    "checks": ["ratio of the standard deviation of the estimates across phases (the true design error on this population) to the mean "
               "successive-difference standard error",
               "share of phases whose 95% normal interval covers the known total",
               "autocorrelation of the per-block volume within windows at lags 1 to 50, flagging the sampling step and its divisors"],
    "verdict": "the design interval is considered supported on the proxy if the ratio is at most 1.5 and the coverage is at least 0.80; "
               "otherwise the sampling reading is inconclusive and the day's verdict is downgraded",
    "limits": "the proxy has about 30 blocks per phase and is made of discontiguous windows, so it tests the error estimator on this day's "
              "volume process at short range, not the whole-day design",
}


def _succ_diff_se(y: np.ndarray, N: int) -> tuple[float, float]:
    """Successive-difference standard deviation and the standard error of the total for a systematic sample of size len(y) from N."""
    if len(y) < 2:
        return float("nan"), float("nan")
    sd = float(np.sqrt(np.sum(np.diff(y) ** 2) / (2 * (len(y) - 1))))
    return sd, sd / np.sqrt(len(y)) * np.sqrt(max(0.0, 1 - len(y) / N)) * N


def _per_block_usd(raw: pd.DataFrame, prices: dict) -> pd.Series:
    raw = raw[raw["execution_status"].isin(SUCCESS_STATUSES)].copy() if len(raw) else raw
    if not len(raw):
        return pd.Series(dtype=float)
    raw["block_date"] = pd.to_datetime(raw["window_day"]).dt.date
    legs = _legs_with_prices(raw, prices)
    bv = batch_values(legs) if len(legs) else pd.DataFrame(columns=["half_gross"])
    if not len(bv):
        return pd.Series(dtype=float)
    bv = bv.join(raw.drop_duplicates("receipt_id").set_index("receipt_id")[["block_height", "window_hour"]])
    return bv.groupby("block_height")["half_gross"].sum()


def systematic_coverage_diagnostic(prices: dict, day: str, step: int, events=None, manifest=None) -> dict | None:
    """Check the error estimator on a proxy population with known total: the consecutive-block hourly windows of the same day."""
    events = INTRADAY_VALIDATION_EVENTS if events is None else events
    manifest = INTRADAY_VALIDATION_MANIFEST if manifest is None else manifest
    if not events.exists() or not manifest.exists():
        return None
    man = json.loads(manifest.read_text())
    wins = [w for w in man["windows"] if w["day"] == day and w.get("usable")]
    if not wins:
        return None
    raw = pd.read_csv(events)
    raw = raw[raw["window_day"] == day]
    got = _per_block_usd(raw, prices)
    series = []
    for w in wins:
        hs = np.arange(w["start_height"], w["start_height"] + w["n"])
        series.append(pd.Series(got.reindex(hs).fillna(0.0).to_numpy(), index=hs))
    pop = pd.concat(series).sort_index()
    T, Npop = float(pop.sum()), int(len(pop))
    ests, ses, covered = [], [], 0
    for phase in range(step):
        samp = pop[(pop.index % step) == phase]
        if len(samp) < 2:
            continue
        est = float(samp.mean()) * Npop
        _, se = _succ_diff_se(samp.to_numpy(dtype=float), Npop)
        ests.append(est); ses.append(se); covered += int(est - 1.96 * se <= T <= est + 1.96 * se)
    ests, ses = np.array(ests), np.array(ses)
    # autocorrelation within windows (pairs never straddle two windows)
    lags = {}
    max_lag = min(50, max(len(sr) for sr in series) - 1)
    for L in range(1, max_lag + 1):
        a, b = [], []
        for sr in series:
            v = sr.to_numpy(dtype=float)
            if len(v) > L:
                a.append(v[:-L]); b.append(v[L:])
        if not a:
            continue
        a, b = np.concatenate(a), np.concatenate(b)
        lags[L] = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else 0.0
    npairs = sum(max(0, len(sr) - 1) for sr in series)
    thr = 2 / np.sqrt(npairs) if npairs else 1.0
    divisors = [d for d in range(1, step + 1) if step % d == 0]
    flagged = {str(L): lags[L] for L in divisors if L in lags and abs(lags[L]) > thr}
    ratio = float(ests.std(ddof=1) / ses.mean()) if len(ests) > 1 and ses.mean() > 0 else None
    zero_se_with_dispersion = bool(len(ests) > 1 and ses.mean() == 0 and ests.std(ddof=1) > 0)   # every phase looks certain, yet the phases disagree
    cov = covered / len(ests) if len(ests) else None
    ok = ratio is not None and cov is not None and ratio <= 1.5 and cov >= 0.80 and not zero_se_with_dispersion
    # Post hoc, exploratory (not part of the declared verdict): the same check with smaller steps, so that each phase holds more
    # blocks; it shows whether a failure at the declared step is driven by the few blocks per phase and the concentration of volume.
    by_step = {}
    for k in sorted({step, 20, 10, 8, 5}):
        if k > Npop // 2:
            continue
        e_k, s_k, c_k = [], [], 0
        for phase in range(k):
            samp = pop[(pop.index % k) == phase]
            if len(samp) < 2:
                continue
            est = float(samp.mean()) * Npop
            _, se = _succ_diff_se(samp.to_numpy(dtype=float), Npop)
            e_k.append(est); s_k.append(se); c_k += int(est - 1.96 * se <= T <= est + 1.96 * se)
        if len(e_k) > 1 and np.mean(s_k) > 0:
            by_step[str(k)] = {"blocks_per_phase": int(Npop // k), "ratio_true_sd_to_estimated_se": float(np.std(e_k, ddof=1) / np.mean(s_k)),
                               "normal_interval_coverage": c_k / len(e_k), "phases": len(e_k)}
    return {"rule": SYSTEMATIC_COVERAGE_RULE, "proxy_blocks": Npop, "proxy_windows": len(wins), "proxy_total_usd": T,
            "phases_evaluated": int(len(ests)), "blocks_per_phase_mean": float(Npop / step),
            "sd_of_estimates_across_phases_usd": float(ests.std(ddof=1)) if len(ests) > 1 else None,
            "mean_successive_difference_se_usd": float(ses.mean()) if len(ses) else None,
            "ratio_true_sd_to_estimated_se": ratio, "estimated_error_zero_while_phases_disagree": zero_se_with_dispersion, "normal_interval_coverage": cov,
            "autocorrelation_threshold": float(thr), "autocorrelation_flagged_at_step_or_divisors": flagged,
            "largest_autocorrelations": {str(L): v for L, v in sorted(lags.items(), key=lambda kv: -abs(kv[1]))[:5]},
            "supported": bool(ok),
            "post_hoc_by_step": {"kind": "exploratory, not part of the declared verdict", "steps": by_step,
                                 "reading": "ratio and coverage as the blocks per phase grow; the declared design has about 3,500 blocks per phase, far beyond what this proxy can hold"},
            "reading": (("on the proxy population the successive-difference error is of the right size and the normal interval covers the known total "
                         "in the declared share of phases; no autocorrelation at the step or its divisors is flagged" if not flagged else
                         "on the proxy population the error size and coverage pass but autocorrelation is flagged at a divisor of the step; the interval is read with that caveat")
                        if ok else
                        "on the proxy population the successive-difference error understates the true design error or the interval under-covers; "
                        "the sampling reading for this day is inconclusive")}


def systematic_coverage_simulation(step: int = 40, N: int = 140_000, phases: int = 60, seed: int = 20261108) -> dict:
    """Coverage of the design and bootstrap intervals on synthetic populations: concentrated, dependent, periodic at the step, periodic off the step."""
    rng = np.random.default_rng(seed)
    heavy = np.exp(rng.normal(0, 2.5, N))                                      # concentrated: a few blocks carry most of the total
    ar = np.empty(N); ar[0] = 0.0
    eps = rng.normal(0, 1, N)
    for i in range(1, N):
        ar[i] = 0.9 * ar[i - 1] + eps[i]
    dependent = np.exp(ar) * (rng.random(N) < 0.3)                              # bursts with slowly varying intensity
    periodic_step = np.where(np.arange(N) % step == 1, 100.0, 0.0)              # the auditor's case
    periodic_off = np.where(np.arange(N) % 37 == 1, 100.0, 0.0)                 # a period that is not a divisor of the step
    pops = {"concentrated_iid": heavy, "dependent_bursts": dependent, "periodic_at_step": periodic_step, "periodic_off_step": periodic_off}
    out = {}
    for name, y in pops.items():
        T = float(y.sum())
        cov_n, cov_b, rel = 0, 0, []
        for ph in rng.choice(step, size=phases, replace=False) if phases <= step else range(step):
            samp = y[ph::step]
            est = samp.mean() * N
            _, se = _succ_diff_se(samp, N)
            cov_n += int(est - 1.96 * se <= T <= est + 1.96 * se)
            boot = rng.choice(samp, size=(200, len(samp)), replace=True).mean(axis=1) * N
            lo, hi = np.quantile(boot, [0.025, 0.975])
            cov_b += int(lo <= T <= hi)
            rel.append((est - T) / T if T else 0.0)
        n_ph = phases if phases <= step else step
        out[name] = {"normal_interval_coverage": cov_n / n_ph, "bootstrap_coverage": cov_b / n_ph,
                     "relative_error_sd": float(np.std(rel)), "phases": n_ph}
    cov_c = out["concentrated_iid"]["normal_interval_coverage"]; cov_d = out["dependent_bursts"]["normal_interval_coverage"]
    out["reading"] = (f"for concentrated independent volume and for dependent bursts the intervals cover the total in about {cov_c:.0%} and {cov_d:.0%} of phases, "
                      "below the nominal 95%: with a heavy-tailed volume the intervals are somewhat too narrow and should be read as indicative; for a pattern "
                      "periodic at the sampling step both intervals fail completely (the sample sees one phase only), while a period that is not a divisor of the "
                      "step is handled; this is why the real-data diagnostic on the proxy population matters")
    out["settings"] = {"step": step, "blocks": N, "phases": min(phases, step), "seed": seed, "bootstrap_draws": 200}
    return out


def systematic_day(prices: dict, llama: pd.Series, events=None, manifest=None, intraday_days: list[dict] | None = None,
                   diagnostic_events=None, diagnostic_manifest=None, simulate: bool = True) -> dict:
    """Design-based estimate of one day's volume from a systematic block sample (every k-th block over the whole day).

    Estimate = mean USD per existing sampled block x heights in the day. Standard error from successive differences (Wolter 2007,
    v2) under the assumptions listed in SYSTEMATIC_ASSUMPTIONS; a percentile bootstrap is a second approximation. The error
    estimator is checked on a proxy population with known total (systematic_coverage_diagnostic) and on synthetic populations
    (systematic_coverage_simulation); the verdict is downgraded to inconclusive when the diagnostic fails."""
    from .blocks import SYSTEMATIC_EVENTS, SYSTEMATIC_MANIFEST, SYSTEMATIC_RULE
    events = SYSTEMATIC_EVENTS if events is None else events
    manifest = SYSTEMATIC_MANIFEST if manifest is None else manifest
    out = {"rule": SYSTEMATIC_RULE, "assumptions": SYSTEMATIC_ASSUMPTIONS, "status": "pending: systematic day not fetched yet (make blocks-systematic-day)"}
    if not events.exists() or not manifest.exists():
        return out
    man = json.loads(manifest.read_text())
    heights = sorted(int(h) for h in man["heights_sampled"])
    nulls = set(int(h) for h in man.get("heights_without_block", []))
    heights_existing = [h for h in heights if h not in nulls]
    raw = pd.read_csv(events)
    got = _per_block_usd(raw, prices)
    per_block = got.reindex(heights_existing).fillna(0.0)
    y = per_block.to_numpy(dtype=float)
    N_heights = int(man["blocks_in_day"])
    # existing blocks among the day's heights: scale by the observed share of existing heights in the sample
    N = int(round(N_heights * (len(heights_existing) / len(heights)))) if heights else N_heights
    mean = float(y.mean()) if len(y) else float("nan")
    est = mean * N
    sd, se_total = _succ_diff_se(y, N)
    ref = llama.get(pd.Timestamp(man["day"]))
    ref = float(ref) if ref is not None and pd.notna(ref) else None
    raw_ok = raw[raw["execution_status"].isin(SUCCESS_STATUSES)] if len(raw) else raw
    by_hour_usd = {}
    if len(got):
        hours = raw_ok.drop_duplicates("receipt_id").set_index("receipt_id")["window_hour"]
        bh = _legs_with_prices(raw_ok.assign(block_date=pd.to_datetime(raw_ok["window_day"]).dt.date), prices)
        bvh = batch_values(bh) if len(bh) else pd.DataFrame(columns=["half_gross"])
        if len(bvh):
            bvh = bvh.join(hours)
            by_hour_usd = {f"{int(h):02d}": float(v) for h, v in bvh.groupby("window_hour")["half_gross"].sum().items()}
    top_share = float(np.sort(y)[::-1][: max(1, len(y) // 100)].sum() / y.sum()) if y.sum() > 0 else None
    rng = np.random.default_rng(20261107)
    boot = rng.choice(y, size=(4000, len(y)), replace=True).mean(axis=1) * N if len(y) > 1 else np.array([])
    boot_ci = [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))] if len(boot) else None
    same_day_24 = next((d for d in (intraday_days or []) if d.get("day") == man["day"]), None)
    diag = systematic_coverage_diagnostic(prices, man["day"], int(man["step"]), events=diagnostic_events, manifest=diagnostic_manifest)
    sim = systematic_coverage_simulation(step=int(man["step"])) if simulate else None
    out.update({"status": "complete" if man.get("complete") else "partial extract", "day": man["day"], "fetched_at": man.get("fetched_at"),
                "design": {"step": man["step"], "offset": man["offset"], "heights_in_day": N_heights, "blocks_in_day_estimated": N,
                           "blocks_requested": man["blocks_requested"], "blocks_fetched": man["blocks_fetched"],
                           "heights_without_block": len(nulls) if "heights_without_block" in man else None,
                           "fetch_failed": man.get("fetch_failed"), "blocks_missing": int(man.get("blocks_missing", 0)),
                           "sampling_fraction": man["blocks_fetched"] / N if N else None},
                "sampled_usd": float(y.sum()), "blocks_with_volume": int((y > 0).sum()),
                "share_of_sampled_usd_in_top_1pct_blocks": top_share,
                "estimate_usd": est, "standard_error_usd": se_total, "ci95_usd": [est - 1.96 * se_total, est + 1.96 * se_total],
                "relative_standard_error": (se_total / est) if est else None,
                "ci95_usd_bootstrap": boot_ci,
                "reference_usd": ref, "ratio_to_reference": (est / ref) if ref else None,
                "ratio_ci95": [(est - 1.96 * se_total) / ref, (est + 1.96 * se_total) / ref] if ref else None,
                "ratio_ci95_bootstrap": [boot_ci[0] / ref, boot_ci[1] / ref] if (ref and boot_ci) else None,
                "reference_inside_ci95": bool(ref and est - 1.96 * se_total <= ref <= est + 1.96 * se_total) if ref else None,
                "reference_inside_ci95_bootstrap": bool(ref and boot_ci and boot_ci[0] <= ref <= boot_ci[1]) if (ref and boot_ci) else None,
                "usd_by_hour": by_hour_usd,
                "same_day_other_designs": ({"two_fixed_windows_ratio": same_day_24.get("ratio_fixed_hours_to_reference"),
                                            "twenty_four_hourly_windows_ratio": same_day_24.get("ratio_all_hours_to_reference"),
                                            "blocks_observed_24_windows": same_day_24.get("blocks_observed")} if same_day_24 else None),
                "coverage_diagnostic": diag, "coverage_simulation": sim})
    r = out["ratio_to_reference"]
    if r is not None:
        lo, hi = out["ratio_ci95"]
        blo, bhi = out["ratio_ci95_bootstrap"] or (None, None)
        both_exclude = (not out["reference_inside_ci95"]) and (out["reference_inside_ci95_bootstrap"] is False)
        either_includes = out["reference_inside_ci95"] or bool(out["reference_inside_ci95_bootstrap"])
        diag_ok = bool(diag and diag.get("supported"))
        no_volume = y.sum() <= 0
        out["sampling_verdict"] = ("inconclusive: no volume observed in the sample" if no_volume else
                                   "inconclusive: the error estimator is not supported on the proxy population" if (diag is not None and not diag_ok) else
                                   "unchecked: no proxy population available for this day" if diag is None else
                                   "supported on the proxy population")
        head = (f"on this day the even {man['step']}-block systematic sample estimates {r:.2f} of the reference with a 95% design interval of {lo:.2f} to {hi:.2f} "
                f"(percentile bootstrap {blo:.2f} to {bhi:.2f}); both intervals are approximations under the stated assumptions and share the same unobserved blocks; ")
        if no_volume or (diag is not None and not diag_ok):
            body = ("the sampling error cannot be bounded with this design on this day (" + out["sampling_verdict"] + "), so the gap to the reference is not attributed")
        elif both_exclude:
            body = ("both intervals exclude parity, which is evidence against a purely sampling explanation of this day's gap conditional on the design and on an error "
                    "estimator that the proxy-population diagnostic supports; what remains is definitional (what the reference counts, one- or two-sided notional, "
                    "confidential intents), a difference in reconstruction or pricing, or a temporal pattern at the sampling interval that a single systematic start cannot detect")
        elif either_includes:
            body = "at least one interval includes parity, so for this day the gap to the reference is compatible with sampling error under our definition"
        else:
            body = "the two intervals disagree about parity; the sampling error alone cannot be ruled out or confirmed"
        out["reading"] = head + body + "; one day cannot establish the global total"
    return out


def intraday_validation(prices: dict, blocks_per_day: pd.Series, llama: pd.Series, motivating: dict | None) -> dict:
    """Pre-declared check of the motivating bias factor on validation days chosen by position, not by volume."""
    out = {"rule": INTRADAY_VALIDATION_RULE, "status": "pending: validation days not fetched yet (make blocks-intraday-validation)"}
    v = intraday(prices, blocks_per_day, llama, events=INTRADAY_VALIDATION_EVENTS, manifest=INTRADAY_VALIDATION_MANIFEST)
    if not v:
        return out
    med_m = (motivating or {}).get("fixed_window_bias_factor_median")
    med_v = v.get("fixed_window_bias_factor_median")
    med_cons = v.get("fixed_window_bias_factor_median_unbounded_as_infinite")
    unbounded = v.get("days_with_unbounded_factor") or []
    out.update({"status": "complete" if v.get("complete") else "partial extract", "days": v.get("days"), "fetched_at": v.get("fetched_at"),
                "complete": v.get("complete"), "days_total": len(v.get("days") or []), "days_with_defined_factor": v.get("days_with_defined_factor"),
                "days_with_unbounded_factor": unbounded,
                "unbounded_factor_reading": ("on these days the two fixed windows observed no volume while other hours did, so the factor is "
                                             "unbounded rather than missing; the verdict is required to hold both excluding them and treating "
                                             "them as infinite (which moves the median to the largest defined factor)") if unbounded else None,
                "validation_median_factor": med_v, "validation_mean_factor": v.get("fixed_window_bias_factor_mean"),
                "validation_median_factor_unbounded_as_infinite": med_cons,
                "motivating_median_factor": med_m, "ratio_validation_over_motivating": (med_v / med_m) if (med_v and med_m) else None,
                "ratio_validation_over_motivating_unbounded_as_infinite": (med_cons / med_m) if (med_cons and med_m and np.isfinite(med_cons)) else None,
                "validation_ratio_all_hours_to_reference_median": v.get("ratio_all_hours_to_reference_median")})
    if med_v and med_m:
        checks = [med_v / med_m] + ([med_cons / med_m] if med_cons is not None and np.isfinite(med_cons) else [])
        if med_cons is not None and not np.isfinite(med_cons):
            checks.append(np.inf)
        out["within_declared_range"] = bool(all(0.5 <= r <= 2.0 for r in checks))
        out["verdict"] = (("validation days reproduce the motivating factor within the declared x0.5-x2 range"
                           + (" (also when the day with an unbounded factor is treated as infinite)" if unbounded else ""))
                          if out["within_declared_range"]
                          else "validation days do not reproduce the motivating factor within the declared range: the correction is not supported")
    return out


def trace_examples(legs: pd.DataFrame, raw: pd.DataFrame, ef: pd.Series) -> list[dict]:
    """Deterministic receipt-level walkthroughs from log to volume."""
    reg = intents.registry()
    per = legs.groupby("receipt_id").agg(accounts=("account", "nunique"), tokens=("token", "nunique"), legs=("token", "size"),
                                         unpriced=("usd", lambda s: int(s.isna().sum())), day=("block_date", "first"),
                                         legacy=("intent_hash", lambda s: bool(s.isna().all())))
    bv = batch_values(legs)
    per = per.join(bv)
    ai_valued = legs.groupby(["receipt_id", "account", "intent_key"])["usd"].apply(lambda s: s.notna().any())
    unvalued_receipts = set(ai_valued[~ai_valued].reset_index()["receipt_id"])
    picks = []
    simple = per[(per["accounts"] == 2) & (per["tokens"] == 2) & (per["unpriced"] == 0) & (~per["legacy"])].sort_values(["day", "legs"])
    if len(simple):
        picks.append(("simple_two_party_fully_priced", simple.index[0]))
    multi = per[~per["legacy"]].sort_values(["accounts", "day"], ascending=[False, True])
    if len(multi):
        picks.append(("multi_participant_batch", multi.index[0]))
    partial = per[(per["unpriced"] > 0) & (~per.index.isin(unvalued_receipts))].sort_values("day")
    if len(partial):
        picks.append(("unpriced_leg_valued_by_other_side", partial.index[0]))
    unval = per[per.index.isin(unvalued_receipts)].sort_values("day")
    if len(unval):
        picks.append(("account_intent_without_any_price", unval.index[0]))
    if len(per):
        picks.append(("largest_sampled_batch", per["half_gross"].idxmax()))
    legacy = per[per["legacy"]].sort_values("day")
    if len(legacy):
        picks.append(("legacy_single_object_event_2024", legacy.index[0]))
    out = []
    for kind, rid in picks:
        g = legs[legs["receipt_id"] == rid]
        rows = []
        for r in g.itertuples(index=False):
            entry = reg.get(r.token)
            rows.append({"account": r.account, "intent_hash": r.intent_hash, "asset_id": r.token, "symbol": entry[0] if entry else None,
                         "decimals": entry[1] if entry else None, "raw_amount": str(r.amount),
                         "units": float(r.amount) / 10 ** entry[1] if entry else None, "usd": None if pd.isna(r.usd) else float(r.usd)})
        sides = g.dropna(subset=["usd"]).groupby(["account", "intent_key", "direction"])["usd"].sum().unstack(fill_value=0)
        for c in ("in", "out"):
            if c not in sides:
                sides[c] = 0.0
        ai = [{"account": a, "intent": i, "priced_in_usd": float(s["in"]), "priced_out_usd": float(s["out"]), "larger_side_usd": float(max(s["in"], s["out"]))}
              for (a, i), s in sides.iterrows()]
        logs = raw.loc[raw["receipt_id"] == rid]
        head = logs.iloc[0]
        day = pd.Timestamp(head["window_day"]).date()
        batch_usd = float(sum(x["larger_side_usd"] for x in ai) / 2)
        out.append({"kind": kind, "receipt_id": rid, "block_height": int(head["block_height"]), "block_timestamp_ns": str(head["block_timestamp"]),
                    "window": f"{head['window_day']} {int(head['window_hour']):02d}:00 UTC", "caller": head["caller"], "execution_status": head["execution_status"],
                    "block_url": f"https://mainnet.neardata.xyz/v0/block/{int(head['block_height'])}",
                    "token_diff_logs": [l for l in logs["log"] if '"event":"token_diff"' in l],
                    "legs": rows, "account_intents": ai, "batch_volume_usd": batch_usd,
                    "half_gross_rule": "sum of larger priced side per account-intent, divided by two",
                    "expansion_factor_for_day": float(ef.get(day, np.nan)), "contribution_to_day_estimate_usd": batch_usd * float(ef.get(day, np.nan))})
    return out


def run() -> dict:
    status_path = MODELS / "intents_status.json"
    ins = json.loads(status_path.read_text()) if status_path.exists() else {}
    for name in ["intents_reconciliation.json", "intents_reconciliation_daily.csv", "intents_trace_examples.json"]:
        (MODELS / name).unlink(missing_ok=True)
    if not ins.get("computed") or ins.get("source") != "neardata block sample":
        out = {"computed": False, "reason": "reconciliation needs the computed block-sample L2 layer", "economic_unit": ECONOMIC_UNIT}
        (MODELS / "intents_reconciliation.json").write_text(json_dumps(out, indent=1))
        print("reconcile: not computed")
        return out
    raw = pd.read_csv(DATA / "blocks" / "intents_events_sampled.csv")
    raw = raw[raw["execution_status"].isin(SUCCESS_STATUSES)].copy()
    ok = usable_windows() or set()
    raw = raw[[(d, int(h)) in ok for d, h in zip(raw["window_day"], raw["window_hour"])]].copy()
    raw["block_date"] = pd.to_datetime(raw["window_day"]).dt.date
    prices = intents._daily_prices()
    legs = _legs_with_prices(raw, prices)
    roles = intents.identify_solvers(legs, sampled=True)
    daily = pd.read_csv(MODELS / "intents_daily.csv", parse_dates=["date"])
    d = pd.read_csv(DERIVED / "daily.csv", parse_dates=["date"]).set_index("date")
    llama, bpd = d["intents_volume_usd"], d["blocks"]
    table = daily_table(daily, legs, raw, llama, bpd)
    table.to_csv(MODELS / "intents_reconciliation_daily.csv", index=False)
    ef = intents.expansion_factors(raw)
    examples = trace_examples(legs, raw, ef)
    (MODELS / "intents_trace_examples.json").write_text(json_dumps(examples, indent=1, default=str))
    with_ref = table[table["reference_usd"] > 0]
    pooled = _pooled(with_ref["volume_expanded_usd"].to_numpy(dtype=float), with_ref["reference_usd"].to_numpy(dtype=float))
    w03, w15 = with_ref["window03_sampled_usd"], with_ref["window15_sampled_usd"]
    both = with_ref[(w03 > 0) & (w15 > 0)]
    dominant = ((with_ref[["window03_sampled_usd", "window15_sampled_usd"]].max(axis=1) / with_ref[["window03_sampled_usd", "window15_sampled_usd"]].sum(axis=1).replace(0, np.nan)) > 0.8).mean()
    coverage = {"days_sampled": int(len(table)), "days_with_reference": int(len(with_ref)),
                "block_coverage_share_mean": float(table["block_coverage_share"].mean()),
                "windows_per_day": 2, "blocks_per_window": 50,
                "between_window_ratio_15_over_03": {"median": float((both["window15_sampled_usd"] / both["window03_sampled_usd"]).median()) if len(both) else None, "days_both_positive": int(len(both))},
                "share_of_days_one_window_carries_over_80pct": float(dominant) if len(with_ref) else None,
                "reading": ("two 50-block windows observe about 0.07% of a day's blocks; the 15:00 UTC window carries several times the 03:00 volume, "
                            "so the day mean is sensitive to which hours are observed. The intraday block measures this directly where available")}
    valuation = valuation_component(legs)
    routes = route_component(legs, roles)
    intra = intraday(prices, bpd, llama)
    validation = intraday_validation(prices, bpd, llama, intra)
    sysday = systematic_day(prices, llama, intraday_days=(validation.get("days") or []) + ((intra or {}).get("days") or []))
    alt = routes["alternative_definitions_total_usd"]
    ratio = pooled.get("ratio")
    residual = {}
    if ratio:
        two_sided = ratio * alt["full_gross_participant_notional"] / alt["half_gross_participant_notional"] if alt["half_gross_participant_notional"] else None
        bias = intra.get("fixed_window_bias_factor_median") if intra else None
        bias_mean = intra.get("fixed_window_bias_factor_mean") if intra else None
        after = ratio * bias if bias else None
        conf = REFERENCE_DEFINITION["confidential_intents"]["share_of_dune_total"]
        after_conf = ratio / (1 - conf)
        after_conf_intra = after / (1 - conf) if after else None
        residual = {"pooled_ratio": ratio,
                    "if_reference_were_two_sided_notional": two_sided,
                    "confidential_intents_share_of_reference": conf,
                    "after_confidential_intents_exclusion": after_conf,
                    "intraday_bias_factor_used": bias,
                    "after_intraday_bias_correction": after,
                    "after_intraday_bias_correction_mean_factor": ratio * bias_mean if bias_mean else None,
                    "after_confidential_and_intraday": after_conf_intra,
                    "after_both": two_sided * bias if (two_sided and bias) else None,
                    "unexplained_factor_to_parity": (1 / after) if after else (1 / ratio),
                    "unexplained_factor_after_confidential_and_intraday": (1 / after_conf_intra) if after_conf_intra else (1 / after_conf),
                    "two_sided_and_intraday_overshoot": bool(two_sided and bias and two_sided * bias > 1),
                    "reading": ("identified components: definitional (one- versus two-sided notional, unresolved), coverage of the reference "
                                "(confidential intents are inside the Dune series and outside any public log; cumulative share from a secondary "
                                "source, an estimate) and intraday coverage (measured on three days, checked on three more). The factor to parity "
                                "that remains after the confidential share and the measured intraday bias is unexplained and is reported as such, "
                                "not attributed to missing large trades. The two-sided reading and the intraday factor are separate hypotheses: "
                                "that their combination exceeds parity shows the two readings cannot both be taken at face value together, but "
                                "it does not identify which one overstates, and estimation error and unidentified components remain")}
    out = {"computed": True, "economic_unit": ECONOMIC_UNIT, "reference_definition": REFERENCE_DEFINITION, "pooled_ratio_all_days": pooled,
           "components": {"temporal_coverage": coverage, "valuation": valuation, "route_reconstruction": routes, "residual": residual},
           "holdout": holdout(table), "intraday": intra or {"available": False, "how": "make blocks-intraday (network, several hours under the public rate limit)"},
           "intraday_validation": validation, "systematic_day": sysday,
           "trace_examples": [e["kind"] for e in examples],
           "not_possible_here": ["complete-day extracts (FastNear public rate limit ~0.35 blocks/s; a NEAR day has ~150,000 blocks)",
                                 "a reference of independent origin: every public series found (DefiLlama, revenue.near.org, near-intents.org) derives from NEAR's own metrics datasets; the only independent indexer found (Flipside ez_intents) requires an account",
                                 "the published definition of volume_amount_usd in dune.near.dataset_near_intents_metrics (one- or two-sided)",
                                 "the share of confidential intents in the comparison period (only a cumulative share from a secondary source is available)"]}
    (MODELS / "intents_reconciliation.json").write_text(json_dumps(out, indent=1, default=str))
    print(f"reconcile: {len(table)} days, pooled ratio {ratio:.3f}, holdout {out['holdout']['verdict']}" if ratio else "reconcile: no reference days")
    return out
