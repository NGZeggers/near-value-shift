"""Write notebooks/walkthrough.ipynb: a notebook that loads every pipeline output and re-plots the key results.
Generated as plain JSON so the repo never depends on Jupyter at build time; run it with `uv run jupyter lab`."""
from __future__ import annotations

import json

from .config import ROOT

CELLS = [
    ("markdown", "# From clicks to settlement: walkthrough\n\nThis notebook reads the outputs produced by `make features models` and re-plots the key results. "
                 "Run the pipeline first. Nothing here hits the network."),
    ("code", "import json, pandas as pd, numpy as np, matplotlib.pyplot as plt\nfrom pathlib import Path\nD = Path('../data/derived'); M = D / 'models'\n"
             "daily = pd.read_csv(D / 'daily.csv', parse_dates=['date']).set_index('date')\nmonthly = pd.read_csv(D / 'monthly.csv', parse_dates=['month']).set_index('month')\ndaily.tail(3)"),
    ("markdown", "## 1. Raw activity vs value-weighted activity"),
    ("code", "fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)\n"
             "daily['active_accounts'].rolling(30).mean().plot(ax=axes[0], logy=True, title='Daily active accounts (30d mean, log)')\n"
             "monthly['intents_volume_usd'].plot(ax=axes[1], kind='bar', title='Intents volume per month (USD)'); axes[1].set_xticklabels([t.strftime('%Y-%m') if i % 6 == 0 else '' for i, t in enumerate(monthly.index)])\n"
             "daily['usd_per_txn'].rolling(30).mean().plot(ax=axes[2], logy=True, title='USD per transaction (30d mean, log)')\nplt.tight_layout()"),
    ("markdown", "## 2. Structural breaks and correlations (L3)"),
    ("code", "breaks = json.loads((M / 'breaks.json').read_text())\n{k: v['breaks'] for k, v in breaks.items()}"),
    ("code", "pd.read_csv(M / 'yearly_corr.csv').set_index('year').round(2)"),
    ("code", "pd.DataFrame(json.loads((M / 'var_granger.json').read_text())).set_index('metric').reindex(columns=['n_weeks', 'lag_aic', 'inference_valid', 'note', 'usage_granger_causes_price', 'price_granger_causes_usage'])"),
    ("code", "pd.DataFrame(json.loads((M / 'johansen.json').read_text())).set_index('metric')[['rank_5pct','inference_valid','note']]"),
    ("markdown", "## 3. Signal tests and scenarios (L4)"),
    ("code", "ic = pd.DataFrame(json.loads((M / 'signal_ic.json').read_text()))\nic[ic.horizon_weeks == 12].pivot_table(index='metric', columns='benchmark', values='spearman_ic').round(2)"),
    ("code", "sc = json.loads((M / 'scenarios.json').read_text()); sc['inputs'], sc['price_to_fees']"),
    ("markdown", "## 4. Quality-adjusted accounts (L1) and Intents microstructure (L2)\n\nComputed from the committed block sample, or optional BigQuery extracts. Descriptive clustering is separate from the frozen past-only QAA used in predictive tests. Human/bot names are proxy labels, not verified identities."),
    ("code", "if (M / 'qaa_monthly.csv').exists():\n    q = pd.read_csv(M / 'qaa_monthly.csv', parse_dates=['month']).set_index('month')\n    q[['active_accounts_bq', 'qaa']].plot(logy=True, title='Active accounts vs QAA')\n    display(pd.read_csv(M / 'qaa_clusters.csv'))\nelse:\n    print(json.loads((M / 'qaa_status.json').read_text()))"),
    ("code", "intents_status = json.loads((M / 'intents_status.json').read_text())\nif intents_status.get('computed'):\n    im = pd.read_csv(M / 'intents_monthly.csv', parse_dates=['month']).set_index('month')\n    im[['hhi_solver', 'top1_solver_share']].plot(title='Solver concentration')\n    display(im.tail())\nelse:\n    print(intents_status)"),
    ("code", "display(pd.read_csv(M / 'qaa_causal_monthly.csv').tail())\nif intents_status.get('computed'):\n    display(pd.read_csv(M / 'intents_quarterly.csv'))\n    print('Cross-check:', intents_status['cross_check_passed'])\nelse:\n    print('Independent L2 cross-check unavailable:', intents_status['reason'])"),
    ("markdown", "## 5. Realized revenue definitions\n\nNet captured revenue is measured from wallet receipts. Buyback-labelled revenue is not proof of burning or direct holder dividends. Future governance allocation is discretionary."),
    ("code", "monthly[['intents_fees_usd','intents_revenue_usd','intents_holders_revenue_usd']].tail(12)"),
    ("markdown", "## 6. Reconciliation of the on-chain estimate\n\nEconomic unit, per-day table, decomposition (coverage, valuation, routes, residual), pre-declared tolerance and holdout, and the intraday comparison when `make blocks-intraday` has run."),
    ("code", "rec = json.loads((M / 'intents_reconciliation.json').read_text())\nprint(json.dumps(rec.get('economic_unit'), indent=1))\nif rec.get('computed'):\n    display(pd.read_csv(M / 'intents_reconciliation_daily.csv').set_index('date')[['blocks_observed','volume_sampled_usd','volume_expanded_usd','reference_usd','ratio','legs_unpriced','holdout_role']].tail(12))\n    print(json.dumps(rec['holdout'], indent=1)); print(json.dumps(rec['components']['residual'], indent=1))\n    print(json.dumps({k: v for k, v in rec['intraday'].items() if k != 'days'}, indent=1, default=str))"),
    ("code", "ex = json.loads((M / 'intents_trace_examples.json').read_text()) if (M / 'intents_trace_examples.json').exists() else []\nfor e in ex[:2]:\n    print(e['kind'], e['receipt_id'], e['block_url']); display(pd.DataFrame(e['legs'])); print('batch volume USD', e['batch_volume_usd'])"),
    ("markdown", "## 7. Behavioral groups: scope and sensitivity\n\nGroup names describe behavior; there are no verified human/bot labels. The share depends on the criterion, the model and the hour of observation; a name-only split is shown as the baseline."),
    ("code", "sens = json.loads((M / 'qaa_sensitivity.json').read_text()) if (M / 'qaa_sensitivity.json').exists() else {}\nprint(json.dumps({k: sens.get(k) for k in ['latest_month','criteria','name_only_baseline','inclusion_probability_weighting','by_window_hour','model_agreement']}, indent=1))\nif (M / 'qaa_examples.json').exists():\n    display(pd.DataFrame(json.loads((M / 'qaa_examples.json').read_text()))[['label','kind','account','txns','active_days','distinct_contracts','name_class']])"),
    ("markdown", "## 8. Pre-registered out-of-sample evaluation and value bridge\n\nThe protocol was fixed before scoring; a negative result is carried into the verdict. The bridge marks every step observed, classified, inferred or unavailable and sets issuance against executed buybacks."),
    ("code", "oos = json.loads((M / 'signal_oos.json').read_text()) if (M / 'signal_oos.json').exists() else {}\nprint(json.dumps(oos.get('summary'), indent=1))\nif oos:\n    display(pd.DataFrame(oos['tests'])[['predictor','kind','horizon_weeks','benchmark','n_calibration','n_evaluation','ic_calibration','ic_evaluation_signed','walk_forward_hit_rate','status']])"),
    ("code", "b = json.loads((M / 'value_bridge.json').read_text()) if (M / 'value_bridge.json').exists() else {}\nif b:\n    display(pd.DataFrame(b['steps'])[['step','name','usd','near','share_of_previous','status']])\n    print(json.dumps(b['dilution'], indent=1, default=str))\n    display(pd.DataFrame({k: v['assumptions'] | {'net_yield_on_mcap': v['net_yield_on_mcap']} for k, v in b['scenarios'].items()}))\n    print('dominant assumption:', b['dominant_assumption']['dominant'])"),
]


def run() -> None:
    nb = {"cells": [{"id": f"cell-{i:02d}", "cell_type": t, "metadata": {}, "source": s, **({"outputs": [], "execution_count": None} if t == "code" else {})} for i, (t, s) in enumerate(CELLS)],
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    out = ROOT / "notebooks" / "walkthrough.ipynb"
    out.write_text(json.dumps(nb, indent=1))
    print(f"notebook: {out.relative_to(ROOT)}")
