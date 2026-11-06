"""The dashboard narrative is computed from the same artifacts as the thesis, never typed by hand."""
import json
import re

from near_thesis import charts, narrative
from near_thesis.config import ROOT


def test_verdict_statement_is_shared_with_thesis():
    thesis = (ROOT / "THESIS.md").read_text()
    for computed, cross_ok in [(True, False), (True, True), (False, False)]:
        s = narrative.verdict_statement(computed, cross_ok)
        assert s.startswith("Current verdict:")
    # the generated thesis carries exactly one of the two possible statements, in bold
    assert ("**" + narrative.verdict_statement(True, False) + "**" in thesis) or ("**" + narrative.verdict_statement(True, True) + "**" in thesis)


def test_story_blocks_are_complete_and_anchored():
    spec = charts.build()
    assert {"verdict", "argument", "sections", "against"} <= set(spec)
    v = spec["verdict"]
    assert v["status"] in {"supported", "unresolved"}
    assert {c["state"] for c in v["checks"]} <= {"pass", "fail", "open"}
    assert len(v["checks"]) == 3 and len(v["changes"]) >= 3
    ids = {"#chart-" + c["id"] for c in spec["charts"]} | {"#sec-" + s["id"] for s in spec["sections"].values()}
    for step in spec["argument"]:
        assert step["href"] in ids, step["href"]
        assert not re.search(r"\bn/?a\b|nan|None", step["text"]), step["text"]
    for item in spec["against"]:
        assert item["href"] in ids
    for sec in {c["section"] for c in spec["charts"]}:
        assert sec in spec["sections"], sec
        assert all(spec["sections"][sec][k] for k in ("question", "intro", "limit"))
    assert len(spec["kpis"]) == 6
    ratio = next(k for k in spec["kpis"] if k["unit"] == "ratio")
    assert ratio["state"] in {"pass", "fail", "open"}


def test_story_is_deterministic():
    a, b = charts.build(), charts.build()
    for key in ("verdict", "argument", "sections", "against", "kpis"):
        assert json.dumps(a[key], sort_keys=True) == json.dumps(b[key], sort_keys=True)
