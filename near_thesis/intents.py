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
STABLE_SYMBOLS = {"usdc", "usdt", "usdt0", "dai", "frax", "usde", "pyusd", "usd1", "fdusd", "busd", "tusd", "lusd", "usdy", "usds", "xusd", "usdg"}
# fallback for tokens absent from the registry: substring of the token id -> (CoinGecko id, decimals)
MAJORS = {"wrap.near": ("near", 24), "nbtc": ("bitcoin", 8), "btc": ("bitcoin", 8), "eth.omft": ("ethereum", 18),
          "aurora": ("ethereum", 18), "eth.bridge": ("ethereum", 18), "weth": ("ethereum", 18), "sol.omft": ("solana", 9),
          "xrp.omft": ("ripple", 6), "doge.omft": ("dogecoin", 8), "zec.omft": ("zcash", 8), "ltc.omft": ("litecoin", 8),
          "bch.omft": ("bitcoin-cash", 8), "tron.omft": ("tron", 6)}
STABLE_DECIMALS = 6
GECKO_ALIASES = {"wrapped-near": "near", "wrapped-bitcoin": "bitcoin", "weth": "ethereum", "wrapped-solana": "solana", "wrapped-steth": "ethereum"}


def load_token_registry() -> dict[str, tuple[str, int, str | None]]:
    """asset id (lower) -> (symbol lower, decimals, CoinGecko id) from the 1Click snapshot (data/raw/intents_tokens.json)."""
    f = DATA / "raw" / "intents_tokens.json"
    if not f.exists():
        return {}
    out = {}
    for t in json.loads(f.read_text()).get("data") or []:
        try:
            out[str(t["assetId"]).lower()] = (str(t.get("symbol", "")).lower(), int(t["decimals"]), t.get("coingeckoId"))
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
    t = token.lower()
    reg = registry().get(t)
    if reg:
        return reg[1]
    if STABLE_RE.search(t):
        return STABLE_DECIMALS
    for k, (_, dec) in MAJORS.items():
        if k in t:
            return dec
    return None


def price_leg(token: str, amount_raw: int, prices: dict[str, float]) -> float | None:
    """USD value of an amount of `token` on a day, or None when unpriced. Registry first (1Click asset list), then
    name heuristics for assets no longer listed. Stablecoins at par; majors at the day's DefiLlama price."""
    t = token.lower()
    reg = registry().get(t)
    if reg:
        sym, dec, gid = reg
        if sym in STABLE_SYMBOLS:
            return abs(amount_raw) / 10 ** dec
        gid = GECKO_ALIASES.get(gid, gid)
        if gid and prices.get(gid):
            return abs(amount_raw) / 10 ** dec * prices[gid]
        return None
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
        data = ev.get("data")
        items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])  # 2024 events carry one object
        for item in items:
            if not isinstance(item, dict):
                continue
            for token, amt in (item.get("diff") or {}).items():
                try:
                    rows.append((r.block_date, r.receipt_id, item.get("account_id"), item.get("intent_hash") or item.get("hash"), token, int(amt)))
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
        # value of a batch = the largest priced outflow of any party (for a two-party swap, the notional once);
        # independent of who is classified as a solver, so thin samples do not drop or double-count batches
        out = g[(g["amount"] < 0)].dropna(subset=["usd"])
        per_batch = out.groupby(["receipt_id", "account"])["usd"].sum().groupby("receipt_id").max()
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
    """Sampled days -> monthly totals with a bootstrap CI over days (days treated as exchangeable within month).
    With two sampled days per month the interval is indicative only; see quarterly_estimates and pooled_ratio."""
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


def quarterly_estimates(daily: pd.DataFrame, llama: pd.Series, n_boot: int = 2000, seed: int = 11) -> pd.DataFrame:
    """Quarter totals (about six sampled days each) with a day-bootstrap CI, next to DefiLlama's quarter total."""
    rng = np.random.default_rng(seed)
    rows = []
    for q, g in daily.groupby(daily["date"].dt.to_period("Q")):
        ll_q = llama[(llama.index >= q.start_time) & (llama.index <= q.end_time)].dropna()
        days = int(len(ll_q)) or (q.end_time - q.start_time).days + 1  # a partial quarter is compared on the days DefiLlama has
        v = g["volume_priced_usd"].to_numpy()
        est = v.mean() * days
        boots = [rng.choice(v, size=len(v), replace=True).mean() * days for _ in range(n_boot)] if len(v) > 1 else [est]
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
        from .blocks import usable_windows
        ok = usable_windows() or set()
        raw = raw[[(d, int(h)) in ok for d, h in zip(raw["window_day"], raw["window_hour"])]].copy()  # drop windows with only planning probes
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
    out_ = legs[legs["amount"] < 0].copy()
    out_["usd"] = [price_leg(t, a, _daily_prices().get(str(d), {})) for t, a, d in zip(out_["token"], out_["amount"], out_["block_date"])]
    pb = out_.dropna(subset=["usd"]).groupby(["receipt_id", "account"])["usd"].sum().groupby("receipt_id").max()
    tail = {"priced_batches": int(len(pb)), "max_batch_usd": float(pb.max()) if len(pb) else None,
            "top1pct_share": float(pb[pb >= pb.quantile(0.99)].sum() / pb.sum()) if len(pb) else None,
            "top10pct_share": float(pb[pb >= pb.quantile(0.90)].sum() / pb.sum()) if len(pb) else None}
    status = {"computed": True, "source": source, "coverage": coverage, "ratio_to_defillama": ratio, "sample_tail": tail, "sampled_days": int(daily["date"].nunique()), "events": int(len(raw)), "token_diff_legs": int(len(legs)),
              "solver_accounts": int(len(solvers)), "priced_batch_share_mean": float(daily["priced_batch_share"].mean()),
              "event_counts": events["event"].value_counts().to_dict(),
              "assumptions": {"solver_min_batches_per_day": SOLVER_MIN_BATCHES, "solver_min_counterparties": SOLVER_MIN_COUNTERPARTIES}}
    (MODELS / "intents_status.json").write_text(json.dumps(status, indent=1, default=str))
    print(f"L2: {len(raw):,} events on {status['sampled_days']} days -> {len(solvers)} solver accounts, priced share {status['priced_batch_share_mean']:.0%}")
    return status
