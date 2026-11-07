"""Value bridge (observed/classified/unavailable steps, issuance, scenarios) and the pre-registered out-of-sample test."""
import json

import pytest

import numpy as np
import pandas as pd

from near_thesis import bridge, signal


def _daily(tmp_path):
    idx = pd.date_range("2025-01-01", "2026-11-01", freq="D")
    n = len(idx)
    d = pd.DataFrame({"date": idx, "intents_volume_usd": 1_000_000.0, "intents_fees_usd": 1_000.0, "intents_revenue_usd": 200.0,
                      "intents_holders_revenue_usd": np.where(idx >= "2026-02-23", 200.0, 0.0), "near_price": 2.0, "market_cap_usd": 2.0e9,
                      "circulating_supply": 1.0e9, "total_supply": np.linspace(1.0e9, 1.05e9, n)})
    (tmp_path / "daily.csv").write_text(d.to_csv(index=False))
    return d


def test_bridge_without_wallet_snapshot_marks_purchases_unavailable(tmp_path, monkeypatch):
    _daily(tmp_path)
    monkeypatch.setattr(bridge, "DERIVED", tmp_path)
    monkeypatch.setattr(bridge, "MODELS", tmp_path)
    monkeypatch.setattr(bridge, "load_raw", lambda name, optional=False: None)
    out = bridge.run()
    steps = {s["step"]: s for s in out["steps"]}
    assert "unavailable" in steps[5]["status"] and steps[5]["usd"] is None
    assert steps[2]["share_of_previous"] == 0.001 and abs(steps[3]["share_of_previous"] - 0.2) < 1e-12
    assert out["dilution"]["circulating_supply_field"]["stale_in_source"] is True
    assert out["dilution"]["net_new_total_near"] > 0 and out["dilution"]["buyback_to_issuance_ratio"] is None
    for sc in out["scenarios"].values():
        assert sc["issuance_usd"] > 0 and sc["net_yield_on_mcap"] == (sc["buyback_accrual_usd"] - sc["issuance_usd"]) / 2.0e9
    assert out["scenarios"]["adverse"]["net_yield_on_mcap"] < out["scenarios"]["base"]["net_yield_on_mcap"] < out["scenarios"]["favorable"]["net_yield_on_mcap"]
    assert out["dominant_assumption"]["dominant"] in {"volume", "take_rate", "capture", "allocation", "issuance"}


def test_bridge_counts_only_intents_settled_transfers_as_purchases(tmp_path, monkeypatch):
    _daily(tmp_path)
    monkeypatch.setattr(bridge, "DERIVED", tmp_path)
    monkeypatch.setattr(bridge, "MODELS", tmp_path)
    ts = int(pd.Timestamp("2026-06-01").timestamp()) * 10**9
    txns = [
        {"receipt_id": "a", "predecessor_account_id": "intents.near", "receiver_account_id": bridge.BUYBACK_WALLET, "block_timestamp": str(ts),
         "receipt_outcome": {"status": True}, "actions": [{"action": "TRANSFER", "deposit": 100 * 1e24}]},
        {"receipt_id": "b", "predecessor_account_id": "1csfundsadmin.sputnik-dao.near", "receiver_account_id": bridge.BUYBACK_WALLET, "block_timestamp": str(ts),
         "receipt_outcome": {"status": True}, "actions": [{"action": "TRANSFER", "deposit": 50 * 1e24}]},
        {"receipt_id": "c", "predecessor_account_id": bridge.BUYBACK_WALLET, "receiver_account_id": "x.near", "block_timestamp": str(ts),
         "receipt_outcome": {"status": True}, "actions": [{"action": "TRANSFER", "deposit": 5 * 1e24}]},
        {"receipt_id": "d", "predecessor_account_id": "intents.near", "receiver_account_id": bridge.BUYBACK_WALLET, "block_timestamp": str(ts),
         "receipt_outcome": {"status": False}, "actions": [{"action": "TRANSFER", "deposit": 999 * 1e24}]},
        {"receipt_id": "e", "predecessor_account_id": "intents.near", "receiver_account_id": bridge.BUYBACK_WALLET, "block_timestamp": str(int(pd.Timestamp("2026-11-03").timestamp()) * 10**9),
         "receipt_outcome": {"status": True}, "actions": [{"action": "TRANSFER", "deposit": 777 * 1e24}]},
    ]
    snaps = {"nearblocks_buybacks_txns": {"source": "s", "fetched_at": "t", "data": {"wallet": bridge.BUYBACK_WALLET, "txns": txns}},
             "nearblocks_buybacks_account": {"source": "s", "fetched_at": "t", "data": {"amount": str(int(145 * 1e24)), "created": {"block_timestamp": str(ts)}}}}
    monkeypatch.setattr(bridge, "load_raw", lambda name, optional=False: snaps.get(name))
    out = bridge.run()
    r = out["receipts"]
    assert abs(r["near_in"] - 100) < 1e-9 and abs(r["near_in_from_treasury_wallets"] - 50) < 1e-9 and abs(r["near_out"] - 5) < 1e-9  # failed and post-cutoff receipts excluded
    assert r["usd_in_at_daily_price"] == 200.0
    steps = {s["step"]: s for s in out["steps"]}
    assert steps[5]["near"] == 100 and "observed" in steps[5]["status"]
    assert abs(steps[6]["share_of_previous"] - 145 / 150) < 1e-12
    assert out["dilution"]["buyback_to_issuance_ratio"] == 100 / out["dilution"]["net_new_total_near"]
    monthly = pd.read_csv(tmp_path / "value_bridge_monthly.csv", parse_dates=["month"]).set_index("month")
    assert monthly.loc["2026-06-01", "buyback_wallet_near_in"] == 100


def _weekly(n=320, seed=3, effect=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-07-05", periods=n, freq="W-SUN")
    usage = np.exp(np.cumsum(rng.normal(0, 0.1, n)))
    btc = np.exp(np.cumsum(rng.normal(0, 0.05, n)))
    sig = pd.Series(np.log(pd.Series(usage).rolling(4).mean()).diff(4).to_numpy())
    noise = rng.normal(0, 0.1, n)
    near = np.exp(np.cumsum(effect * sig.shift(12).fillna(0).to_numpy() + np.log(btc).copy() * 0 + noise))
    return pd.DataFrame({"active_accounts": usage, "near_price": near, "price_bitcoin": btc, "price_ethereum": btc}, index=idx)


def test_oos_purges_calibration_targets_and_reports_not_evaluable():
    w = _weekly()
    o = signal.oos_table(w)
    assert o["protocol"]["calibration_end"] == "2025-06-29"
    rows = [r for r in o["tests"] if r["predictor"] == "active_accounts" and r["benchmark"] == "btc"]
    for r in rows:
        if "ic_evaluation_signed" in r:
            gap = (pd.Timestamp(r["evaluation_start"]) - pd.Timestamp(r["calibration_end"])).days
            assert gap > 7 * r["horizon_weeks"]          # purged by at least the horizon
            assert r["frozen_sign"] in (1.0, -1.0) and r["walk_forward_n"] > 0
    short = signal.oos_table(w.iloc[-40:])
    assert all("not evaluable" in r["status"] for r in short["tests"])
    assert short["summary"]["evaluable"] == 0 and "evaluable" in short["summary"]["conclusion"]


def test_oos_fails_a_signal_without_predictive_content():
    o = signal.oos_table(_weekly(effect=0.0))
    assert o["summary"]["passing"] == 0
    assert set(r["kind"] for r in o["tests"]) == {"usage", "naive_benchmark"}


def test_bridge_rejects_missing_or_non_boolean_statuses(tmp_path, monkeypatch):
    """Second audit, point C: an absent or non-boolean status must never count as success."""
    _daily(tmp_path)
    monkeypatch.setattr(bridge, "DERIVED", tmp_path)
    monkeypatch.setattr(bridge, "MODELS", tmp_path)
    monkeypatch.setattr(bridge, "TRACE", tmp_path / "no_trace.json")
    ts = str(int(pd.Timestamp("2026-06-01").timestamp()) * 10**9)
    base = {"predecessor_account_id": "intents.near", "receiver_account_id": bridge.BUYBACK_WALLET, "block_timestamp": ts}
    txns = [
        {**base, "receipt_id": "ok", "receipt_outcome": {"status": True}, "actions": [{"action": "TRANSFER", "deposit": 100 * 1e24}]},
        {**base, "receipt_id": "missing", "actions": [{"action": "TRANSFER", "deposit": 100 * 1e24}]},                           # no receipt_outcome at all
        {**base, "receipt_id": "empty", "receipt_outcome": {}, "actions": [{"action": "TRANSFER", "deposit": 100 * 1e24}]},      # outcome without status
        {**base, "receipt_id": "string", "receipt_outcome": {"status": "true"}, "actions": [{"action": "TRANSFER", "deposit": 100 * 1e24}]},
        {**base, "receipt_id": "one", "receipt_outcome": {"status": 1}, "actions": [{"action": "TRANSFER", "deposit": 100 * 1e24}]},
        {**base, "receipt_id": "dict", "receipt_outcome": {"status": {"SuccessValue": ""}}, "actions": [{"action": "TRANSFER", "deposit": 100 * 1e24}]},
        {**base, "receipt_id": "failed", "receipt_outcome": {"status": False}, "actions": [{"action": "TRANSFER", "deposit": 100 * 1e24}]},
    ]
    snaps = {"nearblocks_buybacks_txns": {"source": "s", "fetched_at": "t", "data": {"wallet": bridge.BUYBACK_WALLET, "txns": txns}},
             "nearblocks_buybacks_account": {"source": "s", "fetched_at": "t", "data": {"amount": str(int(100 * 1e24)), "created": {"block_timestamp": ts}}}}
    monkeypatch.setattr(bridge, "load_raw", lambda name, optional=False: snaps.get(name))
    out = bridge.run()
    r = out["receipts"]
    assert abs(r["near_in"] - 100) < 1e-9                       # only the explicit boolean success counts
    assert r["receipts_excluded"] == {"failed": 1, "missing_or_invalid_status": 5}
    assert bridge.receipt_status(None) == "missing_or_invalid_status" and bridge.receipt_status({"status": True}) == "success"
    led = r["ledger"]
    assert abs(led["reconstructed_balance_at_fetch_near"] - 100) < 1e-9 and abs(led["unexplained_residual_near"]) < 1e-9
    steps = {s["step"]: s for s in out["steps"]}
    assert "inferred" in steps[5]["status"] and "observed" in steps[5]["status"]
    assert "inferred" in steps[6]["status"] and abs(steps[6]["near"] - 100) < 1e-9


def test_bridge_ledger_reconciles_at_cutoff_not_at_fetch(tmp_path, monkeypatch):
    _daily(tmp_path)
    monkeypatch.setattr(bridge, "DERIVED", tmp_path)
    monkeypatch.setattr(bridge, "MODELS", tmp_path)
    monkeypatch.setattr(bridge, "TRACE", tmp_path / "no_trace.json")
    t_in = str(int(pd.Timestamp("2026-06-01").timestamp()) * 10**9)
    t_after = str(int(pd.Timestamp("2026-11-03").timestamp()) * 10**9)
    W = bridge.BUYBACK_WALLET
    txns = [
        {"receipt_id": "a", "predecessor_account_id": "intents.near", "receiver_account_id": W, "block_timestamp": t_in, "receipt_outcome": {"status": True}, "actions": [{"action": "TRANSFER", "deposit": 100 * 1e24}]},
        {"receipt_id": "b", "predecessor_account_id": W, "receiver_account_id": "x.near", "block_timestamp": t_in, "receipt_outcome": {"status": True}, "transaction_hash": "T1",
         "outcomes_agg": {"transaction_fee": 1e24}, "actions": [{"action": "TRANSFER", "deposit": 10 * 1e24}]},
        {"receipt_id": "c", "predecessor_account_id": W, "receiver_account_id": W, "block_timestamp": t_in, "receipt_outcome": {"status": True}, "transaction_hash": "T1",
         "outcomes_agg": {"transaction_fee": 1e24}, "actions": [{"action": "FUNCTION_CALL", "method": "confirm", "deposit": 0}]},   # same transaction: fee counted once
        {"receipt_id": "d", "predecessor_account_id": "intents.near", "receiver_account_id": W, "block_timestamp": t_after, "receipt_outcome": {"status": True}, "actions": [{"action": "TRANSFER", "deposit": 50 * 1e24}]},
    ]
    snaps = {"nearblocks_buybacks_txns": {"source": "s", "fetched_at": "t", "data": {"wallet": W, "txns": txns}},
             "nearblocks_buybacks_account": {"source": "s", "fetched_at": "t", "data": {"amount": str(int(139 * 1e24)), "created": {"block_timestamp": t_in}}}}
    monkeypatch.setattr(bridge, "load_raw", lambda name, optional=False: snaps.get(name))
    out = bridge.run()
    led = out["receipts"]["ledger"]
    assert abs(led["reconstructed_balance_at_fetch_near"] - (150 - 10 - 1)) < 1e-9 and abs(led["unexplained_residual_near"]) < 1e-9
    assert abs(led["reconstructed_balance_at_cutoff_near"] - (100 - 10 - 1)) < 1e-9 and abs(led["inflows_after_cutoff_near"] - 50) < 1e-9
    steps = {s["step"]: s for s in out["steps"]}
    assert abs(steps[6]["share_of_previous"] - 89 / 100) < 1e-12        # at the cutoff, not snapshot balance / cutoff inflows


def test_oos_criterion_is_familywise_not_nominal():
    """Second audit, point A: the auditor's reproduction. Nominal interval excludes zero, familywise includes it -> no pass."""
    draws = np.concatenate([np.full(40, -0.1), np.linspace(0.1, 0.9, 3960)])
    c = signal.oos_criterion(draws, family=24)
    lo, hi = c["ci95_block_bootstrap"]; flo, fhi = c["ci95_familywise_bonferroni"]
    assert lo > 0 and flo < 0
    assert c["passes_nominal_interval_exploratory"] is True and c["passes_declared_criterion"] is False
    assert "exploratory" in c["status"]
    strong = signal.oos_criterion(np.linspace(0.2, 0.9, 4000), family=24)
    assert strong["passes_declared_criterion"] is True and "familywise" in strong["status"]


def test_oos_protocol_declares_retrospective_scope_and_prospective_plan():
    p = signal.OOS_PROTOCOL
    assert "retrospective" in p["declaration"] and "cannot establish" in p["declaration"]
    assert "Bonferroni" in p["fixed_rule"] and "not tested for passing" in p["benchmark_predictor_treatment"]
    assert "oos_freeze.json" in p["prospective"]["intents_and_qaa"] and "never recompute" in p["prospective"]["intents_and_qaa"]
    short = signal.oos_table(_weekly().iloc[-40:], frozen_plan={})          # no persisted plan: a draft, labelled as such
    rows = [r for r in short["tests"] if r["kind"] == "usage"]
    assert all(r["prospective_plan"]["frozen"] is False and "draft" in r["prospective_plan"]["status"] for r in rows)
    assert short["summary"]["prospective"]["frozen"] is False


def test_prospective_plan_is_persisted_and_invariant_to_new_history(tmp_path):
    """The auditor's reproduction: adding 20 weeks must not move the cutoff, the sign or the evaluation dates; matured targets must score."""
    full = _weekly(n=130, seed=5)
    w60 = full.iloc[:60]
    frozen_on = str((w60.index.max() + pd.Timedelta(days=6)).date())        # the freeze happens after the last observation
    path = tmp_path / "oos_freeze.json"
    plan = signal.freeze_prospective_plan(w60, frozen_on, path=path)
    assert plan["frozen_on"] == frozen_on and plan["data_cutoff"] == str(w60.index.max().date())
    key = "active_accounts h=12 vs btc"
    e = plan["tests"][key]
    assert e["frozen_sign"] in (1.0, -1.0) and e["calibration_sha256"] and e["calibration_end"] == e["last_signal_week_with_realized_target"]
    assert len(e["interim_signal_weeks_excluded"]) == 12 and len(e["evaluation_signal_weeks"]) == 20
    assert pd.Timestamp(e["evaluation_starts"]) > pd.Timestamp(frozen_on) and pd.Timestamp(e["evaluation_starts"]) - pd.Timestamp(frozen_on) <= pd.Timedelta(days=7)
    assert pd.Timestamp(e["evaluable_from"]) == pd.Timestamp(e["evaluation_ends"]) + pd.Timedelta(weeks=12)
    with pytest.raises(FileExistsError):
        signal.freeze_prospective_plan(w60, frozen_on, path=path)

    def planned(w):
        o = signal.oos_table(w, freeze_path=path)
        r = [t for t in o["tests"] if t["kind"] == "usage" and t["horizon_weeks"] == 12 and t["benchmark"] == "btc"][0]
        return r["prospective_plan"], o["summary"]["prospective"]

    p60, _ = planned(w60)
    p80, s80 = planned(full.iloc[:80])                                         # 20 more weeks: the auditor's case
    for k in ("frozen_on", "last_signal_week_with_realized_target", "frozen_sign", "evaluation_starts", "evaluation_ends", "evaluable_from", "calibration_weeks"):
        assert p60[k] == p80[k] == e[k if k != "frozen_sign" else "frozen_sign"]
    assert p80["frozen"] is True and p80["calibration_data_unchanged"] is True and p80["protocol_unchanged"] is True
    assert "not evaluable yet" in p80["status"] and p80["evaluation_targets_realized"] < 20 and s80["tests_scored"] == 0

    p130, s130 = planned(full)                                                 # all 20 targets realized: scored, no new deferral
    assert p130["evaluation_targets_realized"] == 20 and "ic_evaluation_signed" in p130 and isinstance(p130["passes_declared_criterion"], bool)
    assert p130["status"].startswith("prospective:") and p130["evaluable_from"] == e["evaluable_from"] and p130["frozen_sign"] == e["frozen_sign"]
    assert s130["tests_scored"] >= 1 and "prospective:" in signal.oos_table(full, freeze_path=path)["summary"]["conclusion"]

    revised = full.copy()
    revised.loc[revised.index[:30], "active_accounts"] *= 1.5                 # a revised history is flagged, not silently recalibrated
    pr, _ = planned(revised)
    assert pr["calibration_data_unchanged"] is False and pr["frozen_sign"] == e["frozen_sign"]


def test_prospective_evaluation_detects_a_changed_protocol(tmp_path, monkeypatch):
    """The auditor's reproduction: the hash lives at the root of the frozen file and must be compared, not defaulted to unchanged."""
    full = _weekly(n=130, seed=5)
    w60 = full.iloc[:60]
    path = tmp_path / "oos_freeze.json"
    plan = signal.freeze_prospective_plan(w60, str((w60.index.max() + pd.Timedelta(days=6)).date()), path=path)
    assert plan["protocol_sha256"] == signal.protocol_hash() and "protocol_sha256" not in next(iter(plan["tests"].values()))

    def flag(w):
        o = signal.oos_table(w, freeze_path=path)
        return [t["prospective_plan"] for t in o["tests"] if t["kind"] == "usage"][0], o["summary"]["prospective"]["protocol_unchanged"]

    p_same, s_same = flag(full)
    assert p_same["protocol_unchanged"] is True and s_same is True and p_same["protocol_sha256_persisted"] == plan["protocol_sha256"]
    changed = dict(signal.OOS_PROTOCOL)
    changed["fixed_rule"] = changed["fixed_rule"] + " (re-tuned)"
    monkeypatch.setattr(signal, "OOS_PROTOCOL", changed)
    p_changed, s_changed = flag(full)
    assert p_changed["protocol_unchanged"] is False and s_changed is False
    monkeypatch.setattr(signal, "OOS_PROTOCOL", dict(signal.OOS_PROTOCOL, minimum_rows={"calibration": 30, "evaluation": 10}))
    assert flag(full)[1] is False
    # a frozen file without a root hash is treated as changed, never as unchanged
    stale = json.loads(path.read_text()); stale.pop("protocol_sha256")
    path.write_text(json.dumps(stale))
    monkeypatch.undo()
    assert flag(full)[1] is False
