import functools
import http.server
import json
import os
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(os.environ.get('NEAR_AUDIT_ROOT', Path(__file__).resolve().parents[2])).resolve()
OUT = Path(os.environ['NEAR_AUDIT_OUTPUT']) if 'NEAR_AUDIT_OUTPUT' in os.environ else Path(tempfile.mkdtemp(prefix='near-audit-browser-'))
OUT.mkdir(parents=True, exist_ok=True)
results = []

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
        record(mode+'_20_charts', page.locator('section.card').count() == len(spec['charts']))
        record(mode+'_6_kpis', page.locator('#kpis .kpi').count() == 5 and page.locator('#hero .value').count() == 1)
        record(mode+'_valid_svg_geometry', geometry() == 0, geometry())
        record(mode+'_no_javascript_errors', not errors, errors.copy())
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
    page.screenshot(path=str(OUT/'dashboard-desktop.png'), full_page=True)
    for width in [375, 768]:
        page.set_viewport_size({'width': width, 'height': 900})
        page.goto(base)
        record(f'layout_{width}_no_overflow', page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.evaluate('({content:document.documentElement.scrollWidth,viewport:innerWidth})'))
    page.screenshot(path=str(OUT/'dashboard-mobile.png'), full_page=True)
    response = page.goto(base+'/walkthrough.html')
    record('executed_notebook_available', response.status == 200 and page.locator('.jp-Notebook').count() > 0)
    page.goto('https://ngzeggers.github.io/near-value-shift/')
    deployed = page.locator('#spec').text_content()
    record('public_demo_same_data', json.loads(deployed) == spec)
    record('public_demo_same_chart_count', page.locator('section.card').count() == len(spec['charts']))
    # Test actual site generation with hostile chart text and script terminators.
    hostile = '</script><script>window.__audit_xss=1</script><img src=x onerror="window.__audit_xss=2">'
    malicious = json.loads(json.dumps(spec))
    malicious['charts'][0]['title'] = hostile
    malicious['charts'][0]['sentence'] = hostile
    malicious['charts'][0]['series'][0]['name'] = hostile
    safe_html = html.replace((ROOT/'site/data.json').read_text().replace('</', '<\\/'), json.dumps(malicious).replace('</', '<\\/'))
    page.set_content(safe_html)
    record('hostile_text_not_executed', page.evaluate('window.__audit_xss === undefined') and page.locator('section.card h3').first.text_content() == hostile)
    zero = json.loads(json.dumps(spec))
    zero['charts'] = [dict(spec['charts'][0], y_log=False, y_domain=None, annotations=[], series=[{'name':'zero', 'points':[['2026-01-01',0],['2026-01-02',0]]}])]
    zero_html = html.replace((ROOT/'site/data.json').read_text().replace('</', '<\\/'), json.dumps(zero).replace('</', '<\\/'))
    page.set_content(zero_html)
    record('zero_series_has_valid_geometry', geometry() == 0, geometry())
    record('all_normal_actions_no_javascript_exceptions', not errors, errors)
    browser.close()
server.shutdown()
(OUT/'browser-results.json').write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
print(f'Browser evidence: {OUT}')
