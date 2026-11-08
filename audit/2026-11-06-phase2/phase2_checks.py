"""Phase 2 independent checks. Failures describe required robust behavior."""
import asyncio
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from near_thesis import blocks, charts, econ, fetch, intents, onchain, qaa


@pytest.fixture
def l2(tmp_path, monkeypatch):
    for name in ['bq','models','derived','blocks']:
        (tmp_path/name).mkdir()
    monkeypatch.setattr(intents, 'BQ_DIR', tmp_path/'bq')
    monkeypatch.setattr(intents, 'MODELS', tmp_path/'models')
    monkeypatch.setattr(intents, 'DERIVED', tmp_path/'derived')
    monkeypatch.setattr(intents, 'DATA', tmp_path)
    monkeypatch.setattr(intents, '_REGISTRY', {'asset':('usdc',6,'usd-coin')})
    monkeypatch.setattr(intents, '_daily_prices', lambda: {})
    pd.DataFrame({'date':['2026-06-01'],'intents_volume_usd':[100.]}).to_csv(tmp_path/'derived/daily.csv',index=False)
    log='EVENT_JSON:'+json.dumps({'standard':'dip4','event':'token_diff','data':[
        {'account_id':'a.near','intent_hash':'a','diff':{'asset':'-1000000'}},
        {'account_id':'b.near','intent_hash':'b','diff':{'asset':'1000000'}}]})
    frame=pd.DataFrame([{'block_date':'2026-06-01','receipt_id':'r','caller':'relay.near','log':log,'execution_status':'SUCCESS_VALUE'}])
    path=tmp_path/'bq/l2_intents_events.csv'
    frame.to_csv(path,index=False)
    return tmp_path,path,frame


def test_duplicate_logs_cannot_double_volume(l2):
    root,path,frame=l2
    assert intents.run()['computed']
    original=pd.read_csv(root/'models/intents_daily.csv').volume_priced_usd.sum()
    pd.concat([frame,frame],ignore_index=True).to_csv(path,index=False)
    status=intents.run()
    assert not status['computed'] or pd.read_csv(root/'models/intents_daily.csv').volume_priced_usd.sum()==original


def test_truncated_event_must_not_produce_partial_metrics(l2):
    root,path,frame=l2
    corrupt=frame.copy()
    corrupt['receipt_id']='bad'
    corrupt['log']='EVENT_JSON:{"standard":"dip4","event":"token_diff","data":['
    pd.concat([frame,corrupt],ignore_index=True).to_csv(path,index=False)
    assert intents.run()['computed'] is False


def test_success_column_cannot_override_mismatched_attestation(l2,monkeypatch):
    root,path,frame=l2
    frame['window_day']='2026-06-01'
    frame['window_hour']=3
    frame['block_height']=7
    frame['block_timestamp']=1780272000000000000
    frame.to_csv(root/'blocks/intents_events_sampled.csv',index=False)
    path.unlink()
    monkeypatch.setattr(blocks,'BLOCKS',root/'blocks')
    pd.DataFrame({'date':['2026-06-01'],'intents_volume_usd':[100.],'blocks':[100000]}).to_csv(root/'derived/daily.csv',index=False)
    (root/'blocks/sample_manifest.json').write_text(json.dumps({'windows':[{'day':'2026-06-01','hour':3,'n':50,'fetched':50,'usable':True}]}))
    (root/'blocks/event_verification.json').write_text(json.dumps({'blocks_checked':1,'input_events':1,
        'accepted_events':1,'failed_events_removed':0,'input_sha256':'1'*64,'output_sha256':'0'*64}))
    # Real attestation schema, conflicting content. This is a local integrity
    # check; the existing committed-data CI test is a separate mitigation.
    assert intents.run()['computed'] is False


def test_valid_l2_control(l2):
    root,path,frame=l2
    status=intents.run()
    assert status['computed'] is True
    assert pd.read_csv(root/'models/intents_daily.csv').volume_priced_usd.sum()==1


def sampler_fixture(tmp_path,monkeypatch):
    cache=tmp_path/'cache';cache.mkdir()
    monkeypatch.setattr(blocks,'BLOCKS',tmp_path)
    monkeypatch.setattr(blocks,'CACHE',cache)
    monkeypatch.setattr(blocks.requests,'get',lambda *a,**kw:pytest.fail('network reached'))
    (tmp_path/'sample_plan.json').write_text(json.dumps([{'day':'2026-01-01','hour':3,'start_height':7}]))
    ev=tmp_path/'intents_events_sampled.csv';tx=tmp_path/'tx_sampled.csv'
    ev.write_text('original events');tx.write_text('original transactions')
    return ev,tx,cache


def test_offline_without_cache_preserves_existing_extracts(tmp_path,monkeypatch):
    ev,tx,cache=sampler_fixture(tmp_path,monkeypatch)
    try:
        blocks.run(offline=True,blocks_per_window=1)
    except ValueError:
        pass
    assert ev.read_text()=='original events'
    assert tx.read_text()=='original transactions'


def test_invalid_worker_count_cannot_truncate_extracts(tmp_path,monkeypatch):
    ev,tx,cache=sampler_fixture(tmp_path,monkeypatch)
    with pytest.raises(ValueError):
        blocks.run(offline=True,blocks_per_window=1,workers=0)
    assert ev.read_text()=='original events'
    assert tx.read_text()=='original transactions'


def test_qaa_unavailable_cannot_feed_old_predictive_features(tmp_path,monkeypatch):
    monkeypatch.setattr(qaa,'MODELS',tmp_path)
    monkeypatch.setattr(qaa,'load_inputs',lambda:None)
    monkeypatch.setattr(qaa,'load_sampled',lambda:None)
    pd.DataFrame({'month':['2026-01-01'],'available_at':['2026-02-01'],'qaa':[123.]}).to_csv(tmp_path/'qaa_causal_monthly.csv',index=False)
    assert qaa.run()['computed'] is False
    result=qaa.available_series(pd.date_range('2026-02-01',periods=5))
    assert result is None or result.isna().all()


@pytest.mark.parametrize('cutoff,expected_month,expected_qaa',[
    ('2026-03-31','2026-03',12.),('2026-03-01','2026-02',8.)])
def test_publisher_uses_actual_latest_complete_month(tmp_path,monkeypatch,cutoff,expected_month,expected_qaa):
    monkeypatch.setattr(onchain,'DERIVED',tmp_path)
    monkeypatch.setattr(onchain,'MODELS',tmp_path)
    monkeypatch.setattr(onchain,'ROOT',tmp_path)
    monkeypatch.setattr(onchain,'raw_manifest',lambda:[])
    (tmp_path/'THESIS.md').write_text('test')
    (tmp_path/'signal_ic.json').write_text('[]')
    pd.DataFrame({'date':[str((pd.Timestamp(cutoff)-pd.Timedelta(days=1)).date()),cutoff]}).to_csv(tmp_path/'daily.csv',index=False)
    pd.DataFrame({'month':['2026-02-01','2026-03-01'],'active_accounts':[10.,20.],
        'intents_volume_usd':[100.,200.],'usd_per_txn':[1.,2.]}).to_csv(tmp_path/'monthly.csv',index=False)
    pd.DataFrame({'month':['2026-02-01','2026-03-01'],'qaa':[8.,12.]}).to_csv(tmp_path/'qaa_monthly.csv',index=False)
    result=onchain.payload()
    assert result['month']==expected_month
    assert result['qaa']==expected_qaa


def test_constant_series_breaks_are_inconclusive_not_crash():
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        result=econ.detect_breaks(pd.Series(1.,index=pd.date_range('2024-01-01',periods=400)))
    assert not result['breaks']


def test_constant_series_johansen_is_inconclusive_not_crash():
    d=pd.DataFrame({'near_price':1.,'usage':1.},index=pd.date_range('2024-01-01',periods=800))
    result=econ.johansen(d,'usage',None)
    assert result['inference_valid'] is False


def test_infinite_chart_points_cannot_break_json():
    series=pd.Series([1.,np.inf],index=pd.date_range('2026-01-01',periods=2))
    points=charts._pts(series)
    json.dumps(points,allow_nan=False)


def test_committed_analytical_json_is_standards_compliant():
    def reject(value):raise ValueError('Non-JSON constant: '+value)
    failures=[]
    for path in Path('data/derived').rglob('*.json'):
        try:json.loads(path.read_text(),parse_constant=reject)
        except ValueError:failures.append(str(path))
    assert not failures,failures


def test_unknown_fetch_source_cannot_claim_success(monkeypatch):
    with pytest.raises((SystemExit,ValueError)):
        fetch.run(['typo-source'])


@pytest.mark.parametrize('log',[None,'','plain','EVENT_JSON:{','EVENT_JSON:[]'])
def test_non_events_are_ignored_by_low_level_parser(log):
    assert intents.parse_event(log) is None


@pytest.mark.parametrize('token',['nep141:fake-usdc.attacker.near','nep141:btc.attacker.near','nep141:wrap.near.attacker'])
def test_unknown_assets_remain_unpriced(token,monkeypatch):
    monkeypatch.setattr(intents,'_REGISTRY',{})
    assert intents.price_leg(token,10**24,{'near':4.,'bitcoin':80000.}) is None


def test_invalid_network_fails_before_any_signer_import(tmp_path,monkeypatch):
    monkeypatch.setenv('NEAR_NETWORK','invalid-network')
    with pytest.raises(SystemExit,match='testnet or mainnet'):
        asyncio.run(onchain.publish(dry_run=True))


@pytest.mark.parametrize('seed',range(20))
def test_balanced_multiuser_ledger_matches_independent_notional(seed,monkeypatch):
    """Known USD/NEAR prices and balanced economic sides supply a reference oracle."""
    monkeypatch.setattr(intents,'_REGISTRY',{'usd':('usdc',6,'usd-coin'),'near':('near',24,'near')})
    rng=np.random.default_rng(seed)
    n=int(rng.integers(2,9));values=[4*int(x) for x in rng.integers(1,100,n)]
    day='2026-06-01';rows=[]
    for i,value in enumerate(values):
        rows.extend([(day,'batch',f'user{i}',f'intent{i}','usd',-value*10**6),
                     (day,'batch',f'user{i}',f'intent{i}','near',(value//4)*10**24)])
    total=sum(values)
    rows.extend([(day,'batch','solver','solver-intent','usd',total*10**6),
                 (day,'batch','solver','solver-intent','near',-(total//4)*10**24)])
    legs=pd.DataFrame(rows,columns=['block_date','receipt_id','account','intent_hash','token','amount'])
    roles=pd.DataFrame([(day,f'user{i}',False) for i in range(n)]+[(day,'solver',True)],columns=['block_date','account','is_solver'])
    events=pd.DataFrame({'block_date':[day],'event':['token_diff']})
    result=intents.daily_metrics(legs,roles,events,{day:{'near':4.}}).iloc[0]
    assert result.volume_priced_usd==pytest.approx(total)
    assert result.users==n and result.solvers==1
    assert result.hhi_solver==1 and result.fully_priced_batch_share==1


@pytest.mark.parametrize('seed',range(10))
def test_hhi_scale_invariance_and_bounds(seed):
    weights=np.random.default_rng(seed).uniform(.01,100,8)
    value=intents.hhi(weights)
    assert 1/len(weights)<=value<=1
    assert intents.hhi(1000*weights)==pytest.approx(value)
