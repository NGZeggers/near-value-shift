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
SUCCESS_STATUSES = frozenset({'SUCCESS_VALUE', 'SUCCESS_RECEIPT_ID'})
CACHE_SCHEMA = 2
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


def fetch_block(height: int, retries: int = 6, rate_limit_retries: int = 40, *, offline: bool = False) -> dict | None:
    cached = CACHE / f"{height}.json"
    if cached.exists():
        saved = json.loads(cached.read_text())
        if saved is None or (saved.get('schema_version') == CACHE_SCHEMA and saved.get('height') == height):
            return saved
    if offline:
        raise ValueError(f'No status-aware cached block {height}; rerun verification online')
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
            if slim['height'] != height:
                raise ValueError('Returned block height does not match request')
            CACHE.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(slim, separators=(",", ":")))
            return slim
        except (requests.RequestException, ValueError):
            attempt += 1
            time.sleep(2 * attempt)
    return None


def outcome_status(status: object) -> str:
    """Only explicit successful protocol outcome variants establish execution."""
    if isinstance(status, dict) and len(status) == 1:
        if 'SuccessValue' in status and isinstance(status['SuccessValue'], str):
            return 'SUCCESS_VALUE'
        if 'SuccessReceiptId' in status and isinstance(status['SuccessReceiptId'], str):
            return 'SUCCESS_RECEIPT_ID'
        if 'Failure' in status:
            return 'FAILURE'
    return 'UNKNOWN'


def extract(block: dict) -> dict:
    """Keep only what the pipeline needs; a full block is ~200 KB, this is a few KB."""
    hdr = block["block"]["header"]
    ts = int(hdr["timestamp"]); height = int(hdr["height"])
    txs, events, n_outcomes, receipts = [], [], 0, {}
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
            outcome = ((o.get("execution_outcome") or {}).get("outcome") or {})
            logs = outcome.get('logs') or []
            status = outcome_status(outcome.get('status'))
            rid = rc.get('receipt_id')
            receipts[rid] = {'status': status, 'logs': logs, 'caller': rc.get('predecessor_id')}
            if status not in SUCCESS_STATUSES:
                continue
            for log in logs:
                if isinstance(log, str) and log.startswith("EVENT_JSON:"):
                    events.append([rid, rc.get("predecessor_id"), log, status])
    return {"schema_version": CACHE_SCHEMA, "height": height, "ts": ts, "n_outcomes": n_outcomes,
            "txs": txs, "events": events, 'receipts': receipts}


def verify_events(*, offline: bool = False) -> dict:
    """Revalidate every saved event, replacing the extract only after complete verification.

    New-schema block caches make interrupted runs resumable. Legacy slim caches
    have lost the execution status and must be fetched again, never upgraded by assumption.
    """
    import hashlib
    import io

    path = BLOCKS / 'intents_events_sampled.csv'
    original = path.read_bytes()
    reader = csv.DictReader(io.StringIO(original.decode()))
    fields = list(reader.fieldnames or [])
    rows = list(reader)
    heights = sorted({int(row['block_height']) for row in rows})
    checked = {}
    for i, height in enumerate(heights):
        checked[height] = fetch_block(height, offline=offline)
        if checked[height] is None:
            raise ValueError(f'Block {height} unavailable; original extract preserved')
        if checked[height]['height'] != height:
            raise ValueError('Block height mismatch; original extract preserved')
        if (i + 1) % 25 == 0:
            print(f'Verified {i+1}/{len(heights)} blocks; original extract unchanged until complete', flush=True)
    kept, failed = [], 0
    for row in rows:
        block = checked[int(row['block_height'])]
        rc = block['receipts'].get(row['receipt_id'])
        if not rc or row['log'] not in rc['logs'] or row['caller'] != rc['caller'] or int(row['block_timestamp']) != block['ts']:
            raise ValueError('Event provenance mismatch; original extract preserved')
        if rc['status'] not in SUCCESS_STATUSES | {'FAILURE'}:
            raise ValueError('Unknown execution status; original extract preserved')
        if rc['status'] == 'FAILURE':
            failed += 1
            continue
        kept.append(dict(row, execution_status=rc['status']))
    if 'execution_status' not in fields:
        fields.append('execution_status')
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(kept)
    verified = buffer.getvalue().encode()
    report = {'source': NEARDATA, 'blocks_checked': len(heights), 'input_events': len(rows),
              'accepted_events': len(kept), 'failed_events_removed': failed,
              'input_sha256': hashlib.sha256(original).hexdigest(), 'output_sha256': hashlib.sha256(verified).hexdigest()}
    # Refuse concurrent changes; replace atomically after all checks pass.
    if path.read_bytes() != original:
        raise ValueError('Extract changed during verification; refusing replacement')
    temporary = path.with_suffix('.csv.tmp')
    temporary.write_bytes(verified)
    temporary.replace(path)
    (BLOCKS / 'event_verification.json').write_text(json.dumps(report, indent=1) + '\n')
    return report


def min_usable(n: int) -> int:
    """A window counts as sampled when at least 10 blocks (or a fifth of the budget) were read; planning probes alone do not."""
    return max(10, n // 5)


def usable_windows() -> set[tuple[str, int]] | None:
    """(day, hour) of windows with enough blocks in data/blocks/sample_manifest.json; None when there is no manifest."""
    f = BLOCKS / "sample_manifest.json"
    if not f.exists():
        return None
    man = json.loads(f.read_text())
    return {(w["day"], int(w["hour"])) for w in man["windows"] if w.get("usable", w.get("fetched", w["n"]) >= min_usable(w["n"]))}


def write_manifest(P: list[dict], fetched: dict, blocks_per_window: int, day_step: int, windows: tuple[int, ...], missing: int, requested: int) -> dict:
    """Manifest with per-window fetched counts; written during the run so a partial sample is usable (and resumable)."""
    wins = [dict(w, n=blocks_per_window, fetched=fetched.get(i, 0), usable=fetched.get(i, 0) >= min_usable(blocks_per_window)) for i, w in enumerate(P)]
    got = sum(fetched.values())
    man = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": NEARDATA, "windows": wins,
           "blocks_requested": requested, "blocks_fetched": got, "blocks_missing": missing, "complete": got + missing >= requested,
           "day_step": day_step, "hours": list(windows), "blocks_per_window": blocks_per_window}
    (BLOCKS / "sample_manifest.json").write_text(json.dumps(man, indent=1))
    return man


def run(day_step: int = 15, windows: tuple[int, ...] = (3, 15), blocks_per_window: int = 50, workers: int = 2, offline: bool = False) -> dict:
    """offline=True rebuilds the CSVs and the manifest from the cache only (no network): the state of a partial run."""
    BLOCKS.mkdir(parents=True, exist_ok=True)
    plan_file = BLOCKS / "sample_plan.json"
    if plan_file.exists():
        P = json.loads(plan_file.read_text())
    else:
        if offline:
            raise ValueError('Offline sampling requires an existing sample_plan.json')
        print("planning windows (secant search on block timestamps)...")
        P = plan(day_step, windows, blocks_per_window)
        plan_file.write_text(json.dumps(P, indent=1))
    heights = [(i, w["start_height"] + j) for i, w in enumerate(P) for j in range(blocks_per_window)]
    if offline:
        heights = [(i, h) for i, h in heights if (CACHE / f"{h}.json").exists()]
        # Validate old caches before opening/truncating any extract. Offline means
        # no cache upgrade via HTTP, even after the schema migration.
        for _, height in heights:
            fetch_block(height, offline=True)
    requested = len(P) * blocks_per_window
    print(f"{len(P)} windows over {len({w['day'] for w in P})} days, {len(heights)} blocks to read" + (" (offline, from cache)" if offline else ""))
    t0 = time.time(); done = 0; missing = 0; fetched: dict[int, int] = {}
    ev_path, tx_path = BLOCKS / "intents_events_sampled.csv", BLOCKS / "tx_sampled.csv"
    with ev_path.open("w", newline="") as fe, tx_path.open("w", newline="") as ft:
        we, wt = csv.writer(fe), csv.writer(ft)
        we.writerow(["block_date", "block_timestamp", "receipt_id", "caller", "log", "window_day", "window_hour", "block_height", 'execution_status'])
        wt.writerow(["block_date", "window_day", "window_hour", "block_height", "block_timestamp", "signer", "receiver", "action_kind", "method", "deposit"])
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(fetch_block, h, offline=offline): (i, h) for i, h in heights}
            for f in as_completed(futs):
                i, h = futs[f]; w = P[i]
                b = f.result()
                done += 1
                if b is None:
                    missing += 1
                else:
                    fetched[i] = fetched.get(i, 0) + 1
                    day = datetime.fromtimestamp(b["ts"] / 1e9, tz=timezone.utc).strftime("%Y-%m-%d")
                    for rid, pred, log, status in b["events"]:
                        we.writerow([day, b["ts"], rid, pred, log, w["day"], w["hour"], b["height"], status])
                    for s_, r, kind, m, dep in b["txs"]:
                        wt.writerow([day, w["day"], w["hour"], b["height"], b["ts"], s_, r, kind, m, dep])
                if done % 100 == 0:
                    fe.flush(); ft.flush()
                    write_manifest(P, fetched, blocks_per_window, day_step, windows, missing, requested)
                    el = time.time() - t0
                    print(f"  {done}/{len(heights)} blocks, {missing} missing, {el:,.0f}s, rate {_rate[0]:.2f}/s, eta {(len(heights) - done) / max(done / el, 1e-9) / 60:,.0f} min", flush=True)
    man = write_manifest(P, fetched, blocks_per_window, day_step, windows, missing, requested)
    print(f"done: {sum(fetched.values())} blocks in {time.time() - t0:,.0f}s -> data/blocks/ (complete={man['complete']})")
    return man


# ---------- intraday profile for selected sampled days (reconciliation of the fixed-window expansion) ----------

INTRADAY_HOURS = tuple(range(24))
INTRADAY_PLAN = BLOCKS / "intraday_plan.json"
INTRADAY_EVENTS = BLOCKS / "intraday_events.csv"
INTRADAY_MANIFEST = BLOCKS / "intraday_manifest.json"
# Declared before any intraday block was fetched (2026-11-06). Days come from the committed fixed-window sample,
# restricted to days with both windows usable and a DefiLlama reference value: the day with the highest reference
# volume, the 2026 day closest to the 2026 median, and the 2025 day closest to the 2025 median.
INTRADAY_SELECTION_RULE = ("sampled days with both fixed windows usable and a DefiLlama reference; pick the highest-volume day, "
                           "the day closest to the 2026 median and the day closest to the 2025 median; declared before fetching")


def intraday_plan(days: list[str], blocks_per_window: int = 50, hours: tuple[int, ...] = INTRADAY_HOURS, plan_path: Path | None = None) -> list[dict]:
    """One window per hour for each selected day. Hours already planned in sample_plan.json reuse their start heights."""
    plan_path = INTRADAY_PLAN if plan_path is None else plan_path
    known = {}
    if (BLOCKS / "sample_plan.json").exists():
        for w in json.loads((BLOCKS / "sample_plan.json").read_text()):
            known[(w["day"], int(w["hour"]))] = int(w["start_height"])
    out = []
    if plan_path.exists():
        out = json.loads(plan_path.read_text())
    have = {(w["day"], int(w["hour"])) for w in out}
    todo = [(d, h) for d in days for h in hours if (d, h) not in have]
    if not todo:
        return out
    top = latest_height()
    for day, hr in todo:
        if (day, hr) in known:
            h = known[(day, hr)]
        else:
            ts = int(datetime.fromisoformat(day).replace(hour=hr, tzinfo=timezone.utc).timestamp() * 1e9)
            anchors = [v for (d, _), v in known.items() if d == day] or [v for v in known.values()]
            h = find_height_fast(ts, min(anchors) if anchors else 130_000_000, top)
        out.append({"day": day, "hour": hr, "start_height": h, "n": blocks_per_window})
        plan_path.write_text(json.dumps(sorted(out, key=lambda w: (w["day"], w["hour"])), indent=1))
        print(f"  intraday window {day} {hr:02d}:00 -> height {h}", flush=True)
    return sorted(out, key=lambda w: (w["day"], w["hour"]))


def run_intraday(days: list[str] | None = None, blocks_per_window: int = 50, workers: int = 2, offline: bool = False, *,
                 plan_path: Path | None = None, events_path: Path | None = None, manifest_path: Path | None = None, selection_rule: str | None = None) -> dict:
    """Fetch every hourly window of the selected days (resumable through the shared block cache) and write
    data/blocks/intraday_events.csv plus intraday_manifest.json. Acquisition only: no reconciliation happens here."""
    plan_path = INTRADAY_PLAN if plan_path is None else plan_path
    events_path = INTRADAY_EVENTS if events_path is None else events_path
    manifest_path = INTRADAY_MANIFEST if manifest_path is None else manifest_path
    selection_rule = INTRADAY_SELECTION_RULE if selection_rule is None else selection_rule
    BLOCKS.mkdir(parents=True, exist_ok=True)
    if days is None:
        if not plan_path.exists():
            raise ValueError("No intraday plan; pass --days")
        days = sorted({w["day"] for w in json.loads(plan_path.read_text())})
    if offline and not plan_path.exists():
        raise ValueError("Offline intraday extraction requires an existing intraday plan")
    P = intraday_plan(days, blocks_per_window, plan_path=plan_path) if not offline else [w for w in json.loads(plan_path.read_text()) if w["day"] in set(days)]
    P = [w for w in P if w["day"] in set(days)]
    heights = [(i, w["start_height"] + j) for i, w in enumerate(P) for j in range(blocks_per_window)]
    if offline:
        heights = [(i, h) for i, h in heights if (CACHE / f"{h}.json").exists()]
    print(f"intraday: {len(P)} windows over {len(days)} days, {len(heights)} blocks" + (" (offline)" if offline else ""), flush=True)
    t0 = time.time(); fetched: dict[int, int] = {}; missing = 0; done = 0
    tmp = events_path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="") as fe:
        we = csv.writer(fe)
        we.writerow(["block_date", "block_timestamp", "receipt_id", "caller", "log", "window_day", "window_hour", "block_height", "execution_status"])
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(fetch_block, h, offline=offline): (i, h) for i, h in heights}
            for f in as_completed(futs):
                i, h = futs[f]; w = P[i]
                b = f.result(); done += 1
                if b is None:
                    missing += 1
                else:
                    fetched[i] = fetched.get(i, 0) + 1
                    day = datetime.fromtimestamp(b["ts"] / 1e9, tz=timezone.utc).strftime("%Y-%m-%d")
                    for rid, pred, log, status in b["events"]:
                        we.writerow([day, b["ts"], rid, pred, log, w["day"], w["hour"], b["height"], status])
                if done % 100 == 0:
                    el = time.time() - t0
                    print(f"  {done}/{len(heights)} blocks, {missing} missing, {el:,.0f}s, rate {_rate[0]:.2f}/s, eta {(len(heights) - done) / max(done / el, 1e-9) / 60:,.0f} min", flush=True)
    tmp.replace(events_path)
    wins = [dict(w, fetched=fetched.get(i, 0), usable=fetched.get(i, 0) >= min_usable(blocks_per_window)) for i, w in enumerate(P)]
    man = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": NEARDATA, "days": sorted(set(days)),
           "hours": list(INTRADAY_HOURS), "blocks_per_window": blocks_per_window, "selection_rule": selection_rule,
           "windows": wins, "blocks_requested": len(P) * blocks_per_window, "blocks_fetched": sum(fetched.values()), "blocks_missing": missing,
           "complete": sum(fetched.values()) + missing >= len(P) * blocks_per_window}
    manifest_path.write_text(json.dumps(man, indent=1))
    print(f"intraday done: {man['blocks_fetched']} blocks in {time.time() - t0:,.0f}s (complete={man['complete']})")
    return man


# ---------------------------------------------------------------------------------------------------------------------
# Validation days for the intraday correction. Declared 2026-11-07, after the three motivating days were measured and
# before any validation block was fetched. Selection is by position in the chronological list, not by volume, so the
# validation days are not chosen for being large or typical; aggregation and the acceptance range are fixed here.
INTRADAY_VALIDATION_PLAN = BLOCKS / "intraday_validation_plan.json"
INTRADAY_VALIDATION_EVENTS = BLOCKS / "intraday_validation_events.csv"
INTRADAY_VALIDATION_MANIFEST = BLOCKS / "intraday_validation_manifest.json"
INTRADAY_VALIDATION_RULE = {
    "declared": "2026-11-07, after the motivating days were measured and before any validation block was fetched",
    "selection": ("sampled days with both fixed windows usable and a DefiLlama reference, excluding the three motivating days, "
                  "sorted chronologically; take the days at positions floor(n/4), floor(n/2) and floor(3n/4)"),
    "aggregation": "median of the per-day fixed-window bias factors over the validation days",
    "acceptance": ("the motivating median is considered supported if the validation median lies within x0.5 to x2 of it; "
                   "the range reflects the day-level dispersion already observed on the motivating days (2.0 to 7.7)"),
    "not_a_correction_of_the_estimator": "the declared estimator stays uncorrected; the factor is published as a sensitivity in either outcome",
}


def intraday_validation_days(motivating: list[str]) -> list[str]:
    """Apply INTRADAY_VALIDATION_RULE to the committed sample (days with both fixed windows usable and a reference)."""
    from .reconcile import _reference_days
    cands = sorted(d for d in _reference_days() if d not in set(motivating))
    n = len(cands)
    if n < 3:
        return cands
    return [cands[n // 4], cands[n // 2], cands[3 * n // 4]]


def run_intraday_validation(blocks_per_window: int = 50, workers: int = 2, offline: bool = False) -> dict:
    """Same acquisition as run_intraday on the validation days, written to separate files so the motivating extract is untouched."""
    import json as _json
    motivating = sorted({w["day"] for w in _json.loads(INTRADAY_PLAN.read_text())}) if INTRADAY_PLAN.exists() else []
    if INTRADAY_VALIDATION_PLAN.exists():
        days = sorted({w["day"] for w in _json.loads(INTRADAY_VALIDATION_PLAN.read_text())})
    else:
        days = intraday_validation_days(motivating)
    print(f"intraday validation days (by position, excluding {motivating}): {days}", flush=True)
    man = run_intraday(days=days, blocks_per_window=blocks_per_window, workers=workers, offline=offline,
                       plan_path=INTRADAY_VALIDATION_PLAN, events_path=INTRADAY_VALIDATION_EVENTS, manifest_path=INTRADAY_VALIDATION_MANIFEST,
                       selection_rule=INTRADAY_VALIDATION_RULE["selection"] + "; " + INTRADAY_VALIDATION_RULE["declared"])
    man["role"] = "validation"; man["rule"] = INTRADAY_VALIDATION_RULE; man["motivating_days"] = motivating
    INTRADAY_VALIDATION_MANIFEST.write_text(_json.dumps(man, indent=1))
    return man


# ---------------------------------------------------------------------------------------------------------------------
# Buyback receipt trace: for a pre-declared sample of inbound NEAR receipts of the buyback multisig, read the block in
# which each receipt executed and record the Intents event that produced it. Declared 2026-11-07 before any block was read.
BUYBACK_TRACE = BLOCKS / "buyback_trace.json"
BUYBACK_TRACE_RULE = {
    "declared": "2026-11-07, before reading any of these blocks",
    "sample": "inbound TRANSFER receipts from intents.near sorted by block timestamp: every 80th receipt starting at the first, plus the five largest by amount",
    "what_is_read": ("the blocks from the originating transaction's block to the block in which the receipt executed (at most 8): dip4 native_withdraw / "
                     "intents_executed and nep245 mt_burn events whose receiver and amount match the receipt, plus any dip4 token_diff event of the same "
                     "Intents account in those blocks"),
    "what_it_establishes": ("the NEAR arrived as a withdrawal from an Intents-side account balance (observed for every sampled receipt); the purchase itself is "
                            "the earlier token_diff of the same account, observed only when it falls inside the blocks read, so purchase attribution for the "
                            "whole inflow remains inferred"),
}
INTENTS_RPC = "https://rpc.mainnet.fastnear.com"


def _view(contract: str, method: str, args: dict) -> object:
    import base64
    body = {"jsonrpc": "2.0", "id": "v", "method": "query", "params": {"request_type": "call_function", "finality": "final", "account_id": contract,
                                                                       "method_name": method, "args_base64": base64.b64encode(json.dumps(args).encode()).decode()}}
    r = requests.post(INTENTS_RPC, json=body, timeout=30, headers=UA)
    r.raise_for_status()
    res = r.json().get("result") or {}
    if "error" in res or "result" not in res:
        return {"error": res.get("error", "no result")}
    return json.loads(bytes(res["result"]))


def buyback_trace_sample(txns: list[dict], wallet: str, every: int = 80, largest: int = 5) -> list[dict]:
    inb = [t for t in txns if t.get("predecessor_account_id") == "intents.near" and t.get("receiver_account_id") == wallet
           and any(a.get("action") == "TRANSFER" and a.get("deposit") for a in t.get("actions") or [])]
    inb.sort(key=lambda t: int(t["block_timestamp"]))
    pick = {t["receipt_id"]: t for t in inb[::every]}
    for t in sorted(inb, key=lambda t: -float(sum(float(a["deposit"]) for a in t["actions"] if a.get("action") == "TRANSFER")))[:largest]:
        pick[t["receipt_id"]] = t
    return sorted(pick.values(), key=lambda t: int(t["block_timestamp"]))


def trace_receipt(t: dict, blocks_read: list[dict]) -> dict:
    """Match one inbound receipt to the Intents events emitted between its transaction block and its execution block (cached extract format)."""
    amount = int(sum(float(a["deposit"]) for a in t["actions"] if a.get("action") == "TRANSFER"))
    events = [e for b in blocks_read for e in b.get("events", [])]
    heights = [b["height"] for b in blocks_read]
    out = {"receipt_id": t["receipt_id"], "transaction_hash": t.get("transaction_hash"), "receipt_block_height": int(t["receipt_block"]["block_height"]),
           "transaction_block_height": int((t.get("block") or {}).get("block_height") or t["receipt_block"]["block_height"]), "blocks_read": heights,
           "block_timestamp": blocks_read[-1]["ts"] if blocks_read else None,
           "amount_yocto": str(amount), "amount_near": amount / 1e24, "block_url": NEARDATA.format(h=heights[0]) if heights else None,
           "withdraw_event": None, "intents_account": None, "mt_burn_token": None, "token_diff_same_block": [], "match": "no matching event in the blocks read"}
    for rid, pred, log, status in events:
        if not log.startswith("EVENT_JSON:"):
            continue
        try:
            ev = json.loads(log[len("EVENT_JSON:"):])
        except ValueError:
            continue
        data = ev.get("data") or []
        if ev.get("event") == "native_withdraw":
            for d in data:
                if d.get("receiver_id") == t["receiver_account_id"] and abs(int(d.get("amount", 0)) - amount) <= 1e18:
                    out.update({"withdraw_event": {"intent_hash": d.get("intent_hash"), "amount": d.get("amount"), "receipt_id_of_execute_intents": rid, "caller": pred},
                                "intents_account": d.get("account_id"), "match": "native_withdraw event with matching receiver and amount",
                                "block_url": NEARDATA.format(h=next((b["height"] for b in blocks_read if any(e[0] == rid for e in b.get("events", []))), heights[0]))})
        elif ev.get("event") == "mt_burn" and out["intents_account"]:
            for d in data:
                if d.get("owner_id") == out["intents_account"] and any(abs(int(x) - amount) <= 1e18 for x in d.get("amounts", [])):
                    out["mt_burn_token"] = (d.get("token_ids") or [None])[0]
    if out["intents_account"]:
        swaps = []
        for rid, pred, log, status in events:
            if '"token_diff"' in log and out["intents_account"] in log:
                out["token_diff_same_block"].append(rid)
                try:
                    for d in json.loads(log[len("EVENT_JSON:"):]).get("data") or []:
                        if d.get("account_id") == out["intents_account"]:
                            diff = {k: int(v) for k, v in (d.get("diff") or {}).items()}
                            swaps.append({"receipt_id": rid, "sold": sorted(k for k, v in diff.items() if v < 0), "bought": sorted(k for k, v in diff.items() if v > 0)})
                except (ValueError, TypeError):
                    pass
        out["swap_observed"] = swaps
    return out


def run_buyback_trace(offline: bool = False) -> dict:
    from .http import load_raw
    raw = load_raw("nearblocks_buybacks_txns")
    wallet = raw["data"]["wallet"]
    sample = buyback_trace_sample(raw["data"]["txns"], wallet)
    print(f"buyback trace: {len(sample)} receipts of {sum(1 for t in raw['data']['txns'] if t.get('predecessor_account_id') == 'intents.near')} inbound from intents.near", flush=True)
    rows, missing = [], 0
    for i, t in enumerate(sample, 1):
        h_end = int(t["receipt_block"]["block_height"])
        h_start = int((t.get("block") or {}).get("block_height") or h_end)
        h_start = max(h_start, h_end - 7)
        read = []
        for h in range(h_start, h_end + 1):
            b = fetch_block(h, offline=offline)
            if b is None:
                missing += 1
            else:
                read.append(b)
        rows.append(trace_receipt(t, read) if read else {"receipt_id": t["receipt_id"], "receipt_block_height": h_end, "match": "blocks not available"})
        if i % 10 == 0:
            print(f"  {i}/{len(sample)} receipts, {missing} blocks missing", flush=True)
    accounts = sorted({r["intents_account"] for r in rows if r.get("intents_account")})
    balances = {}
    if not offline:
        for acc in accounts:
            try:
                res = _view("intents.near", "mt_tokens_for_owner", {"account_id": acc})
                balances[acc] = {"token_ids_held": len(res), "holds_wrap_near": any(x.get("token_id") == "nep141:wrap.near" for x in res)} if isinstance(res, list) else res
            except (requests.RequestException, ValueError) as e:
                balances[acc] = {"error": str(e)}
    out = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": NEARDATA, "rule": BUYBACK_TRACE_RULE, "wallet": wallet,
           "receipts_in_snapshot_from_intents_near": sum(1 for t in raw["data"]["txns"] if t.get("predecessor_account_id") == "intents.near"),
           "sampled": len(sample), "blocks_missing": missing,
           "matched_native_withdraw": sum(1 for r in rows if r.get("withdraw_event")),
           "with_token_diff_in_same_block": sum(1 for r in rows if r.get("token_diff_same_block")),
           "with_wrap_near_bought_in_same_block": sum(1 for r in rows if any("nep141:wrap.near" in sw.get("bought", []) for sw in r.get("swap_observed") or [])),
           "distinct_intents_accounts": len(accounts),
           "intents_accounts": accounts, "intents_side_balances_at_fetch": balances, "receipts": rows}
    BUYBACK_TRACE.write_text(json.dumps(out, indent=1))
    print(f"buyback trace done: {out['matched_native_withdraw']}/{len(sample)} matched native_withdraw, accounts {accounts}")
    return out


BUYBACK_TRACE_EXTENSION = BLOCKS / "buyback_trace_extension.json"
BUYBACK_TRACE_EXTENSION_RULE = {
    "declared": "2026-11-07, after the first trace was published and before any additional block was read",
    "population": "the sampled receipts whose Intents account had no token_diff in the blocks between the originating transaction and the receipt",
    "search": "read the blocks immediately before the originating transaction block, newest first, up to 40 blocks (about 45 seconds), and stop at the "
              "first block that carries a token_diff event of that Intents account",
    "what_it_establishes": ("whether the funding swap of the withdrawal is visible shortly before it; a swap found this way is an observed exchange of the "
                            "same Intents-side account, not proof that the withdrawn NEAR was bought with those exact proceeds; the origin of the sold asset "
                            "(bridge deposit, earlier swap) is not traced"),
}


def _account_token_diffs(block: dict, account: str) -> list[dict]:
    found = []
    for rid, pred, log, status in block.get("events", []):
        if '"token_diff"' not in log or account not in log or not log.startswith("EVENT_JSON:"):
            continue
        try:
            data = json.loads(log[len("EVENT_JSON:"):]).get("data") or []
        except ValueError:
            continue
        for d in data:
            if d.get("account_id") == account:
                diff = {k: int(v) for k, v in (d.get("diff") or {}).items()}
                found.append({"receipt_id": rid, "block_height": block["height"], "status": status,
                              "sold": sorted(k for k, v in diff.items() if v < 0), "bought": sorted(k for k, v in diff.items() if v > 0)})
    return found


def run_buyback_trace_extension(back: int = 40, offline: bool = False) -> dict:
    """Second, pre-declared pass over the traced sample: look for the funding swap in the blocks just before the withdrawal."""
    trace = json.loads(BUYBACK_TRACE.read_text())
    todo = [r for r in trace["receipts"] if r.get("intents_account") and not r.get("token_diff_same_block")]
    print(f"buyback trace extension: {len(todo)} receipts without a same-range token_diff; reading up to {back} blocks before each", flush=True)
    rows, missing, blocks_read = [], 0, 0
    for i, r in enumerate(todo, 1):
        acc, start = r["intents_account"], int(r["transaction_block_height"])
        found, scanned = [], []
        for h in range(start - 1, start - back - 1, -1):
            b = fetch_block(h, offline=offline)
            blocks_read += 1
            if b is None:
                missing += 1
                continue
            scanned.append(h)
            found = _account_token_diffs(b, acc)
            if found:
                break
        rows.append({"receipt_id": r["receipt_id"], "intents_account": acc, "transaction_block_height": start, "blocks_scanned_back": len(scanned),
                     "earliest_block_scanned": min(scanned) if scanned else None,
                     "swap_found": bool(found), "blocks_before_withdrawal": (start - found[0]["block_height"]) if found else None,
                     "swap": found[0] if found else None,
                     "wrap_near_bought": bool(found and "nep141:wrap.near" in found[0]["bought"]),
                     "block_url": NEARDATA.format(h=found[0]["block_height"]) if found else None})
        print(f"  {i}/{len(todo)} receipts, {blocks_read} blocks read, {missing} missing, {sum(1 for x in rows if x['swap_found'])} swaps found", flush=True)
    out = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": NEARDATA, "rule": BUYBACK_TRACE_EXTENSION_RULE,
           "blocks_back": back, "receipts_searched": len(todo), "blocks_read": blocks_read, "blocks_missing": missing,
           "swap_found": sum(1 for x in rows if x["swap_found"]), "wrap_near_bought": sum(1 for x in rows if x["wrap_near_bought"]),
           "distance_blocks": sorted(x["blocks_before_withdrawal"] for x in rows if x["swap_found"]),
           "first_pass_with_swap_in_range": int(trace.get("with_token_diff_in_same_block", 0)), "sampled": int(trace.get("sampled", 0)),
           "receipts": rows}
    BUYBACK_TRACE_EXTENSION.write_text(json.dumps(out, indent=1))
    print(f"buyback trace extension: {out['swap_found']}/{len(todo)} funding swaps found within {back} blocks -> {BUYBACK_TRACE_EXTENSION}", flush=True)
    return out


INTRADAY_SIGNERS = BLOCKS / "intraday_signers.csv"


def write_intraday_signers(offline: bool = True) -> pd.DataFrame:
    """Per (day, hour, signer) activity inside every hourly window of the six intraday days, from the cached blocks.

    Acquisition artifact for the QAA inclusion measurement: the same observation design as the main sample (50-block
    windows), but 24 windows per day instead of the two fixed ones, so the fixed-window inclusion of accounts can be measured."""
    import pandas as pd
    rows = []
    for man_path in (INTRADAY_MANIFEST, INTRADAY_VALIDATION_MANIFEST):
        man = json.loads(man_path.read_text())
        for w in man["windows"]:
            if not w.get("usable"):
                continue
            agg: dict[str, dict] = {}
            for h in range(w["start_height"], w["start_height"] + w["n"]):
                b = fetch_block(h, offline=offline)
                if b is None:
                    continue
                for signer, receiver, kind, method, deposit in b.get("txs", []):
                    a = agg.setdefault(signer, {"txns": 0, "receivers": set(), "methods": set(), "function_calls": 0, "transfers": 0, "self_txns": 0, "intents_actions": 0, "blocks": set()})
                    a["txns"] += 1; a["receivers"].add(receiver); a["blocks"].add(h)
                    if method: a["methods"].add(method)
                    a["function_calls"] += kind == "FUNCTION_CALL"; a["transfers"] += kind == "TRANSFER"
                    a["self_txns"] += signer == receiver; a["intents_actions"] += receiver == "intents.near"
            for signer, a in agg.items():
                rows.append({"window_day": w["day"], "window_hour": int(w["hour"]), "signer": signer, "txns": a["txns"], "distinct_receivers": len(a["receivers"]),
                             "distinct_methods": len(a["methods"]), "function_calls": a["function_calls"], "transfers": a["transfers"], "self_txns": a["self_txns"],
                             "intents_actions": a["intents_actions"], "blocks_active": len(a["blocks"])})
    df = pd.DataFrame(rows).sort_values(["window_day", "window_hour", "signer"]).reset_index(drop=True)
    df.to_csv(INTRADAY_SIGNERS, index=False)
    print(f"intraday signers: {len(df):,} (day, hour, signer) rows over {df['window_day'].nunique()} days -> {INTRADAY_SIGNERS}", flush=True)
    return df
