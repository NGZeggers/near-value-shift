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
