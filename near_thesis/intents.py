"""L2: NEAR Intents microstructure from raw DIP-4 events emitted by intents.near.

Input (from `make bq`, sql/l2_intents_events.sql): data/bigquery/l2_intents_events.csv with columns
block_date, block_timestamp, receipt_id, caller, log. One row per EVENT_JSON log line.

Method
1. Parse `EVENT_JSON:{...}`; keep standard "dip4". `token_diff` events carry data[] of {account_id, intent_hash, diff}.
2. A receipt = one execute_intents batch. Within a batch the diffs sum to zero per token; the accounts in the
   batch are the counterparties of one or more swaps.
3. Solver identification (documented assumption, with sensitivity): an account is a solver on a given day if it
   appears in >= SOLVER_MIN_BATCHES batches that day with >= SOLVER_MIN_COUNTERPARTIES distinct counterparties.
   Everyone else is a user.
4. USD pricing: a swap leg denominated in a stablecoin is priced at par; NEAR, BTC, ETH legs are priced with the
   daily price tables; other legs stay unpriced and are reported as such. Volume = sum of priced user outflows.
5. Daily metrics: batches, users, solvers, HHI and top-1/top-5 share of solver volume (priced) or batch count,
   median priced trade size, withdrawal events. Sampled days are expanded to monthly estimates with a
   day-level bootstrap confidence interval.
Outputs (data/derived/models/): intents_daily.csv, intents_monthly.csv, intents_solvers.csv, intents_status.json
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

import numpy as np
import pandas as pd

from .config import BQ_DIR, DATA, DERIVED, MODELS

SOLVER_MIN_BATCHES = 20          # BigQuery full days
SOLVER_MIN_COUNTERPARTIES = 10
SOLVER_MIN_BATCH_SHARE = 0.02    # sampled windows: an account in >= 2% of a day's sampled batches with >= 5 counterparties
STABLE_RE = re.compile(r"(usdc|usdt|usdt0|dai|frax|usde|pyusd|usd1|fdusd|busd|tusd|lusd|usdy|usd\b)", re.I)
# token id -> (price column, decimals). Keys are matched as substrings of the token id.
MAJORS = {"wrap.near": ("near", 24), "nbtc": ("bitcoin", 8), "btc": ("bitcoin", 8), "eth.omft": ("ethereum", 18),
          "aurora": ("ethereum", 18), "eth.bridge": ("ethereum", 18), "weth": ("ethereum", 18)}
STABLE_DECIMALS = 6


def parse_event(log: str) -> dict | None:
    if not isinstance(log, str) or not log.startswith("EVENT_JSON:"):
        return None
    try:
        ev = json.loads(log[len("EVENT_JSON:"):])
    except json.JSONDecodeError:
        return None
    return ev if ev.get("standard") == "dip4" else None


def token_decimals(token: str) -> int | None:
    t = token.lower()
    if STABLE_RE.search(t):
        return STABLE_DECIMALS
    for k, (_, dec) in MAJORS.items():
        if k in t:
            return dec
    return None


def price_leg(token: str, amount_raw: int, prices: dict[str, float]) -> float | None:
    """USD value of an amount of `token` on a day, or None when unpriced."""
    t = token.lower()
    if STABLE_RE.search(t):
        return abs(amount_raw) / 10 ** STABLE_DECIMALS
    for k, (col, dec) in MAJORS.items():
        if k in t and prices.get(col):
            return abs(amount_raw) / 10 ** dec * prices[col]
    return None


def batches_from_events(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (receipt, account, token) with the signed raw diff."""
    rows = []
    for r in df.itertuples(index=False):
        ev = parse_event(r.log)
        if not ev or ev.get("event") != "token_diff":
            continue
        for item in ev.get("data", []):
            for token, amt in (item.get("diff") or {}).items():
                try:
                    rows.append((r.block_date, r.receipt_id, item.get("account_id"), item.get("intent_hash"), token, int(amt)))
                except (TypeError, ValueError):
                    continue
    return pd.DataFrame(rows, columns=["block_date", "receipt_id", "account", "intent_hash", "token", "amount"])


def identify_solvers(legs: pd.DataFrame) -> pd.DataFrame:
    """Per (day, account): batches, distinct counterparties, is_solver."""
    pairs = legs[["block_date", "receipt_id", "account"]].drop_duplicates()
    cp = pairs.merge(pairs, on=["block_date", "receipt_id"], suffixes=("", "_other"))
    cp = cp[cp["account"] != cp["account_other"]]
    stats = cp.groupby(["block_date", "account"]).agg(batches=("receipt_id", "nunique"), counterparties=("account_other", "nunique")).reset_index()
    per_day = pairs.groupby("block_date")["receipt_id"].nunique()
    stats["batch_share"] = stats["batches"] / stats["block_date"].map(per_day)
    absolute = (stats["batches"] >= SOLVER_MIN_BATCHES) & (stats["counterparties"] >= SOLVER_MIN_COUNTERPARTIES)
    relative = (stats["batch_share"] >= SOLVER_MIN_BATCH_SHARE) & (stats["counterparties"] >= 5) & (stats["batches"] >= 5)
    stats["is_solver"] = absolute | relative
    return stats


def _daily_prices() -> dict[str, dict[str, float]]:
    d = pd.read_csv(DERIVED / "daily.csv", parse_dates=["date"]).set_index("date")
    out = {}
    for day, r in d.iterrows():
        out[str(day.date())] = {"near": r.get("near_price"), "bitcoin": r.get("price_bitcoin"), "ethereum": r.get("price_ethereum")}
    return out


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
        user_out = users[users["amount"] < 0]
        priced = user_out.dropna(subset=["usd"])
        per_batch = priced.groupby("receipt_id")["usd"].sum()
        solver_vol = g[g["is_solver"] & (g["amount"] < 0)].dropna(subset=["usd"]).groupby("account")["usd"].sum()
        solver_batches = g[g["is_solver"]].groupby("account")["receipt_id"].nunique()
        conc = solver_vol if len(solver_vol) else solver_batches
        top = conc.sort_values(ascending=False)
        rows.append({
            "date": pd.Timestamp(day), "batches": int(g["receipt_id"].nunique()), "users": int(users["account"].nunique()),
            "solvers": int(g.loc[g["is_solver"], "account"].nunique()),
            "volume_priced_usd": float(per_batch.sum()), "priced_batch_share": float(len(per_batch) / max(1, g["receipt_id"].nunique())),
            "median_trade_usd": float(per_batch.median()) if len(per_batch) else np.nan,
            "p90_trade_usd": float(per_batch.quantile(0.9)) if len(per_batch) else np.nan,
            "hhi_solver": hhi(top.to_numpy(dtype=float)) if len(top) else np.nan,
            "top1_solver_share": float(top.iloc[0] / top.sum()) if len(top) else np.nan,
            "top5_solver_share": float(top.iloc[:5].sum() / top.sum()) if len(top) else np.nan,
            "withdraw_events": int(wd.get(day, 0)),
        })
    return pd.DataFrame(rows).sort_values("date")


def monthly_estimates(daily: pd.DataFrame, n_boot: int = 2000, seed: int = 11) -> pd.DataFrame:
    """Sampled days -> monthly totals with a bootstrap CI over days (days treated as exchangeable within month)."""
    rng = np.random.default_rng(seed)
    rows = []
    for month, g in daily.groupby(daily["date"].dt.to_period("M")):
        dim = month.days_in_month
        v = g["volume_priced_usd"].to_numpy()
        est = v.mean() * dim
        boots = [rng.choice(v, size=len(v), replace=True).mean() * dim for _ in range(n_boot)] if len(v) > 1 else [est]
        rows.append({"month": month.to_timestamp(), "sampled_days": int(len(v)), "volume_est_usd": float(est),
                     "volume_ci_lo": float(np.quantile(boots, 0.025)), "volume_ci_hi": float(np.quantile(boots, 0.975)),
                     "users_per_day": float(g["users"].mean()), "solvers_per_day": float(g["solvers"].mean()),
                     "hhi_solver": float(g["hhi_solver"].mean()), "top1_solver_share": float(g["top1_solver_share"].mean()),
                     "median_trade_usd": float(g["median_trade_usd"].median())})
    return pd.DataFrame(rows)


def expansion_factors(raw: pd.DataFrame) -> pd.Series:
    """blocks in the day (NearBlocks) / blocks sampled that day -> multiply sampled counts and volume to daily totals."""
    man = json.loads((DATA / "blocks" / "sample_manifest.json").read_text())
    sampled = {}
    for w in man["windows"]:
        sampled[pd.Timestamp(w["day"]).date()] = sampled.get(pd.Timestamp(w["day"]).date(), 0) + w["n"]
    d = pd.read_csv(DERIVED / "daily.csv", parse_dates=["date"]).set_index("date")["blocks"]
    bpd = {k.date(): float(v) for k, v in d.items()}
    return pd.Series({day: bpd.get(day, 150_000.0) / n for day, n in sampled.items()})


def run() -> dict:
    f = BQ_DIR / "l2_intents_events.csv"
    sampled = DATA / "blocks" / "intents_events_sampled.csv"
    if f.exists():
        source = "bigquery"
    elif sampled.exists() and (DATA / "blocks" / "sample_manifest.json").exists():
        f, source = sampled, "neardata block sample"
    else:
        status = {"computed": False, "reason": "no data/bigquery/l2_intents_events.csv (make bq) and no data/blocks/intents_events_sampled.csv (make blocks)."}
        (MODELS / "intents_status.json").write_text(json.dumps(status, indent=1))
        print("L2: not computed (no on-chain extract)")
        return status
    raw = pd.read_csv(f)
    raw["block_date"] = pd.to_datetime(raw["block_date"]).dt.date
    if source != "bigquery":
        raw["block_date"] = pd.to_datetime(raw["window_day"]).dt.date  # attribute a window to its planned day
    events = raw.assign(event=[(parse_event(l) or {}).get("event") for l in raw["log"]])
    legs = batches_from_events(raw)
    if legs.empty:
        status = {"computed": False, "reason": f"{source}: no token_diff events in the extract."}
        (MODELS / "intents_status.json").write_text(json.dumps(status, indent=1))
        print("L2: no token_diff events found")
        return status
    roles = identify_solvers(legs)
    daily = daily_metrics(legs, roles, events, _daily_prices())
    if source != "bigquery":
        ef = expansion_factors(raw)
        f_ = daily["date"].dt.date.map(ef).fillna(1.0)
        daily["expansion_factor"] = f_
        for c in ["batches", "users", "volume_priced_usd", "withdraw_events"]:
            daily[c + "_sampled"] = daily[c]
            daily[c] = daily[c] * f_          # users expanded is an upper bound (the same user can appear in other windows)
    monthly = monthly_estimates(daily)
    daily.to_csv(MODELS / "intents_daily.csv", index=False)
    monthly.to_csv(MODELS / "intents_monthly.csv", index=False)
    solvers = roles[roles["is_solver"]].groupby("account").agg(days=("block_date", "nunique"), batches=("batches", "sum")).sort_values("batches", ascending=False).reset_index()
    solvers.to_csv(MODELS / "intents_solvers.csv", index=False)
    status = {"computed": True, "source": source, "sampled_days": int(daily["date"].nunique()), "events": int(len(raw)), "token_diff_legs": int(len(legs)),
              "solver_accounts": int(len(solvers)), "priced_batch_share_mean": float(daily["priced_batch_share"].mean()),
              "event_counts": events["event"].value_counts().to_dict(),
              "assumptions": {"solver_min_batches_per_day": SOLVER_MIN_BATCHES, "solver_min_counterparties": SOLVER_MIN_COUNTERPARTIES}}
    (MODELS / "intents_status.json").write_text(json.dumps(status, indent=1, default=str))
    print(f"L2: {len(raw):,} events on {status['sampled_days']} days -> {len(solvers)} solver accounts, priced share {status['priced_batch_share_mean']:.0%}")
    return status
