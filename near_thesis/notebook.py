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
    ("code", "pd.DataFrame(json.loads((M / 'var_granger.json').read_text())).set_index('metric')[['n_weeks', 'lag_aic', 'usage_granger_causes_price', 'price_granger_causes_usage']]"),
    ("markdown", "## 3. Signal tests and scenarios (L4)"),
    ("code", "ic = pd.DataFrame(json.loads((M / 'signal_ic.json').read_text()))\nic[ic.horizon_weeks == 12].pivot_table(index='metric', columns='benchmark', values='spearman_ic').round(2)"),
    ("code", "sc = json.loads((M / 'scenarios.json').read_text()); sc['inputs'], sc['price_to_fees']"),
    ("markdown", "## 4. Quality-adjusted accounts (L1) and Intents microstructure (L2)\n\nThese cells only run after `make bq` has produced the BigQuery extracts."),
    ("code", "if (M / 'qaa_monthly.csv').exists():\n    q = pd.read_csv(M / 'qaa_monthly.csv', parse_dates=['month']).set_index('month')\n    q[['active_accounts_bq', 'qaa']].plot(logy=True, title='Active accounts vs QAA')\n    display(pd.read_csv(M / 'qaa_clusters.csv'))\nelse:\n    print(json.loads((M / 'qaa_status.json').read_text()))"),
    ("code", "if (M / 'intents_monthly.csv').exists():\n    im = pd.read_csv(M / 'intents_monthly.csv', parse_dates=['month']).set_index('month')\n    im[['hhi_solver', 'top1_solver_share']].plot(title='Solver concentration')\n    display(im.tail())\nelse:\n    print(json.loads((M / 'intents_status.json').read_text()))"),
]


def run() -> None:
    nb = {"cells": [{"cell_type": t, "metadata": {}, "source": s, **({"outputs": [], "execution_count": None} if t == "code" else {})} for t, s in CELLS],
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    out = ROOT / "notebooks" / "walkthrough.ipynb"
    out.write_text(json.dumps(nb, indent=1))
    print(f"notebook: {out.relative_to(ROOT)}")
