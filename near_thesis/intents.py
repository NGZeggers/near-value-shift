"""L2: NEAR Intents microstructure from raw DIP-4 events emitted by intents.near.

Input (from `make bq`, sql/l2_intents_events.sql): data/bigquery/l2_intents_events.csv with columns
block_date, block_timestamp, receipt_id, caller, log, execution_status. One row per successful EVENT_JSON log line.

Method
1. Parse `EVENT_JSON:{...}`; keep standard "dip4". `token_diff` events carry data[] of {account_id, intent_hash, diff}.
2. A receipt = one execute_intents batch. Within a batch the diffs sum to zero per token; the accounts in the
   batch are the counterparties of one or more swaps.
3. Solver identification (documented assumption, with sensitivity): an account is a solver on a given day if it
   appears in >= SOLVER_MIN_BATCHES batches that day with >= SOLVER_MIN_COUNTERPARTIES distinct counterparties.
   Everyone else is a user.
4. USD pricing: exact registry identifiers establish asset identity/decimals. Registered stablecoins are priced
   at par; registered majors use daily prices; unknown legs stay unpriced. Volume is half gross participant
   notional, using the larger priced inflow/outflow per account-intent.
5. Daily metrics: batches, users, solvers, HHI and top-1/top-5 share of solver volume (priced) or batch count,
   median priced trade size, withdrawal events. Sampled days are expanded to monthly estimates with a
   day-level bootstrap confidence interval.
Outputs (data/derived/models/): intents_daily.csv, intents_monthly.csv, intents_solvers.csv, intents_status.json
"""
from __future__ import annotations

import json
import math
import re
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd

from .config import BQ_DIR, DATA, DERIVED, MODELS

SOLVER_MIN_BATCHES = 20          # BigQuery full days
SOLVER_MIN_COUNTERPARTIES = 10
SOLVER_MIN_BATCH_SHARE = 0.02    # sampled windows: an account in >= 2% of a day's sampled batches with >= 5 counterparties
STABLE_SYMBOLS = {"usdc", "usdt", "usdt0", "dai", "frax", "usde", "pyusd", "usd1", "fdusd", "busd", "tusd", "lusd", "usdy", "usds", "xusd", "usdg"}
GECKO_ALIASES = {"wrapped-near": "near", "wrapped-bitcoin": "bitcoin", "weth": "ethereum", "wrapped-solana": "solana", "wrapped-steth": "ethereum"}


def load_token_registry() -> dict[str, tuple[str, int, str | None]]:
    """Exact asset id -> (symbol lower, decimals, CoinGecko id) from the committed 1Click snapshot."""
    f = DATA / "raw" / "intents_tokens.json"
    if not f.exists():
        return {}
    out = {}
    for t in json.loads(f.read_text()).get("data") or []:
        try:
            dec = t['decimals']
            if isinstance(dec, bool) or not isinstance(dec, int) or not 0 <= dec <= 38:
                continue
            out[str(t["assetId"])] = (str(t.get("symbol", "")).lower(), dec, t.get("coingeckoId"))
        except (KeyError, TypeError, ValueError):
            continue
    return out


_REGISTRY: dict | None = None


def registry() -> dict:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_token_registry()
    return _REGISTRY


def parse_event(log: str) -> dict | None:
    if not isinstance(log, str) or not log.startswith("EVENT_JSON:"):
        return None
    try:
        ev = json.loads(log[len("EVENT_JSON:"):])
    except json.JSONDecodeError:
        return None
    return ev if isinstance(ev, dict) and ev.get("standard") == "dip4" else None


def token_decimals(token: str) -> int | None:
    reg = registry().get(token)
    return reg[1] if reg else None


def price_leg(token: str, amount_raw: int, prices: dict[str, float]) -> float | None:
    """Exact registry identifier only; unknown assets remain unpriced.

    Asset identifiers can contain case-sensitive multi-token IDs. Never lowercase
    identifiers or infer identity/decimals from an attacker-controlled name.
    """
    reg = registry().get(token)
    if reg:
        sym, dec, gid = reg
        if sym in STABLE_SYMBOLS:
            return abs(amount_raw) / 10 ** dec
        gid = GECKO_ALIASES.get(gid, gid)
        if gid and prices.get(gid) is not None and math.isfinite(prices[gid]) and prices[gid] > 0:
            return abs(amount_raw) / 10 ** dec * prices[gid]
        return None
    return None


def batches_from_events(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (receipt, account, token) with the signed raw diff."""
    rows = []
    rejected = 0
    for r in df.itertuples(index=False):
        ev = parse_event(r.log)
        if not ev or ev.get("event") != "token_diff":
            continue
        data = ev.get("data")
        if not isinstance(data, (list, dict)):
            rejected += 1
            continue
        items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])  # 2024 events carry one object
        for item in items:
            if not isinstance(item, dict):
                rejected += 1
                continue
            diff = item.get('diff')
            account = item.get('account_id')
            intent = item.get('intent_hash') or item.get('hash')
            if not isinstance(diff, dict) or not isinstance(account, str) or not account or (intent is not None and not isinstance(intent, str)):
                rejected += 1
                continue
            parsed = []
            for token, amt in diff.items():
                try:
                    if not isinstance(token, str) or not token or isinstance(amt, bool) or not isinstance(amt, (str, int)):
                        raise ValueError('invalid leg')
                    if isinstance(amt, str) and not re.fullmatch(r'-?\d{1,39}', amt):
                        raise ValueError('invalid integer amount')
                    value = int(amt)
                    if abs(value) > 2**127 - 1:
                        raise ValueError('amount outside signed 128-bit range')
                    parsed.append((r.block_date, r.receipt_id, account, intent, token, value))
                except (TypeError, ValueError):
                    rejected += 1
                    break
            else:
                rows.extend(parsed)
    if rejected:
        warnings.warn(f'Rejected {rejected} malformed token_diff items', RuntimeWarning, stacklevel=2)
    result = pd.DataFrame(rows, columns=["block_date", "receipt_id", "account", "intent_hash", "token", "amount"])
    result.attrs['rejected_items'] = rejected
    return result


def identify_solvers(legs: pd.DataFrame, *, sampled: bool = False, min_share: float = SOLVER_MIN_BATCH_SHARE) -> pd.DataFrame:
    """Per (day, account): batches, distinct counterparties, is_solver."""
    pairs = legs[["block_date", "receipt_id", "account"]].drop_duplicates()
    cp = pairs.merge(pairs, on=["block_date", "receipt_id"], suffixes=("", "_other"))
    cp = cp[cp["account"] != cp["account_other"]]
    stats = cp.groupby(["block_date", "account"]).agg(batches=("receipt_id", "nunique"), counterparties=("account_other", "nunique")).reset_index()
    per_day = pairs.groupby("block_date")["receipt_id"].nunique()
    stats["batch_share"] = stats["batches"] / stats["block_date"].map(per_day)
    absolute = (stats["batches"] >= SOLVER_MIN_BATCHES) & (stats["counterparties"] >= SOLVER_MIN_COUNTERPARTIES)
    relative = (stats["batch_share"] >= min_share) & (stats["counterparties"] >= 5) & (stats["batches"] >= 5)
    stats["is_solver"] = (absolute | relative) if sampled else absolute
    return stats


def _daily_prices(max_gap_days: int = 7) -> dict[str, dict[str, float]]:
    """day -> {coingecko id: USD price} from every data/raw/price_<id>.json snapshot. DefiLlama's daily series have
    occasional missing days; a price is carried forward for at most `max_gap_days` days."""
    cols = {}
    for f in sorted((DATA / "raw").glob("price_*.json")):
        cid = f.stem[len("price_"):]
        pts = json.loads(f.read_text()).get("data") or []
        if pts:
            ser = pd.Series({pd.Timestamp(int(ts), unit="s").normalize(): float(px) for ts, px in pts})
            cols[cid] = ser[~ser.index.duplicated(keep="last")]
    if not cols:
        return {}
    df = pd.DataFrame(cols).sort_index()
    df = df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="D")).ffill(limit=max_gap_days)
    return {day.strftime("%Y-%m-%d"): {k: v for k, v in row.items() if pd.notna(v)} for day, row in df.iterrows()}


def hhi(shares: np.ndarray) -> float:
    s = shares / shares.sum() if shares.sum() else shares
    return float((s ** 2).sum())


def daily_metrics(legs: pd.DataFrame, roles: pd.DataFrame, events: pd.DataFrame, prices: dict) -> pd.DataFrame:
    legs = legs.merge(roles[["block_date", "account", "is_solver"]], on=["block_date", "account"], how="left")
    legs["is_solver"] = legs["is_solver"].fillna(False)
    legs["usd"] = [price_leg(t, a, prices.get(str(d), {})) for t, a, d in zip(legs["token"], legs["amount"], legs["block_date"])]
    rows = []
    wd = events[events["event"].str.endswith("_withdraw", na=False)].groupby("block_date").size()
    for day, g in legs.groupby("block_date"):
        users = g[~g["is_solver"]]
        # Half the gross participant notional: for each account-intent take the larger
        # priced inflow/outflow, then sum both sides and divide by two. This retains
        # multiple trades in a receipt and works when only the common stable leg is priced.
        # This is a flow estimator, not a guaranteed swap reconstruction for routed batches.
        priced = g.dropna(subset=["usd"]).copy()
        priced["intent_key"] = priced["intent_hash"].fillna("legacy")
        priced["direction"] = np.where(priced["amount"] < 0, "out", "in")
        flows = priced.groupby(["receipt_id", "account", "intent_key", "direction"])["usd"].sum().unstack(fill_value=0)
        per_batch = flows.max(axis=1).groupby("receipt_id").sum() / 2
        complete = g.groupby("receipt_id")["usd"].apply(lambda a: a.notna().all())
        solver_vol = g[g["is_solver"] & (g["amount"] < 0)].dropna(subset=["usd"]).groupby("account")["usd"].sum()
        solver_batches = g[g["is_solver"]].groupby("account")["receipt_id"].nunique()
        conc = solver_vol if len(solver_vol) else solver_batches
        top = conc.sort_values(ascending=False)
        rows.append({
            "date": pd.Timestamp(day), "batches": int(g["receipt_id"].nunique()), "users": int(users["account"].nunique()),
            "solvers": int(g.loc[g["is_solver"], "account"].nunique()),
            "volume_priced_usd": float(per_batch.sum()), "priced_batch_share": float(len(per_batch) / max(1, g["receipt_id"].nunique())),
            "fully_priced_batch_share": float(complete.mean()), "priced_legs": int(g["usd"].notna().sum()), "total_legs": int(len(g)),
            "median_trade_usd": float(per_batch.median()) if len(per_batch) else np.nan,
            "p90_trade_usd": float(per_batch.quantile(0.9)) if len(per_batch) else np.nan,
            "hhi_solver": hhi(top.to_numpy(dtype=float)) if len(top) else np.nan,
            "top1_solver_share": float(top.iloc[0] / top.sum()) if len(top) else np.nan,
            "top5_solver_share": float(top.iloc[:5].sum() / top.sum()) if len(top) else np.nan,
            "withdraw_events": int(wd.get(day, 0)),
        })
    return pd.DataFrame(rows).sort_values("date")


def monthly_estimates(daily: pd.DataFrame, n_boot: int = 2000, seed: int = 11) -> pd.DataFrame:
    """Sampled days -> monthly totals with a bootstrap CI over days (days treated as exchangeable within month).
    With two sampled days per month the interval is indicative only; see quarterly_estimates and pooled_ratio."""
    rng = np.random.default_rng(seed)
    rows = []
    for month, g in daily.groupby(daily["date"].dt.to_period("M")):
        dim = month.days_in_month
        v = g["volume_priced_usd"].to_numpy()
        est = v.mean() * dim
        boots = [rng.choice(v, size=len(v), replace=True).mean() * dim for _ in range(n_boot)] if len(v) > 1 else [np.nan]
        rows.append({"month": month.to_timestamp(), "sampled_days": int(len(v)), "volume_est_usd": float(est),
                     "volume_ci_lo": float(np.quantile(boots, 0.025)), "volume_ci_hi": float(np.quantile(boots, 0.975)),
                     "users_per_day": float(g["users"].mean()), "solvers_per_day": float(g["solvers"].mean()),
                     "hhi_solver": float(g["hhi_solver"].mean()), "top1_solver_share": float(g["top1_solver_share"].mean()),
                     "median_trade_usd": float(g["median_trade_usd"].median())})
    return pd.DataFrame(rows)


def quarterly_estimates(daily: pd.DataFrame, llama: pd.Series, n_boot: int = 2000, seed: int = 11) -> pd.DataFrame:
    """Quarter totals (about six sampled days each) with a day-bootstrap CI, next to DefiLlama's quarter total."""
    rng = np.random.default_rng(seed)
    rows = []
    for q, g in daily.groupby(daily["date"].dt.to_period("Q")):
        ll_q = llama[(llama.index >= q.start_time) & (llama.index <= q.end_time)].dropna()
        days = int(len(ll_q)) or (q.end_time - q.start_time).days + 1  # a partial quarter is compared on the days DefiLlama has
        v = g["volume_priced_usd"].to_numpy()
        est = v.mean() * days
        boots = [rng.choice(v, size=len(v), replace=True).mean() * days for _ in range(n_boot)] if len(v) > 1 else [np.nan]
        ll = ll_q.sum()
        rows.append({"quarter": q.start_time, "sampled_days": int(len(v)), "days": days, "volume_est_usd": float(est),
                     "volume_ci_lo": float(np.quantile(boots, 0.025)), "volume_ci_hi": float(np.quantile(boots, 0.975)),
                     "defillama_usd": float(ll), "ratio": float(est / ll) if ll else np.nan})
    return pd.DataFrame(rows)


def pooled_ratio(daily: pd.DataFrame, llama: pd.Series, n_boot: int = 4000, seed: int = 11) -> dict:
    """Sum of expanded on-chain volume over all sampled days divided by DefiLlama's volume on the same days,
    with a bootstrap CI over days (ratio of sums is robust to the heavy right tail of daily volume)."""
    rng = np.random.default_rng(seed)
    d = daily.assign(llama=daily["date"].map(llama)).dropna(subset=["llama"])
    d = d[d["llama"] > 0]
    if d.empty:
        return {}
    a, b = d["volume_priced_usd"].to_numpy(), d["llama"].to_numpy()
    ratio = a.sum() / b.sum()
    idx = rng.integers(0, len(a), size=(n_boot, len(a)))
    boots = a[idx].sum(axis=1) / b[idx].sum(axis=1)
    return {"days": int(len(d)), "ratio": float(ratio), "ci_lo": float(np.quantile(boots, 0.025)), "ci_hi": float(np.quantile(boots, 0.975)),
            "median_daily_ratio": float(np.median(a / b))}


def expansion_factors(raw: pd.DataFrame) -> pd.Series:
    """blocks in the day (NearBlocks) / blocks sampled that day -> multiply sampled counts and volume to daily totals."""
    man = json.loads((DATA / "blocks" / "sample_manifest.json").read_text())
    sampled = {}
    for w in man["windows"]:
        n = int(w.get("fetched", w["n"]))
        if w.get("usable", True) and n > 0:
            sampled[pd.Timestamp(w["day"]).date()] = sampled.get(pd.Timestamp(w["day"]).date(), 0) + n
    d = pd.read_csv(DERIVED / "daily.csv", parse_dates=["date"]).set_index("date")["blocks"]
    bpd = {k.date(): float(v) for k, v in d.items()}
    return pd.Series({day: bpd.get(day, 150_000.0) / n for day, n in sampled.items()})


def _unavailable(reason: str, *, source: str | None = None, **details) -> dict:
    # Invalidate stale numerical outputs rather than leaving old metrics available
    # to notebooks or other consumers that read files directly.
    for name in ['intents_daily.csv', 'intents_monthly.csv', 'intents_quarterly.csv',
                 'intents_solvers.csv', 'intents_solver_sensitivity.json']:
        (MODELS / name).unlink(missing_ok=True)
    status = {'computed': False, 'source': source, 'reason': reason, **details}
    (MODELS / 'intents_status.json').write_text(json.dumps(status, indent=1) + '\n')
    print(f'L2: not computed ({reason})')
    return status


def run() -> dict:
    f = BQ_DIR / "l2_intents_events.csv"
    sampled = DATA / "blocks" / "intents_events_sampled.csv"
    if f.exists():
        source = "bigquery"
    elif sampled.exists() and (DATA / "blocks" / "sample_manifest.json").exists():
        f, source = sampled, "neardata block sample"
    else:
        return _unavailable('No on-chain extract; run make blocks or optional make bq')
    raw = pd.read_csv(f)
    from .blocks import SUCCESS_STATUSES
    if 'execution_status' not in raw:
        return _unavailable('Legacy extract has no execution status. Run near-thesis verify-events before using L2.',
                            source=source, unverified_events=len(raw))
    known = raw.execution_status.isin(SUCCESS_STATUSES | {'FAILURE'})
    if not known.all():
        return _unavailable('Unknown receipt execution status; revalidate the entire extract.',
                            source=source, unverified_events=int((~known).sum()))
    failed_events = int((raw.execution_status == 'FAILURE').sum())
    raw = raw[raw.execution_status.isin(SUCCESS_STATUSES)].copy()
    raw["block_date"] = pd.to_datetime(raw["block_date"]).dt.date
    if source != "bigquery":
        from .blocks import usable_windows
        ok = usable_windows() or set()
        raw = raw[[(d, int(h)) in ok for d, h in zip(raw["window_day"], raw["window_hour"])]].copy()  # drop windows with only planning probes
        raw["block_date"] = pd.to_datetime(raw["window_day"]).dt.date  # attribute a window to its planned day
    events = raw.assign(event=[(parse_event(l) or {}).get("event") for l in raw["log"]])
    legs = batches_from_events(raw)
    if legs.attrs.get('rejected_items', 0):
        return _unavailable('Malformed token_diff items; refusing partial metrics.', source=source,
                            rejected_items=legs.attrs['rejected_items'])
    if legs.empty:
        return _unavailable('No successful token_diff events in the extract.', source=source)
    roles = identify_solvers(legs, sampled=source != "bigquery")
    prices = _daily_prices()
    daily = daily_metrics(legs, roles, events, prices)
    if source != "bigquery":
        ef = expansion_factors(raw)
        # All usable sampled days belong to the sampling frame, including observed zero-event days.
        daily = daily.set_index("date").reindex(pd.DatetimeIndex(sorted(pd.Timestamp(day) for day in ef.index))).rename_axis("date").reset_index()
        zero_cols = ["batches", "users", "solvers", "volume_priced_usd", "withdraw_events", "priced_legs", "total_legs"]
        daily[zero_cols] = daily[zero_cols].fillna(0)
        f_ = daily["date"].dt.date.map(ef).fillna(1.0)
        daily["expansion_factor"] = f_
        daily["users_sampled"] = daily["users"]
        for c in ["batches", "volume_priced_usd", "withdraw_events"]:
            daily[c + "_sampled"] = daily[c]
            daily[c] = daily[c] * f_
    monthly = monthly_estimates(daily)
    llama = pd.read_csv(DERIVED / "daily.csv", parse_dates=["date"]).set_index("date")["intents_volume_usd"]
    quarterly = quarterly_estimates(daily, llama)
    ratio = pooled_ratio(daily, llama)
    daily.to_csv(MODELS / "intents_daily.csv", index=False)
    monthly.to_csv(MODELS / "intents_monthly.csv", index=False)
    quarterly.to_csv(MODELS / "intents_quarterly.csv", index=False)
    solvers = roles[roles["is_solver"]].groupby("account").agg(days=("block_date", "nunique"), batches=("batches", "sum")).sort_values("batches", ascending=False).reset_index()
    solvers.to_csv(MODELS / "intents_solvers.csv", index=False)
    coverage = {}
    if source != "bigquery":
        man = json.loads((DATA / "blocks" / "sample_manifest.json").read_text())
        coverage = {"blocks_fetched": man.get("blocks_fetched"), "blocks_requested": man.get("blocks_requested"), "sample_complete": man.get("complete"),
                    "days_with_blocks": len({w["day"] for w in man["windows"] if w.get("usable", True) and w.get("fetched", w["n"])})}
    out_ = legs.copy()
    out_["usd"] = [price_leg(t, a, prices.get(str(d), {})) for t, a, d in zip(out_["token"], out_["amount"], out_["block_date"])]
    out_["intent_key"] = out_["intent_hash"].fillna("legacy")
    out_["direction"] = np.where(out_["amount"] < 0, "out", "in")
    pb = out_.dropna(subset=["usd"]).groupby(["receipt_id", "account", "intent_key", "direction"])["usd"].sum().unstack(fill_value=0).max(axis=1).groupby("receipt_id").sum() / 2
    tail = {"priced_batches": int(len(pb)), "max_batch_usd": float(pb.max()) if len(pb) else None,
            "top1pct_share": float(pb[pb >= pb.quantile(0.99)].sum() / pb.sum()) if len(pb) else None,
            "top10pct_share": float(pb[pb >= pb.quantile(0.90)].sum() / pb.sum()) if len(pb) else None}
    sensitivity = []
    if source != "bigquery":
        for share in [0.01, 0.02, 0.05]:
            rr = identify_solvers(legs, sampled=True, min_share=share)
            dm = daily_metrics(legs, rr, events, prices)
            sensitivity.append({"min_batch_share": share, "solver_accounts": int(rr.loc[rr.is_solver, "account"].nunique()),
                                "mean_hhi": float(dm.hhi_solver.mean())})
    (MODELS / "intents_solver_sensitivity.json").write_text(json.dumps(sensitivity, indent=1) + "\n")
    status = {"computed": True, "source": source, "coverage": coverage, "ratio_to_defillama": ratio, "sample_tail": tail, "sampled_days": int(daily["date"].nunique()), "days_with_token_diff": int(legs.block_date.nunique()), "events": int(len(raw)), "token_diff_legs": int(len(legs)),
              'execution_status_verified': True, 'failed_events_excluded': failed_events,
              'pricing_policy': 'exact case-sensitive registry asset identifiers; unknown assets unpriced',
              "solver_accounts": int(len(solvers)), "priced_batch_share_mean": float(daily["priced_batch_share"].mean()),
              "fully_priced_batch_share_mean": float(daily["fully_priced_batch_share"].mean()),
              "priced_leg_share": float(out_["usd"].notna().mean()),
              "volume_method": "half gross participant notional: sum max(priced inflow, priced outflow) per account-intent / 2; fixed-window expansion; not a validated total or guaranteed lower bound",
              "cross_check_passed": bool(ratio and ratio["ci_lo"] <= 1 <= ratio["ci_hi"]),
              "event_counts": events["event"].value_counts().to_dict(),
              "assumptions": {"solver_min_batches_per_day": SOLVER_MIN_BATCHES, "solver_min_counterparties": SOLVER_MIN_COUNTERPARTIES,
                              "mode": "absolute or (batch share >= 2%, batches >= 5, counterparties >= 5)" if source != "bigquery" else "absolute only",
                              "users": "observed unique accounts in windows; never expanded to daily unique users",
                              "intervals": "conditional day bootstrap; excludes intraday, routing and price uncertainty; not a population confidence guarantee"}}
    (MODELS / "intents_status.json").write_text(json.dumps(status, indent=1, default=str))
    print(f"L2: {len(raw):,} events on {status['sampled_days']} days -> {len(solvers)} solver accounts, priced share {status['priced_batch_share_mean']:.0%}")
    return status
