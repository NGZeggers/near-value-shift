"""L1: Quality-Adjusted Active Accounts (QAA) by behavioral clustering of account-months.

Inputs (from `make bq`): data/bigquery/l1_account_month_features.csv, data/bigquery/l1_account_month_actions.csv
Outputs (data/derived/models/): qaa_monthly.csv, qaa_clusters.csv, qaa_status.json
If the inputs are missing the layer writes qaa_status.json with computed=false and the reason, and every
downstream consumer (THESIS.md, dashboard) says "not computed" instead of inventing a number.
"""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np
import pandas as pd
from sklearn.metrics import silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import RobustScaler

from .config import BQ_DIR, DATA, DERIVED, MODELS

NUMERIC = ["log_txns", "active_day_share", "log_receivers", "self_share", "log_gap_median", "gap_cv",
           "fc_share", "transfer_share", "log_methods", "log_contracts", "intents_share", "log_deposit"]
NAME_CLASSES = ["tg", "sweat", "implicit", "named", "other"]
SAMPLE_MAX = 250_000
METHOD_VERSION = "qaa-v3-self-calls-windows"


def load_inputs() -> pd.DataFrame | None:
    f1, f2 = BQ_DIR / "l1_account_month_features.csv", BQ_DIR / "l1_account_month_actions.csv"
    if not f1.exists():
        return None
    a = pd.read_csv(f1, parse_dates=["month"])
    if f2.exists():
        b = pd.read_csv(f2, parse_dates=["month"])
        a = a.merge(b, on=["month", "account"], how="left")
    return a


def load_sampled() -> pd.DataFrame | None:
    """Account-month features from sampled blocks (data/blocks/tx_sampled.csv). Same columns as the BigQuery extract,
    computed within the sampled windows only; active_days counts sampled windows with activity."""
    f = DATA / "blocks" / "tx_sampled.csv"
    if not f.exists():
        return None
    t = pd.read_csv(f)
    if t.empty:
        return None
    from .blocks import usable_windows
    ok = usable_windows()
    if ok is not None:
        t = t[[(d, int(h)) in ok for d, h in zip(t["window_day"], t["window_hour"])]].copy()  # windows with only planning probes carry no signal
        if t.empty:
            return None
    t["month"] = pd.to_datetime(t["window_day"]).dt.to_period("M").dt.to_timestamp()
    t["window"] = t["window_day"] + "T" + t["window_hour"].astype(str)
    t["deposit"] = pd.to_numeric(t["deposit"], errors="coerce").fillna(0)
    t["is_self"] = t["signer"].eq(t["receiver"])
    g = t.sort_values("block_timestamp").groupby(["month", "signer"])
    base = g.agg(txns=("receiver", "size"), active_days=("window", "nunique"), distinct_receivers=("receiver", "nunique"),
                 self_txns=("is_self", "sum"),
                 actions=("action_kind", "size"), function_calls=("action_kind", lambda a: int((a == "FUNCTION_CALL").sum())),
                 transfers=("action_kind", lambda a: int((a == "TRANSFER").sum())), distinct_methods=("method", "nunique"),
                 distinct_contracts=("receiver", "nunique"), intents_actions=("receiver", lambda r: int((r == "intents.near").sum())),
                 deposit_near=("deposit", lambda d: float(d.sum()) / 1e24)).reset_index().rename(columns={"signer": "account"})
    # inter-arrival gaps are measured inside a window only (gaps across windows are sampling artefacts)
    gaps = t.sort_values("block_timestamp").groupby(["month", "signer", "window"])["block_timestamp"].apply(lambda x: x.diff().dropna() / 1e9)
    gs = gaps.groupby(level=[0, 1]).agg(gap_median_s="median", gap_cv=lambda x: float(x.std() / x.mean()) if len(x) > 1 and x.mean() else np.nan).reset_index().rename(columns={"signer": "account"})
    df = base.merge(gs, on=["month", "account"], how="left")
    windows = t.groupby("month")["window"].nunique()
    df["observation_periods"] = df["month"].map(windows)
    a = df["account"].astype(str)
    df["name_class"] = np.select([a.str.endswith(".tg"), a.str.endswith(".sweat"), a.str.fullmatch(r"[0-9a-f]{64}"), a.str.endswith(".near")],
                                 ["tg", "sweat", "implicit", "named"], "other")
    return df


def featurize(df: pd.DataFrame) -> pd.DataFrame:
    x = pd.DataFrame(index=df.index)
    days = df["month"].dt.days_in_month
    x["log_txns"] = np.log1p(df["txns"])
    x["active_day_share"] = df["active_days"] / df.get("observation_periods", days)
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
    ev = np.random.default_rng(3).choice(n, size=min(3_000, n), replace=False)
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


def _input_hash(x: pd.DataFrame) -> str:
    """Canonical decimal serialization retains exponents, schema, row keys and method version."""
    h = hashlib.sha256(json.dumps([METHOD_VERSION, list(x.columns), [str(i) for i in x.index]], separators=(",", ":")).encode())
    for row in x.to_numpy(dtype=float):
        h.update((",".join(format(float(v), ".6g") if v else "0" for v in row) + "\n").encode())
    return h.hexdigest()


def causal_monthly(df: pd.DataFrame, x: pd.DataFrame, *, sampled: bool, calibration_months: int = 6) -> dict:
    """Freeze a GMM on the first six months; later months never change the calibration.

    Labels describe behavior, not verified people. Publish each result only on the first day
    of the following month. The model parameters and calibration hash are committed JSON.
    """
    months = sorted(df["month"].unique())
    if len(months) <= calibration_months:
        pd.DataFrame(columns=["month", "available_at", "qaa"]).to_csv(MODELS / "qaa_causal_monthly.csv", index=False)
        return {"computed": False, "reason": "not enough months after calibration"}
    cutoff = pd.Timestamp(months[calibration_months])
    train = df["month"] < cutoff
    calibration = x.loc[train].copy()
    calibration.index = pd.MultiIndex.from_frame(df.loc[train, ["month", "account"]])
    key = _input_hash(calibration)
    path = MODELS / "qaa_causal_model.json"
    saved = json.loads(path.read_text()) if path.exists() else {}
    if saved.get("calibration_sha256") != key or os.getenv("QAA_REFIT"):
        scaler = RobustScaler().fit(x.loc[train, NUMERIC])
        z = np.hstack([scaler.transform(x.loc[train, NUMERIC]), x.loc[train, [f"name_{c}" for c in NAME_CLASSES]].to_numpy()])
        # Bound calibration work without using any price/return data to choose the model.
        ix = np.sort(np.random.default_rng(19).choice(len(z), min(10_000, len(z)), replace=False))
        models = [GaussianMixture(k, covariance_type="diag", random_state=19, n_init=2).fit(z[ix]) for k in range(3, 7) if k <= len(ix)]
        model = min(models, key=lambda a: a.bic(z[ix]))
        prof = label_clusters(df.loc[train].reset_index(drop=True), x.loc[train].reset_index(drop=True), model.predict(z))
        saved = {"method": "frozen_calibration_gmm_diag_bic", "calibration_sha256": key,
                 "training_start": str(pd.Timestamp(months[0]).date()), "training_end": str((cutoff - pd.Timedelta(days=1)).date()),
                 "first_prediction_month": str(cutoff.date()), "calibration_months": calibration_months,
                 "center": scaler.center_.tolist(), "scale": scaler.scale_.tolist(),
                 "means": model.means_.tolist(), "variances": model.covariances_.tolist(), "weights": model.weights_.tolist(),
                 "labels": {str(int(r.cluster)): r.label for r in prof.itertuples()}, "k": model.n_components}
        # Serialize before inference, so persisted parameter precision is exactly what predictions use.
        saved = json.loads(json.dumps(saved, default=lambda v: int(v)))
        path.write_text(json.dumps(saved, indent=1) + "\n")
    pred = df.loc[~train].copy()
    xp = x.loc[~train]
    z = np.hstack([(xp[NUMERIC].to_numpy() - np.array(saved["center"])) / np.array(saved["scale"]),
                   xp[[f"name_{c}" for c in NAME_CLASSES]].to_numpy()])
    means, var = np.array(saved["means"]), np.array(saved["variances"])
    scores = np.array([np.log(w) - 0.5 * (np.log(2 * np.pi * v).sum() + ((z - mu) ** 2 / v).sum(axis=1))
                       for w, mu, v in zip(saved["weights"], means, var)])
    pred["label"] = [saved["labels"][str(int(k))] for k in scores.argmax(axis=0)]
    result = pred.groupby("month").agg(accounts=("account", "nunique"))
    result["qaa_share"] = pred.assign(quality=pred["label"].isin(QUALITY)).groupby("month")["quality"].mean()
    if sampled:
        nb = pd.read_csv(DERIVED / "monthly.csv", parse_dates=["month"]).set_index("month")["active_accounts"]
        result["accounts"] = nb.reindex(result.index)
    result["qaa"] = result["accounts"] * result["qaa_share"]
    result["available_at"] = result.index + pd.offsets.MonthBegin(1)
    result.reset_index().to_csv(MODELS / "qaa_causal_monthly.csv", index=False)
    return {"computed": True, "method": saved["method"], "training_end": saved["training_end"],
            "first_available_at": str(result["available_at"].min().date()), "months": len(result), "k": saved["k"]}


def available_series(index: pd.DatetimeIndex) -> pd.Series | None:
    """Only the frozen, out-of-calibration QAA is allowed in predictive models."""
    f = MODELS / "qaa_causal_monthly.csv"
    if not f.exists():
        return None
    q = pd.read_csv(f, parse_dates=["available_at"])
    if q.empty:
        return None
    return q.set_index("available_at")["qaa"].reindex(index, method="ffill")


def run() -> dict:
    df = load_inputs()
    source = "bigquery"
    if df is None:
        df = load_sampled()
        source = "neardata block sample"
    if df is None:
        status = {"computed": False, "reason": "no data/bigquery/l1_*.csv (make bq) and no data/blocks/tx_sampled.csv (make blocks)."}
        (MODELS / "qaa_status.json").write_text(json.dumps(status, indent=1))
        print("L1: not computed (no on-chain extract)")
        return status
    if source != "bigquery":
        df = df[df["txns"] >= 1]
    df = df.sort_values(["month", "account"]).reset_index(drop=True)
    x = featurize(df)
    keyed = x.copy()
    keyed.index = pd.MultiIndex.from_frame(df[["month", "account"]])
    input_key = _input_hash(keyed)
    # The fitted assignment is a committed model artifact: HDBSCAN flips a few borderline points between platforms
    # (BLAS differences), which would make THESIS.md differ by a fraction of a percent per machine. The build reuses
    # the committed assignment when it matches the input exactly; `QAA_REFIT=1 make models` refits and rewrites it.
    assign_path = MODELS / "qaa_assignments.csv"
    key_cols = ["month", "account"]
    reuse = assign_path.exists() and not os.getenv("QAA_REFIT")
    if reuse:
        prev = pd.read_csv(assign_path, parse_dates=["month"])
        same_rows = len(prev) == len(df) and prev[key_cols].merge(df[key_cols], on=key_cols).shape[0] == len(df)
        reuse = same_rows and prev["input_sha256"].iloc[0] == input_key
    if reuse:
        labels = df[key_cols].merge(prev, on=key_cols, how="left")["cluster"].to_numpy()
        info = json.loads(prev["fit_info"].iloc[0])
    else:
        labels, info = fit_clusters(x)
        pd.DataFrame({"month": df["month"].to_numpy(), "account": df["account"].to_numpy(), "cluster": labels,
                      "input_sha256": input_key, "fit_info": json.dumps(info, default=str)}).to_csv(assign_path, index=False)
    prof = label_clusters(df, x, labels)
    df = df.assign(cluster=labels).merge(prof[["cluster", "label"]], on="cluster", how="left")
    monthly = df.groupby("month").agg(active_accounts_bq=("account", "nunique"))
    shares = df.pivot_table(index="month", columns="label", values="account", aggfunc="nunique").fillna(0)
    monthly = monthly.join(shares)
    monthly["qaa"] = shares[[c for c in shares.columns if c in QUALITY]].sum(axis=1)
    monthly["qaa_share"] = monthly["qaa"] / monthly["active_accounts_bq"]
    monthly["quality_share_strict"] = shares.get("human_multi_app", pd.Series(0, index=shares.index)) / monthly["active_accounts_bq"]
    monthly["quality_share_including_ambiguous"] = 1 - shares[[c for c in shares if c in {"automation", "miniapp_farming"}]].sum(axis=1) / monthly["active_accounts_bq"]
    if source != "bigquery":
        # sampled mode: the share is the estimate; scale it by NearBlocks' monthly mean of daily active accounts
        nb = pd.read_csv(DERIVED / "monthly.csv", parse_dates=["month"]).set_index("month")["active_accounts"]
        monthly["qaa_share_sampled"] = monthly["qaa_share"]
        monthly["active_accounts_bq"] = nb.reindex(monthly.index)
        monthly["qaa"] = monthly["qaa_share"] * monthly["active_accounts_bq"]
    monthly.reset_index().to_csv(MODELS / "qaa_monthly.csv", index=False)
    prof.to_csv(MODELS / "qaa_clusters.csv", index=False)
    # Proxy anchors are assumptions; never report this as human/bot ground-truth accuracy.
    anchors = np.where(df["account"].str.endswith((".tg", ".sweat")), "miniapp_name_proxy", "unverified")
    pd.crosstab(pd.Series(anchors, name="anchor_proxy"), df["label"]).to_csv(MODELS / "qaa_anchor_profiles.csv")
    causal = causal_monthly(df, x, sampled=source != "bigquery")
    status = {"computed": True, "source": source, **info, "months": int(monthly.shape[0]),
              "labels": prof.set_index("cluster")["label"].to_dict(), "quality_labels": sorted(QUALITY),
              "method_version": METHOD_VERSION, "causal": causal,
              "validation": "silhouette is geometric separation; anchor profiles use name proxies, not verified people; sensitivity shares reported monthly"}
    (MODELS / "qaa_status.json").write_text(json.dumps(status, indent=1, default=str))
    print(f"L1: {info['algorithm']} on {info['n']:,} account-months -> {len(prof)} clusters, QAA for {len(monthly)} months")
    return status
