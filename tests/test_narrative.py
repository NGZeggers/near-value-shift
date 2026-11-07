"""The dashboard narrative is computed from the same artifacts as the thesis, never typed by hand."""
import json
import re

from near_thesis import charts, narrative, thesis
from near_thesis.config import ROOT, MODELS


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
    # every main claim carries an evidence kind, and every method link resolves to a chart, section or repository document
    kinds = set(spec["kinds"])
    assert kinds == {"observed", "estimate", "assumption", "inconclusive"}
    for item in spec["verdict"]["checks"] + spec["argument"] + spec["against"] + spec["kpis"] + spec["sensitivity"]:
        assert item["kind"] in kinds, item
    docs = {"#sensitivity"}
    for item in spec["verdict"]["checks"] + spec["argument"]:
        assert item["links"], item
        for link in item["links"]:
            assert link["href"] in ids or link["href"] in docs or link["href"].startswith("https://github.com/NGZeggers/near-value-shift/blob/main/"), link
    for row in spec["sensitivity"]:
        assert row["variants"] and row["effect"] and row["href"] in ids
    assert spec["dates"]["analysis_cutoff"] == spec["data_through"]


def test_story_is_deterministic():
    a, b = charts.build(), charts.build()
    for key in ("verdict", "argument", "sections", "against", "kpis"):
        assert json.dumps(a[key], sort_keys=True) == json.dumps(b[key], sort_keys=True)


def test_thesis_and_dashboard_share_reconciliation_and_granger_results():
    spec, text = charts.build(), thesis.build()
    for change in spec['verdict']['changes']:
        assert change in text
    first = spec['verdict']['changes'][0]
    assert 'ci_lo <= 1.0 <= ci_hi' in first
    assert 'fixed intraday windows, not complete-day extracts' in first
    status = json.loads((MODELS / 'intents_status.json').read_text())
    assert f"{status['sampled_days']} sampled days" in first
    summary = narrative.granger_summary(json.loads((MODELS / 'var_granger.json').read_text()))
    assert summary in text
    assert summary.strip() in spec['sections']['4. Price and usage']['intro']


def test_granger_summary_excludes_significant_but_ineligible_models():
    rows = [
        dict(metric='txns', inference_valid=True,
             usage_granger_causes_price={'p_value_holm': 0.00477},
             price_granger_causes_usage={'p_value_holm': 0.19}),
        dict(metric='intents_volume_usd', inference_valid=False,
             usage_granger_causes_price={'p_value_holm': 0.0001},
             price_granger_causes_usage={'p_value_holm': 0.0001}),
    ]
    text = narrative.granger_summary(rows)
    assert 'transaction counts (Holm p = 0.005)' in text
    assert 'price leads usage for no metric' in text
    assert 'Intents volume fail the prerequisites and are inconclusive' in text
    assert '0.0001' not in text
    assert 'No VAR model passes' in narrative.granger_summary(rows[1:])


def test_verdict_conditions_do_not_invent_missing_or_full_day_coverage():
    missing = narrative.verdict_changes({'computed': False})[0]
    assert 'unavailable' in missing and '1.0' in missing
    assert 'sampled days' not in missing
    full_day = narrative.verdict_changes(dict(
        computed=True, cross_check_passed=True, source='bigquery',
        ratio_to_defillama=dict(ratio=1.1, ci_lo=0.9, ci_hi=1.3, days=12),
    ))[0]
    assert 'consistent' in full_day and '12 matched days' in full_day
    assert 'fixed intraday windows' not in full_day
