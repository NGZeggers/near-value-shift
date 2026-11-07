import numpy as np
import pandas as pd

from near_thesis import qaa


def synthetic(n=3000, seed=1):
    rng = np.random.default_rng(seed)
    months = pd.to_datetime(["2025-01-01", "2025-02-01"])
    rows = []
    for i in range(n):
        kind = rng.choice(["bot", "farm", "human"], p=[0.3, 0.4, 0.3])
        m = months[i % 2]
        if kind == "bot":
            rows.append(dict(month=m, account=f"relayer{i}.near", txns=int(rng.integers(500, 5000)), active_days=28,
                             distinct_receivers=2, self_txns=0, gap_median_s=30, gap_cv=0.2, name_class="named",
                             actions=600, function_calls=600, transfers=0, distinct_methods=1, distinct_contracts=1,
                             intents_actions=0, deposit_near=0))
        elif kind == "farm":
            rows.append(dict(month=m, account=f"user{i}.tg", txns=int(rng.integers(5, 40)), active_days=int(rng.integers(3, 20)),
                             distinct_receivers=1, self_txns=0, gap_median_s=86400, gap_cv=1.5, name_class="tg",
                             actions=20, function_calls=20, transfers=0, distinct_methods=1, distinct_contracts=1,
                             intents_actions=0, deposit_near=0))
        else:
            rows.append(dict(month=m, account=f"alice{i}.near", txns=int(rng.integers(2, 60)), active_days=int(rng.integers(1, 15)),
                             distinct_receivers=int(rng.integers(3, 12)), self_txns=1, gap_median_s=40000, gap_cv=2.0,
                             name_class="named", actions=30, function_calls=20, transfers=10, distinct_methods=6,
                             distinct_contracts=5, intents_actions=0, deposit_near=3.5))
    return pd.DataFrame(rows)


def test_featurize_and_cluster_recovers_groups():
    df = synthetic()
    x = qaa.featurize(df)
    assert list(x.columns[: len(qaa.NUMERIC)]) == qaa.NUMERIC
    labels, info = qaa.fit_clusters(x, k_range=range(3, 5))
    prof = qaa.label_clusters(df, x, labels)
    assert {"high_frequency_regular", "miniapp_pattern"} <= set(prof["label"])
    assert set(prof["label"]) & {"light_general", "multi_app"}
    df2 = df.assign(cluster=labels).merge(prof[["cluster", "label"]], on="cluster")
    diverse = df2[df2["account"].str.startswith("alice")]
    assert diverse["label"].isin(qaa.QUALITY).mean() > 0.9
    assert not any("human" in l or "bot" in l for l in prof["label"])  # names describe behavior, not identity


def test_inclusion_weights_undo_visibility_differences():
    w = qaa.inclusion_weights(pd.Series([1, 2, 4, 4]), pd.Series([4, 4, 4, 4]))
    assert w.iloc[3] == 1.0                      # active in every window: always observed
    assert w.iloc[0] > w.iloc[1] > w.iloc[2]    # rarely active accounts are under-observed and weigh more
    assert abs(w.iloc[0] - 1 / (1 - 0.75 ** 4)) < 1e-12


def test_legacy_identity_labels_are_migrated_in_frozen_model(tmp_path, monkeypatch):
    import json
    df = synthetic(n=800)
    df['month'] = pd.date_range('2025-01-01', periods=8, freq='MS').repeat(100)
    monkeypatch.setattr(qaa, 'MODELS', tmp_path)
    qaa.causal_monthly(df, qaa.featurize(df), sampled=False)
    path = tmp_path / 'qaa_causal_model.json'
    saved = json.loads(path.read_text())
    saved['labels'] = {k: {'light_general': 'human_light', 'multi_app': 'human_multi_app', 'miniapp_pattern': 'miniapp_farming'}.get(v, v) for k, v in saved['labels'].items()}
    path.write_text(json.dumps(saved))
    qaa.causal_monthly(df, qaa.featurize(df), sampled=False)
    labels = set(json.loads(path.read_text())['labels'].values())
    assert not labels & set(qaa.LEGACY_LABELS)
    assert labels <= set(qaa.GROUP_DEFINITIONS)


def test_assignment_hash_preserves_magnitude_schema_and_keys():
    x = pd.DataFrame([[0.01, 2.]], columns=['share', 'count'], index=['alice'])
    assert qaa._input_hash(x) != qaa._input_hash(x * 10)
    assert qaa._input_hash(x) != qaa._input_hash(x.rename(index={'alice': 'bob'}))
    assert qaa._input_hash(x) != qaa._input_hash(x.rename(columns={'share': 'other'}))


def test_frozen_qaa_cannot_use_future_months(tmp_path, monkeypatch):
    df = synthetic(n=800)
    df['month'] = pd.date_range('2025-01-01', periods=8, freq='MS').repeat(100)
    monkeypatch.setattr(qaa, 'MODELS', tmp_path)
    first = df[df.month < '2025-08-01'].copy()
    qaa.causal_monthly(first, qaa.featurize(first), sampled=False)
    before = pd.read_csv(tmp_path / 'qaa_causal_monthly.csv')
    model = (tmp_path / 'qaa_causal_model.json').read_bytes()
    df.loc[df.month == '2025-08-01', 'txns'] *= 100
    qaa.causal_monthly(df, qaa.featurize(df), sampled=False)
    after = pd.read_csv(tmp_path / 'qaa_causal_monthly.csv')
    pd.testing.assert_frame_equal(before, after.iloc[:1].reset_index(drop=True))
    assert model == (tmp_path / 'qaa_causal_model.json').read_bytes()
    index = pd.date_range('2025-07-01', '2025-08-02')
    series = qaa.available_series(index)
    assert series.loc[:'2025-07-31'].isna().all()
    assert pd.notna(series.loc['2025-08-01'])


def test_inclusion_from_intraday_measures_fixed_window_coverage(tmp_path):
    """Accounts active in one window are seen by the two fixed windows with probability 2/24; heavy accounts are always seen."""
    rows = []
    rng = np.random.default_rng(0)
    for i in range(240):                       # light .tg accounts: one random window each
        rows.append(dict(window_day="2026-01-01", window_hour=int(rng.integers(0, 24)), signer=f"u{i}.tg", txns=1, distinct_receivers=1,
                         distinct_methods=1, function_calls=1, transfers=0, self_txns=0, intents_actions=0, blocks_active=1))
    for i in range(10):                        # heavy named accounts: every window
        for h in range(24):
            rows.append(dict(window_day="2026-01-01", window_hour=h, signer=f"bot{i}.near", txns=20, distinct_receivers=2,
                             distinct_methods=1, function_calls=20, transfers=0, self_txns=0, intents_actions=0, blocks_active=20))
    f = tmp_path / "signers.csv"
    pd.DataFrame(rows).to_csv(f, index=False)
    out = qaa.inclusion_from_intraday(f)
    p = out["pooled"]
    assert p["accounts_24_windows"] == 250 and p["inclusion_by_activity"]["9-24 windows"]["inclusion"] == 1.0
    assert 0.02 < p["inclusion_by_activity"]["1 window"]["inclusion"] < 0.2          # about 2/24 of the light accounts
    nq = p["name_only_quality_share"]
    assert nq["fixed_windows"] > nq["all_24_windows"]                                   # fixed windows over-represent the heavy named accounts
    assert nq["fixed_windows_inclusion_weighted"] < nq["fixed_windows"]                 # the weighting moves toward the fuller observation
    assert out["kind"].startswith("observed") and out["weighting_check"]["days_compared"] == 1
    assert qaa.inclusion_from_intraday(tmp_path / "missing.csv") is None


def test_refit_variants_report_agreement_and_shares():
    df = synthetic(n=2000, seed=4).sort_values(["month", "account"]).reset_index(drop=True)
    x = qaa.featurize(df)
    committed, _ = qaa.fit_clusters(x)
    res = qaa.refit_variants(df, x, committed, pd.DatetimeIndex(sorted(df["month"].unique())))
    assert len(res["variants"]) == len(qaa.REFIT_GRID) and res["kind"] == "sensitivity"
    same = res["variants"][0]
    assert same["algorithm"] == "hdbscan" and same["adjusted_rand_index_vs_committed"] > 0.95   # the committed parameters refit on the same machine
    for v in res["variants"]:
        assert -0.5 <= v["adjusted_rand_index_vs_committed"] <= 1.0
        assert 0 <= v["latest_month_share"]["default"] <= 1
    lo, hi = res["default_share_range"]
    assert lo <= same["latest_month_share"]["default"] <= hi
