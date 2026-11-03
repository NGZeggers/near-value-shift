import json

import pandas as pd

from near_thesis import intents


def ev(event, data):
    return "EVENT_JSON:" + json.dumps({"standard": "dip4", "version": "0.3.0", "event": event, "data": data})


def make_df():
    rows = []
    day = "2026-03-01"
    # solver "mm.near" trades with 30 users: user sells 100 USDC for 25 NEAR (raw units)
    for i in range(30):
        rid = f"r{i}"
        rows.append((day, rid, "relay.near", ev("token_diff", [
            {"account_id": f"u{i}.near", "intent_hash": f"h{i}a", "diff": {"nep141:usdc.near": "-100000000", "nep141:wrap.near": "25000000000000000000000000"}},
            {"account_id": "mm.near", "intent_hash": f"h{i}b", "diff": {"nep141:usdc.near": "100000000", "nep141:wrap.near": "-25000000000000000000000000"}},
        ])))
        rows.append((day, rid, "relay.near", ev("intents_executed", [{"account_id": f"u{i}.near", "intent_hash": f"h{i}a"}])))
    rows.append((day, "w1", "u1.near", ev("ft_withdraw", [{"account_id": "u1.near", "token": "usdc.near", "amount": "1"}])))
    return pd.DataFrame(rows, columns=["block_date", "receipt_id", "caller", "log"])


def test_parse_and_roles_and_metrics():
    df = make_df()
    df["block_date"] = pd.to_datetime(df["block_date"]).dt.date
    legs = intents.batches_from_events(df)
    assert len(legs) == 30 * 4
    roles = intents.identify_solvers(legs)
    assert roles.loc[roles["account"] == "mm.near", "is_solver"].all()
    assert not roles.loc[roles["account"] == "u1.near", "is_solver"].any()
    events = df.assign(event=[(intents.parse_event(l) or {}).get("event") for l in df["log"]])
    prices = {"2026-03-01": {"near": 4.0, "bitcoin": 80000.0, "ethereum": 3000.0}}
    daily = intents.daily_metrics(legs, roles, events, prices)
    r = daily.iloc[0]
    assert r["batches"] == 30 and r["users"] == 30 and r["solvers"] == 1
    assert abs(r["volume_priced_usd"] - 30 * 100.0) < 1e-6      # user outflow priced by the stable leg
    assert r["top1_solver_share"] == 1.0 and r["hhi_solver"] == 1.0
    assert r["withdraw_events"] == 1
    m = intents.monthly_estimates(daily, n_boot=50)
    assert abs(m.iloc[0]["volume_est_usd"] - 3000 * 31) < 1e-6


def test_token_diff_single_object_and_registry(monkeypatch):
    from near_thesis import intents
    monkeypatch.setattr(intents, "_REGISTRY", {"nep141:eth-0xa0b8.omft.near": ("usdc", 6, "usd-coin"), "nep141:sol.omft.near": ("sol", 9, "solana")})
    log = 'EVENT_JSON:{"standard":"dip4","version":"0.1.0","event":"token_diff","data":{"account_id":"a.near","diff":{"nep141:eth-0xa0b8.omft.near":"-7000000","nep141:sol.omft.near":"2000000000"}}}'
    df = pd.DataFrame([{"block_date": "2024-12-04", "receipt_id": "r1", "log": log}])
    legs = intents.batches_from_events(df)
    assert len(legs) == 2 and set(legs["account"]) == {"a.near"}
    assert intents.price_leg("nep141:eth-0xa0b8.omft.near", -7000000, {}) == 7.0
    assert intents.price_leg("nep141:sol.omft.near", 2000000000, {"solana": 150.0}) == 300.0
    assert intents.price_leg("nep141:unknown.near", 1, {}) is None


def test_multiple_users_in_receipt_with_only_stable_leg_priced(monkeypatch):
    monkeypatch.setattr(intents, '_REGISTRY', {})
    legs = pd.DataFrame([
        ('2026-03-01', 'r', 'alice', 'a', 'usdc', -10_000_000),
        ('2026-03-01', 'r', 'alice', 'a', 'unknown', 10),
        ('2026-03-01', 'r', 'bob', 'b', 'usdc', -20_000_000),
        ('2026-03-01', 'r', 'bob', 'b', 'unknown', 20),
        ('2026-03-01', 'r', 'solver', 's', 'usdc', 30_000_000),
        ('2026-03-01', 'r', 'solver', 's', 'unknown', -30),
    ], columns=['block_date','receipt_id','account','intent_hash','token','amount'])
    roles = pd.DataFrame([('2026-03-01', a, a == 'solver') for a in ['alice','bob','solver']], columns=['block_date','account','is_solver'])
    events = pd.DataFrame({'block_date':['2026-03-01'], 'event':['token_diff']})
    r = intents.daily_metrics(legs, roles, events, {}).iloc[0]
    assert r.volume_priced_usd == 30  # both users retained, independent of solver identity
    assert r.priced_batch_share == 1
    assert r.fully_priced_batch_share == 0
    assert r.priced_legs / r.total_legs == 0.5


def test_sample_run_retains_zero_days_and_loads_prices_once(tmp_path, monkeypatch):
    from near_thesis import blocks as blocks_mod
    for p in ['blocks', 'bq', 'derived', 'models']:
        (tmp_path / p).mkdir()
    df = make_df()
    df['window_day'] = df.block_date
    df['window_hour'] = 3
    df.to_csv(tmp_path / 'blocks/intents_events_sampled.csv', index=False)
    manifest = {'windows': [{'day': d, 'hour': 3, 'n': 50, 'fetched': 50, 'usable': True} for d in ['2026-03-01','2026-03-02']]}
    (tmp_path / 'blocks/sample_manifest.json').write_text(json.dumps(manifest))
    pd.DataFrame({'date':['2026-03-01','2026-03-02'], 'blocks':[100_000,100_000], 'intents_volume_usd':[6_000_000,6_000_000]}).to_csv(tmp_path / 'derived/daily.csv', index=False)
    monkeypatch.setattr(intents, 'DATA', tmp_path)
    monkeypatch.setattr(intents, 'BQ_DIR', tmp_path / 'bq')
    monkeypatch.setattr(intents, 'DERIVED', tmp_path / 'derived')
    monkeypatch.setattr(intents, 'MODELS', tmp_path / 'models')
    monkeypatch.setattr(blocks_mod, 'BLOCKS', tmp_path / 'blocks')
    calls = []
    def prices():
        calls.append(1)
        return {'2026-03-01': {'near':4.0}}
    monkeypatch.setattr(intents, '_daily_prices', prices)
    status = intents.run()
    daily = pd.read_csv(tmp_path / 'models/intents_daily.csv')
    assert status['sampled_days'] == 2 and status['days_with_token_diff'] == 1
    assert daily.iloc[1].volume_priced_usd == 0
    assert daily.iloc[0].users == 30  # observed users must not be multiplied by 2,000
    assert len(calls) == 1


def test_solver_relative_threshold_is_sampled_only():
    rows = []
    for i in range(5):
        for a in ['mm', f'u{i}']:
            rows.append(('2026-03-01', str(i), a))
    legs = pd.DataFrame(rows, columns=['block_date','receipt_id','account'])
    assert not intents.identify_solvers(legs).is_solver.any()
    assert intents.identify_solvers(legs, sampled=True).is_solver.any()
