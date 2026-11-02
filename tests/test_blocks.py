from near_thesis import blocks


def test_extract_keeps_intents_logs_and_transactions():
    block = {"block": {"header": {"height": 5, "timestamp": 1700000000000000000}},
             "shards": [{"chunk": {"transactions": [
                            {"transaction": {"signer_id": "alice.near", "receiver_id": "intents.near", "actions": [{"FunctionCall": {"method_name": "execute_intents", "deposit": "0"}}]}},
                            {"transaction": {"signer_id": "bob.near", "receiver_id": "carol.near", "actions": [{"Transfer": {"deposit": "1000"}}, "CreateAccount"]}}]},
                         "receipt_execution_outcomes": [
                            {"receipt": {"receipt_id": "r1", "receiver_id": "intents.near", "predecessor_id": "relay.near"},
                             "execution_outcome": {"outcome": {"logs": ["EVENT_JSON:{\"standard\":\"dip4\",\"event\":\"token_diff\",\"data\":[]}", "plain log"]}}},
                            {"receipt": {"receipt_id": "r2", "receiver_id": "other.near", "predecessor_id": "x.near"},
                             "execution_outcome": {"outcome": {"logs": ["EVENT_JSON:{}"]}}}]}]}
    s = blocks.extract(block)
    assert s["height"] == 5 and s["n_outcomes"] == 2
    assert s["events"] == [["r1", "relay.near", "EVENT_JSON:{\"standard\":\"dip4\",\"event\":\"token_diff\",\"data\":[]}"]]
    kinds = [t[2] for t in s["txs"]]
    assert kinds == ["FUNCTION_CALL", "TRANSFER", "CREATEACCOUNT"]
    assert s["txs"][0][3] == "execute_intents"
