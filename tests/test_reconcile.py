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


def test_systematic_day_estimate_and_design_error(tmp_path, monkeypatch):
    """Mean per sampled block x blocks in the day; successive-difference standard error; pending without data."""
    assert reconcile.systematic_day({}, pd.Series(dtype=float), events=tmp_path / "no.csv", manifest=tmp_path / "no.json")["status"].startswith("pending")
    day = "2025-11-14"
    heights = list(range(1000, 1000 + 40 * 10, 40))
    rows = []
    for i, h in enumerate(heights):
        if i % 2 == 0:                       # half the blocks carry one 100-USDC swap
            log = json.dumps({"standard": "dip4", "event": "token_diff", "data": [
                {"account_id": "u", "intent_hash": f"u{i}", "diff": {"usdc": str(-100 * 10**6), "zzz": "1"}},
                {"account_id": "mm", "intent_hash": f"m{i}", "diff": {"usdc": str(100 * 10**6), "zzz": "-1"}}]})
            rows.append({"block_date": day, "block_timestamp": i, "receipt_id": f"r{i}", "caller": "relay", "log": "EVENT_JSON:" + log,
                         "window_day": day, "window_hour": i % 24, "block_height": h, "execution_status": "SUCCESS_VALUE"})
    (tmp_path / "e.csv").write_text(pd.DataFrame(rows).to_csv(index=False))
    man = {"day": day, "step": 40, "offset": 0, "blocks_in_day": 400, "blocks_requested": 10, "blocks_fetched": 10, "blocks_missing": 0, "complete": True,
           "heights_sampled": heights, "heights_without_block": [], "fetch_failed": 0, "fetched_at": "x"}
    (tmp_path / "m.json").write_text(json.dumps(man))
    monkeypatch.setattr(intents, "_REGISTRY", {"usdc": ("usdc", 6, "usd-coin")})
    ref = pd.Series({pd.Timestamp(day): 20_000.0})
    out = reconcile.systematic_day({}, ref, events=tmp_path / "e.csv", manifest=tmp_path / "m.json",
                                   intraday_days=[{"day": day, "ratio_fixed_hours_to_reference": 0.3, "ratio_all_hours_to_reference": 0.4, "blocks_observed": 1200}],
                                   diagnostic_events=tmp_path / "none.csv", diagnostic_manifest=tmp_path / "none.json", simulate=False)
    assert out["sampled_usd"] == pytest.approx(500.0) and out["estimate_usd"] == pytest.approx(500 / 10 * 400)   # 20,000 = the reference
    assert out["ratio_to_reference"] == pytest.approx(1.0) and out["reference_inside_ci95"] is True
    sd = np.sqrt(sum(100.0**2 for _ in range(9)) / (2 * 9))          # alternating 100/0: every successive difference is 100
    assert out["standard_error_usd"] == pytest.approx(sd / np.sqrt(10) * np.sqrt(1 - 10 / 400) * 400)
    assert out["same_day_other_designs"]["two_fixed_windows_ratio"] == 0.3 and "includes parity" in out["reading"]
    assert out["ratio_ci95_bootstrap"][0] <= 1.0 <= out["ratio_ci95_bootstrap"][1]
    assert out["coverage_diagnostic"] is None and out["sampling_verdict"].startswith("unchecked") and len(out["assumptions"]) == 4



def _periodic_windows(tmp_path, day, step=40, period=40, n_windows=24, n=50, start=100_000):
    """Hourly windows of consecutive blocks whose volume is 100 USDC only at heights == 1 mod period: a proxy population with a known total."""
    rows, wins = [], []
    for k in range(n_windows):
        h0 = start + k * 5_000
        wins.append({"day": day, "hour": k, "start_height": h0, "n": n, "fetched": n, "usable": True})
        for h in range(h0, h0 + n):
            if h % period == 1:
                log = json.dumps({"standard": "dip4", "event": "token_diff", "data": [
                    {"account_id": "u", "intent_hash": f"u{h}", "diff": {"usdc": str(-100 * 10**6), "zzz": "1"}},
                    {"account_id": "mm", "intent_hash": f"m{h}", "diff": {"usdc": str(100 * 10**6), "zzz": "-1"}}]})
                rows.append({"block_date": day, "block_timestamp": h, "receipt_id": f"r{h}", "caller": "relay", "log": "EVENT_JSON:" + log,
                             "window_day": day, "window_hour": k, "block_height": h, "execution_status": "SUCCESS_VALUE"})
    (tmp_path / "w.csv").write_text(pd.DataFrame(rows).to_csv(index=False))
    (tmp_path / "w.json").write_text(json.dumps({"days": [day], "windows": wins}))
    return tmp_path / "w.csv", tmp_path / "w.json"


def test_systematic_day_adversarial_periodic_pattern_is_inconclusive(tmp_path, monkeypatch):
    """The auditor's case: volume only at heights == 1 mod 40, phase 0. The estimate is 0 with zero error; the verdict must not attribute the gap."""
    monkeypatch.setattr(intents, "_REGISTRY", {"usdc": ("usdc", 6, "usd-coin")})
    day = "2025-11-14"
    heights = list(range(0, 4000, 40))                                   # phase 0 never meets a volume block
    (tmp_path / "e.csv").write_text(pd.DataFrame(columns=["block_date", "block_timestamp", "receipt_id", "caller", "log", "window_day", "window_hour", "block_height", "execution_status"]).to_csv(index=False))
    man = {"day": day, "step": 40, "offset": 0, "blocks_in_day": 4000, "blocks_requested": 100, "blocks_fetched": 100, "blocks_missing": 0, "complete": True,
           "heights_sampled": heights, "heights_without_block": [], "fetch_failed": 0, "fetched_at": "x"}
    (tmp_path / "m.json").write_text(json.dumps(man))
    ev, mf = _periodic_windows(tmp_path, day)
    out = reconcile.systematic_day({}, pd.Series({pd.Timestamp(day): 10_000.0}), events=tmp_path / "e.csv", manifest=tmp_path / "m.json",
                                   diagnostic_events=ev, diagnostic_manifest=mf, simulate=False)
    assert out["estimate_usd"] == 0 and out["ratio_ci95"] == [0.0, 0.0]
    assert out["sampling_verdict"].startswith("inconclusive") and "not attributed" in out["reading"]
    dg = out["coverage_diagnostic"]
    assert dg["supported"] is False and (dg["ratio_true_sd_to_estimated_se"] is None or dg["ratio_true_sd_to_estimated_se"] > 1.5)
    assert dg["estimated_error_zero_while_phases_disagree"] is True             # phase 1 sees everything, the others nothing, every SE is zero
    assert "40" in dg["autocorrelation_flagged_at_step_or_divisors"] or dg["normal_interval_coverage"] < 0.8


def test_systematic_coverage_diagnostic_supports_an_unstructured_population(tmp_path, monkeypatch):
    monkeypatch.setattr(intents, "_REGISTRY", {"usdc": ("usdc", 6, "usd-coin")})
    day = "2025-11-14"
    ev, mf = _periodic_windows(tmp_path, day, period=7)                   # a period that is not a divisor of 40, spread across phases
    dg = reconcile.systematic_coverage_diagnostic({}, day, 40, events=ev, manifest=mf)
    assert dg["phases_evaluated"] == 40 and dg["ratio_true_sd_to_estimated_se"] < 1.5 and dg["normal_interval_coverage"] >= 0.8
    assert dg["supported"] is True


def test_systematic_coverage_simulation_fails_only_at_the_step():
    sim = reconcile.systematic_coverage_simulation(step=40, N=140_000, phases=20, seed=1)
    assert sim["periodic_at_step"]["normal_interval_coverage"] == 0 and sim["periodic_at_step"]["bootstrap_coverage"] == 0
    assert sim["concentrated_iid"]["normal_interval_coverage"] >= 0.8 and sim["periodic_off_step"]["normal_interval_coverage"] >= 0.8



def test_systematic_day_unchecked_estimator_never_claims_support(tmp_path, monkeypatch):
    """Both intervals exclude the reference and no proxy population exists: the status is unchecked and the text must not claim support."""
    monkeypatch.setattr(intents, "_REGISTRY", {"usdc": ("usdc", 6, "usd-coin")})
    day = "2025-11-14"
    heights = list(range(1000, 1000 + 40 * 10, 40))
    rows = []
    for i, h in enumerate(heights):
        usd = 100 if i % 2 == 0 else 90                                      # steady volume: a tight interval far from the reference
        log = json.dumps({"standard": "dip4", "event": "token_diff", "data": [
            {"account_id": "u", "intent_hash": f"u{i}", "diff": {"usdc": str(-usd * 10**6), "zzz": "1"}},
            {"account_id": "mm", "intent_hash": f"m{i}", "diff": {"usdc": str(usd * 10**6), "zzz": "-1"}}]})
        rows.append({"block_date": day, "block_timestamp": i, "receipt_id": f"r{i}", "caller": "relay", "log": "EVENT_JSON:" + log,
                     "window_day": day, "window_hour": i % 24, "block_height": h, "execution_status": "SUCCESS_VALUE"})
    (tmp_path / "e.csv").write_text(pd.DataFrame(rows).to_csv(index=False))
    man = {"day": day, "step": 40, "offset": 0, "blocks_in_day": 400, "blocks_requested": 10, "blocks_fetched": 10, "blocks_missing": 0, "complete": True,
           "heights_sampled": heights, "heights_without_block": [], "fetch_failed": 0, "fetched_at": "x"}
    (tmp_path / "m.json").write_text(json.dumps(man))
    out = reconcile.systematic_day({}, pd.Series({pd.Timestamp(day): 100_000.0}), events=tmp_path / "e.csv", manifest=tmp_path / "m.json",
                                   diagnostic_events=tmp_path / "none.csv", diagnostic_manifest=tmp_path / "none.json", simulate=False)
    assert out["reference_inside_ci95"] is False and out["reference_inside_ci95_bootstrap"] is False
    assert out["sampling_verdict"].startswith("unchecked")
    assert "could not be checked" in out["reading"] and "not attributed" in out["reading"] and "diagnostic supports" not in out["reading"]


def test_complete_days_compare_full_volume_with_reference_and_sampled_expansion(tmp_path):
    f = tmp_path / "l2_full_days_valued.csv"
    pd.DataFrame([{"block_date": "2025-05-18", "complete_usd": 300.0, "receipts_valued": 3, "receipts_with_token_diff": 3, "legs": 6, "legs_unpriced": 0},
                  {"block_date": "2025-06-02", "complete_usd": 100.0, "receipts_valued": 1, "receipts_with_token_diff": 1, "legs": 2, "legs_unpriced": 0}]).to_csv(f, index=False)
    table = pd.DataFrame({"date": pd.to_datetime(["2025-05-18", "2025-06-02"]), "volume_expanded_usd": [600.0, 50.0]})
    llama = pd.Series({pd.Timestamp("2025-05-18"): 1000.0, pd.Timestamp("2025-06-02"): 0.0})
    check = {"day": "2025-11-14", "blocks_compared": 10, "sql_over_python_pooled": 1.001, "passes": True}
    out = reconcile.complete_days({}, llama, table, files=[f], check=check)
    d0 = out["days"][0]
    assert d0["ratio_complete_to_reference"] == pytest.approx(0.3) and d0["ratio_sampled_to_complete"] == pytest.approx(2.0)
    assert out["days_with_reference"] == 1 and out["pooled_ratio_complete_to_reference"] == pytest.approx(0.3)
    assert out["sql_valuation_check"]["passes"] is True and "no sampling error remains" in out["reading"] and "reproduces" in out["reading"]
    bad = reconcile.complete_days({}, llama, table, files=[f], check=dict(check, sql_over_python_pooled=3.0, passes=False))
    assert "not confirmed" in bad["reading"]
    assert reconcile.complete_days({}, llama, table, files=[])["status"].startswith("pending")
