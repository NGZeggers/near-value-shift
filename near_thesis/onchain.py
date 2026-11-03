"""Stretch goal: publish the daily index on-chain so the thesis' key numbers are verifiable without trusting this repo.

We write to NEAR Social (an on-chain key-value store; `v1.social08.testnet` on testnet, `social.near` on mainnet)
under <account>/near_thesis/index, together with the SHA-256 of THESIS.md and of every raw snapshot. No contract to deploy.

Requires `uv sync --extra onchain` and, in .env: NEAR_ACCOUNT_ID, NEAR_PRIVATE_KEY (ed25519:...), NEAR_NETWORK=testnet.
Signing a transaction needs explicit human approval (hackathon rule): this command is never run by the build.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone

import pandas as pd

from .config import DERIVED, MODELS, ROOT
from .http import raw_manifest

SOCIAL = {"testnet": ("v1.social08.testnet", "https://rpc.testnet.near.org"), "mainnet": ("social.near", "https://rpc.mainnet.near.org")}


def payload() -> dict:
    d = pd.read_csv(DERIVED / "daily.csv", parse_dates=["date"]).set_index("date")
    m = pd.read_csv(DERIVED / "monthly.csv", parse_dates=["month"]).set_index("month")
    full = m[m.index < m.index.max()].iloc[-1]
    qaa = MODELS / "qaa_monthly.csv"
    q = pd.read_csv(qaa, parse_dates=["month"]).set_index("month").iloc[-1] if qaa.exists() else None
    ic = {r["metric"]: r["spearman_ic"] for r in json.loads((MODELS / "signal_ic.json").read_text()) if r.get("horizon_weeks") == 12 and r.get("benchmark") == "btc" and "spearman_ic" in r}
    return {
        "as_of": str(d.index.max().date()),
        "month": str(full.name.date())[:7],
        "active_accounts_daily_mean": round(float(full["active_accounts"])),
        "qaa": None if q is None else round(float(q["qaa"])),
        "intents_volume_usd": round(float(full["intents_volume_usd"])),
        "usd_per_txn": round(float(full["usd_per_txn"]), 2),
        "ic_intents_12w_vs_btc": round(ic.get("intents_volume_usd", float("nan")), 3) if "intents_volume_usd" in ic else None,
        "thesis_sha256": hashlib.sha256((ROOT / "THESIS.md").read_bytes()).hexdigest(),
        "raw_manifest_sha256": hashlib.sha256(json.dumps([r["sha256"] for r in raw_manifest()]).encode()).hexdigest(),
        "repo": "https://github.com/NGZeggers/near-value-shift",
    }


async def publish(dry_run: bool = True) -> dict:
    network = os.getenv("NEAR_NETWORK", "testnet")
    contract, rpc = SOCIAL[network]
    account_id, key = os.getenv("NEAR_ACCOUNT_ID"), os.getenv("NEAR_PRIVATE_KEY")
    index = payload()
    (DERIVED / "onchain_index.json").write_text(json.dumps(index, indent=1))  # what the chain would hold; diffable in git
    data = {account_id or "<account>": {"near_thesis": {"index": json.dumps(dict(index, published_at=datetime.now(timezone.utc).isoformat(timespec="seconds")))}}}
    print(json.dumps(data, indent=1))
    if dry_run:
        print(f"dry run: would call {contract}.set on {network} from {account_id} (saved data/derived/onchain_index.json)")
        return data
    if not (account_id and key):
        raise SystemExit("NEAR_ACCOUNT_ID and NEAR_PRIVATE_KEY are required in .env")
    from py_near.account import Account  # type: ignore

    acc = Account(account_id, key, rpc_addr=rpc)
    await acc.startup()
    res = await acc.function_call(contract, "set", {"data": data}, gas=100_000_000_000_000, amount=50_000_000_000_000_000_000_000)  # 0.05 NEAR storage deposit
    print("tx:", res.transaction.hash)
    return {"tx": res.transaction.hash}


def read_index(account_id: str, network: str = "testnet") -> dict | None:
    """Read <account>/near_thesis/index back from NEAR Social with a plain RPC view call (no keys, no py-near)."""
    import base64

    import requests

    contract, rpc = SOCIAL[network]
    args = base64.b64encode(json.dumps({"keys": [f"{account_id}/near_thesis/index"]}).encode()).decode()
    body = {"jsonrpc": "2.0", "id": "1", "method": "query",
            "params": {"request_type": "call_function", "finality": "final", "account_id": contract, "method_name": "get", "args_base64": args}}
    r = requests.post(rpc, json=body, timeout=30); r.raise_for_status()
    res = r.json().get("result", {})
    if "error" in res or not res.get("result"):
        return None
    tree = json.loads(bytes(res["result"]).decode())
    raw = ((tree.get(account_id) or {}).get("near_thesis") or {}).get("index")
    return json.loads(raw) if raw else None


def verify(account_id: str | None = None, network: str | None = None) -> bool:
    """Compare the on-chain index with this checkout: same THESIS.md hash means the published numbers are the ones here."""
    account_id = account_id or os.getenv("NEAR_ACCOUNT_ID")
    network = network or os.getenv("NEAR_NETWORK", "testnet")
    if not account_id:
        raise SystemExit("pass --account or set NEAR_ACCOUNT_ID")
    chain = read_index(account_id, network)
    if chain is None:
        print(f"no index published under {account_id}/near_thesis/index on {network}")
        return False
    local = payload()
    mismatches = [k for k, v in local.items() if chain.get(k) != v]
    same = not mismatches
    print(json.dumps({"network": network, "account": account_id, "published_at": chain.get("published_at"), "as_of_chain": chain.get("as_of"),
                      "as_of_local": local["as_of"], "index_matches": same, "mismatched_fields": mismatches, "chain": chain}, indent=1))
    return same


def run(dry_run: bool = True) -> None:
    asyncio.run(publish(dry_run))
