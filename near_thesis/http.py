"""HTTP fetch with retries and raw snapshotting.

Every external pull is written to data/raw/<name>.json as {fetched_at, source, data}.
Downstream layers read ONLY these snapshots, so `make features ... site` is fully offline
and reproducible, and the snapshots can be hashed for the reproducibility report.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

import requests

from .config import RAW

UA = "near-thesis/0.1 (NEAR Hackathon 2026; research pipeline)"


def fetch_json(url: str, *, retries: int = 3, timeout: int = 60, headers: dict | None = None,
               method: str = "GET", json_body: Any = None) -> Any:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.request(method, url, timeout=timeout, json=json_body,
                                 headers={"user-agent": UA, "accept": "application/json", **(headers or {})})
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            last = e
            status = getattr(e.response, "status_code", None)
            if status is not None and status < 500 and status != 429:
                raise
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
        time.sleep(1.5 * attempt)
    assert last is not None
    raise last


def save_raw(name: str, source: str, data: Any, note: str | None = None) -> dict:
    payload = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "source": source, "note": note, "data": data}
    path = RAW / f"{name}.json"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"  saved {path.relative_to(RAW.parents[1])} ({path.stat().st_size / 1024:,.0f} KB)")
    return payload


def load_raw(name: str, *, optional: bool = False) -> dict | None:
    path = RAW / f"{name}.json"
    if not path.exists():
        if optional:
            return None
        raise FileNotFoundError(f"missing {path}. Run `make fetch` first.")
    return json.loads(path.read_text())


def raw_manifest() -> list[dict]:
    """SHA-256 and metadata for every snapshot, for the reproducibility report."""
    out = []
    for p in sorted(RAW.glob("*.json")):
        meta = json.loads(p.read_text())
        out.append({"file": p.name, "fetched_at": meta.get("fetched_at"), "source": meta.get("source"),
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size})
    return out
