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
