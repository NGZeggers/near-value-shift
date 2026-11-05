import csv
import json
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from near_thesis import blocks, intents, fetch, http


@pytest.mark.parametrize('status,expected', [({'SuccessValue': ''}, 1), ({'SuccessReceiptId':'r'}, 1),
    ({'Failure':{}}, 0), ({}, 0), (None, 0), ({'SuccessValue':'', 'Failure':{}}, 0)])
def test_extractor_requires_explicit_success(status, expected):
    body = {'block': {'header': {'height': 3, 'timestamp': 10}}, 'shards': [{
        'receipt_execution_outcomes': [{'receipt': {'receipt_id':'r', 'receiver_id':'intents.near', 'predecessor_id':'a'},
            'execution_outcome': {'outcome': {'status':status, 'logs':['EVENT_JSON:{}']}}}]}]}
    parsed = blocks.extract(body)
    assert len(parsed['events']) == expected
    assert parsed['schema_version'] == blocks.CACHE_SCHEMA


def test_old_slim_cache_cannot_be_treated_as_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(blocks, 'CACHE', tmp_path)
    (tmp_path/'7.json').write_text(json.dumps({'height':7,'events':[]}))
    with pytest.raises(ValueError, match='status-aware'):
        blocks.fetch_block(7, offline=True)


def test_offline_sampler_preserves_extracts_when_cache_needs_migration(tmp_path, monkeypatch):
    cache = tmp_path/'cache'; cache.mkdir()
    monkeypatch.setattr(blocks, 'BLOCKS', tmp_path)
    monkeypatch.setattr(blocks, 'CACHE', cache)
    monkeypatch.setattr(blocks.requests, 'get', lambda *a,**kw: pytest.fail('network reached in offline mode'))
    (tmp_path/'sample_plan.json').write_text(json.dumps([{'day':'2026-01-01','hour':3,'start_height':7}]))
    (cache/'7.json').write_text(json.dumps({'height':7,'events':[]}))
    original = tmp_path/'intents_events_sampled.csv'; original.write_text('original')
    with pytest.raises(ValueError, match='status-aware'):
        blocks.run(offline=True,blocks_per_window=1)
    assert original.read_text()=='original'


def test_status_aware_verification_resumes_offline_without_network(tmp_path, monkeypatch):
    path = event_extract(tmp_path)
    cache = tmp_path/'cache'; cache.mkdir()
    monkeypatch.setattr(blocks, 'BLOCKS', tmp_path)
    monkeypatch.setattr(blocks, 'CACHE', cache)
    monkeypatch.setattr(blocks.requests, 'get', lambda *a,**kw: pytest.fail('offline verification attempted a request'))
    for height, rid, caller in [(1,'r','a'),(2,'s','b')]:
        (cache/f'{height}.json').write_text(json.dumps({'schema_version':blocks.CACHE_SCHEMA,
            'height':height,'ts':height*10,'receipts':{rid:{'status':'SUCCESS_VALUE','caller':caller,'logs':['EVENT_JSON:{}']}}}))
    report = blocks.verify_events(offline=True)
    assert report['accepted_events']==2
    assert pd.read_csv(path).execution_status.tolist()==['SUCCESS_VALUE','SUCCESS_VALUE']


def event_extract(tmp_path):
    path = tmp_path/'intents_events_sampled.csv'
    rows = [{'block_height':1, 'block_timestamp':10, 'receipt_id':'r', 'caller':'a', 'log':'EVENT_JSON:{}'},
            {'block_height':2, 'block_timestamp':20, 'receipt_id':'s', 'caller':'b', 'log':'EVENT_JSON:{}'}]
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    return path


def test_revalidation_filters_failures_and_keeps_provenance(tmp_path, monkeypatch):
    path = event_extract(tmp_path)
    monkeypatch.setattr(blocks, 'BLOCKS', tmp_path)
    def fetch(h, **kwargs):
        rid, caller, status = ('r','a','SUCCESS_VALUE') if h==1 else ('s','b','FAILURE')
        return {'height':h, 'ts':h*10, 'receipts': {rid:{'status':status,'caller':caller,'logs':['EVENT_JSON:{}']}}}
    monkeypatch.setattr(blocks, 'fetch_block', fetch)
    report = blocks.verify_events(offline=True)
    result = pd.read_csv(path)
    assert len(result)==1 and result.execution_status.tolist()==['SUCCESS_VALUE']
    assert report['failed_events_removed']==1
    assert (tmp_path/'event_verification.json').exists()


def test_incomplete_verification_preserves_original_extract(tmp_path, monkeypatch):
    path = event_extract(tmp_path); original = path.read_bytes()
    monkeypatch.setattr(blocks, 'BLOCKS', tmp_path)
    monkeypatch.setattr(blocks, 'fetch_block', lambda h, **kw: None)
    with pytest.raises(ValueError): blocks.verify_events(offline=True)
    assert path.read_bytes()==original


@pytest.mark.parametrize('state', [None, 'UNKNOWN'])
def test_legacy_or_unknown_extract_disables_l2_and_invalidates_stale_outputs(tmp_path, monkeypatch, state):
    for name in ['blocks','bq','models']: (tmp_path/name).mkdir()
    pd.DataFrame({'block_date':['2026-01-01'], 'log':['EVENT_JSON:{}'],
                  **({'execution_status':[state]} if state else {})}).to_csv(tmp_path/'blocks/intents_events_sampled.csv',index=False)
    (tmp_path/'blocks/sample_manifest.json').write_text('{}')
    monkeypatch.setattr(intents, 'DATA', tmp_path)
    monkeypatch.setattr(intents, 'BQ_DIR', tmp_path/'bq')
    monkeypatch.setattr(intents, 'MODELS', tmp_path/'models')
    (tmp_path/'models/intents_monthly.csv').write_text('stale')
    assert intents.run()['computed'] is False
    assert not (tmp_path/'models/intents_monthly.csv').exists()


def test_asset_identifiers_are_exact_and_case_sensitive(monkeypatch):
    monkeypatch.setattr(intents, '_REGISTRY', {'nep245:bridge.near:AbC': ('usdc',6,'usd-coin')})
    assert intents.price_leg('nep245:bridge.near:AbC',10**6,{})==1
    assert intents.price_leg('nep245:bridge.near:abc',10**6,{}) is None
    assert intents.token_decimals('nep245:bridge.near:abc') is None


@pytest.mark.parametrize('send,expected', [('',False),('0',False),('1',True)])
def test_make_signs_only_for_explicit_one(send, expected):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(['make','-n','onchain',f'SEND={send}'],cwd=root,capture_output=True,text=True,check=True)
    assert ('--send' in result.stdout) == expected


@pytest.mark.parametrize('send', ['false','yes','2','1 0'])
def test_make_rejects_ambiguous_send_values(send):
    result = subprocess.run(['make','-n','onchain',f'SEND={send}'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode != 0
    assert '--send' not in result.stdout


def test_unsupported_explorer_fails_even_without_credentials(monkeypatch):
    monkeypatch.setattr(fetch, 'INTENTS_EXPLORER_JWT', None)
    with pytest.raises(SystemExit, match='intents'):
        fetch.run(['intents'])


@pytest.mark.parametrize('retries', [0, -1, True, 1.5])
def test_invalid_retry_configuration_does_not_make_requests(monkeypatch, retries):
    monkeypatch.setattr(http.requests, 'request', lambda *a,**k: pytest.fail('network must not be reached'))
    with pytest.raises(ValueError): http.fetch_json('https://example.invalid', retries=retries)


@pytest.mark.parametrize('data', [None, 17, 'malformed', [{'account_id':'a','diff':['bad']}],
    [{'account_id':'a','diff':{'token':True}}], [{'account_id':'a','diff':{'token':'1.5'}}]])
def test_malformed_production_input_never_publishes_partial_metrics(tmp_path, monkeypatch, data):
    for name in ['bq','models']: (tmp_path/name).mkdir()
    raw = pd.DataFrame([{'block_date':'2026-01-01','receipt_id':'r', 'execution_status':'SUCCESS_VALUE',
                        'log':'EVENT_JSON:'+json.dumps({'standard':'dip4','event':'token_diff','data':data})}])
    raw.to_csv(tmp_path/'bq/l2_intents_events.csv',index=False)
    monkeypatch.setattr(intents, 'DATA', tmp_path)
    monkeypatch.setattr(intents, 'BQ_DIR', tmp_path/'bq')
    monkeypatch.setattr(intents, 'MODELS', tmp_path/'models')
    with pytest.warns(RuntimeWarning, match='Rejected'):
        status = intents.run()
    assert status['computed'] is False and status['rejected_items'] == 1
