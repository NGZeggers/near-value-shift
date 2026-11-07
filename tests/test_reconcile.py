import pytest
"""Reconciliation artifacts: economic unit, per-day table, holdout split, trace examples and intraday comparison."""
import json

import numpy as np
import pandas as pd

from near_thesis import intents, reconcile


def _legs():
    rows = [
        # receipt r1: alice sells 100 USDC for NEAR, mm takes the other side (fully priced)
        ("2026-03-01", "r1", "alice", "a1", "usdc", -100_000_000), ("2026-03-01", "r1", "alice", "a1", "near", 25 * 10**24),
        ("2026-03-01", "r1", "mm", "m1", "usdc", 100_000_000), ("2026-03-01", "r1", "mm", "m1", "near", -25 * 10**24),
        # receipt r2: bob pays 40 USDC for an unpriced asset; carol pays 60 USDC; mm receives both
        ("2026-03-01", "r2", "bob", "b1", "usdc", -40_000_000), ("2026-03-01", "r2", "bob", "b1", "zzz", 7),
        ("2026-03-01", "r2", "carol", "c1", "usdc", -60_000_000), ("2026-03-01", "r2", "carol", "c1", "zzz", 9),
        ("2026-03-01", "r2", "mm", "m2", "usdc", 100_000_000), ("2026-03-01", "r2", "mm", "m2", "zzz", -16),
        # receipt r3: both legs unpriced
        ("2026-03-02", "r3", "dave", "d1", "zzz", -5), ("2026-03-02", "r3", "dave", "d1", "yyy", 5),
        ("2026-03-02", "r3", "mm", "m3", "zzz", 5), ("2026-03-02", "r3", "mm", "m3", "yyy", -5),
    ]
    legs = pd.DataFrame(rows, columns=["block_date", "receipt_id", "account", "intent_hash", "token", "amount"])
    legs["block_date"] = pd.to_datetime(legs["block_date"]).dt.date
    return legs


def _price(legs):
    px = {"usdc": lambda a: abs(a) / 1e6, "near": lambda a: abs(a) / 1e24 * 4.0}
    legs["usd"] = [px[t](a) if t in px else None for t, a in zip(legs["token"], legs["amount"])]
    legs["intent_key"] = legs["intent_hash"].fillna("legacy")
    legs["direction"] = np.where(legs["amount"] < 0, "out", "in")
    legs["window_hour"] = 3
    legs["block_height"] = 1
    legs["block_timestamp"] = 1
    return legs


def test_batch_values_use_half_gross_and_keep_every_participant():
    legs = _price(_legs())
    bv = reconcile.batch_values(legs)
    assert abs(bv.loc["r1", "half_gross"] - 100.0) < 1e-9          # one swap counted once
    assert abs(bv.loc["r2", "half_gross"] - 100.0) < 1e-9          # 40 + 60 from users, 100 from mm, halved
    assert "r3" not in bv.index                                      # nothing priced
    assert abs(bv["gross"].sum() - 2 * bv["half_gross"].sum()) < 1e-9


def test_valuation_component_counts_unvalued_account_intents_not_unpriced_legs():
    legs = _price(_legs())
    v = reconcile.valuation_component(legs)
    assert v["legs_unpriced"] == 7 and v["account_intents"] == 7
    assert v["account_intents_without_any_priced_side"] == 2 and v["batches_with_unvalued_account_intent"] == 1
    check = v["two_sided_pricing_check"]
    assert check["account_intents_two_sided"] == 2 and abs(check["in_over_out"]["p50"] - 1.0) < 1e-9


def test_route_component_reports_definitional_bounds_and_dust():
    legs = _price(_legs())
    roles = pd.DataFrame({"block_date": [legs["block_date"].iloc[0]] * 2, "account": ["mm", "alice"], "is_solver": [True, False]})
    r = reconcile.route_component(legs, roles)
    alt = r["alternative_definitions_total_usd"]
    assert abs(alt["full_gross_participant_notional"] - 2 * alt["half_gross_participant_notional"]) < 1e-9
    assert abs(alt["user_side_notional_heuristic_roles"] - 200.0) < 1e-9
    assert r["per_token_net_relative_to_gross"]["p99"] == 0.0        # synthetic receipts balance exactly
    assert r["accounts_per_batch"] == {2: 2, 3: 1}


def test_holdout_split_alternates_days_and_applies_declared_tolerance():
    days = pd.date_range("2026-01-01", periods=6, freq="D")
    table = pd.DataFrame({"date": [str(d.date()) for d in days], "volume_expanded_usd": [90, 100, 110, 95, 105, 100.0],
                          "reference_usd": [100.0] * 6, "holdout_role": ["calibration", "validation"] * 3})
    h = reconcile.holdout(table)
    assert h["calibration"]["days"] == 3 and h["validation"]["days"] == 3
    assert h["validation"]["within_tolerance"] is True
    table["volume_expanded_usd"] *= 0.25
    h2 = reconcile.holdout(table)
    assert h2["validation"]["within_tolerance"] is False and "outside" in h2["verdict"]
    assert reconcile.TOLERANCE["point_ratio_min"] == 0.8 and reconcile.TOLERANCE["point_ratio_max"] == 1.25


def test_trace_examples_reproduce_batch_volume_from_logs():
    legs = _price(_legs())
    raw = pd.DataFrame({"receipt_id": ["r1", "r2", "r3"], "window_day": ["2026-03-01", "2026-03-01", "2026-03-02"], "window_hour": [3, 3, 15],
                        "block_height": [10, 11, 12], "block_timestamp": [1, 2, 3], "caller": ["relay"] * 3, "execution_status": ["SUCCESS_VALUE"] * 3,
                        "log": ['EVENT_JSON:{"standard":"dip4","event":"token_diff","data":[]}'] * 3})
    ef = pd.Series({pd.Timestamp("2026-03-01").date(): 1000.0, pd.Timestamp("2026-03-02").date(): 1000.0})
    ex = reconcile.trace_examples(legs, raw, ef)
    kinds = {e["kind"]: e for e in ex}
    assert {"simple_two_party_fully_priced", "multi_participant_batch", "unpriced_leg_valued_by_other_side", "account_intent_without_any_price"} <= set(kinds)
    simple = kinds["simple_two_party_fully_priced"]
    assert simple["receipt_id"] == "r1" and abs(simple["batch_volume_usd"] - 100.0) < 1e-9
    assert abs(simple["contribution_to_day_estimate_usd"] - 100_000.0) < 1e-9
    assert sum(a["larger_side_usd"] for a in simple["account_intents"]) / 2 == simple["batch_volume_usd"]
    assert simple["block_url"].endswith("/block/10")


def test_intraday_measures_fixed_window_bias(tmp_path, monkeypatch):
    man = {"days": ["2026-03-01"], "selection_rule": "test", "fetched_at": "x", "blocks_per_window": 10, "complete": True,
           "windows": [{"day": "2026-03-01", "hour": h, "start_height": h * 10, "n": 10, "fetched": 10, "usable": True} for h in range(24)]}
    rows = []
    for h in range(24):
        usd = 10 if h in (3, 15) else 40   # the fixed hours are quiet hours
        log = json.dumps({"standard": "dip4", "event": "token_diff", "data": [
            {"account_id": "u", "intent_hash": f"u{h}", "diff": {"usdc": str(-usd * 10**6), "zzz": "1"}},
            {"account_id": "mm", "intent_hash": f"m{h}", "diff": {"usdc": str(usd * 10**6), "zzz": "-1"}}]})
        rows.append({"block_date": "2026-03-01", "block_timestamp": h, "receipt_id": f"r{h}", "caller": "relay", "log": "EVENT_JSON:" + log,
                     "window_day": "2026-03-01", "window_hour": h, "block_height": h * 10, "execution_status": "SUCCESS_VALUE"})
    (tmp_path / "intraday_events.csv").write_text(pd.DataFrame(rows).to_csv(index=False))
    (tmp_path / "intraday_manifest.json").write_text(json.dumps(man))
    monkeypatch.setattr(reconcile, "INTRADAY_EVENTS", tmp_path / "intraday_events.csv")
    monkeypatch.setattr(reconcile, "INTRADAY_MANIFEST", tmp_path / "intraday_manifest.json")
    monkeypatch.setattr(intents, "_REGISTRY", {"usdc": ("usdc", 6, "usd-coin")})
    day = pd.Timestamp("2026-03-01")
    out = reconcile.intraday({}, pd.Series({day: 24_000.0}), pd.Series({day: 100_000.0}))
    d = out["days"][0]
    assert d["hours_usable"] == 24 and abs(d["fixed_window_bias_factor"] - (22 * 40 + 2 * 10) / 24 / 10) < 1e-9
    assert abs(d["expanded_from_all_hours_usd"] - (22 * 40 + 2 * 10) / 240 * 24_000) < 1e-6
    assert d["ratio_fixed_hours_to_reference"] < d["ratio_all_hours_to_reference"]
    assert out["fixed_window_bias_factor_mean"] > 1 and out["fixed_window_bias_factor_median"] == out["fixed_window_bias_factor_mean"]  # one day
    assert out["aggregate_used_for_correction"] == "median" and abs(out["ratio_all_hours_to_reference_median"] - d["ratio_all_hours_to_reference"]) < 1e-12
    assert d["largest_hour"] == "00" and abs(d["largest_hour_share_of_sampled"] - 40 / (22 * 40 + 2 * 10)) < 1e-12


def test_economic_unit_and_tolerance_are_declared_text():
    assert "half gross participant notional" in reconcile.ECONOMIC_UNIT["our_measure"]
    assert "dune.near.dataset_near_intents_metrics" in reconcile.ECONOMIC_UNIT["reference"]
    assert "before" in reconcile.TOLERANCE["declared"] and "before" in reconcile.HOLDOUT_RULE


def test_intraday_validation_rule_is_declared_and_pending_without_data(tmp_path, monkeypatch):
    from near_thesis import blocks
    rule = blocks.INTRADAY_VALIDATION_RULE
    assert "before any validation block" in rule["declared"] and "position" in rule["selection"] and "median" in rule["aggregation"]
    monkeypatch.setattr(reconcile, "INTRADAY_VALIDATION_EVENTS", tmp_path / "none.csv")
    monkeypatch.setattr(reconcile, "INTRADAY_VALIDATION_MANIFEST", tmp_path / "none.json")
    out = reconcile.intraday_validation({}, pd.Series(dtype=float), pd.Series(dtype=float), {"fixed_window_bias_factor_median": 2.8})
    assert out["status"].startswith("pending") and "within_declared_range" not in out


def test_intraday_validation_days_pick_positions_not_volume(monkeypatch):
    from near_thesis import blocks
    days = [f"2026-01-{d:02d}" for d in range(1, 13)]      # 12 candidate days, motivating ones excluded first
    monkeypatch.setattr(reconcile, "_reference_days", lambda: days + ["2026-02-01"])
    picked = blocks.intraday_validation_days(["2026-02-01"])
    assert picked == [days[3], days[6], days[9]]


def test_intraday_validation_verdict_uses_declared_range(tmp_path, monkeypatch):
    man = {"days": ["2026-03-01"], "selection_rule": "test", "fetched_at": "x", "blocks_per_window": 10, "complete": True,
           "windows": [{"day": "2026-03-01", "hour": h, "start_height": h * 10, "n": 10, "fetched": 10, "usable": True} for h in range(24)]}
    rows = []
    for h in range(24):
        usd = 10 if h in (3, 15) else 30
        log = json.dumps({"standard": "dip4", "event": "token_diff", "data": [
            {"account_id": "u", "intent_hash": f"u{h}", "diff": {"usdc": str(-usd * 10**6), "zzz": "1"}},
            {"account_id": "mm", "intent_hash": f"m{h}", "diff": {"usdc": str(usd * 10**6), "zzz": "-1"}}]})
        rows.append({"block_date": "2026-03-01", "block_timestamp": h, "receipt_id": f"r{h}", "caller": "relay", "log": "EVENT_JSON:" + log,
                     "window_day": "2026-03-01", "window_hour": h, "block_height": h * 10, "execution_status": "SUCCESS_VALUE"})
    (tmp_path / "v.csv").write_text(pd.DataFrame(rows).to_csv(index=False))
    (tmp_path / "v.json").write_text(json.dumps(man))
    monkeypatch.setattr(reconcile, "INTRADAY_VALIDATION_EVENTS", tmp_path / "v.csv")
    monkeypatch.setattr(reconcile, "INTRADAY_VALIDATION_MANIFEST", tmp_path / "v.json")
    monkeypatch.setattr(intents, "_REGISTRY", {"usdc": ("usdc", 6, "usd-coin")})
    day = pd.Timestamp("2026-03-01")
    factor = (22 * 30 + 2 * 10) / 24 / 10
    out = reconcile.intraday_validation({}, pd.Series({day: 24_000.0}), pd.Series({day: 100_000.0}), {"fixed_window_bias_factor_median": factor})
    assert out["within_declared_range"] is True and "reproduce" in out["verdict"]
    out2 = reconcile.intraday_validation({}, pd.Series({day: 24_000.0}), pd.Series({day: 100_000.0}), {"fixed_window_bias_factor_median": factor * 3})
    assert out2["within_declared_range"] is False and "not supported" in out2["verdict"]


def test_intraday_validation_treats_zero_fixed_window_day_as_unbounded(tmp_path, monkeypatch):
    """A day whose fixed windows observe nothing has an unbounded factor; the verdict must hold with it treated as infinite."""
    days = ["2026-03-01", "2026-03-02", "2026-03-03"]
    man = {"days": days, "selection_rule": "test", "fetched_at": "x", "blocks_per_window": 10, "complete": True,
           "windows": [{"day": d, "hour": h, "start_height": (i * 24 + h) * 10, "n": 10, "fetched": 10, "usable": True}
                       for i, d in enumerate(days) for h in range(24)]}
    rows = []
    for i, d in enumerate(days):
        for h in range(24):
            usd = 10 if h in (3, 15) else 30
            if d == "2026-03-03" and h in (3, 15):
                continue  # fixed windows observed no volume at all on the third day
            log = json.dumps({"standard": "dip4", "event": "token_diff", "data": [
                {"account_id": "u", "intent_hash": f"u{i}{h}", "diff": {"usdc": str(-usd * 10**6), "zzz": "1"}},
                {"account_id": "mm", "intent_hash": f"m{i}{h}", "diff": {"usdc": str(usd * 10**6), "zzz": "-1"}}]})
            rows.append({"block_date": d, "block_timestamp": h, "receipt_id": f"r{i}{h}", "caller": "relay", "log": "EVENT_JSON:" + log,
                         "window_day": d, "window_hour": h, "block_height": (i * 24 + h) * 10, "execution_status": "SUCCESS_VALUE"})
    (tmp_path / "v.csv").write_text(pd.DataFrame(rows).to_csv(index=False))
    (tmp_path / "v.json").write_text(json.dumps(man))
    monkeypatch.setattr(reconcile, "INTRADAY_VALIDATION_EVENTS", tmp_path / "v.csv")
    monkeypatch.setattr(reconcile, "INTRADAY_VALIDATION_MANIFEST", tmp_path / "v.json")
    monkeypatch.setattr(intents, "_REGISTRY", {"usdc": ("usdc", 6, "usd-coin")})
    bpd = pd.Series({pd.Timestamp(d): 24_000.0 for d in days})
    ref = pd.Series({pd.Timestamp(d): 100_000.0 for d in days})
    factor = (22 * 30 + 2 * 10) / 24 / 10
    out = reconcile.intraday_validation({}, bpd, ref, {"fixed_window_bias_factor_median": factor})
    assert out["days_with_defined_factor"] == 2 and out["days_with_unbounded_factor"] == ["2026-03-03"]
    assert out["validation_median_factor"] == pytest.approx(factor)
    assert out["validation_median_factor_unbounded_as_infinite"] == pytest.approx(factor)  # median of [f, f, inf]
    assert out["within_declared_range"] is True and "unbounded" in out["verdict"]
    # With only one defined day the conservative median is infinite and the verdict cannot pass.
    rows2 = [r for r in rows if r["window_day"] != "2026-03-01"]
    man["days"] = days[1:]
    (tmp_path / "v.csv").write_text(pd.DataFrame(rows2).to_csv(index=False))
    (tmp_path / "v.json").write_text(json.dumps(man))
    out2 = reconcile.intraday_validation({}, bpd, ref, {"fixed_window_bias_factor_median": factor})
    assert out2["within_declared_range"] is False


def test_reference_definition_declares_confidential_component_as_estimate():
    rd = reconcile.REFERENCE_DEFINITION
    share = rd["confidential_intents"]["share_of_dune_total"]
    c = rd["confidential_intents"]["cumulative_usd_billion"]
    assert share == pytest.approx(c["confidential"] / c["dune_total"]) and 0.05 < share < 0.1
    assert rd["confidential_intents"]["kind"].startswith("estimate") and "both readings" in rd["one_or_two_sided"]
    assert "Dune" in reconcile.ECONOMIC_UNIT["shared_origin"] and "independent" in reconcile.ECONOMIC_UNIT["shared_origin"]
    out = reconcile.MODELS / "intents_reconciliation.json"
    if out.exists():
        res = json.loads(out.read_text())["components"]["residual"]
        assert res["after_confidential_intents_exclusion"] == pytest.approx(res["pooled_ratio"] / (1 - share))
        assert res["after_confidential_and_intraday"] == pytest.approx(res["after_intraday_bias_correction"] / (1 - share))
