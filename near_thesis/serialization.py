"""Standards-compliant JSON for analytical artifacts."""
from __future__ import annotations
import json
import math
from numbers import Real


def finite_values(value):
    if isinstance(value, dict):
        return {k: finite_values(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_values(v) for v in value]
    if isinstance(value, Real) and not math.isfinite(value):
        return None
    return value


def dumps(value, **kwargs):
    kwargs['allow_nan'] = False
    return json.dumps(finite_values(value), **kwargs)
