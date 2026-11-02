"""L1: Quality-Adjusted Active Accounts (QAA) by behavioral clustering of account-months.

Inputs (from `make bq`): data/bigquery/l1_account_month_features.csv, data/bigquery/l1_account_month_actions.csv
Outputs (data/derived/models/): qaa_monthly.csv, qaa_clusters.csv, qaa_status.json
If the inputs are missing the layer writes qaa_status.json with computed=false and the reason, and every
downstream consumer (THESIS.md, dashboard) says "not computed" instead of inventing a number.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.metrics import silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import RobustScaler

from .config import BQ_DIR, MODELS

NUMERIC = ["log_txns", "active_day_share", "log_receivers", "self_share", "log_gap_median", "gap_cv",
           "fc_share", "transfer_share", "log_methods", "log_contracts", "intents_share", "log_deposit"]
NAME_CLASSES = ["tg", "sweat", "implicit", "named", "other"]
SAMPLE_MAX = 250_000


def load_inputs() -> pd.DataFrame | None:
    f1, f2 = BQ_DIR / "l1_account_month_features.csv", BQ_DIR / "l1_account_month_actions.csv"
    if not f1.exists():
        return None
    a = pd.read_csv(f1, parse_dates=["month"])
    if f2.exists():
        b = pd.read_csv(f2, parse_dates=["month"])
        a = a.merge(b, on=["month", "account"], how="left")
    return a


def featurize(df: pd.DataFrame) -> pd.DataFrame:
    x = pd.DataFrame(index=df.index)
    days = df["month"].dt.days_in_month
    x["log_txns"] = np.log1p(df["txns"])
    x["active_day_share"] = df["active_days"] / days
    x["log_receivers"] = np.log1p(df["distinct_receivers"])
    x["self_share"] = df["self_txns"] / df["txns"].clip(lower=1)
    x["log_gap_median"] = np.log1p(df.get("gap_median_s", pd.Series(np.nan, index=df.index)).fillna(days * 86400))
    x["gap_cv"] = df.get("gap_cv", pd.Series(np.nan, index=df.index)).fillna(1.0).clip(0, 5)
    actions = df.get("actions", pd.Series(np.nan, index=df.index)).fillna(0).clip(lower=1)
    x["fc_share"] = df.get("function_calls", pd.Series(0, index=df.index)).fillna(0) / actions
    x["transfer_share"] = df.get("transfers", pd.Series(0, index=df.index)).fillna(0) / actions
    x["log_methods"] = np.log1p(df.get("distinct_methods", pd.Series(0, index=df.index)).fillna(0))
    x["log_contracts"] = np.log1p(df.get("distinct_contracts", pd.Series(0, index=df.index)).fillna(0))
    x["intents_share"] = df.get("intents_actions", pd.Series(0, index=df.index)).fillna(0) / actions
    x["log_deposit"] = np.log1p(df.get("deposit_near", pd.Series(0, index=df.index)).fillna(0).clip(lower=0))
    for c in NAME_CLASSES:
        x[f"name_{c}"] = (df["name_class"] == c).astype(float)
    return x.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def fit_clusters(x: pd.DataFrame, *, k_range=range(3, 9)) -> tuple[np.ndarray, dict]:
    """HDBSCAN when installed (density-based, finds the bot blobs); otherwise GMM with BIC-selected k."""
    scaler = RobustScaler().fit(x[NUMERIC])
    z = np.hstack([scaler.transform(x[NUMERIC]), x[[f"name_{c}" for c in NAME_CLASSES]].to_numpy()])
    n = len(z)
    samp = np.sort(np.random.default_rng(7).choice(n, size=min(SAMPLE_MAX, n), replace=False))
    info: dict = {"n": int(n), "fit_sample": int(len(samp))}
    try:
        import hdbscan  # type: ignore
        model = hdbscan.HDBSCAN(min_cluster_size=max(50, int(0.005 * len(samp))), min_samples=25, prediction_data=True)
        model.fit(z[samp])
        labels = np.full(n, -1)
        labels[samp] = model.labels_
        rest = np.setdiff1d(np.arange(n), samp)
        if len(rest):
            labels[rest], _ = hdbscan.approximate_predict(model, z[rest])
        info["algorithm"] = "hdbscan"
        info["noise_share"] = float((labels == -1).mean())
    except ImportError:
        best, best_bic = None, np.inf
        for k in k_range:
            g = GaussianMixture(k, covariance_type="diag", random_state=0, n_init=2).fit(z[samp])
            b = g.bic(z[samp])
            if b < best_bic:
                best, best_bic = g, b
        labels = best.predict(z)
        info["algorithm"] = f"gmm_diag_k{best.n_components}_bic"
    ev = np.random.default_rng(3).choice(n, size=min(20_000, n), replace=False)
    mask = labels[ev] >= 0
    if mask.sum() > 100 and len(np.unique(labels[ev][mask])) > 1:
        info["silhouette_sample"] = float(silhouette_score(z[ev][mask], labels[ev][mask]))
    return labels, info


def label_clusters(df: pd.DataFrame, x: pd.DataFrame, labels: np.ndarray) -> pd.DataFrame:
    """Rule-based naming of clusters from their medians. These rules are the documented assumptions."""
    prof = x.assign(cluster=labels, txns=df["txns"].to_numpy()).groupby("cluster").median(numeric_only=True)
    prof["size"] = pd.Series(labels).value_counts()
    prof["share"] = prof["size"] / len(labels)
    names = {}
    for c, r in prof.iterrows():
        if c == -1:
            names[c] = "noise"
        elif r["intents_share"] > 0.2:
            names[c] = "intents_participant"
        elif r["txns"] >= 200 and r["gap_cv"] < 0.6:
            names[c] = "automation"
        elif r["name_tg"] + r["name_sweat"] >= 0.5 and r["log_contracts"] < np.log1p(2):
            names[c] = "miniapp_farming"
        elif r["txns"] >= 200:
            names[c] = "heavy_unlabeled"
        elif r["log_contracts"] >= np.log1p(2) or r["log_methods"] >= np.log1p(2):
            names[c] = "human_multi_app"
        else:
            names[c] = "human_light"
    prof["label"] = pd.Series(names)
    prof.index.name = "cluster"
    return prof.reset_index()


QUALITY = {"human_multi_app", "human_light", "intents_participant"}


def run() -> dict:
    df = load_inputs()
    if df is None:
        status = {"computed": False, "reason": "data/bigquery/l1_account_month_features.csv missing. Run `make bq` after docs/SETUP_BIGQUERY.md."}
        (MODELS / "qaa_status.json").write_text(json.dumps(status, indent=1))
        print("L1: not computed (no BigQuery extract)")
        return status
    x = featurize(df)
    labels, info = fit_clusters(x)
    prof = label_clusters(df, x, labels)
    df = df.assign(cluster=labels).merge(prof[["cluster", "label"]], on="cluster", how="left")
    monthly = df.groupby("month").agg(active_accounts_bq=("account", "nunique"))
    shares = df.pivot_table(index="month", columns="label", values="account", aggfunc="nunique").fillna(0)
    monthly = monthly.join(shares)
    monthly["qaa"] = shares[[c for c in shares.columns if c in QUALITY]].sum(axis=1)
    monthly["qaa_share"] = monthly["qaa"] / monthly["active_accounts_bq"]
    monthly.reset_index().to_csv(MODELS / "qaa_monthly.csv", index=False)
    prof.to_csv(MODELS / "qaa_clusters.csv", index=False)
    status = {"computed": True, **info, "months": int(monthly.shape[0]),
              "labels": prof.set_index("cluster")["label"].to_dict(), "quality_labels": sorted(QUALITY)}
    (MODELS / "qaa_status.json").write_text(json.dumps(status, indent=1, default=str))
    print(f"L1: {info['algorithm']} on {info['n']:,} account-months -> {len(prof)} clusters, QAA for {len(monthly)} months")
    return status
