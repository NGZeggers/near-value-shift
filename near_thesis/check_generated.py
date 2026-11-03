"""Compare rebuilt artifacts to Git (or a directory), allowing only numerical machine precision."""
from __future__ import annotations

import argparse
import io
import json
import math
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd

from .config import ROOT

FIXED = ['THESIS.md', 'docs/METRICS.md', 'docs/REPRODUCIBILITY.md', 'site/data.json', 'notebooks/walkthrough.ipynb']
RTOL, ATOL = 1e-9, 1e-11


def equivalent(a, b) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equivalent(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equivalent(x, y) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return (math.isnan(a) and math.isnan(b)) or math.isclose(a, b, rel_tol=RTOL, abs_tol=ATOL)
    return type(a) is type(b) and a == b


def same_artifact(path: str, expected: bytes, actual: bytes) -> bool:
    if expected == actual:
        return True
    if path.endswith('.json'):
        return equivalent(json.loads(expected), json.loads(actual))
    if path.endswith('.csv'):
        a, b = pd.read_csv(io.BytesIO(expected)), pd.read_csv(io.BytesIO(actual))
        if a.shape != b.shape or list(a.columns) != list(b.columns):
            return False
        for col in a:
            if pd.api.types.is_numeric_dtype(a[col]) and pd.api.types.is_numeric_dtype(b[col]):
                if not np.allclose(a[col].to_numpy(dtype=float), b[col].to_numpy(dtype=float), rtol=RTOL, atol=ATOL, equal_nan=True):
                    return False
            elif not a[col].fillna('<missing>').equals(b[col].fillna('<missing>')):
                return False
        return True
    # The argument, metric/provenance docs and notebook definitions are exact text.
    return False


def run(baseline_dir: Path | None = None) -> list[str]:
    paths = set(FIXED)
    paths.update(str(p.relative_to(ROOT)) for p in (ROOT / 'data/derived').rglob('*') if p.suffix in {'.csv','.json'})
    if baseline_dir:
        paths.update(str(p.relative_to(baseline_dir)) for p in (baseline_dir / 'data/derived').rglob('*') if p.suffix in {'.csv','.json'})
    else:
        paths.update(subprocess.check_output(['git','ls-files','--','data/derived'], cwd=ROOT, text=True).splitlines())
    failed = []
    for rel in sorted(paths):
        current = ROOT / rel
        if baseline_dir:
            previous = baseline_dir / rel
            expected = previous.read_bytes() if previous.exists() else None
        else:
            result = subprocess.run(['git','show',f'HEAD:{rel}'], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            expected = result.stdout if result.returncode == 0 else None
        if expected is None or not current.exists() or not same_artifact(rel, expected, current.read_bytes()):
            failed.append(rel)
    return failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-dir', type=Path)
    args = parser.parse_args()
    failed = run(args.baseline_dir)
    if failed:
        raise SystemExit('Stale or missing generated artifacts (rebuild and commit):\n' + '\n'.join(failed))
    print(f'Generated artifacts match (numeric rtol={RTOL}, atol={ATOL}; text and hashes exact).')


if __name__ == '__main__':
    main()
