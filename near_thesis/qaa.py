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

# Group names describe observed behavior only. No label asserts that an account is a human or a bot: the project has
# no verified identity anchors, so names that implied identity were retired (see LEGACY_LABELS).
GROUP_RULES = [
    ("intents_participant", "median share of actions sent to intents.near above 20%"),
    ("high_frequency_regular", "median of at least 200 transactions per month with regular inter-arrival gaps (gap CV below 0.6)"),
    ("miniapp_pattern", "at least half of the accounts carry a .tg or .sweat name and the median account touches fewer than two contracts"),
    ("heavy_unclassified", "median of at least 200 transactions per month without a regular gap pattern"),
    ("multi_app", "median account touches at least two contracts or two methods"),
    ("light_general", "none of the above: few actions, no mini-app name pattern"),
    ("noise", "HDBSCAN outliers, not assigned to any group"),
]
GROUP_DEFINITIONS = dict(GROUP_RULES)
LEGACY_LABELS = {"human_light": "light_general", "human_multi_app": "multi_app", "miniapp_farming": "miniapp_pattern",
                 "automation": "high_frequency_regular", "heavy_unlabeled": "heavy_unclassified"}
QUALITY = {"multi_app", "light_general", "intents_participant"}          # the default QAA numerator
NON_QUALITY = {"high_frequency_regular", "miniapp_pattern"}              # excluded under every criterion
# strict = multi_app only; default = QUALITY; broad = everything except NON_QUALITY (noise and heavy_unclassified count)
CRITERIA = {"strict": "multi_app only", "default": "multi_app, light_general and intents_participant",
            "including_ambiguous": "all groups except high_frequency_regular and miniapp_pattern (noise and heavy_unclassified count)"}


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


def label_clusters(df: pd.DataFrame, x: pd.DataFrame, labels: np.ndarray, *, heavy_txns: int = 200, multi_contracts: int = 2) -> pd.DataFrame:
    """Rule-based naming of clusters from their medians (GROUP_RULES). The thresholds are documented assumptions;
    `sensitivity` re-runs them with alternative values."""
    prof = x.assign(cluster=labels, txns=df["txns"].to_numpy()).groupby("cluster").median(numeric_only=True)
    prof["size"] = pd.Series(labels).value_counts()
    prof["share"] = prof["size"] / len(labels)
    names = {}
    for c, r in prof.iterrows():
        if c == -1:
            names[c] = "noise"
        elif r["intents_share"] > 0.2:
            names[c] = "intents_participant"
        elif r["txns"] >= heavy_txns and r["gap_cv"] < 0.6:
            names[c] = "high_frequency_regular"
        elif r["name_tg"] + r["name_sweat"] >= 0.5 and r["log_contracts"] < np.log1p(multi_contracts):
            names[c] = "miniapp_pattern"
        elif r["txns"] >= heavy_txns:
            names[c] = "heavy_unclassified"
        elif r["log_contracts"] >= np.log1p(multi_contracts) or r["log_methods"] >= np.log1p(multi_contracts):
            names[c] = "multi_app"
        else:
            names[c] = "light_general"
    prof["label"] = pd.Series(names)
    prof.index.name = "cluster"
    return prof.reset_index()


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
    if saved.get("labels") and any(v in LEGACY_LABELS for v in saved["labels"].values()):
        # identity-sounding names were retired; the frozen parameters are unchanged
        saved["labels"] = {k: LEGACY_LABELS.get(v, v) for k, v in saved["labels"].items()}
        path.write_text(json.dumps(saved, indent=1) + "\n")
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


def inclusion_weights(active_windows: pd.Series, observed_windows: pd.Series) -> pd.Series:
    """Weights that undo the higher visibility of frequently active accounts.

    An account active in a of the W sampled windows has an estimated per-window activity probability a/W and is seen
    at least once with probability 1 - (1 - a/W)^W. Weighting each observed account by the inverse of that probability
    corrects the share only among accounts active in at least one window; accounts never seen stay unobserved."""
    a = active_windows.clip(lower=1).astype(float)
    w = observed_windows.clip(lower=1).astype(float)
    p = 1 - (1 - (a / w).clip(upper=1)) ** w
    return 1 / p.clip(lower=1e-9)


def sensitivity(df: pd.DataFrame, x: pd.DataFrame, labels: np.ndarray, monthly: pd.DataFrame, *, sampled: bool) -> dict:
    """How much the quality share depends on the criterion, the labeling thresholds, the model, the hour of
    observation and the inclusion probability of accounts. All variants reuse the committed cluster assignment."""
    lab = pd.Series(labels, index=df.index)
    quality = lab.map(lambda l: l in QUALITY) if "label" not in df else df["label"].isin(QUALITY)
    last = monthly.index[-1]
    last_rows = df["month"] == last
    seen_once = float((df["txns"] == 1).mean())
    one_window = float((df["active_days"] == 1).mean())
    # criterion: which groups count
    lm = monthly.iloc[-1]
    criteria = {"strict": float(lm["quality_share_strict"]), "default": float(lm["qaa_share"]), "including_ambiguous": float(lm["quality_share_including_ambiguous"]),
                "groups_counted": {"strict": ["multi_app"], "default": sorted(QUALITY), "including_ambiguous": sorted(set(df["label"].unique()) - NON_QUALITY)},
                "why_strict_is_low": (f"{seen_once:.0%} of account-months show exactly one transaction inside the sampled windows and {one_window:.0%} are active in a "
                                      "single window, so multi-contract behavior is rarely observable; no cluster reaches a median of two contracts")}
    # labeling thresholds
    variants = {}
    for ht, mc in [(100, 2), (200, 1), (400, 2), (200, 3)]:
        prof = label_clusters(df, x, labels, heavy_txns=ht, multi_contracts=mc)
        q = df[["cluster"]].merge(prof[["cluster", "label"]], on="cluster", how="left")["label"].isin(QUALITY)
        variants[f"heavy_txns={ht},multi_contracts={mc}"] = float(q[last_rows.to_numpy()].mean())
    # noise bounds
    noise = df["label"] == "noise"
    lower = float((quality & ~noise)[last_rows].mean())
    upper = float((quality | noise)[last_rows].mean())
    # name-only baseline: the share of accounts without a mini-app name pattern
    name_ok = ~df["account"].str.endswith((".tg", ".sweat"))
    base_m = name_ok.groupby(df["month"]).mean()
    q_m = quality.groupby(df["month"]).mean()
    name_only = {"latest_month": float(base_m.iloc[-1]), "mean_abs_difference_vs_default": float((base_m - q_m).abs().mean()),
                 "correlation_with_default": float(base_m.corr(q_m)) if len(base_m) > 2 else None,
                 "reading": "if the clustering share tracks the name-only share closely, the behavioral model adds little beyond the name class in these sparse windows"}
    # inclusion-probability weighting
    w = inclusion_weights(df["active_days"], df["observation_periods"] if "observation_periods" in df else df["month"].dt.days_in_month)
    weighted = (quality * w).groupby(df["month"]).sum() / w.groupby(df["month"]).sum()
    freq = {"latest_month_unweighted": float(q_m.iloc[-1]), "latest_month_weighted": float(weighted.iloc[-1]),
            "mean_abs_difference": float((weighted - q_m).abs().mean()), "direction": "weighted below unweighted" if weighted.iloc[-1] < q_m.iloc[-1] else "weighted above unweighted",
            "reading": "a sensitivity under stated assumptions, not a demonstrated correction of the observation bias",
            "assumptions": ["each account's per-window activity probability is constant over the month and estimated from the same windows that observe it",
                            "windows are independent draws for every account; the fixed 03:00/15:00 UTC design is treated as if it were random",
                            "accounts never seen in any window have no weight: the index covers observed accounts only",
                            "heterogeneity between accounts beyond activity frequency is ignored"],
            "validation": "not validated externally; a fuller observation of the same months would be needed to test it"}
    # hour of observation
    by_hour = None
    tx = DATA / "blocks" / "tx_sampled.csv"
    if sampled and tx.exists():
        t = pd.read_csv(tx, usecols=["window_day", "window_hour", "signer"])
        t["month"] = pd.to_datetime(t["window_day"]).dt.to_period("M").dt.to_timestamp()
        pairs = t.drop_duplicates(["month", "signer", "window_hour"]).rename(columns={"signer": "account"})
        merged = pairs.merge(df[["month", "account"]].assign(quality=quality.to_numpy()), on=["month", "account"], how="inner")
        hm = merged.groupby(["month", "window_hour"])["quality"].mean().unstack()
        if hm.shape[1] >= 2:
            cols = list(hm.columns)
            by_hour = {"hours": [int(c) for c in cols], "latest_month": {str(int(c)): float(hm.iloc[-1][c]) for c in cols},
                       "mean_abs_difference_between_hours": float((hm[cols[0]] - hm[cols[1]]).abs().mean()),
                       "months": int(len(hm)), "reading": "shares computed separately on accounts observed in each fixed window"}
    # model agreement: retrospective HDBSCAN versus frozen past-only GMM
    agreement = None
    cm = MODELS / "qaa_causal_monthly.csv"
    if cm.exists():
        c = pd.read_csv(cm, parse_dates=["month"]).set_index("month")["qaa_share"]
        both = pd.concat([q_m.rename("descriptive"), c.rename("frozen")], axis=1).dropna()
        if len(both):
            agreement = {"months": int(len(both)), "latest": {"descriptive": float(both["descriptive"].iloc[-1]), "frozen": float(both["frozen"].iloc[-1])},
                         "mean_abs_difference": float((both["descriptive"] - both["frozen"]).abs().mean()),
                         "correlation": float(both["descriptive"].corr(both["frozen"])) if len(both) > 2 else None,
                         "reading": "the two models label the same months differently; the level of the share depends on the model, its trend less so"}
    scope = {"observed_unit": "accounts signing at least one transaction inside the sampled windows",
             "account_months": int(len(df)), "share_with_one_transaction": seen_once, "share_active_in_one_window": one_window,
             "population_extrapolation": ("the QAA count multiplies the sampled share by NearBlocks mean daily active accounts; "
                                          "inclusion probability rises with activity, so the count is an illustrative rescaling and the share is the measured quantity"),
             "identity": "no verified human or bot labels exist; groups are behavioral patterns"}
    incl = inclusion_from_intraday() if sampled else None
    if incl:
        freq["validation"] = ("checked within six days against 24 hourly windows of the same design (inclusion_from_intraday_days); the month-level "
                              "bias of the share is still not identified")
    refits = json.loads(REFITS.read_text()) if REFITS.exists() else None
    not_done = ["external human/bot labels (none available)", "a fuller observation of whole months (the within-day inclusion measurement covers six days)"]
    if not refits:
        not_done.insert(0, "refits with other clustering hyper-parameters (make qaa-refits writes them as a committed sensitivity artifact)")
    return {"latest_month": str(last.date())[:7], "criteria": criteria, "label_threshold_variants_default_share": variants,
            "noise_bounds_default_share": {"noise_excluded": lower, "noise_included": upper},
            "name_only_baseline": name_only, "inclusion_probability_weighting": freq, "inclusion_from_intraday_days": incl, "by_window_hour": by_hour,
            "model_agreement": agreement, "refits": refits, "scope": scope,
            "not_done": not_done}


INTRADAY_SIGNERS = DATA / "blocks" / "intraday_signers.csv"
FIXED_HOURS = (3, 15)
ACTIVITY_STRATA = [(1, 1, "1 window"), (2, 3, "2-3 windows"), (4, 8, "4-8 windows"), (9, 24, "9-24 windows")]


def _name_class(account: pd.Series) -> pd.Series:
    out = pd.Series("named", index=account.index)
    out[account.str.endswith(".tg")] = "tg"
    out[account.str.endswith(".sweat")] = "sweat"
    out[account.str.fullmatch(r"[0-9a-f]{64}")] = "implicit"
    return out


def inclusion_from_intraday(path=INTRADAY_SIGNERS) -> dict | None:
    """Measure the fixed-window inclusion of accounts against 24 hourly windows of the same days (same 50-block design).

    Six days carry 24 windows (make blocks-intraday / -validation). Within each day, the accounts seen in the 03:00 and 15:00
    windows are a subset of those seen in all 24: the ratio is the inclusion probability the two-window design achieves for a
    day, overall and by activity level and name class. The name-only quality share (accounts without a .tg/.sweat name) is
    compared between the two designs, and the inclusion weighting that the sensitivity applies to the two-window data is
    checked against the fuller observation. This measures inclusion within a day on six days; it is not the month-level
    population the QAA share describes, and 24 windows still observe about 0.8% of a day's blocks."""
    if not os.path.exists(path):
        return None
    d = pd.read_csv(path)
    d["name_class"] = _name_class(d["signer"])
    d["fixed"] = d["window_hour"].isin(FIXED_HOURS)
    acc = d.groupby(["window_day", "signer"]).agg(windows_active=("window_hour", "nunique"), fixed_windows_active=("fixed", "sum"),
                                                   txns=("txns", "sum"), receivers=("distinct_receivers", "sum"), name_class=("name_class", "first")).reset_index()
    acc["seen_fixed"] = acc["fixed_windows_active"] > 0
    acc["quality_name_only"] = ~acc["name_class"].isin(["tg", "sweat"])
    acc["multi_receiver_observable"] = acc["receivers"] >= 2

    def summarize(a: pd.DataFrame) -> dict:
        n24, nfix = int(len(a)), int(a["seen_fixed"].sum())
        fx = a[a["seen_fixed"]]
        w = inclusion_weights(fx["fixed_windows_active"], pd.Series(len(FIXED_HOURS), index=fx.index)) if len(fx) else pd.Series(dtype=float)
        share24 = float(a["quality_name_only"].mean()) if n24 else None
        share2 = float(fx["quality_name_only"].mean()) if nfix else None
        weighted2 = float((fx["quality_name_only"] * w).sum() / w.sum()) if nfix and w.sum() else None
        strata = {}
        for lo, hi, name in ACTIVITY_STRATA:
            m = a["windows_active"].between(lo, hi)
            strata[name] = {"accounts": int(m.sum()), "inclusion": float(a.loc[m, "seen_fixed"].mean()) if m.any() else None}
        by_name = {k: {"accounts": int(len(g)), "inclusion": float(g["seen_fixed"].mean())} for k, g in a.groupby("name_class")}
        return {"accounts_24_windows": n24, "accounts_fixed_windows": nfix, "inclusion_overall": (nfix / n24) if n24 else None,
                "inclusion_by_activity": strata, "inclusion_by_name_class": by_name,
                "share_active_in_one_window_of_24": float((a["windows_active"] == 1).mean()) if n24 else None,
                "multi_receiver_observable_share": {"fixed_windows": float(fx["multi_receiver_observable"].mean()) if nfix else None, "all_24_windows": float(a["multi_receiver_observable"].mean()) if n24 else None},
                "name_only_quality_share": {"fixed_windows": share2, "fixed_windows_inclusion_weighted": weighted2, "all_24_windows": share24,
                                            "weighting_moves_toward_fuller_observation": (None if None in (share2, weighted2, share24) else bool(abs(weighted2 - share24) < abs(share2 - share24)))}}

    days = {day: summarize(g) for day, g in acc.groupby("window_day")}
    pooled = summarize(acc)
    moved = [v["name_only_quality_share"]["weighting_moves_toward_fuller_observation"] for v in days.values()]
    moved = [m for m in moved if m is not None]
    return {"days": days, "pooled": pooled, "design": {"fixed_hours_utc": list(FIXED_HOURS), "windows_per_day": 24, "blocks_per_window": 50,
                                                      "days": sorted(days), "selection": "the three motivating and the three validation days of the volume reconciliation; not chosen for this measurement"},
            "weighting_check": {"days_where_weighting_moves_toward_fuller_observation": int(sum(moved)), "days_compared": len(moved)},
            "reading": ("inclusion is the share of a day's 24-window accounts that the two fixed windows observe; it rises with activity, so "
                        "light accounts are under-observed and the sampled population is tilted toward frequent signers. The name-only share "
                        "under the two designs shows how much the composition shifts; the weighting check tells whether the inclusion weighting "
                        "used as a sensitivity moves the two-window share toward the 24-window share. Within-day inclusion on six days is an "
                        "observed quantity; it does not identify the month-level bias of the QAA share, which would need a fuller observation of "
                        "whole months"),
            "kind": "observed (within-day, six days), used as a check of the weighting sensitivity"}


REFITS = MODELS / "qaa_refits.json"
REFIT_GRID = [("hdbscan", {"min_cluster_size": None, "min_samples": 25}, "committed hyper-parameters refitted on this machine"),
              ("hdbscan", {"min_cluster_size": 0.5, "min_samples": 25}, "half the minimum cluster size"),
              ("hdbscan", {"min_cluster_size": 2.0, "min_samples": 25}, "double the minimum cluster size"),
              ("hdbscan", {"min_cluster_size": None, "min_samples": 10}, "min_samples 10"),
              ("hdbscan", {"min_cluster_size": None, "min_samples": 50}, "min_samples 50"),
              ("gmm", {}, "Gaussian mixture, diagonal covariance, BIC-selected k in 3..8")]


def refit_variants(df: pd.DataFrame, x: pd.DataFrame, committed: np.ndarray, monthly_index: pd.DatetimeIndex) -> dict:
    """Refit the clustering under other hyper-parameters and an alternative algorithm; report agreement with the committed assignment
    and the resulting latest-month shares. Sensitivity only: the committed assignment stays the baseline (platform-dependent fits)."""
    from sklearn.metrics import adjusted_rand_score
    scaler = RobustScaler().fit(x[NUMERIC])
    z = np.hstack([scaler.transform(x[NUMERIC]), x[[f"name_{c}" for c in NAME_CLASSES]].to_numpy()])
    n = len(z)
    base_mcs = max(50, int(0.005 * n))
    last = df["month"] == monthly_index[-1]
    out = []
    for algo, params, desc in REFIT_GRID:
        if algo == "hdbscan":
            import hdbscan  # type: ignore
            mcs = base_mcs if params["min_cluster_size"] is None else max(10, int(base_mcs * params["min_cluster_size"]))
            labels = hdbscan.HDBSCAN(min_cluster_size=mcs, min_samples=params["min_samples"]).fit(z).labels_
            used = {"min_cluster_size": mcs, "min_samples": params["min_samples"]}
        else:
            best, best_bic = None, np.inf
            for k in range(3, 9):
                g = GaussianMixture(k, covariance_type="diag", random_state=0, n_init=2).fit(z)
                if g.bic(z) < best_bic:
                    best, best_bic = g, g.bic(z)
            labels = best.predict(z)
            used = {"k": int(best.n_components)}
        prof = label_clusters(df.drop(columns=[c for c in ("cluster", "label") if c in df]), x, labels)
        lab = pd.Series(labels).map(prof.set_index("cluster")["label"])
        out.append({"algorithm": algo, "variant": desc, "parameters": used, "clusters": int(len(set(labels)) - (1 if -1 in labels else 0)),
                    "noise_share": float((labels == -1).mean()),
                    "adjusted_rand_index_vs_committed": float(adjusted_rand_score(committed, labels)),
                    "latest_month_share": {"strict": float(lab[last.to_numpy()].eq("multi_app").mean()),
                                           "default": float(lab[last.to_numpy()].isin(QUALITY).mean()),
                                           "including_ambiguous": float((~lab[last.to_numpy()].isin(NON_QUALITY)).mean())}})
    defaults = [r["latest_month_share"]["default"] for r in out]
    return {"computed_on": pd.Timestamp.utcnow().strftime("%Y-%m-%d"), "n": int(n), "latest_month": str(monthly_index[-1].date())[:7],
            "baseline_min_cluster_size": base_mcs, "variants": out,
            "default_share_range": [min(defaults), max(defaults)],
            "reading": ("the committed assignment is the baseline; these refits show how much the latest default share and the partition itself "
                        "depend on hyper-parameters and on the algorithm. Computed by `make qaa-refits` on one machine (HDBSCAN assignments are "
                        "platform-dependent) and committed as a sensitivity artifact; not regenerated by the build"),
            "kind": "sensitivity"}


def run_refits() -> dict:
    df = load_inputs()
    if df is None:
        df = load_sampled()
    df = df[df["txns"] >= 1].sort_values(["month", "account"]).reset_index(drop=True)
    x = featurize(df)
    prev = pd.read_csv(MODELS / "qaa_assignments.csv", parse_dates=["month"])
    committed = df[["month", "account"]].merge(prev, on=["month", "account"], how="left")["cluster"].to_numpy()
    res = refit_variants(df, x, committed, pd.DatetimeIndex(sorted(df["month"].unique())))
    REFITS.write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(f"qaa refits: {len(res['variants'])} variants; latest default share range {res['default_share_range'][0]:.1%}-{res['default_share_range'][1]:.1%} -> {REFITS}")
    return res


def examples(df: pd.DataFrame, x: pd.DataFrame, per_group: int = 3) -> list[dict]:
    """Traceable account-months per group: the members closest to the group's median feature vector (typical cases)
    plus the single farthest member (the least typical account the rule still covers)."""
    cols = ["month", "account", "label", "txns", "active_days", "observation_periods", "distinct_receivers", "distinct_contracts",
            "distinct_methods", "self_txns", "function_calls", "transfers", "intents_actions", "deposit_near", "gap_median_s", "gap_cv", "name_class"]
    cols = [c for c in cols if c in df]
    scale = x[NUMERIC].std().replace(0, 1.0)
    out = []
    for label, g in df.groupby("label"):
        z = (x.loc[g.index, NUMERIC] - x.loc[g.index, NUMERIC].median()) / scale
        dist = np.sqrt((z ** 2).sum(axis=1)).sort_values(kind="stable")
        picks = [(i, "typical") for i in dist.index[:per_group]] + ([(dist.index[-1], "least_typical")] if len(dist) > per_group else [])
        for idx, kind in picks:
            row = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in df.loc[idx, cols].items()}
            row["month"] = str(pd.Timestamp(row["month"]).date())[:7]
            row["kind"] = kind
            row["rule"] = GROUP_DEFINITIONS.get(label, "")
            out.append(row)
    return out


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
    monthly["quality_share_strict"] = shares.get("multi_app", pd.Series(0, index=shares.index)) / monthly["active_accounts_bq"]
    monthly["quality_share_including_ambiguous"] = 1 - shares[[c for c in shares if c in NON_QUALITY]].sum(axis=1) / monthly["active_accounts_bq"]
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
    sens = sensitivity(df, x, labels, monthly, sampled=source != "bigquery")
    (MODELS / "qaa_sensitivity.json").write_text(json.dumps(sens, indent=1, default=str) + "\n")
    (MODELS / "qaa_examples.json").write_text(json.dumps(examples(df, x), indent=1, default=str) + "\n")
    status = {"computed": True, "source": source, **info, "months": int(monthly.shape[0]),
              "labels": prof.set_index("cluster")["label"].to_dict(), "quality_labels": sorted(QUALITY),
              "group_definitions": GROUP_DEFINITIONS, "criteria": CRITERIA,
              "method_version": METHOD_VERSION, "causal": causal,
              "scope": sens["scope"],
              "validation": "silhouette is geometric separation; group names describe behavior, not verified identity; see qaa_sensitivity.json"}
    (MODELS / "qaa_status.json").write_text(json.dumps(status, indent=1, default=str))
    print(f"L1: {info['algorithm']} on {info['n']:,} account-months -> {len(prof)} clusters, QAA for {len(monthly)} months")
    return status
