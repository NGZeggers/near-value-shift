import pandas as pd
import pytest
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
