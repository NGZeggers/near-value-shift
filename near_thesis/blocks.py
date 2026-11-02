"""On-chain sampling without BigQuery: fetch full blocks from FastNear's public block API (neardata) and extract
(a) every DIP-4 event log emitted by intents.near and (b) every transaction's signer/receiver/method.

The API rate-limits per IP at roughly 0.3-0.4 requests/s (measured 2026-11-02), so the sample budget is small by
design: ~5,000 blocks takes about 4-5 hours. Fetched blocks are cached, so the budget can be raised later and resumed.

Design: stratified sample of days (every `day_step` days since INTENTS_START), `windows` fixed UTC hours per day,
`blocks_per_window` consecutive blocks per window. Block heights for each timestamp are found by binary search on
the archival RPC. Expansion to daily totals uses blocks-per-day from NearBlocks (data/derived/daily.csv).

Outputs (data/blocks/): intents_events_sampled.csv (same schema as the BigQuery extract), tx_sampled.csv,
sample_manifest.json. Resumable: blocks already fetched are skipped (per-block JSONL cache in data/blocks/cache/).
"""
from __future__ import annotations

import csv
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .config import DATA, INTENTS_START

NEARDATA = "https://mainnet.neardata.xyz/v0/block/{h}"
ARCHIVAL_RPC = "https://archival-rpc.mainnet.fastnear.com"
BLOCKS = DATA / "blocks"
CACHE = BLOCKS / "cache"
UA = {"user-agent": "near-thesis/0.1 (NEAR Hackathon 2026; sampled block reader)"}
RATE_PER_S = 0.35  # measured 2026-11-02: the public block API sustains ~0.3-0.4 requests/s per IP before answering 429
RATE_MIN, RATE_MAX = 0.12, 0.6
_lock = threading.Lock()
_next_slot = [0.0]
_rate = [RATE_PER_S]


def _throttle() -> None:
    with _lock:
        now = time.monotonic()
        wait = max(0.0, _next_slot[0] - now)
        _next_slot[0] = max(now, _next_slot[0]) + 1.0 / _rate[0]
    if wait:
        time.sleep(wait)


def _adapt(ok: bool) -> None:
    """AIMD: a 429 cuts the rate by a third, every success nudges it up by 1%."""
    with _lock:
        _rate[0] = max(RATE_MIN, _rate[0] * 0.67) if not ok else min(RATE_MAX, _rate[0] * 1.01)


def rpc_block(height: int) -> dict | None:
    try:
        r = requests.post(ARCHIVAL_RPC, json={"jsonrpc": "2.0", "id": 1, "method": "block", "params": {"block_id": height}}, timeout=30, headers=UA)
        return r.json().get("result")
    except (requests.RequestException, ValueError):
        return None


def latest_height() -> int:
    r = requests.get("https://mainnet.neardata.xyz/v0/last_block/final", timeout=30, headers=UA, allow_redirects=True)
    r.raise_for_status()
    return int(r.json()["block"]["header"]["height"])


def find_height(ts_ns: int, lo: int, hi: int) -> int:
    """Smallest height whose block timestamp >= ts_ns (binary search; skipped heights are stepped over)."""
    while lo < hi:
        mid = (lo + hi) // 2
        b = rpc_block(mid)
        step = 0
        while b is None and step < 20:  # height without a block: probe forward
            step += 1
            b = rpc_block(mid + step)
        if b is None:
            lo = mid + step + 1
            continue
        if int(b["header"]["timestamp"]) >= ts_ns:
            hi = mid
        else:
            lo = mid + step + 1
    return lo


def block_ts(height: int) -> tuple[int, int] | None:
    """(height, timestamp_ns) from neardata, stepping forward over skipped heights."""
    for step in range(0, 6):
        b = fetch_block(height + step)
        if b is not None:
            return b["height"], b["ts"]
    return None


def find_height_fast(ts_ns: int, guess: int, top: int, tol_s: float = 90.0, max_iter: int = 12) -> int:
    """Secant iteration on neardata block timestamps (fast, cached). Stops within tol_s seconds of the target,
    returning the first height at or after the target instant. Falls back to the archival-RPC binary search."""
    h, t = block_ts(min(max(guess, 1), top)) or (None, None)
    if h is None:
        return find_height(ts_ns, max(1, guess - 10_000_000), top)
    rate = 0.6e9  # ns per block, refined below
    prev = None
    for _ in range(max_iter):
        err = (ts_ns - t) / 1e9
        if abs(err) <= tol_s:
            break
        if prev is not None and prev[0] != h and prev[1] != t:
            rate = max(0.3e9, min(2e9, (t - prev[1]) / (h - prev[0])))
        prev = (h, t)
        step = int((ts_ns - t) / rate)
        nh = min(max(h + step, 1), top)
        got = block_ts(nh)
        if got is None:
            break
        h, t = got
    # within tol_s of the target instant is good enough for a sampling window start
    return h


def plan(day_step: int = 15, windows: tuple[int, ...] = (3, 15), blocks_per_window: int = 250, start: str = INTENTS_START) -> list[dict]:
    """List of windows {day, hour, start_height, n}. Day sampling is deterministic (fixed step from INTENTS_START)."""
    d0 = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end = datetime.now(timezone.utc) - timedelta(days=1)
    top = latest_height()
    out, guess = [], 130_000_000
    day = d0
    while day <= end:
        for hr in windows:
            ts = int((day.replace(hour=hr)).timestamp() * 1e9)
            h = find_height_fast(ts, guess, top)
            out.append({"day": day.strftime("%Y-%m-%d"), "hour": hr, "start_height": h, "n": blocks_per_window})
            guess = h + int((hr and 0) or 0) + 12 * 3600 * 2  # next window is hours/days ahead; secant corrects it
            print(f"  window {day.strftime('%Y-%m-%d')} {hr:02d}:00 -> height {h}", flush=True)
        day += timedelta(days=day_step)
    return out


def fetch_block(height: int, retries: int = 6, rate_limit_retries: int = 40) -> dict | None:
    cached = CACHE / f"{height}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    attempt = limited = 0
    while attempt < retries and limited < rate_limit_retries:
        try:
            _throttle()
            r = requests.get(NEARDATA.format(h=height), timeout=60, headers=UA, allow_redirects=True)
            if r.status_code == 429:  # retry-after is always 0 here; back off on our own
                limited += 1; _adapt(False)
                time.sleep(min(10.0, 1.5 * limited))
                continue
            _adapt(True)
            if r.status_code == 404:
                CACHE.mkdir(parents=True, exist_ok=True); cached.write_text("null"); return None
            if r.status_code >= 500:
                raise requests.HTTPError(str(r.status_code))
            r.raise_for_status()
            full = r.json()
            if not full:  # skipped height: the API answers 200 with a null body
                CACHE.mkdir(parents=True, exist_ok=True); cached.write_text("null"); return None
            slim = extract(full)
            CACHE.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(slim, separators=(",", ":")))
            return slim
        except (requests.RequestException, ValueError):
            attempt += 1
            time.sleep(2 * attempt)
    return None


def extract(block: dict) -> dict:
    """Keep only what the pipeline needs; a full block is ~200 KB, this is a few KB."""
    hdr = block["block"]["header"]
    ts = int(hdr["timestamp"]); height = int(hdr["height"])
    txs, events, n_outcomes = [], [], 0
    for sh in block.get("shards", []):
        chunk = sh.get("chunk") or {}
        for t in chunk.get("transactions", []) or []:
            tx = t["transaction"]
            for a in tx.get("actions", []) or []:
                if isinstance(a, dict) and "FunctionCall" in a:
                    fc = a["FunctionCall"]; txs.append([tx["signer_id"], tx["receiver_id"], "FUNCTION_CALL", fc.get("method_name"), str(fc.get("deposit", "0"))])
                elif isinstance(a, dict) and "Transfer" in a:
                    txs.append([tx["signer_id"], tx["receiver_id"], "TRANSFER", None, str(a["Transfer"].get("deposit", "0"))])
                else:
                    kind = a if isinstance(a, str) else next(iter(a.keys()), "OTHER")
                    txs.append([tx["signer_id"], tx["receiver_id"], str(kind).upper(), None, "0"])
        for o in sh.get("receipt_execution_outcomes", []) or []:
            n_outcomes += 1
            rc = o.get("receipt") or {}
            if rc.get("receiver_id") != "intents.near":
                continue
            logs = ((o.get("execution_outcome") or {}).get("outcome") or {}).get("logs") or []
            for log in logs:
                if isinstance(log, str) and log.startswith("EVENT_JSON:"):
                    events.append([rc.get("receipt_id"), rc.get("predecessor_id"), log])
    return {"height": height, "ts": ts, "n_outcomes": n_outcomes, "txs": txs, "events": events}


def run(day_step: int = 15, windows: tuple[int, ...] = (3, 15), blocks_per_window: int = 250, workers: int = 2) -> dict:
    BLOCKS.mkdir(parents=True, exist_ok=True)
    plan_file = BLOCKS / "sample_plan.json"
    if plan_file.exists():
        P = json.loads(plan_file.read_text())
    else:
        print("planning windows (secant search on block timestamps)...")
        P = plan(day_step, windows, blocks_per_window)
        plan_file.write_text(json.dumps(P, indent=1))
    heights = [(w, w["start_height"] + i) for w in P for i in range(blocks_per_window)]  # the plan fixes the windows; n per window is a budget knob
    print(f"{len(P)} windows over {len({w['day'] for w in P})} days, {len(heights)} blocks to read")
    t0 = time.time(); done = 0; missing = 0
    ev_path, tx_path = BLOCKS / "intents_events_sampled.csv", BLOCKS / "tx_sampled.csv"
    with ev_path.open("w", newline="") as fe, tx_path.open("w", newline="") as ft:
        we, wt = csv.writer(fe), csv.writer(ft)
        we.writerow(["block_date", "block_timestamp", "receipt_id", "caller", "log", "window_day", "window_hour", "block_height"])
        wt.writerow(["block_date", "window_day", "window_hour", "block_height", "block_timestamp", "signer", "receiver", "action_kind", "method", "deposit"])
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(fetch_block, h): (w, h) for w, h in heights}
            for f in as_completed(futs):
                w, h = futs[f]
                b = f.result()
                done += 1
                if b is None:
                    missing += 1; continue
                day = datetime.fromtimestamp(b["ts"] / 1e9, tz=timezone.utc).strftime("%Y-%m-%d")
                for rid, pred, log in b["events"]:
                    we.writerow([day, b["ts"], rid, pred, log, w["day"], w["hour"], b["height"]])
                for s, r, kind, m, dep in b["txs"]:
                    wt.writerow([day, w["day"], w["hour"], b["height"], b["ts"], s, r, kind, m, dep])
                if done % 100 == 0:
                    el = time.time() - t0
                    print(f"  {done}/{len(heights)} blocks, {missing} missing, {el:,.0f}s, rate {_rate[0]:.2f}/s, eta {(len(heights) - done) / max(done / el, 1e-9) / 60:,.0f} min", flush=True)
    man = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": NEARDATA, "windows": P,
           "blocks_requested": len(heights), "blocks_missing": missing, "day_step": day_step, "hours": list(windows), "blocks_per_window": blocks_per_window}
    (BLOCKS / "sample_manifest.json").write_text(json.dumps(man, indent=1))
    print(f"done: {done - missing} blocks in {time.time() - t0:,.0f}s -> data/blocks/")
    return man
