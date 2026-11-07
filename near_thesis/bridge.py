"""Value bridge: from settled volume to what reaches the token, step by step, with each step marked observed,
classified, inferred or unavailable, and with issuance set against executed buybacks.

Inputs: data/derived/daily.csv (DefiLlama volume/fees/revenue series, NearBlocks supply and price) and the optional
NearBlocks snapshots of the buyback multisig (data/raw/nearblocks_buybacks_txns.json, nearblocks_buybacks_account.json).
Outputs (data/derived/models/): value_bridge.json, value_bridge_monthly.csv.

Nothing here is a forecast. The three scenarios are illustrative and every assumption is printed next to its result.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .config import DERIVED, MODELS
from .http import load_raw

BUYBACK_WALLET = "buybacks.multisignature.near"
BUYBACK_START = "2026-02-23"          # DefiLlama fees/near-intents adapter constant
YOCTO = 1e24
FEE_WALLETS = {"fefundsadmin.sputnik-dao.near", "1csfundsadmin.sputnik-dao.near", BUYBACK_WALLET}

SCENARIOS = {
    # multipliers on the observed trailing-year inputs; allocation = share of net captured revenue used for buybacks
    "adverse": {"volume": 0.5, "take_rate": 0.75, "capture": 0.75, "allocation": 0.5, "issuance": 1.25},
    "base": {"volume": 1.0, "take_rate": 1.0, "capture": 1.0, "allocation": None, "issuance": 1.0},   # None = observed buyback-labelled share
    "favorable": {"volume": 2.0, "take_rate": 1.25, "capture": 1.25, "allocation": 1.0, "issuance": 0.75},
}


def buyback_receipts(cutoff: pd.Timestamp, price: pd.Series) -> dict | None:
    raw = load_raw("nearblocks_buybacks_txns", optional=True)
    acct = load_raw("nearblocks_buybacks_account", optional=True)
    if raw is None:
        return None
    rows = []
    for t in raw["data"]["txns"]:
        ts = pd.Timestamp(int(str(t.get("block_timestamp") or t["receipt_block"]["block_timestamp"])[:10]), unit="s").normalize()
        for a in t.get("actions") or []:
            if a.get("action") != "TRANSFER" or not a.get("deposit"):
                continue
            amt = float(a["deposit"]) / YOCTO
            inbound = t.get("receiver_account_id") == BUYBACK_WALLET
            rows.append({"date": ts, "receipt_id": t.get("receipt_id"), "predecessor": t.get("predecessor_account_id"), "receiver": t.get("receiver_account_id"),
                         "near": amt, "direction": "in" if inbound else "out", "status": bool((t.get("receipt_outcome") or {}).get("status", True))})
    df = pd.DataFrame(rows)
    if df.empty:
        return {"transfers": 0}
    df = df[df["status"]]
    df["usd"] = df["near"] * df["date"].map(price).astype(float)
    inw = df[(df["direction"] == "in") & (df["date"] <= cutoff)]
    out = df[(df["direction"] == "out") & (df["date"] <= cutoff)]
    by_pred = inw.groupby("predecessor")["near"].sum().sort_values(ascending=False)
    treasury = inw["predecessor"].isin(FEE_WALLETS - {BUYBACK_WALLET})
    purchases = inw[inw["predecessor"] == "intents.near"]        # swap outputs settled by intents.near: executed purchases
    monthly = purchases.groupby(purchases["date"].dt.to_period("M").dt.to_timestamp()).agg(near_in=("near", "sum"), usd_in=("usd", "sum"), transfers=("near", "size"))
    balance = float(acct["data"]["amount"]) / YOCTO if acct else None
    created = pd.Timestamp(int(str(acct["data"]["created"]["block_timestamp"])[:10]), unit="s") if acct else None
    return {"source": raw["source"], "fetched_at": raw["fetched_at"], "transfers_in": int(len(inw)), "transfers_out": int(len(out)),
            "near_in_total": float(inw["near"].sum()), "usd_in_total_at_daily_price": float(inw["usd"].sum()),
            "near_in": float(purchases["near"].sum()), "usd_in_at_daily_price": float(purchases["usd"].sum()), "purchase_transfers": int(len(purchases)),
            "near_in_from_treasury_wallets": float(inw.loc[treasury, "near"].sum()),
            "near_in_other": float(inw.loc[~treasury & (inw["predecessor"] != "intents.near"), "near"].sum()),
            "near_out": float(out["near"].sum()), "first_inbound": str(inw["date"].min().date()) if len(inw) else None, "last_inbound_before_cutoff": str(inw["date"].max().date()) if len(inw) else None,
            "inbound_by_predecessor_near": {k: float(v) for k, v in by_pred.head(6).items()},
            "share_from_intents_near": float(by_pred.get("intents.near", 0.0) / by_pred.sum()) if by_pred.sum() else None,
            "balance_near_at_fetch": balance, "wallet_created": str(created.date()) if created is not None else None,
            "adapter_buyback_start": BUYBACK_START, "monthly": monthly}


def run() -> dict:
    d = pd.read_csv(DERIVED / "daily.csv", parse_dates=["date"]).set_index("date")
    cutoff = d.index.max()
    y = d.loc[d.index > cutoff - pd.Timedelta(days=365)]
    vol = float(y["intents_volume_usd"].sum()); fees = float(y["intents_fees_usd"].sum())
    rev = float(y["intents_revenue_usd"].sum(min_count=1)) if "intents_revenue_usd" in y else np.nan
    hold = float(y["intents_holders_revenue_usd"].sum(min_count=1)) if "intents_holders_revenue_usd" in y else np.nan
    price = d["near_price"].ffill()
    mcap = float(d["market_cap_usd"].dropna().iloc[-1])
    avg_price = float(y["near_price"].mean())
    circ = d["circulating_supply"].dropna(); tot = d["total_supply"].dropna() if "total_supply" in d else pd.Series(dtype=float)
    c0, c1 = float(circ.loc[:y.index[0]].iloc[-1]), float(circ.iloc[-1])
    t0, t1 = (float(tot.loc[:y.index[0]].iloc[-1]), float(tot.iloc[-1])) if len(tot) else (np.nan, np.nan)
    receipts = buyback_receipts(cutoff, price)
    bb_near = receipts["near_in"] if receipts and receipts.get("purchase_transfers") else None
    bb_usd = receipts["usd_in_at_daily_price"] if receipts and receipts.get("purchase_transfers") else None
    # steps of the bridge; share_of_previous makes the funnel explicit
    steps = [
        {"step": 1, "name": "Settled volume through Intents", "short": "Settled volume", "usd": vol, "status": "observed (third-party series)",
         "source": "DefiLlama dexs/near-intents dailyVolume, a pass-through of dune.near.dataset_near_intents_metrics", "share_of_previous": None},
        {"step": 2, "name": "Gross swap fees", "short": "Gross fees", "usd": fees, "status": "observed (third-party series)",
         "source": "DefiLlama fees/near-intents dailyFees: protocol fee plus affiliate fees across integrators (Dune datasets)", "share_of_previous": fees / vol if vol else None,
         "note": f"take rate {fees / vol * 1e4:.1f} bps of volume" if vol else None},
        {"step": 3, "name": "Net revenue captured by NEAR (NEAR/wNEAR swept into revenue wallets)", "short": "Net captured revenue", "usd": rev, "status": "observed (adapter wallet receipts)",
         "source": "DefiLlama dailyRevenue: TRANSFER and wrap.near inflows to fefundsadmin, 1csfundsadmin and buybacks wallets, internal hops excluded", "share_of_previous": rev / fees if fees else None,
         "note": "sweeps are periodic, so a day's receipts can exceed that day's fees"},
        {"step": 4, "name": "Revenue labelled as buyback (dates on or after 2026-02-23)", "short": "Labelled as buyback", "usd": hold, "status": "classified by an adapter date rule, not by transaction",
         "source": "DefiLlama dailyHoldersRevenue = dailyRevenue on or after BUYBACK_START", "share_of_previous": hold / rev if rev else None},
    ]
    if bb_near is not None:
        steps.append({"step": 5, "name": f"Executed purchases: NEAR settled by intents.near into {BUYBACK_WALLET}", "short": "NEAR received by buyback wallet", "usd": bb_usd, "near": bb_near,
                      "status": "observed (NearBlocks receipts, valued at the daily NEAR price)",
                      "source": receipts["source"], "share_of_previous": bb_usd / hold if hold else None,
                      "note": (f"{receipts['purchase_transfers']} swap-output transfers from {receipts['first_inbound']} to {receipts['last_inbound_before_cutoff']}; "
                               f"a further {receipts['near_in_from_treasury_wallets']:,.0f} NEAR arrived from the other revenue wallets (treasury moves, excluded here as the adapter excludes them) "
                               f"and {receipts['near_in_other']:,.0f} NEAR from other accounts. The wallet was created {receipts['wallet_created']}, after the adapter's buyback start "
                               f"{BUYBACK_START}, so labelled revenue before that date cannot be matched to this wallet")})
        held_share = receipts["balance_near_at_fetch"] / receipts["near_in_total"] if receipts.get("balance_near_at_fetch") and receipts["near_in_total"] else None
        steps.append({"step": 6, "name": "Destination of purchased tokens", "short": "Held in the multisig", "near": receipts.get("balance_near_at_fetch"), "usd": None,
                      "status": "observed balance (held in the multisig; no burn observed)",
                      "source": f"NearBlocks account snapshot {receipts['fetched_at']}", "share_of_previous": held_share,
                      "note": (f"balance at the snapshot divided by all inbound NEAR before the cutoff; outbound transfers before the cutoff: {receipts['near_out']:,.0f} NEAR. "
                               "Holding is not supply destruction")})
    else:
        steps.append({"step": 5, "name": "Executed purchases", "short": "Executed purchases", "usd": None, "status": "unavailable (run `near-thesis fetch --only buybacks`)", "source": "NearBlocks", "share_of_previous": None})
        steps.append({"step": 6, "name": "Destination of purchased tokens", "short": "Destination", "usd": None, "status": "unavailable", "source": "NearBlocks", "share_of_previous": None})
    new_total = (t1 - t0) if np.isfinite(t1) else np.nan
    circ_window = circ.loc[y.index[0]:]
    circ_stale = bool(len(circ_window) and circ_window.nunique() == 1)
    last_circ_change = str(circ[circ.diff() != 0].index.max().date()) if (circ.diff() != 0).any() else None
    # Issuance is measured on total supply (protocol issuance net of gas burn). NearBlocks' circulating-supply field
    # stops changing in 2025-08 and is reported, not used.
    new_circ = new_total if np.isfinite(new_total) else (c1 - c0)
    dilution = {"window": [str(y.index[0].date()), str(cutoff.date())], "status": "observed: NearBlocks daily total supply",
                "measure": "total supply change: protocol issuance net of gas burn; unlocks of already-issued tokens are not dilution of supply",
                "total_supply_start_near": t0 if np.isfinite(t0) else None, "total_supply_end_near": t1 if np.isfinite(t1) else None,
                "net_new_total_near": new_total if np.isfinite(new_total) else None,
                "annual_total_supply_growth": (t1 / t0 - 1) if np.isfinite(t1) and t0 else None,
                "circulating_supply_field": {"start": c0, "end": c1, "stale_in_source": circ_stale, "last_change": last_circ_change,
                                             "note": "constant in the NearBlocks snapshot over the window, so it is not used"},
                "net_new_usd_at_average_price": new_circ * avg_price,
                "buyback_near_received_12m": bb_near, "buyback_to_issuance_ratio": (bb_near / new_circ) if (bb_near is not None and new_circ > 0) else None,
                "note": ("buybacks are held, not burned, so they do not reduce supply and are not netted twice: issuance is counted once here and buybacks once above")}
    # scenarios: annual accrual to buybacks vs annual issuance, as yields on market cap
    capture = rev / fees if fees else np.nan
    alloc_obs = (hold / rev) if rev else np.nan
    take_bps = fees / vol * 1e4 if vol else np.nan
    scen = {}
    for name, m in SCENARIOS.items():
        alloc = alloc_obs if m["allocation"] is None else m["allocation"]
        accrual = vol * m["volume"] * (take_bps * m["take_rate"] / 1e4) * (capture * m["capture"]) * alloc
        issuance_usd = new_circ * m["issuance"] * avg_price
        scen[name] = {"assumptions": {"volume_usd": vol * m["volume"], "take_rate_bps": take_bps * m["take_rate"], "capture_share": capture * m["capture"],
                                      "allocation_to_buybacks": alloc, "net_new_supply_near": new_circ * m["issuance"], "near_price_usd": avg_price},
                      "buyback_accrual_usd": accrual, "issuance_usd": issuance_usd,
                      "buyback_yield_on_mcap": accrual / mcap, "dilution_yield_on_mcap": issuance_usd / mcap, "net_yield_on_mcap": (accrual - issuance_usd) / mcap}
    # dominant assumption: one-at-a-time moves from base to the adverse value
    base = scen["base"]["net_yield_on_mcap"]
    ranking = []
    for key in ["volume", "take_rate", "capture", "allocation", "issuance"]:
        m = dict(SCENARIOS["base"]); m[key] = SCENARIOS["adverse"][key]
        alloc = alloc_obs if m["allocation"] is None else m["allocation"]
        accrual = vol * m["volume"] * (take_bps * m["take_rate"] / 1e4) * (capture * m["capture"]) * alloc
        issuance_usd = new_circ * m["issuance"] * avg_price
        ranking.append({"assumption": key, "net_yield_on_mcap": (accrual - issuance_usd) / mcap, "change_vs_base": (accrual - issuance_usd) / mcap - base})
    ranking.sort(key=lambda r: abs(r["change_vs_base"]), reverse=True)
    monthly = pd.DataFrame({"buyback_labelled_revenue_usd": d["intents_holders_revenue_usd"].resample("MS").sum(min_count=1)}) if "intents_holders_revenue_usd" in d else pd.DataFrame()
    if receipts and isinstance(receipts.get("monthly"), pd.DataFrame):
        monthly = monthly.join(receipts["monthly"].rename(columns={"near_in": "buyback_wallet_near_in", "usd_in": "buyback_wallet_usd_in", "transfers": "buyback_wallet_transfers"}), how="outer")
    monthly = monthly.loc[(monthly.index >= pd.Timestamp("2026-01-01")) & (monthly.index + pd.offsets.MonthEnd(0) <= cutoff)]
    monthly.index.name = "month"
    monthly.reset_index().to_csv(MODELS / "value_bridge_monthly.csv", index=False)
    out = {"as_of": str(cutoff.date()), "window_days": 365, "market_cap_usd": mcap, "average_near_price_usd": avg_price,
           "steps": steps, "dilution": dilution,
           "receipts": {k: v for k, v in (receipts or {}).items() if k != "monthly"} if receipts else {"available": False},
           "scenarios": scen, "scenario_multipliers": SCENARIOS,
           "dominant_assumption": {"method": "one at a time: each input moved from its base to its adverse value, others held at base; ranked by the absolute change in net yield",
                                   "ranking": ranking, "dominant": ranking[0]["assumption"] if ranking else None},
           "what_weakens_the_thesis": ("issuance above buyback accrual in every scenario means settlement growth does not translate into net token accrual; "
                                       "a fall in volume or capture, or an allocation decision away from buybacks, removes the accrual entirely"),
           "status_legend": {"observed": "read from a public source and reproducible from the committed snapshot", "classified": "a rule applied by the data provider",
                             "inferred": "computed from observed items under a stated assumption", "unavailable": "not obtainable without credentials or absent on-chain"}}
    (MODELS / "value_bridge.json").write_text(json.dumps(out, indent=1, default=lambda v: None if (isinstance(v, float) and np.isnan(v)) else str(v)))
    print(f"bridge: {len(steps)} steps, net yield base {scen['base']['net_yield_on_mcap']:+.2%}, dominant assumption {out['dominant_assumption']['dominant']}")
    return out
