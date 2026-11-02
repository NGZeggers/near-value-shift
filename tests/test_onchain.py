import json

from near_thesis import onchain


def test_payload_is_deterministic_and_complete():
    a, b = onchain.payload(), onchain.payload()
    assert a == b
    for k in ["as_of", "month", "active_accounts_daily_mean", "intents_volume_usd", "usd_per_txn", "thesis_sha256", "raw_manifest_sha256", "repo"]:
        assert k in a
    assert len(a["thesis_sha256"]) == 64
    json.dumps(a)  # serialisable


def test_read_index_handles_missing(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"result": {"result": [], "logs": []}}
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: R())
    assert onchain.read_index("nobody.testnet") is None
