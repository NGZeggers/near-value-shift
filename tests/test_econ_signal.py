import numpy as np
import pandas as pd

from near_thesis import econ, signal


def test_detect_breaks_finds_level_shift():
    idx = pd.date_range("2024-01-01", periods=600, freq="D")
    rng = np.random.default_rng(0)
    level = np.r_[np.full(300, 1000.0), np.full(300, 10000.0)] * np.exp(rng.normal(0, 0.05, 600))
    res = econ.detect_breaks(pd.Series(level, index=idx), min_size=60)
    assert len(res["breaks"]) >= 1
    first = pd.Timestamp(res["breaks"][0])
    assert abs((first - idx[300]).days) <= 10


def test_adf_detects_random_walk_vs_noise():
    rng = np.random.default_rng(1)
    noise = pd.Series(rng.normal(size=400))
    walk = pd.Series(np.cumsum(rng.normal(size=400)))
    assert econ.adf(noise)["stationary_5pct"] is True
    assert econ.adf(walk)["stationary_5pct"] is False


def test_block_bootstrap_ci_contains_rho_and_is_wide_for_independent_series():
    rng = np.random.default_rng(2)
    x = rng.normal(size=200)
    y = 0.6 * x + rng.normal(size=200)
    lo, hi = signal.block_bootstrap_ci(x, y, block=4, n_boot=300)
    assert lo > 0.3 and hi < 0.8
    lo2, hi2 = signal.block_bootstrap_ci(x, rng.normal(size=200), block=4, n_boot=300)
    assert lo2 < 0 < hi2


def test_var_does_not_infer_when_stationarity_is_unestablished(monkeypatch):
    idx = pd.date_range('2024-01-01', periods=800)
    d = pd.DataFrame({'near_price':np.arange(800)+10., 'usage':np.arange(800)+20.}, index=idx)
    monkeypatch.setattr(econ, 'adf', lambda s: {'stationary_5pct':False,'p_value':0.5})
    r = econ.var_granger(d, 'usage', None)
    assert r['inference_valid'] is False
    assert 'usage_granger_causes_price' not in r


def test_johansen_full_rank_is_not_reported_as_absence(monkeypatch):
    from types import SimpleNamespace
    idx = pd.date_range('2024-01-01', periods=800)
    d = pd.DataFrame({'near_price':np.arange(800)+10., 'usage':np.arange(800)+20.}, index=idx)
    monkeypatch.setattr(econ, 'coint_johansen', lambda *a,**k: SimpleNamespace(lr1=np.array([25.,6.]), cvt=np.array([[10,15,20],[2,3.8,5]])))
    r = econ.johansen(d, 'usage', None)
    assert r['rank_5pct'] == 2
    assert r['cointegrated_5pct'] is None and r['inference_valid'] is False


def test_bootstrap_is_reproducible_between_calls():
    rng = np.random.default_rng(42)
    x,y = rng.normal(size=(2,80))
    first = signal.block_bootstrap_ci(x,y,8,n_boot=100)
    signal.block_bootstrap_ci(y,x,4,n_boot=150)
    assert signal.block_bootstrap_ci(x,y,8,n_boot=100) == first
