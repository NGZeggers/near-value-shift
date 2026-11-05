import json
import asyncio
import sys
from types import SimpleNamespace
import pytest

from near_thesis import onchain
from near_thesis import cli


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


def test_verify_rejects_modified_numbers_even_with_matching_hash(monkeypatch):
    from near_thesis import onchain
    local = {'thesis_sha256':'same', 'intents_volume_usd':100, 'as_of':'2026-11-01'}
    monkeypatch.setattr(onchain, 'payload', lambda: local)
    monkeypatch.setattr(onchain, 'read_index', lambda *a: {**local, 'intents_volume_usd':999})
    assert onchain.verify('audit.testnet','testnet') is False


@pytest.mark.parametrize('network,environment', [('testnet', 'mainnet'), ('mainnet', 'testnet')])
def test_cli_network_and_account_override_environment_without_signing(monkeypatch, tmp_path, network, environment):
    monkeypatch.setenv('NEAR_NETWORK', environment)
    monkeypatch.setenv('NEAR_ACCOUNT_ID', 'wrong.near')
    monkeypatch.setattr(onchain, 'DERIVED', tmp_path)
    monkeypatch.setattr(onchain, 'payload', lambda: {'audit': True})
    observed = []
    async def publish(*args, **kwargs):
        observed.append(kwargs)
    monkeypatch.setattr(onchain, 'publish', publish)
    cli.main(['onchain', '--network', network, '--account', 'chosen.near'])
    assert observed == [{'account_id': 'chosen.near', 'network': network}]


@pytest.mark.parametrize('network', ['testnet', 'mainnet'])
def test_signer_receives_exact_selected_network_and_account(monkeypatch, tmp_path, network, capsys):
    monkeypatch.setenv('NEAR_NETWORK', 'mainnet' if network == 'testnet' else 'testnet')
    monkeypatch.setenv('NEAR_ACCOUNT_ID', 'wrong.near')
    monkeypatch.setenv('NEAR_PRIVATE_KEY', 'synthetic-key-never-sent')
    monkeypatch.setattr(onchain, 'DERIVED', tmp_path)
    monkeypatch.setattr(onchain, 'payload', lambda: {})
    calls = []
    class Account:
        def __init__(self, account, key, rpc_addr):
            calls.append((account, key, rpc_addr))
        async def startup(self): pass
        async def function_call(self, contract, method, arguments, **kw):
            calls.append((contract, method, kw['amount']))
            return SimpleNamespace(transaction=SimpleNamespace(hash='synthetic-tx'))
    monkeypatch.setitem(sys.modules, 'py_near.account', SimpleNamespace(Account=Account))
    result = asyncio.run(onchain.publish(False, account_id='chosen.near', network=network))
    assert result == {'tx': 'synthetic-tx'}
    assert calls[0] == ('chosen.near', 'synthetic-key-never-sent', onchain.SOCIAL[network][1])
    assert calls[1] == (onchain.SOCIAL[network][0], 'set', 50_000_000_000_000_000_000_000)
    assert 'synthetic-key-never-sent' not in capsys.readouterr().out


def test_verify_and_send_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        cli.main(['onchain', '--verify', '--send'])
