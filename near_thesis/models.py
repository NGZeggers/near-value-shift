"""Run every model layer in dependency order: L1 (QAA) -> L2 (Intents) -> L2 reconciliation -> L3 (econometrics) -> L4 (signal) -> value bridge."""
from __future__ import annotations

from . import bridge, econ, intents, qaa, reconcile, signal


def run() -> None:
    qaa.run()
    intents.run()
    reconcile.run()
    econ.run()
    signal.run()
    bridge.run()
