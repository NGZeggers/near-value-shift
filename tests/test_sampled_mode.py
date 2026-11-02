import json

import pandas as pd

from near_thesis import blocks as blocks_mod, intents, qaa


def _write_sample(tmp_path):
    blocks = tmp_path / "blocks"; blocks.mkdir()
    rows = []
    ts = 1_740_000_000_000_000_000
    for w, hour in enumerate([3, 15]):
        for i in range(40):
            # a relayer with 40 regular txs per window, a human with one, a .tg farmer with two
            rows.append(["2025-03-01", "2025-03-01", hour, 100 + i, ts + w * 10**12 + i * 10**9, "relayer.near", "intents.near", "FUNCTION_CALL", "execute_intents", "0"])
        rows.append(["2025-03-01", "2025-03-01", hour, 100, ts + w * 10**12, "alice.near", "ref.near", "FUNCTION_CALL", "swap", "1000"])
        rows.append(["2025-03-01", "2025-03-01", hour, 101, ts + w * 10**12, "u1.tg", "game.hot.tg", "FUNCTION_CALL", "claim", "0"])
        rows.append(["2025-03-01", "2025-03-01", hour, 105, ts + w * 10**12 + 5 * 10**9, "u1.tg", "game.hot.tg", "FUNCTION_CALL", "claim", "0"])
    pd.DataFrame(rows, columns=["block_date", "window_day", "window_hour", "block_height", "block_timestamp", "signer", "receiver", "action_kind", "method", "deposit"]).to_csv(blocks / "tx_sampled.csv", index=False)
    (blocks / "sample_manifest.json").write_text(json.dumps({"windows": [{"day": "2025-03-01", "hour": 3, "n": 250}, {"day": "2025-03-01", "hour": 15, "n": 250}]}))
    return blocks


def test_load_sampled_builds_account_month_features(tmp_path, monkeypatch):
    blocks = _write_sample(tmp_path)
    monkeypatch.setattr(qaa, "DATA", tmp_path)
    monkeypatch.setattr(blocks_mod, "BLOCKS", blocks)
    df = qaa.load_sampled()
    assert set(df["account"]) == {"relayer.near", "alice.near", "u1.tg"}
    r = df.set_index("account")
    assert r.loc["relayer.near", "txns"] == 80 and r.loc["relayer.near", "active_days"] == 2
    assert r.loc["relayer.near", "gap_cv"] < 0.2 and r.loc["relayer.near", "intents_actions"] == 80
    assert r.loc["u1.tg", "name_class"] == "tg" and r.loc["alice.near", "name_class"] == "named"
    x = qaa.featurize(df)
    assert x.shape[0] == 3 and not x.isna().any().any()


def test_expansion_factor_uses_blocks_per_day(tmp_path, monkeypatch):
    blocks = _write_sample(tmp_path)
    derived = tmp_path / "derived"; derived.mkdir()
    pd.DataFrame({"date": ["2025-03-01"], "blocks": [150000]}).to_csv(derived / "daily.csv", index=False)
    monkeypatch.setattr(intents, "DATA", tmp_path); monkeypatch.setattr(intents, "DERIVED", derived)
    raw = pd.DataFrame({"window_day": ["2025-03-01"]})
    ef = intents.expansion_factors(raw)
    assert abs(ef[pd.Timestamp("2025-03-01").date()] - 300.0) < 1e-9
