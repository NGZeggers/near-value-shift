import pandas as pd
import pytest
import json
from types import SimpleNamespace
from near_thesis import bq


def test_freshness_runs_first_and_stale_data_stops_l1(tmp_path, monkeypatch):
    for name in ['q0_freshness','l1_accounts','l2_events']:
        (tmp_path / (name+'.sql')).write_text('SELECT 1')
    monkeypatch.setattr(bq, 'SQL_DIR', tmp_path)
    monkeypatch.setattr(bq, 'dry_run', lambda _: 0.01)
    executed = []
    def run(path, **kwargs):
        executed.append(path.stem)
        f = tmp_path / (path.stem+'.csv')
        pd.DataFrame({'last_block_date':['2020-01-01']}).to_csv(f,index=False)
        return f
    monkeypatch.setattr(bq,'run_query',run)
    with pytest.raises(SystemExit, match='stale'):
        bq.run(['l1_accounts'])
    assert executed == ['q0_freshness']


def fake_service(tmp_path, monkeypatch, *, cost=2_000_000_000, estimate=0.1, billed=None):
    for name in ['q0_freshness', 'l1_accounts', 'l2_events']:
        (tmp_path / (name + '.sql')).write_text(name)
    monkeypatch.setattr(bq, 'SQL_DIR', tmp_path)
    monkeypatch.setattr(bq, 'BQ_DIR', tmp_path)
    attempts, estimates = [], []
    class Job:
        total_bytes_processed = cost
        total_bytes_billed = billed
        job_id = 'audit-job'
        def result(self): return self
        def to_dataframe(self):
            return pd.DataFrame({'last_block_date': [pd.Timestamp.now(tz='UTC').date().isoformat()]})
    class Client:
        def query(self, sql, job_config):
            if getattr(job_config, 'dry_run', False):
                estimates.append(sql)
                return SimpleNamespace(total_bytes_processed=int(estimate * 1e9))
            cap = job_config.maximum_bytes_billed
            attempts.append((sql, cap))
            if cap is not None and max(cost, billed or 0) > cap:
                raise RuntimeError('maximum_bytes_billed exceeded')
            return Job()
    monkeypatch.setattr(bq, '_client', lambda: (SimpleNamespace(QueryJobConfig=lambda **kw: SimpleNamespace(**kw)), Client()))
    return attempts, estimates


def test_actual_usage_limits_next_query_even_when_estimate_drifted(tmp_path, monkeypatch):
    attempts, estimates = fake_service(tmp_path, monkeypatch)
    monkeypatch.setenv('BQ_MAX_GB_PER_RUN', '3')
    monkeypatch.setattr(bq, 'BQ_MAX_GB_PER_QUERY', 120)
    with pytest.raises(RuntimeError, match='maximum_bytes_billed'):
        bq.run()
    assert attempts == [('q0_freshness', 3_000_000_000), ('l1_accounts', 1_000_000_000)]
    assert estimates == ['q0_freshness', 'l1_accounts']  # one estimate per query
    assert (tmp_path/'q0_freshness.csv').exists()
    assert not (tmp_path/'l1_accounts.csv').exists()


def test_billed_bytes_are_accounted_and_force_cannot_remove_run_cap(tmp_path, monkeypatch):
    attempts, _ = fake_service(tmp_path, monkeypatch, cost=1_000_000_000, billed=2_000_000_000)
    monkeypatch.setenv('BQ_MAX_GB_PER_RUN', '3')
    monkeypatch.setattr(bq, 'BQ_MAX_GB_PER_QUERY', .5)
    with pytest.raises(RuntimeError, match='maximum_bytes_billed'):
        bq.run(force=True)
    assert [cap for _, cap in attempts] == [3_000_000_000, 1_000_000_000]
    meta = json.loads((tmp_path/'q0_freshness.meta.json').read_text())
    assert meta['accounted_bytes'] == 2_000_000_000


def test_single_query_cannot_exceed_query_cap(tmp_path, monkeypatch):
    attempts, _ = fake_service(tmp_path, monkeypatch, estimate=2)
    monkeypatch.setattr(bq, 'BQ_MAX_GB_PER_QUERY', 1)
    with pytest.raises(SystemExit, match='refused'):
        bq.run()
    assert not attempts


@pytest.mark.parametrize('budget', ['0', '-1', 'nan', 'inf'])
def test_invalid_run_budget_is_rejected(tmp_path, monkeypatch, budget):
    attempts, _ = fake_service(tmp_path, monkeypatch)
    monkeypatch.setenv('BQ_MAX_GB_PER_RUN', budget)
    with pytest.raises(SystemExit, match='positive and finite'):
        bq.run()
    assert not attempts
