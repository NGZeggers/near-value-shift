"""Pre-declared receipt trace: sample rule and matching of inbound NEAR receipts to Intents withdraw events."""
import json

from near_thesis import blocks

W = "buybacks.multisignature.near"
ACC = "e52c" + "0" * 60


def _txn(i, amount_near, pred="intents.near"):
    return {"receipt_id": f"r{i}", "transaction_hash": f"t{i}", "predecessor_account_id": pred, "receiver_account_id": W, "block_timestamp": str(10**9 * (1000 + i)),
            "receipt_block": {"block_height": 500 + i}, "block": {"block_height": 497 + i}, "receipt_outcome": {"status": True},
            "actions": [{"action": "TRANSFER", "deposit": amount_near * 1e24}]}


def test_sample_rule_every_80th_plus_five_largest():
    txns = [_txn(i, 1 + (i % 7)) for i in range(400)] + [_txn(900 + j, 1000 + j) for j in range(5)] + [_txn(999, 5, pred="1csfundsadmin.sputnik-dao.near")]
    s = blocks.buyback_trace_sample(txns, W)
    ids = [t["receipt_id"] for t in s]
    assert set(f"r{i}" for i in range(0, 400, 80)) <= set(ids)                  # every 80th of the 405 inbound receipts (indices 0..400)
    assert {f"r{900 + j}" for j in range(5)} <= set(ids) and "r999" not in ids   # the five largest; the treasury transfer is not inbound from intents.near
    assert len(ids) == len(set(ids)) == 10                                       # 6 positional picks + 5 largest, r900 (index 400) counted once


def test_trace_matches_withdraw_amount_and_account_and_flags_token_diff():
    t = _txn(1, 354.084338340641)
    amount = str(int(354.084338340641 * 1e24))
    ev_withdraw = "EVENT_JSON:" + json.dumps({"standard": "dip4", "event": "native_withdraw", "data": [{"intent_hash": "H", "account_id": ACC, "receiver_id": W, "amount": amount}]})
    ev_burn = "EVENT_JSON:" + json.dumps({"standard": "nep245", "event": "mt_burn", "data": [{"owner_id": ACC, "token_ids": ["nep141:wrap.near"], "amounts": [amount], "memo": "withdraw"}]})
    ev_diff = "EVENT_JSON:" + json.dumps({"standard": "dip4", "event": "token_diff", "data": [{"account_id": ACC, "intent_hash": "D", "diff": {"nep141:usdc": "-1", "nep141:wrap.near": "1"}}]})
    other = "EVENT_JSON:" + json.dumps({"standard": "dip4", "event": "native_withdraw", "data": [{"intent_hash": "X", "account_id": "someone", "receiver_id": W, "amount": "1"}]})
    b1 = {"height": 498, "ts": 1, "events": [["e1", "intents.near", ev_withdraw, "SUCCESS_VALUE"], ["e1", "intents.near", ev_burn, "SUCCESS_VALUE"], ["e0", "intents.near", other, "SUCCESS_VALUE"]]}
    b2 = {"height": 499, "ts": 2, "events": [["e2", "intents.near", ev_diff, "SUCCESS_VALUE"]]}
    out = blocks.trace_receipt(t, [b1, b2])
    assert out["match"].startswith("native_withdraw") and out["intents_account"] == ACC and out["withdraw_event"]["intent_hash"] == "H"
    assert out["mt_burn_token"] == "nep141:wrap.near" and out["token_diff_same_block"] == ["e2"]
    assert out["block_url"].endswith("/block/498") and out["blocks_read"] == [498, 499]
    none = blocks.trace_receipt(t, [{"height": 498, "ts": 1, "events": [["e0", "intents.near", other, "SUCCESS_VALUE"]]}])
    assert none["intents_account"] is None and none["match"].startswith("no matching")
