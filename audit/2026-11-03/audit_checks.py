"""Independent audit checks; failing assertions describe required safe behavior."""
import asyncio
import json
import sys
import os
from types import SimpleNamespace

import pandas as pd
import pytest

from near_thesis import blocks, bq, fetch, http, intents, onchain, site
from near_thesis import cli


def event(data):
    return 'EVENT_JSON:' + json.dumps(dict(standard='dip4', event='token_diff', data=data))


def test_failed_receipt_must_not_be_counted_as_settlement():
    log = event([dict(account_id='a.near', diff={'usdc': '-1000000'})])
    block = {'block': {'header': {'height': 1, 'timestamp': 1}}, 'shards': [{
        'receipt_execution_outcomes': [{'receipt': {'receipt_id': 'r', 'receiver_id': 'intents.near'},
        'execution_outcome': {'outcome': {'status': {'Failure': {'error': 'rollback'}}, 'logs': [log]}}}]}]}
    assert blocks.extract(block)['events'] == []


@pytest.mark.parametrize('name', ['nep141:fake-usdc.attacker.near', 'nep141:fake-btc.attacker.near', 'nep141:fake-wrap.near.attacker'])
def test_unknown_token_name_cannot_impersonate_priced_asset(monkeypatch, name):
    monkeypatch.setattr(intents, '_REGISTRY', {})
    assert intents.price_leg(name, 10**24, {'near': 4., 'bitcoin': 80000.}) is None


@pytest.mark.parametrize('diff', ['not-a-mapping', ['not-a-mapping'], 1])
def test_malformed_diff_is_rejected_without_crashing(diff):
    frame = pd.DataFrame([dict(block_date='2026-01-01', receipt_id='r', log=event([dict(account_id='a', diff=diff)]))])
    assert intents.batches_from_events(frame).empty


@pytest.mark.parametrize('log', [None, '', 'plain', 'EVENT_JSON:{', 'EVENT_JSON:[]', 'EVENT_JSON:{"standard":"other"}'])
def test_non_events_are_ignored(log):
    assert intents.parse_event(log) is None


def test_bq_run_budget_enforced_against_executed_query_ceiling(tmp_path, monkeypatch):
    for name in ['q0_freshness', 'l1_accounts']:
        (tmp_path / (name + '.sql')).write_text('SELECT 1')
    monkeypatch.setattr(bq, 'SQL_DIR', tmp_path)
    monkeypatch.setattr(bq, 'BQ_DIR', tmp_path)
    monkeypatch.setattr(bq, 'BQ_MAX_GB_PER_QUERY', 120)
    monkeypatch.setenv('BQ_MAX_GB_PER_RUN', '150')
    ceilings = []
    class Config:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class Job:
        total_bytes_processed = 100 * 10**9
        job_id = 'mock'
        def result(self): return self
        def to_dataframe(self):
            return pd.DataFrame({'last_block_date': [pd.Timestamp.now(tz='UTC').date().isoformat()]})
    class Client:
        def query(self, sql, job_config):
            if not getattr(job_config, 'dry_run', False):
                ceilings.append(job_config.maximum_bytes_billed)
            return Job()
    monkeypatch.setattr(bq, '_client', lambda: (SimpleNamespace(QueryJobConfig=Config), Client()))
    monkeypatch.setattr(bq, 'dry_run', lambda _: 1.)
    bq.run()
    # An execution estimate changed from 1GB to 100GB. The second query's
    # ceiling must also respect the remaining run budget, not only per-query.
    assert sum(ceilings) <= 150 * 10**9


def test_bq_accumulated_budget_cannot_be_bypassed_by_estimate_drift(tmp_path, monkeypatch):
    for name in ['q0_freshness', 'l1_accounts', 'l2_events', 'q1_daily']:
        (tmp_path / (name + '.sql')).write_text('SELECT 1')
    monkeypatch.setattr(bq, 'SQL_DIR', tmp_path)
    monkeypatch.setenv('BQ_MAX_GB_PER_RUN', '3')
    monkeypatch.setattr(bq, 'dry_run', lambda _: .5)
    executed = []
    def run(path, **kwargs):
        executed.append(path.stem)
        f = tmp_path / (path.stem+'.csv')
        pd.DataFrame({'last_block_date': [pd.Timestamp.now(tz='UTC').date().isoformat()]}).to_csv(f, index=False)
        (tmp_path / (path.stem+'.meta.json')).write_text(json.dumps({'bytes_processed': 2*10**9}))
        return f
    monkeypatch.setattr(bq, 'run_query', run)
    try: bq.run()
    except SystemExit: pass
    assert len(executed) <= 1


def test_signing_not_imported_on_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr(onchain, 'DERIVED', tmp_path)
    monkeypatch.setattr(onchain, 'payload', lambda: {'test': True})
    monkeypatch.setenv('NEAR_NETWORK', 'testnet')
    monkeypatch.delenv('NEAR_PRIVATE_KEY', raising=False)
    before = set(sys.modules)
    asyncio.run(onchain.publish(dry_run=True))
    assert not any(x.startswith('py_near') for x in set(sys.modules) - before)


def test_missing_credentials_prevent_transaction(tmp_path, monkeypatch):
    monkeypatch.setattr(onchain, 'DERIVED', tmp_path)
    monkeypatch.setattr(onchain, 'payload', lambda: {})
    monkeypatch.delenv('NEAR_PRIVATE_KEY', raising=False)
    monkeypatch.delenv('NEAR_ACCOUNT_ID', raising=False)
    with pytest.raises(SystemExit, match='required'):
        asyncio.run(onchain.publish(dry_run=False))


def test_cli_testnet_selection_must_override_mainnet_environment(monkeypatch):
    # Stub publishing completely; this test never imports the signer or sends RPC.
    monkeypatch.setenv('NEAR_NETWORK', 'mainnet')
    observed = []
    monkeypatch.setattr(onchain, 'run', lambda **kwargs: observed.append(kwargs.get('network', os.getenv('NEAR_NETWORK'))))
    cli.main(['onchain', '--network', 'testnet'])
    assert observed == ['testnet']


def test_rpc_error_causes_verification_to_fail_closed(monkeypatch):
    import requests
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'error': {'code': -32000, 'message': 'unavailable'}}
    monkeypatch.setattr(requests, 'post', lambda *a, **k: Response())
    assert onchain.read_index('test.near') is None


def test_explorer_configured_must_not_report_success(monkeypatch):
    monkeypatch.setattr(fetch, 'INTENTS_EXPLORER_JWT', 'audit-placeholder-not-a-real-secret')
    with pytest.raises((SystemExit, NotImplementedError)):
        fetch.run(['intents'])


def test_empty_retry_budget_has_clear_validation():
    with pytest.raises(ValueError):
        http.fetch_json('https://example.invalid', retries=0)


def test_http_non_retryable_error_is_not_retried(monkeypatch):
    import requests
    calls = []
    def request(*a, **k):
        calls.append(1)
        response = requests.Response()
        response.status_code = 403
        return response
    monkeypatch.setattr(requests, 'request', request)
    monkeypatch.setattr(http.time, 'sleep', lambda _: None)
    with pytest.raises(requests.HTTPError): http.fetch_json('https://example.invalid')
    assert len(calls) == 1


def test_http_retries_429_then_succeeds(monkeypatch):
    import requests
    calls = []
    def request(*a, **k):
        calls.append(1)
        response = requests.Response()
        response.status_code = 429 if len(calls) == 1 else 200
        response._content = b'{"ok":true}'
        return response
    monkeypatch.setattr(requests, 'request', request)
    monkeypatch.setattr(http.time, 'sleep', lambda _: None)
    assert http.fetch_json('https://example.invalid') == {'ok': True}
    assert len(calls) == 2


def test_site_escapes_script_termination(tmp_path, monkeypatch):
    payload = '</script><script>window.__audit_xss=1</script>'
    (tmp_path/'data.json').write_text(json.dumps({'text': payload}))
    monkeypatch.setattr(site, 'SITE', tmp_path)
    site.run()
    html = (tmp_path/'index.html').read_text()
    assert payload not in html
    assert '<\\/script>' in html
