"""Run every model layer in dependency order: L1 (QAA) -> L2 (Intents) -> L3 (econometrics) -> L4 (signal)."""
from __future__ import annotations

from . import econ, intents, qaa, signal


def run() -> None:
    qaa.run()
    intents.run()
    econ.run()
    signal.run()
