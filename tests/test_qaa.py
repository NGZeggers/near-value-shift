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
    assert {"automation", "miniapp_farming"} <= set(prof["label"])
    assert any(l.startswith("human") for l in prof["label"])
    df2 = df.assign(cluster=labels).merge(prof[["cluster", "label"]], on="cluster")
    human = df2[df2["account"].str.startswith("alice")]
    assert (human["label"].str.startswith("human")).mean() > 0.9
