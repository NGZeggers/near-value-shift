import functools
import http.server
import json
import os
import tempfile
import threading
from unittest.mock import patch
from near_thesis import site
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(os.environ.get('NEAR_AUDIT_ROOT', Path(__file__).resolve().parents[1])).resolve()
OUT = Path(os.environ['NEAR_AUDIT_OUTPUT']) if 'NEAR_AUDIT_OUTPUT' in os.environ else Path(tempfile.mkdtemp(prefix='near-audit-browser-'))
OUT.mkdir(parents=True, exist_ok=True)
results = []

def render_spec(specification):
    """Exercise the real serializer and HTML assembler for each hostile fixture."""
    with tempfile.TemporaryDirectory() as folder:
        target=Path(folder)
        (target/'data.json').write_text(json.dumps(specification))
        with patch.object(site,'SITE',target):
            site.run()
        return (target/'index.html').read_text()


def record(name, ok, detail=None):
    results.append(dict(name=name, passed=bool(ok), detail=detail))

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args): pass

server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(ROOT/'site')))
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{server.server_port}'
spec = json.loads((ROOT/'site/data.json').read_text())
html = (ROOT/'site/index.html').read_text()

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    def geometry():
        return page.locator('svg').evaluate_all("els => els.flatMap(e=>[...e.querySelectorAll('*')]).filter(e=>[...e.attributes].some(a=>/NaN|Infinity/.test(a.value))).length")
    for mode, url in [('http', base), ('file', (ROOT/'site/index.html').as_uri())]:
        page.goto(url)
        record(mode+'_chart_count', page.locator('section.card').count() == len(spec['charts']))
        record(mode+'_6_kpis', len(spec['kpis']) == 6
               and page.locator('#kpis .kpi').count() == len(spec['kpis']) - 1
               and page.locator('#hero .value').count() == 1)
        record(mode+'_valid_svg_geometry', geometry() == 0, geometry())
        record(mode+'_no_javascript_errors', not errors, errors.copy())
        record(mode+'_page_timestamp', page.locator('#page-built time').get_attribute('datetime')
               == page.locator('#page-built time').inner_text()
               and '/*BUILD_TIME*/' not in page.locator('#page-built').inner_text())
        verdict = page.locator('#verdict')
        verdict.locator('summary').click()
        record(mode+'_verdict_conditions', 'ci_lo <= 1.0 <= ci_hi' in verdict.inner_text()
               and all(change in verdict.inner_text() for change in spec['verdict']['changes']))
    page.goto(base)
    for label in ['Since 2023', 'Since 2024', 'Since Intents', 'Last 12 months', 'All']:
        button = page.get_by_role('button', name=label, exact=True)
        button.click()
        record('range_'+label, button.get_attribute('aria-pressed') == 'true' and geometry() == 0)
    for label in ['Dark', 'Light', 'Auto']:
        page.get_by_role('button', name=label, exact=True).click()
        record('theme_'+label, page.locator('html').get_attribute('data-theme') == (None if label == 'Auto' else label.lower()))
    page.get_by_role('button', name='Dark', exact=True).click()
    page.reload()
    record('theme_persists_after_reload', page.locator('html').get_attribute('data-theme') == 'dark')
    first = page.locator('section.card').first
    first.locator('.chart details summary').click()
    page.wait_for_timeout(50)
    record('table_view_populates', first.locator('tbody tr').count() > 0)
    first.get_by_text('Source and query', exact=True).click()
    record('source_query_visible', first.locator('pre').is_visible() and 'source:' in first.locator('pre').inner_text())
    hover = first.locator('svg rect[fill="transparent"]').first
    hover.hover()
    record('tooltip_on_hover', first.locator('.tooltip').is_visible())
    # evidence tags correspond to the computed spec
    for c in spec['verdict']['checks']:
        row = page.locator('#verdict .check', has_text=c['label']).first
        record('verdict_kind_'+c['label'].replace(' ', '_'), row.locator('.kind').inner_text().lower() == c['kind'] and row.locator('.pill').inner_text().lower() == {'pass':'supported','fail':'failing','open':'open'}[c['state']])
    steps = page.locator('#argument .steps li')
    record('argument_kinds_match_spec', [k.lower() for k in steps.locator('.kind').all_inner_texts()] == [s_['kind'] for s_ in spec['argument']])
    record('argument_method_links_present', all(steps.nth(i).locator('.method-links a').count() == len(s_['links']) for i, s_ in enumerate(spec['argument'])))
    record('against_kinds_match_spec', [k.lower() for k in page.locator('#against li .kind').all_inner_texts()] == [x['kind'] for x in spec['against']])
    sens = page.locator('#sensitivity')
    record('sensitivity_blocks_match_spec', sens.locator('.s-block').count() == len(spec['sensitivity']) and all(sens.locator('.s-block').nth(i).locator('tbody tr').count() == len(r['variants']) for i, r in enumerate(spec['sensitivity'])))
    record('dates_chip_shows_cutoff_and_snapshot', spec['data_through'] in page.locator('#dates').inner_text() and spec['data_through'] in page.locator('#built').inner_text() and 'generated' in page.locator('#page-built').inner_text().lower())
    record('internal_links_resolve', page.evaluate("[...document.querySelectorAll('a[href^=\"#\"]')].map(a=>a.getAttribute('href')).filter(h=>h.length>1 && !document.querySelector(h)).length") == 0,
           page.evaluate("[...document.querySelectorAll('a[href^=\"#\"]')].map(a=>a.getAttribute('href')).filter(h=>h.length>1 && !document.querySelector(h))"))
    # keyboard: skip link, focus order through the range buttons, Enter on a details summary
    page.goto(base)
    page.keyboard.press('Tab')
    record('skip_link_receives_focus_first', page.evaluate('document.activeElement && document.activeElement.className') == 'skip')
    page.keyboard.press('Enter')
    record('skip_link_moves_to_main', page.evaluate("location.hash === '#main'"))
    first_range = page.locator('#range button').first
    first_range.focus(); page.keyboard.press('Tab')
    record('range_buttons_are_tabbable', page.evaluate("document.activeElement.closest('#range') !== null and document.activeElement.textContent") in [b for b in ['Since 2023','Since 2024','Since Intents','Last 12 months','All']] if False else page.evaluate("document.activeElement.closest('#range') !== null"))
    page.keyboard.press('Enter')
    record('range_button_activates_by_keyboard', page.evaluate("document.activeElement.getAttribute('aria-pressed') === 'true'") and geometry() == 0)
    summary = page.locator('#verdict details summary')
    summary.focus(); page.keyboard.press('Enter')
    record('details_toggle_by_keyboard', page.locator('#verdict details').evaluate('d => d.open'))
    svg0 = page.locator('section.card svg').first
    record('charts_are_focusable', svg0.get_attribute('tabindex') == '0' and svg0.get_attribute('role') == 'img' and bool(svg0.get_attribute('aria-label')))
    page.screenshot(path=str(OUT/'dashboard-desktop.png'), full_page=True)
    for width in [375, 768]:
        page.set_viewport_size({'width': width, 'height': 900})
        page.goto(base)
        record(f'layout_{width}_no_overflow', page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.evaluate('({content:document.documentElement.scrollWidth,viewport:innerWidth})'))
    page.screenshot(path=str(OUT/'dashboard-mobile.png'), full_page=True)
    response = page.goto(base+'/walkthrough.html')
    record('executed_notebook_available', response.status == 200 and page.locator('.jp-Notebook').count() > 0)
    # Test actual site generation with hostile chart text and script terminators.
    hostile = '</script><script>window.__audit_xss=1</script><img src=x onerror="window.__audit_xss=2">'
    malicious = json.loads(json.dumps(spec))
    malicious['charts'][0]['title'] = hostile
    malicious['charts'][0]['sentence'] = hostile
    malicious['charts'][0]['series'][0]['name'] = hostile
    safe_html = render_spec(malicious)
    page.set_content(safe_html)
    record('hostile_text_not_executed', page.evaluate('window.__audit_xss === undefined') and page.locator('section.card h3').first.text_content() == hostile)
    zero = json.loads(json.dumps(spec))
    zero['charts'] = [dict(spec['charts'][0], y_log=False, y_domain=None, annotations=[], series=[{'name':'zero', 'points':[['2026-01-01',0],['2026-01-02',0]]}])]
    zero_html = render_spec(zero)
    page.set_content(zero_html)
    record('zero_series_has_valid_geometry', geometry() == 0, geometry())
    for label, values, logarithmic in [('flat_negative', [-4,-4], False), ('zero_log', [0,0], True)]:
        zero['charts'][0]['y_log'] = logarithmic
        zero['charts'][0]['series'][0]['points'] = [['2026-01-01', values[0]], ['2026-01-02', values[1]]]
        edge_html = render_spec(zero)
        page.set_content(edge_html)
        record(label+'_has_valid_geometry', geometry() == 0, geometry())

    record('all_normal_actions_no_javascript_exceptions', not errors, errors)
    browser.close()
server.shutdown()
(OUT/'browser-results.json').write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
print(f'Browser evidence: {OUT}')

if any(not result['passed'] for result in results):
    raise SystemExit('Dashboard regression failed; see JSON results')
