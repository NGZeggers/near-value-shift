"""Failure recovery and hostile-input checks beyond the original audit cases."""
import json
from pathlib import Path

import pandas as pd
import pytest

from near_thesis import blocks, econ, fetch, onchain, serialization, site


@pytest.mark.parametrize('response', [{'message':'rate limited'}, [], {'message':'unavailable'}])
def test_nearblocks_error_responses_have_bounded_retries(monkeypatch, response):
    calls=[]
    monkeypatch.setattr(fetch, 'fetch_json', lambda url: calls.append(url) or response)
    monkeypatch.setattr(fetch.time, 'sleep', lambda seconds: None)
    with pytest.raises(RuntimeError, match='pagination failed'):
        fetch._nearblocks_paged('https://example.invalid/?n=1', 'txns')
    assert len(calls)==8


def test_nearblocks_repeated_cursor_is_rejected(monkeypatch):
    monkeypatch.setattr(fetch, 'fetch_json', lambda url: {'txns':[{'id':1}], 'cursor':'same'})
    monkeypatch.setattr(fetch.time, 'sleep', lambda seconds: None)
    with pytest.raises(RuntimeError, match='cursor'):
        fetch._nearblocks_paged('https://example.invalid/?n=1', 'txns')


def test_nearblocks_transient_body_error_recovers(monkeypatch):
    replies=iter([{'message':'rate limited'}, {'txns':[{'id':1}], 'cursor':'next'}, {'txns':[{'id':2}]}])
    monkeypatch.setattr(fetch, 'fetch_json', lambda url: next(replies))
    monkeypatch.setattr(fetch.time, 'sleep', lambda seconds: None)
    assert fetch._nearblocks_paged('https://example.invalid/?n=1','txns')==[{'id':1},{'id':2}]


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-float('inf')])
def test_nested_nonfinite_json_values_become_null(value):
    result=serialization.dumps({'rows':[{'missing':value,'observed':1.25}]})
    assert json.loads(result)=={'rows':[{'missing':None,'observed':1.25}]}
    assert not any(word in result for word in ['NaN','Infinity'])


@pytest.mark.parametrize('payload',['</script><script>window.__x=1</script>','<!--<script>','<&>\u2028\u2029','/*APP*/ /*BUILD_TIME*/'])
def test_embedded_json_cannot_change_html_script_state(tmp_path,monkeypatch,payload):
    monkeypatch.setattr(site,'SITE',tmp_path)
    (tmp_path/'data.json').write_text(json.dumps({'text':payload}))
    site.run()
    html=(tmp_path/'index.html').read_text()
    embedded=html.split('<script id="spec" type="application/json">',1)[1].split('</script>',1)[0]
    assert '<' not in embedded
    assert json.loads(embedded)=={'text':payload}


@pytest.mark.parametrize('bad',['{"value":Infinity}','{"value":NaN}','{'])
def test_invalid_site_json_preserves_existing_page(tmp_path,monkeypatch,bad):
    monkeypatch.setattr(site,'SITE',tmp_path)
    (tmp_path/'data.json').write_text(bad)
    (tmp_path/'index.html').write_text('previous page')
    with pytest.raises(ValueError):site.run()
    assert (tmp_path/'index.html').read_text()=='previous page'


def test_extraction_exception_preserves_both_outputs(tmp_path,monkeypatch):
    monkeypatch.setattr(blocks,'BLOCKS',tmp_path)
    (tmp_path/'sample_plan.json').write_text(json.dumps([{'day':'2026-01-01','hour':3,'start_height':1}]))
    originals={'intents_events_sampled.csv':'events','tx_sampled.csv':'actions','sample_manifest.json':'old manifest'}
    for name,text in originals.items():(tmp_path/name).write_text(text)
    def failure(*a,**kw):raise RuntimeError('interrupted acquisition')
    monkeypatch.setattr(blocks,'fetch_block',failure)
    with pytest.raises(RuntimeError):blocks.run(blocks_per_window=1)
    for name,text in originals.items():assert (tmp_path/name).read_text()==text


@pytest.mark.parametrize('kwargs',[{'workers':False},{'blocks_per_window':0},{'day_step':-1},{'windows':(24,)}])
def test_sampler_rejects_invalid_configuration_before_io(tmp_path,monkeypatch,kwargs):
    monkeypatch.setattr(blocks,'BLOCKS',tmp_path/'absent')
    with pytest.raises(ValueError):blocks.run(**kwargs)
    assert not (tmp_path/'absent').exists()


def test_johansen_invalid_prerequisites_never_call_estimator(monkeypatch):
    monkeypatch.setattr(econ,'adf',lambda s:{'stationary_5pct':False})
    monkeypatch.setattr(econ,'coint_johansen',lambda *a,**kw:pytest.fail('invalid estimator called'))
    frame=pd.DataFrame({'near_price':range(1,801),'usage':range(2,802)},index=pd.date_range('2024-01-01',periods=800))
    assert econ.johansen(frame,'usage',None)['inference_valid'] is False


def test_usable_sampler_output_replaces_old_extract_only_after_success(tmp_path,monkeypatch):
    monkeypatch.setattr(blocks,'BLOCKS',tmp_path)
    (tmp_path/'sample_plan.json').write_text(json.dumps([{'day':'2026-01-01','hour':3,'start_height':1}]))
    (tmp_path/'intents_events_sampled.csv').write_text('old events')
    (tmp_path/'tx_sampled.csv').write_text('old actions')
    (tmp_path/'event_verification.json').write_text('stale attestation')
    def cached(height,**kwargs):
        return {'height':height,'ts':1767225600000000000,'events':[[f'r{height}','relay','EVENT_JSON:{}','SUCCESS_VALUE']],'txs':[]}
    monkeypatch.setattr(blocks,'fetch_block',cached)
    result=blocks.run(blocks_per_window=10)
    assert result['complete'] is True
    assert len(pd.read_csv(tmp_path/'intents_events_sampled.csv'))==10
    assert pd.read_csv(tmp_path/'tx_sampled.csv').empty
    assert not (tmp_path/'event_verification.json').exists()


def test_partially_fetched_unusable_window_preserves_previous_data(tmp_path,monkeypatch):
    monkeypatch.setattr(blocks,'BLOCKS',tmp_path)
    (tmp_path/'sample_plan.json').write_text(json.dumps([{'day':'2026-01-01','hour':3,'start_height':1}]))
    for name in ['intents_events_sampled.csv','tx_sampled.csv','sample_manifest.json']:(tmp_path/name).write_text('original')
    monkeypatch.setattr(blocks,'fetch_block',lambda h,**kw:{'height':h,'ts':1767225600000000000,'events':[],'txs':[]} if h==1 else None)
    with pytest.raises(ValueError):blocks.run(blocks_per_window=10)
    for name in ['intents_events_sampled.csv','tx_sampled.csv','sample_manifest.json']:assert (tmp_path/name).read_text()=='original'
