"""Generate the argument and provenance from outputs; conclusions respect diagnostics and gaps."""
from __future__ import annotations

import hashlib
import json

import pandas as pd

from .config import DATA, DERIVED, DOCS, MODELS, ROOT
from . import narrative
from .http import raw_manifest


def usd(v, d=1):
    if v is None or pd.isna(v):
        return "n/a"
    a = abs(v)
    if a >= 1e9: return f"${v/1e9:.{d}f}B"
    if a >= 1e6: return f"${v/1e6:.{d}f}M"
    if a >= 1e3: return f"${v/1e3:.{d}f}K"
    return f"${v:.2f}"


def num(v, d=0):
    return "n/a" if v is None or pd.isna(v) else f"{v:,.{d}f}"


def pct(a, b):
    return "n/a" if not b or pd.isna(a) or pd.isna(b) else f"{(a/b-1)*100:+.0f}%"


def _json(name):
    return json.loads((MODELS / name).read_text())


def build() -> str:
    d = pd.read_csv(DERIVED / "daily.csv", parse_dates=["date"]).set_index("date")
    m = pd.read_csv(DERIVED / "monthly.csv", parse_dates=["month"]).set_index("month")
    y = pd.read_csv(DERIVED / "yearly.csv").set_index("year")
    full = m[m.index + pd.offsets.MonthEnd(0) <= d.index.max()]
    last = full.iloc[-1]
    lm = str(last.name.date())[:7]
    qs, ins, sc = _json("qaa_status.json"), _json("intents_status.json"), _json("scenarios.json")
    vg, jo, ic = _json("var_granger.json"), _json("johansen.json"), _json("signal_ic.json")
    ratio = ins.get("ratio_to_defillama") or {}
    cross_ok = bool(ins.get("cross_check_passed"))
    inputs = sc["inputs"]
    out = ["# From clicks to settlement: an investment thesis on NEAR\n",
           f"Generated from committed snapshots; analysis through {d.index.max().date()}. `make build` rebuilds this argument, tables, dashboard and executed notebook. Numbers are computed; interpretation and source context are explicit.\n",
           "## Claim and current verdict\n",
           "NEAR's reported activity is shifting from high transaction/account counts toward cross-chain settlement. That is a claim about composition, not proof of token undervaluation or future returns. QAA is a behavioral proxy, not a count of verified humans.\n",
           "**" + narrative.verdict_statement(bool(ins.get("computed")), cross_ok) + "**\n",
           "## Observed activity\n",
           "| Metric (daily mean) | " + " | ".join(str(i) for i in y.index) + " |",
           "|---|" + "---|" * len(y.index)]
    for title, col, fmt in [("Transactions", "txns", num), ("Active accounts", "active_accounts", num),
                            ("USD moved per transaction", "usd_per_txn", usd), ("Gas fees paid, USD", "tx_fee_usd", usd),
                            ("Intents volume, USD", "intents_volume_usd", usd), ("NEAR price", "near_price", usd)]:
        out.append(f"| {title} | " + " | ".join(fmt(y.loc[i, col]) for i in y.index) + " |")
    out += [f"\nLatest full month ({lm}): Intents volume {usd(last.intents_volume_usd)}, mean daily active accounts {num(last.active_accounts)}, "
            f"USD moved per transaction {usd(last.usd_per_txn)}. Latest year has {int(y.iloc[-1]['days'])} observed days.\n",
            "## Evidence for\n",
            "- The reported Intents volume and raw activity series have diverged. This supports a change in composition, subject to source coverage. Native NEAR transfer volume and Intents cross-chain settlement are different measurements, not interchangeable totals.",
            "- A quality adjustment can distinguish behavioral groups. Its uncertainty and sensitivity are reported below; it does not establish that departing accounts were actual bots.",
            "- Intents already has a revenue mechanism. The economic question is how much is retained and allocated, rather than whether any capture exists.\n",
            "## Revenue mechanics: observed capture versus future allocation\n",
            "NEAR's [February 2026 explanation](https://www.near.org/blog/evolving-near-tokenomics) describes an active fee switch and governance-controlled buybacks. "
            "Its [Q2 update](https://www.near.org/blog/the-state-of-near-q-2-2026) describes revenue-funded purchases. These are primary-source context, not a guarantee of dividends or continued purchases. "
            "The [DefiLlama adapter](https://github.com/DefiLlama/dimension-adapters/blob/master/fees/near-intents/index.ts) measures net NEAR/wNEAR receipts into revenue wallets, excludes internal wallet hops, and labels captured revenue after its buyback start as HoldersRevenue. "
            "That classification is not transaction-level proof of each purchase or of burning.\n",
            f"On the analysis cutoff's trailing year: gross Intents fees {usd(inputs['intents_fees_12m_usd'])}; net captured receipts {usd(inputs.get('intents_net_revenue_12m_usd'))}; "
            f"buyback-labelled revenue {usd(inputs.get('intents_holders_revenue_12m_usd'))}. Ratio of net receipts to gross fees: {num(None if inputs.get('observed_capture_share') is None else 100 * inputs['observed_capture_share'], 2)}%. "
            "Receipts are realized in sweeps and can exceed fees on an individual day. The snapshots carry the adapter definitions and are cut to the same analysis end date. "
            "No independent wallet-level purchase audit or supply-destruction calculation is claimed. Gas fees paid are not automatically net supply burn across all historical protocol versions.\n",
            "## Evidence against and unresolved tests\n",
            "- Greater settlement volume does not mechanically imply greater token returns. Gross fees are not token-holder yield; net capture, future allocation and issuance still matter."]
    if ratio:
        out.append(f"- The independent sample-to-DefiLlama ratio is {ratio['ratio']:.3f}, conditional day-bootstrap interval [{ratio['ci_lo']:.3f}, {ratio['ci_hi']:.3f}], over {ratio['days']} matched days. "
                   + ("The interval contains parity." if cross_ok else "The interval excludes parity: our consistency criterion fails, so independent confirmation of the total and trend is not established."))
    elif not ins.get('computed'):
        out.append('- Independent L2 validation is unavailable: ' + ins.get('reason', 'no verified extract'))
    int_ic = next((r for r in ic if r['metric'] == 'intents_volume_usd' and r.get('horizon_weeks') == 12 and r.get('benchmark') == 'btc' and 'spearman_ic' in r), None)
    if int_ic:
        lo, hi = int_ic['ci95_block_bootstrap']
        out.append(f"- Intents growth versus twelve-week forward NEAR excess returns over BTC: IC {int_ic['spearman_ic']:+.2f}, exploratory 95% block interval [{lo:+.2f}, {hi:+.2f}], n={int_ic['n']}. "
                   f"First/second chronological halves: {int_ic['ic_first_half']:+.2f}/{int_ic['ic_second_half']:+.2f}. These are descriptive association checks, not a validated trading signal.")
    out += ["- Fixed intraday windows, sparse sampling, role assumptions, unpriced assets and routed batches can all affect the on-chain comparison. Their separate contributions are not identified.\n",
            "## Quality-adjusted accounts (L1)\n"]
    if qs.get('computed'):
        q = pd.read_csv(MODELS / 'qaa_monthly.csv', parse_dates=['month']).set_index('month')
        pk = q.active_accounts_bq.idxmax()
        out += [f"Source: {qs['source']}; {qs['n']:,} account-months, {qs['months']} months. Retrospective {qs['algorithm']} with corrected self-call counts and window-normalized activity. "
                f"At {str(pk.date())[:7]} QAA was {num(q.loc[pk,'qaa'])}; at {str(q.index[-1].date())[:7]} it was {num(q.iloc[-1].qaa)}. "
                f"The corresponding behavioral shares are {q.loc[pk,'qaa_share']:.1%} and {q.iloc[-1].qaa_share:.1%}. "
                f"Silhouette on at most 3,000 observations: {num(qs.get('silhouette_sample'),2)}. Separation is not human/bot accuracy.\n",
                f"Latest sensitivity: strict multi-app share {q.iloc[-1].quality_share_strict:.1%}; default share {q.iloc[-1].qaa_share:.1%}; including ambiguous groups {q.iloc[-1].quality_share_including_ambiguous:.1%}. "
                "Name-proxy profiles are in `qaa_anchor_profiles.csv`; monthly group counts permit composition checks. Verified human/bot anchor labels are not available. "
                "In sampled mode, shares are rescaled by NearBlocks mean daily active accounts; unequal account inclusion probabilities are not corrected, so these are exploratory proxies with no guaranteed conservative bias.\n"]
        causal = qs.get('causal', {})
        if causal.get('computed'):
            out.append(f"**Past-only QAA for predictive tests:** a separate GMM is calibrated through {causal['training_end']}, then its scaler, parameters and label mapping are frozen. "
                       f"Only later months are predicted; first availability is {causal['first_available_at']}. Each month becomes available on the first day of the following month. "
                       "The full-history descriptive clustering is never fed into signal or Granger tests. The model is frozen calibration, not monthly walk-forward retraining.\n")
    else:
        out.append(f"Not computed: {qs.get('reason')}.\n")
    out += ["## Intents microstructure (L2)\n"]
    if ins.get('computed'):
        cov = ins.get('coverage', {})
        out.append(f"Source: {ins['source']}. {cov.get('blocks_fetched','n/a')} blocks, {ins['sampled_days']} sampled days including observed zero-event days; "
                   f"{ins.get('days_with_token_diff','n/a')} days contain token_diff. Parsed {ins['events']:,} events. {ins['solver_accounts']} accounts satisfy the role heuristic ({ins['assumptions']['mode']}).\n")
        out.append(f"Valuation: {ins['volume_method']}. Batch coverage with any priced leg {ins['priced_batch_share_mean']:.1%}; fully priced batches {ins['fully_priced_batch_share_mean']:.1%}; priced token-diff legs {ins['priced_leg_share']:.1%}. "
                   "Leg coverage is a count share, not a known USD share. Observed users are never multiplied into daily unique users. Solvers and HHI are within-window estimates, not full-market concentration.\n")
        iq = pd.read_csv(MODELS / 'intents_quarterly.csv')
        out.append("| Quarter | Sampled days | Flow estimate / DefiLlama |\n|---|---|---|")
        for r in iq.itertuples(): out.append(f"| {r.quarter[:7]} | {r.sampled_days} | {num(r.ratio,3)} |")
        out.append("\nIntervals condition on the observed sampled days; they omit intraday, routing and pricing uncertainty. One-day strata have no estimable interval. "
                   "The estimator now retains multiple account-intents in a receipt; it still does not identify every economic swap. The gap is unresolved, not a proven tail effect or a guaranteed lower bound. "
                   "Full-day extracts would improve coverage but would not automatically validate this estimator. Role sensitivity is in `intents_solver_sensitivity.json`.\n")
    else:
        out.append('Not computed: ' + ins.get('reason', 'no verified extract') + '\n')
    out += ["## Econometrics (L3)\n", "| Metric | Weeks | VAR status | Johansen rank | Johansen status |\n|---|---|---|---|---|"]
    jmap = {r['metric']: r for r in jo}
    for r in vg:
        j = jmap.get(r['metric'], {})
        vstatus = 'diagnostics passed' if r.get('inference_valid') else r.get('note', 'inconclusive')
        out.append(f"| {r['metric']} | {r['n_weeks']} | {vstatus} | {j.get('rank_5pct','n/a')} | {j.get('note','inconclusive')} |")
    out.append("\nVAR uses weekly log changes, AIC-selected lags and ADF checks on exactly the model sample, followed by stability and residual-whiteness checks. "
               "Only passing models support inference; their directional p-values are Holm-adjusted as a family in `var_granger.json`. A failed prerequisite is inconclusive, not evidence of absence. "
               "Johansen reports ranks 0, 1 and 2 separately and checks compatibility with I(1) inputs. Full rank and mixed integration orders are not reported as absence of cointegration. "
               "Granger describes predictive precedence within the model, not economic causality.\n")
    out += ["## Forward associations (L4)\n", "| Metric | IC 12w vs BTC | Exploratory 95% interval | n |\n|---|---|---|---|"]
    for r in ic:
        if r.get('horizon_weeks') == 12 and r.get('benchmark') == 'btc' and 'spearman_ic' in r:
            lo, hi = r['ci95_block_bootstrap']
            out.append(f"| {r['metric']} | {r['spearman_ic']:+.2f} | {lo:+.2f} to {hi:+.2f} | {r['n']} |")
    out.append(f"\nDeclared family: {len(ic)} tests, two horizons and two benchmarks. Signal is the four-week change in a trailing four-week mean; target is forward excess log return. "
               "Circular block resampling addresses dependence approximately; the individual intervals are exploratory, and familywise Bonferroni intervals are reported separately. "
               "The half-sample split is a stability summary, not walk-forward portfolio evaluation. No returns after the analysis cutoff enter a target.\n")
    out += ["## Relative valuation and scenarios\n",
            "Cross-chain settlement/TVL and local-chain DEX/TVL have different scopes. Peer ranks are descriptive, not like-for-like proof of undervaluation. Gross app-fee/market-cap is not shareholder yield.\n",
            f"The scenario model draws {sc['n']:,} assumptions around observed gross take rate and net capture; future allocation is discretionary. "
            f"Median market-cap/illustrative retained-fees multiple {num(sc['price_to_fees']['p50'])}x, range p5–p95 {num(sc['price_to_fees']['p5'])}x–{num(sc['price_to_fees']['p95'])}x. "
            "The gas-fee term is a paid-fee proxy, not audited net burn; no net-deflation, fair-price or price-forecast claim is made.\n",
            "## What changes the verdict\n",
            "- Independent full-day/routed-batch reconciliation consistent with the reference series would strengthen the descriptive evidence. The current cross-check is " + ('unavailable' if not ins.get('computed') else 'consistent' if cross_ok else 'failing') + ".",
            "- Audited net receipts, executed purchases and supply effects may strengthen or weaken the value-capture case; gross volume alone does not decide it.",
            "- Stable out-of-sample associations with past-only features, dependence-aware uncertainty and multiplicity control are needed before describing usage as a return signal.",
            "- Strong sensitivity to clustering, sampling hours or role thresholds weakens the behavioral interpretation. Verified anchors remain an external data need.\n",
            "## Gaps, provenance and reproduction\n",
            "Raw and extracted inputs and frozen model artifacts are hashed in `docs/REPRODUCIBILITY.md`. Revenue definitions are stored in the raw responses. "
            "BigQuery is optional: its runner checks freshness before L1/L2; actual queries and credentials were not needed for this block-sample build. "
            "Explorer JWT is not used. On-chain publication is an optional dry-run-capable feature, not a claimed deployed result.\n",
            "`uv sync --all-extras && make build && make test`; open `site/index.html` and `site/walkthrough.html`. Sampling limits: `docs/SAMPLING.md`.\n"]
    return '\n'.join(out)


def metrics_doc() -> str:
    rows = [
        ('txns / active_accounts', 'NearBlocks', 'daily transactions / distinct signing accounts'),
        ('tx_fee_near / tx_fee_usd', 'NearBlocks', 'gas fees paid; not audited net supply burn'),
        ('tx_volume_usd / usd_per_txn', 'NearBlocks', 'native NEAR transferred in USD / ratio to transactions'),
        ('intents_volume_usd', 'DefiLlama/Dune', 'reported cross-chain settlement volume'),
        ('intents_fees_usd', 'DefiLlama/Dune', 'gross swap fees'),
        ('intents_revenue_usd', 'DefiLlama/Dune wallet-receipt adapter', 'net captured revenue; internal revenue-wallet hops excluded'),
        ('intents_holders_revenue_usd', 'same adapter', 'buyback-labelled net revenue; not proof of each purchase, dividends or burning'),
        ('near_app_fees_usd', 'DefiLlama', 'gross application fees; not token-holder income'),
        ('tvl_usd / stablecoins_usd', 'DefiLlama', 'chain TVL / circulating stablecoin USD supply'),
        ('near_price / price_bitcoin / price_ethereum', 'NearBlocks / DefiLlama coins', 'daily prices; benchmark histories'),
        ('qaa_monthly.qaa', 'sampled blocks or BigQuery; retrospective HDBSCAN', 'behavioral quality proxy; sampled share multiplied by mean daily active accounts'),
        ('qaa_causal_monthly.qaa', 'frozen past-only calibration GMM', 'out-of-calibration proxy; available on next-month first day; used for predictive tests'),
        ('hhi_solver / top1_solver_share', 'sampled token_diff events or BigQuery', 'within-observation heuristic solver concentration'),
        ('volume_priced_usd', 'same events', 'half sum of max priced inflow/outflow by account-intent; expanded only for additive flows'),
        ('users', 'same events', 'observed unique non-solver accounts, never expanded'),
    ]
    return '# Metric definitions (generated)\n\n| Column | Source | Definition |\n|---|---|---|\n' + '\n'.join(f'| `{a}` | {b} | {c} |' for a,b,c in rows) + '\n'


def repro_doc() -> str:
    out = ['# Reproducibility report (generated)\n',
           'The build reads committed snapshots. Full SHA-256 hashes cover raw files, block extracts, plans, SQL and frozen model artifacts. Snapshot times describe acquisition, not build wall-clock time.\n',
           '| Raw snapshot | Fetched at | Bytes | SHA-256 |\n|---|---|---|---|']
    for r in raw_manifest():
        out.append(f"| {r['file']} | {r['fetched_at']} | {r['bytes']} | `{r['sha256']}` |")
    out += ['\n## Extracts, query definitions and frozen model artifacts\n', '| File | Bytes | SHA-256 |\n|---|---|---|']
    files = list((DATA / 'blocks').glob('*.csv')) + list((DATA / 'blocks').glob('*.json')) + list((DATA / 'bigquery').glob('*.csv'))
    files += list((ROOT / 'sql').glob('*.sql'))
    files += [MODELS / 'qaa_assignments.csv', MODELS / 'qaa_causal_model.json']
    for p in sorted(files):
        if p.exists():
            out.append(f'| {p.relative_to(ROOT)} | {p.stat().st_size} | `{hashlib.sha256(p.read_bytes()).hexdigest()}` |')
    return '\n'.join(out) + '\n'


def run() -> None:
    (ROOT / 'THESIS.md').write_text(build())
    (DOCS / 'METRICS.md').write_text(metrics_doc())
    (DOCS / 'REPRODUCIBILITY.md').write_text(repro_doc())
    print('thesis: THESIS.md and provenance/metric docs regenerated')
