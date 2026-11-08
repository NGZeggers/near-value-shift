"""Value bridge: from settled volume to what reaches the token, step by step, with each step marked observed,
classified, inferred or unavailable, and with issuance set against the NEAR that reached the buyback wallet.
NEAR arriving from intents.near is observed as a withdrawal from an Intents-side balance (data/blocks/buyback_trace.json
checks a pre-declared sample of receipts against their execution blocks); its attribution to executed purchases is inferred.

Inputs: data/derived/daily.csv (DefiLlama volume/fees/revenue series, NearBlocks supply and price) and the optional
NearBlocks snapshots of the buyback multisig (data/raw/nearblocks_buybacks_txns.json, nearblocks_buybacks_account.json).
Outputs (data/derived/models/): value_bridge.json, value_bridge_monthly.csv.

Nothing here is a forecast. The three scenarios are illustrative and every assumption is printed next to its result.
"""
from __future__ import annotations

import json
from .serialization import dumps as json_dumps

import numpy as np
import pandas as pd

from .config import DATA, DERIVED, MODELS
from .http import load_raw

TRACE = DATA / "blocks" / "buyback_trace.json"
TRACE_EXT = DATA / "blocks" / "buyback_trace_extension.json"
ATTRIBUTION = DATA / "bigquery" / "l3_buyback_attribution.csv"
WNEAR_ORIGIN = DATA / "bigquery" / "l3_buyback_wnear_origin.csv"
ATTRIBUTION_RULE = {
    "declared": "2026-11-08, before the query ran",
    "population": "every native_withdraw log of intents.near whose receiver is the buyback wallet on the days with inbound receipts (2026-04-23 to 2026-11-06), from the NEAR public BigQuery dataset",
    "exchange": "the latest token_diff of the same Intents-side account that bought wrap.near, at or before the withdrawal block, searching back one day of blocks",
    "origin": "a bridge deposit (mt_mint) or an internal transfer (mt_transfer) of an asset sold in that exchange to the same account, within one day before the exchange",
    "second_pass": ("declared after the first pass showed withdrawals without an own exchange and before running: for every withdrawal, an internal transfer of "
                    "wrap.near into the withdrawing account (with its source account and whether that source bought wrap.near before the transfer, one hop upstream) "
                    "or a deposit of wrap.near from outside (mt_mint), within one day of blocks"),
    "what_it_establishes": ("the withdrawal is observed for every receipt; the exchange and the transfers are observed events that are compatible with funding the withdrawal "
                            "(same account, at or before the withdrawal, within the declared range), not a demonstrated allocation of those exact funds: balances are fungible, "
                            "amounts per leg and prior balances are not reconciled here, and joins by block height do not fix the order of events inside a block. The strongest "
                            "case is the exchange carried by the same receipt as the withdrawal. Whether the operator intended the withdrawal as a buyback remains an interpretation"),
}
AMOUNT_MATCH_TOLERANCE = "the NearBlocks snapshot stores deposits as floating-point numbers, so amounts are compared at float64 precision (relative 2^-52) and the match is approximate; BigQuery amounts are exact integers"


def _match_snapshot(a: pd.DataFrame, snap: list[dict]) -> dict:
    """Approximate one-to-one reconciliation by UTC day and amount at float precision.

    Admissible pairs are every (snapshot receipt, withdrawal) of the same day whose amounts differ by at most the float64
    representation tolerance. The count of matched pairs is the maximum-cardinality bipartite matching over those pairs, so it does
    not depend on the order of either input. Ambiguity is measured on the admissible relation before any assignment: snapshot
    receipts with more than one admissible withdrawal, withdrawals with more than one admissible snapshot receipt, and the number of
    matched pairs that have an alternative admissible partner (pairs inside a non-trivial component)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import maximum_bipartite_matching
    bq = [(str(pd.Timestamp(d).date()), int(y)) for d, y in zip(a["block_date"], a["amount_yocto"])]
    rows, cols = [], []
    snap_keys = []
    for si, t in enumerate(snap):
        day = pd.Timestamp(int(t["block_timestamp"]) // 10**9, unit="s").strftime("%Y-%m-%d")
        amt = float(sum(float(x["deposit"]) for x in t.get("actions", []) if x.get("action") == "TRANSFER"))
        tol = max(1.0, abs(amt) * 2 ** -52)
        snap_keys.append((day, amt))
        for bi, (d, y) in enumerate(bq):
            if d == day and abs(float(y) - amt) <= tol:
                rows.append(si); cols.append(bi)
    n_s, n_b = len(snap), len(bq)
    if not rows or not n_s or not n_b:
        return {"matched_on_day_and_amount": 0, "ambiguous_snapshot_receipts": 0, "ambiguous_withdrawals": 0, "matched_pairs_with_alternatives": 0,
                "method": "maximum-cardinality bipartite matching over the admissible pairs; order-independent"}
    adj = coo_matrix((np.ones(len(rows), dtype=np.int8), (rows, cols)), shape=(n_s, n_b)).tocsr()
    match = maximum_bipartite_matching(adj, perm_type="column")      # match[si] = bi or -1
    matched = int((match >= 0).sum())
    deg_s = np.asarray(adj.sum(axis=1)).ravel(); deg_b = np.asarray(adj.sum(axis=0)).ravel()
    ambiguous_s = int((deg_s > 1).sum()); ambiguous_b = int((deg_b > 1).sum())
    with_alternatives = int(sum(1 for si, bi in enumerate(match) if bi >= 0 and (deg_s[si] > 1 or deg_b[bi] > 1)))
    return {"matched_on_day_and_amount": matched, "ambiguous_snapshot_receipts": ambiguous_s, "ambiguous_withdrawals": ambiguous_b,
            "matched_pairs_with_alternatives": with_alternatives,
            "method": "maximum-cardinality bipartite matching over the admissible pairs; order-independent"}


def _classify_wnear_origin(a: pd.DataFrame, origin_path=None) -> pd.DataFrame | None:
    """Join the second pass and classify every withdrawal by how the wrap.near reached the account."""
    origin_path = WNEAR_ORIGIN if origin_path is None else origin_path
    if not origin_path.exists():
        return None
    o = pd.read_csv(origin_path)
    m = a.merge(o[["receipt_id", "own_swap_block", "wnear_in_block", "wnear_in_from", "upstream_swap_block", "wnear_mint_block"]], on="receipt_id", how="left")
    own = m["swap_block"].notna() | m["own_swap_block"].notna()
    up = ~own & m["upstream_swap_block"].notna()
    tr = ~own & ~up & m["wnear_in_block"].notna()
    mint = ~own & ~up & ~tr & m["wnear_mint_block"].notna()
    m["wnear_origin_class"] = np.select([own, up, tr, mint], ["own_exchange", "transfer_from_account_that_exchanged", "transfer_without_observed_exchange", "deposit_from_outside"], "none_observed")
    return m


def full_attribution(txns: list[dict] | None = None, path=ATTRIBUTION) -> dict | None:
    """Population-level attribution of the buyback inflows from the BigQuery extract, reconciled with the NearBlocks receipt snapshot."""
    if not path.exists():
        return None
    a = pd.read_csv(path, dtype={"amount_yocto": str})
    a["amount_near"] = [int(y) / 1e24 for y in a["amount_yocto"]]          # exact integers kept in amount_yocto; NEAR only for display
    n = len(a)
    swap = a["swap_block"].notna()
    same_receipt = swap & (a["swap_receipt"] == a["receipt_id"])
    dep = a["deposit_block"].notna(); tr = a["transfer_in_block"].notna()
    out = {"rule": ATTRIBUTION_RULE, "withdrawals": int(n), "near_total": float(a["amount_near"].sum()),
           "distinct_intents_accounts": int(a["intents_account"].nunique()),
           "exchange_observed": int(swap.sum()), "exchange_observed_share": float(swap.mean()) if n else None,
           "exchange_in_same_receipt_as_withdrawal": int(same_receipt.sum()),
           "exchange_kind": "compatible prior event of the same account (latest wrap.near purchase at or before the withdrawal), not a demonstrated allocation of those funds",
           "exchange_observed_near_share": float(a.loc[swap, "amount_near"].sum() / a["amount_near"].sum()) if n and a["amount_near"].sum() > 0 else None,
           "blocks_withdrawal_minus_swap": {"median": float(a.loc[swap, "blocks_withdrawal_minus_swap"].median()) if swap.any() else None,
                                            "p90": float(a.loc[swap, "blocks_withdrawal_minus_swap"].quantile(0.9)) if swap.any() else None,
                                            "within_200_blocks": int((a.loc[swap, "blocks_withdrawal_minus_swap"] <= 200).sum())},
           "origin_deposit_observed": int(dep.sum()), "origin_transfer_in_observed": int((tr & ~dep).sum()),
           "origin_observed_share_of_exchanges": float(((dep | tr) & swap).sum() / swap.sum()) if swap.any() else None,
           "sold_assets_top": a.loc[swap, "sold"].value_counts().head(5).to_dict(),
           "kind": "events observed (public logs); allocation of funds to each withdrawal inferred; intention inferred"}
    if txns is not None:
        snap = [t for t in txns if t.get("predecessor_account_id") == "intents.near"]
        snap_near = sum(float(x["deposit"]) for t in snap for x in t.get("actions", []) if x.get("action") == "TRANSFER") / 1e24
        # The BigQuery row carries the receipt that emitted the native_withdraw log (the execute_intents call); the snapshot carries the
        # child TRANSFER receipt that credited the wallet, so ids never coincide. Match on (day, amount) instead.
        mm = _match_snapshot(a, snap)
        matched = mm["matched_on_day_and_amount"]
        out["reconciliation_with_nearblocks_snapshot"] = {"snapshot_receipts": len(snap), "snapshot_near": snap_near,
                                                           "matched_on_day_and_amount": int(matched), "ambiguous_snapshot_receipts": int(mm["ambiguous_snapshot_receipts"]),
                                                           "ambiguous_withdrawals": int(mm["ambiguous_withdrawals"]), "matched_pairs_with_alternatives": int(mm["matched_pairs_with_alternatives"]),
                                                           "method": mm["method"],
                                                           "snapshot_receipts_unmatched": int(len(snap) - matched), "bigquery_withdrawals_unmatched": int(n - matched),
                                                           "near_ratio_bigquery_over_snapshot": float(a["amount_near"].sum() / snap_near) if snap_near else None,
                                                           "precision": AMOUNT_MATCH_TOLERANCE,
                                                           "kind": "approximate reconciliation by day and amount; not an exact link between the log-emitting receipt and the child transfer receipt (their ids differ by construction)"}
    m = _classify_wnear_origin(a)
    if m is not None:
        classes = ["own_exchange", "transfer_from_account_that_exchanged", "transfer_without_observed_exchange", "deposit_from_outside", "none_observed"]
        by = m.groupby("wnear_origin_class").agg(receipts=("receipt_id", "size"), near=("amount_near", "sum"))
        tot_near = m["amount_near"].sum()
        exch = m["wnear_origin_class"].isin(["own_exchange", "transfer_from_account_that_exchanged"])
        out["wnear_origin"] = {"rule": ATTRIBUTION_RULE["second_pass"],
                               "classes": {c: {"receipts": int(by["receipts"].get(c, 0)), "receipt_share": float(by["receipts"].get(c, 0) / n) if n else None,
                                               "near": float(by["near"].get(c, 0.0)), "near_share": float(by["near"].get(c, 0.0) / tot_near) if tot_near else None} for c in classes},
                               "exchange_observed_within_one_hop": {"receipts": int(exch.sum()), "receipt_share": float(exch.mean()) if n else None,
                                                                    "near_share": float(m.loc[exch, "amount_near"].sum() / tot_near) if tot_near else None},
                               "distinct_source_accounts_of_transfers": int(m["wnear_in_from"].nunique()),
                               "top_source_accounts_by_near": m[m["wnear_in_from"].notna()].groupby("wnear_in_from")["amount_near"].sum().sort_values(ascending=False).head(5).round(0).to_dict()}
        solvers_file = MODELS / "intents_solvers.csv"
        if solvers_file.exists():
            solvers = set(pd.read_csv(solvers_file)["account"].astype(str)) if "account" in pd.read_csv(solvers_file, nrows=1).columns else set()
            src = m[m["wnear_in_from"].notna()]
            out["wnear_origin"]["transfers_from_l2_solver_accounts"] = {"receipts": int(src["wnear_in_from"].isin(solvers).sum()),
                                                                        "near_share_of_transfers": float(src.loc[src["wnear_in_from"].isin(solvers), "amount_near"].sum() / src["amount_near"].sum()) if len(src) and src["amount_near"].sum() > 0 else None,
                                                                        "what": "source accounts that the L2 layer identifies independently as solvers (market makers) from the sampled token_diff events"}
    out["reading"] = (f"of {n:,} withdrawals ({out['near_total']:,.0f} NEAR) a compatible exchange by the same account is observed for {out['exchange_observed']:,} ({out['exchange_observed_share']:.0%} of receipts, "
                      f"{out['exchange_observed_near_share']:.0%} of the NEAR), in {out['exchange_in_same_receipt_as_withdrawal']:,} of them inside the same receipt as the withdrawal; the sold asset reached the account "
                      f"by a bridge deposit in {out['origin_deposit_observed']:,} cases and by an internal transfer in {out['origin_transfer_in_observed']:,}. These are observed events compatible with funding the "
                      "withdrawal; the allocation of those exact funds to each withdrawal is not reconciled (amounts per leg, prior balances and intra-block order are not tracked) and stays inferred")
    if m is not None:
        wo = out["wnear_origin"]; c = wo["classes"]
        out["reading"] += (f". Second pass: every withdrawal has some compatible prior flow of wrap.near observed; counting the account that transferred the wrap.near in and bought it itself (one hop upstream), a compatible exchange is observed for "
                           f"{wo['exchange_observed_within_one_hop']['receipts']:,} withdrawals ({wo['exchange_observed_within_one_hop']['receipt_share']:.0%} of receipts, {wo['exchange_observed_within_one_hop']['near_share']:.0%} of the NEAR); "
                           f"{c['transfer_without_observed_exchange']['receipts']:,} ({c['transfer_without_observed_exchange']['near_share']:.0%} of the NEAR) received wrap.near by internal transfer from {wo['distinct_source_accounts_of_transfers']} source accounts with no observed purchase of their own, "
                           + (f"of which the accounts the L2 layer identifies as solvers account for {wo['transfers_from_l2_solver_accounts']['near_share_of_transfers']:.0%} of that NEAR (a counterparty paying wrap.near directly; its counter-leg is not identified here), " if wo.get("transfers_from_l2_solver_accounts") and wo["transfers_from_l2_solver_accounts"]["near_share_of_transfers"] is not None else "")
                           + f"{c['deposit_from_outside']['receipts']:,} received it as a deposit from outside, and {c['none_observed']['receipts']:,} ({c['none_observed']['near_share']:.0%} of the NEAR) show none of these in the day before; "
                           "transfer amounts are not kept, so a compatible flow is not a reconciled funding of the withdrawal")
    return out


def receipt_status(outcome: object) -> str:
    """Only the source's explicit boolean success counts; anything else is kept apart, never treated as success."""
    if isinstance(outcome, dict):
        st = outcome.get("status")
        if st is True:
            return "success"
        if st is False:
            return "failed"
    return "missing_or_invalid_status"

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
                         "near": amt, "direction": "in" if inbound else "out", "status": receipt_status(t.get("receipt_outcome"))})
    # gas paid by transactions the wallet signed (one fee per transaction, not per receipt)
    fees = {}
    for t in raw["data"]["txns"]:
        if t.get("predecessor_account_id") == BUYBACK_WALLET and t.get("transaction_hash") and receipt_status(t.get("receipt_outcome")) == "success":
            fee = float(((t.get("outcomes_agg") or {}).get("transaction_fee") or 0)) / YOCTO
            ts = pd.Timestamp(int(str(t.get("block_timestamp") or t["receipt_block"]["block_timestamp"])[:10]), unit="s").normalize()
            fees[t["transaction_hash"]] = (ts, fee)
    fee_df = pd.DataFrame([{"date": ts, "near": fee} for ts, fee in fees.values()]) if fees else pd.DataFrame(columns=["date", "near"])
    df = pd.DataFrame(rows)
    if df.empty:
        return {"transfers": 0}
    excluded = {"failed": int((df["status"] == "failed").sum()), "missing_or_invalid_status": int((df["status"] == "missing_or_invalid_status").sum())}
    df = df[df["status"] == "success"]
    df["usd"] = df["near"] * df["date"].map(price).astype(float)
    all_in, all_out = df[df["direction"] == "in"], df[df["direction"] == "out"]
    inw = all_in[all_in["date"] <= cutoff]
    out = all_out[all_out["date"] <= cutoff]
    by_pred = inw.groupby("predecessor")["near"].sum().sort_values(ascending=False)
    treasury = inw["predecessor"].isin(FEE_WALLETS - {BUYBACK_WALLET})
    purchases = inw[inw["predecessor"] == "intents.near"]        # swap outputs settled by intents.near: executed purchases
    monthly = purchases.groupby(purchases["date"].dt.to_period("M").dt.to_timestamp()).agg(near_in=("near", "sum"), usd_in=("usd", "sum"), transfers=("near", "size"))
    balance = float(acct["data"]["amount"]) / YOCTO if acct else None
    created = pd.Timestamp(int(str(acct["data"]["created"]["block_timestamp"])[:10]), unit="s") if acct else None
    # ledger reconstructed from receipts: at the fetch (to check completeness against the snapshot) and at the analysis cutoff
    fees_all = float(fee_df["near"].sum()); fees_cut = float(fee_df.loc[fee_df["date"] <= cutoff, "near"].sum()) if len(fee_df) else 0.0
    ledger_fetch = float(all_in["near"].sum() - all_out["near"].sum() - fees_all)
    ledger_cutoff = float(inw["near"].sum() - out["near"].sum() - fees_cut)
    ledger = {"method": "sum of successful inbound TRANSFER receipts minus outbound TRANSFER receipts minus gas of wallet-signed transactions; no storage or staking terms",
              "reconstructed_balance_at_fetch_near": ledger_fetch, "snapshot_balance_at_fetch_near": balance,
              "unexplained_residual_near": (balance - ledger_fetch) if balance is not None else None,
              "unexplained_residual_share_of_inflows": ((balance - ledger_fetch) / float(all_in["near"].sum())) if (balance is not None and float(all_in["near"].sum())) else None,
              "reconstructed_balance_at_cutoff_near": ledger_cutoff, "cutoff": str(cutoff.date()),
              "inflows_after_cutoff_near": float(all_in.loc[all_in["date"] > cutoff, "near"].sum()), "outflows_after_cutoff_near": float(all_out.loc[all_out["date"] > cutoff, "near"].sum()),
              "gas_paid_near_total": fees_all}
    return {"source": raw["source"], "fetched_at": raw["fetched_at"], "transfers_in": int(len(inw)), "transfers_out": int(len(out)),
            "receipts_excluded": excluded, "ledger": ledger,
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
    trace = json.loads(TRACE.read_text()) if TRACE.exists() else None
    ext = json.loads(TRACE_EXT.read_text()) if TRACE_EXT.exists() else None
    snapshot = load_raw("nearblocks_buybacks_txns", optional=True)
    attribution = full_attribution((snapshot or {}).get("data", {}).get("txns"))
    if trace and attribution:
        trace["full_attribution"] = attribution
    if trace and ext:
        trace["funding_swap_found_within_extension"] = ext["swap_found"]
        trace["funding_swap_observed_total"] = trace["with_token_diff_in_same_block"] + ext["swap_found"]
        trace["extension"] = {k: v for k, v in ext.items() if k != "receipts"}
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
        if trace:
            tr_note = (f"Trace of a pre-declared sample ({trace['sampled']} of {trace['receipts_in_snapshot_from_intents_near']} receipts, every 80th plus the five largest): "
                       f"{trace['matched_native_withdraw']} match a dip4 native_withdraw of wrapped NEAR from {trace.get('distinct_intents_accounts', len(trace['intents_accounts']))} distinct Intents-side accounts; "
                       f"for {trace['with_token_diff_in_same_block']} the funding swap (token_diff of the same account, {trace.get('with_wrap_near_bought_in_same_block', 0)} buying wrap.near) is in the same blocks, "
                       f"for the other {trace['sampled'] - trace['with_token_diff_in_same_block']} it is outside the blocks read and the purchase is not observed. "
                       + (f"A second pre-declared pass over those found the funding swap within {trace['extension']['blocks_back']} blocks before the withdrawal for {trace['funding_swap_found_within_extension']} more "
                          f"({trace['funding_swap_observed_total']} of {trace['sampled']} in total). " if trace.get("extension") else "")
                       + (f"Population from BigQuery: {attribution['reading']}. " if attribution else "The origin of the sold asset is not traced. "))
        else:
            tr_note = "No receipt trace yet (make blocks-buyback-trace). "
        steps.append({"step": 5, "name": f"NEAR withdrawn from Intents into {BUYBACK_WALLET}", "short": "NEAR received by buyback wallet", "usd": bb_usd, "near": bb_near,
                      "status": "observed (receipts, valued at the daily NEAR price); attribution to executed purchases inferred",
                      "source": receipts["source"], "share_of_previous": bb_usd / hold if hold else None,
                      "note": (f"{receipts['purchase_transfers']} inbound transfers from intents.near from {receipts['first_inbound']} to {receipts['last_inbound_before_cutoff']}; "
                               f"a further {receipts['near_in_from_treasury_wallets']:,.0f} NEAR arrived from the other revenue wallets (treasury moves, excluded here as the adapter excludes them) "
                               f"and {receipts['near_in_other']:,.0f} NEAR from other accounts. " + tr_note +
                               f"Receipts excluded: {receipts['receipts_excluded']['failed']} failed, {receipts['receipts_excluded']['missing_or_invalid_status']} without an explicit status. "
                               f"The wallet was created {receipts['wallet_created']}, after the adapter's buyback start "
                               f"{BUYBACK_START}, so labelled revenue before that date cannot be matched to this wallet")})
        led = receipts["ledger"]
        held_share = led["reconstructed_balance_at_cutoff_near"] / receipts["near_in_total"] if receipts["near_in_total"] else None
        steps.append({"step": 6, "name": "Destination at the analysis cutoff (ledger reconstructed from receipts)", "short": "Held in the multisig", "near": led["reconstructed_balance_at_cutoff_near"], "usd": None,
                      "status": "inferred: balance at the cutoff reconstructed from receipts; the snapshot balance is shown separately at its own date",
                      "source": f"NearBlocks receipts to {led['cutoff']}; account snapshot {receipts['fetched_at']}", "share_of_previous": held_share,
                      "note": (f"inbound before the cutoff minus outbound ({receipts['near_out']:,.0f} NEAR) minus gas, divided by all inbound NEAR before the cutoff. "
                               f"Snapshot balance at fetch {receipts['balance_near_at_fetch']:,.0f} NEAR versus {led['reconstructed_balance_at_fetch_near']:,.0f} NEAR reconstructed to the same date "
                               f"(residual {led['unexplained_residual_near']:,.1f} NEAR); inflows after the cutoff {led['inflows_after_cutoff_near']:,.0f} NEAR. "
                               "No burn observed; holding is not supply destruction")})
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
                "buyback_near_received_12m": bb_near, "buyback_measure": "NEAR withdrawn from Intents into the buyback wallet (observed); purchase attribution inferred", "buyback_to_issuance_ratio": (bb_near / new_circ) if (bb_near is not None and new_circ > 0) else None,
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
           "trace": ({k: v for k, v in trace.items() if k != "receipts"} | {"examples": trace["receipts"][:3]}) if trace else {"available": False, "how": "make blocks-buyback-trace"},
           "scenarios": scen, "scenario_multipliers": SCENARIOS,
           "dominant_assumption": {"method": "one at a time: each input moved from its base to its adverse value, others held at base; ranked by the absolute change in net yield",
                                   "ranking": ranking, "dominant": ranking[0]["assumption"] if ranking else None},
           "what_weakens_the_thesis": ("issuance above buyback accrual in every scenario means settlement growth does not translate into net token accrual; "
                                       "a fall in volume or capture, or an allocation decision away from buybacks, removes the accrual entirely"),
           "status_legend": {"observed": "read from a public source and reproducible from the committed snapshot", "classified": "a rule applied by the data provider",
                             "inferred": "computed from observed items under a stated assumption", "unavailable": "not obtainable without credentials or absent on-chain"}}
    (MODELS / "value_bridge.json").write_text(json_dumps(out, indent=1, default=lambda v: None if (isinstance(v, float) and np.isnan(v)) else str(v)))
    print(f"bridge: {len(steps)} steps, net yield base {scen['base']['net_yield_on_mcap']:+.2%}, dominant assumption {out['dominant_assumption']['dominant']}")
    return out
